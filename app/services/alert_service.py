"""Alert service — turns deterministic rule findings into persisted alerts.

This is the bridge between *automated detection* (rule engine) and the
dashboard. It runs the rules and, for any finding without an equivalent open
alert, creates one. Alerts always carry ``requires_human_action`` so the
detection → recommendation → human-decision separation is preserved.
"""

from __future__ import annotations

from datetime import date

from sqlalchemy.orm import Session

from app.agents.base_agent import AgentFinding
from app.agents.rule_engine import RuleEngine
from app.authorization import is_global_viewer
from app.logging_config import get_logger
from app.models.base import AlertSeverity, AlertStatus
from app.models.operations import Alert
from app.models.user import ROLE_SEDE_COORDINATOR, ROLE_STUDENT, ROLE_TUTOR
from app.repositories.repositories import RepositoryBundle
from app.services.auth_service import Identity

logger = get_logger(__name__)

_SEVERITY_MAP = {
    "info": AlertSeverity.INFO.value,
    "warning": AlertSeverity.WARNING.value,
    "critical": AlertSeverity.CRITICAL.value,
}


class AlertService:
    """Synchronizes alerts with the current output of the rule engine."""

    def __init__(self, db: Session) -> None:
        self.db = db
        self.repos = RepositoryBundle(db)
        self.engine = RuleEngine(self.repos)

    def open_alerts(self) -> list[Alert]:
        return self.repos.alerts.open_alerts()

    def scoped_open_alerts(self, identity: Identity) -> list[Alert]:
        """Open alerts visible to ``identity`` (never a global, unscoped list
        for a Sede Coordinator, Tutor or Student — see PERMISSIONS_MATRIX.md
        "Alerts"). Alerts have no direct ``sede_id``/``student_id`` column;
        they link back to the triggering record via ``related_entity_type`` +
        ``related_entity_id``, so scope is resolved by following that link.
        """
        alerts = self.repos.alerts.open_alerts()
        if is_global_viewer(identity):
            return alerts

        if identity.role_code == ROLE_SEDE_COORDINATOR:
            sede_ids = {
                c.sede_id for c in self.repos.sede_coordinators.active()
                if c.user_id == identity.user_id and c.sede_id
            }
            return [a for a in alerts if self._alert_sede_id(a) in sede_ids]

        if identity.role_code == ROLE_TUTOR:
            tutor = self.repos.tutors.get_by_user(identity.user_id)
            if not tutor:
                return []
            student_ids = {
                a.student_id for a in self.repos.assignments.search(tutor_id=tutor.id)
            }
            return [
                a for a in alerts
                if self._alert_student_id(a) in student_ids
                or self._alert_tutor_id(a) == tutor.id
            ]

        if identity.role_code == ROLE_STUDENT:
            student = next(
                (s for s in self.repos.students.search(active=None)
                 if s.user_id == identity.user_id), None,
            )
            if not student:
                return []
            return [a for a in alerts if self._alert_student_id(a) == student.id]

        return []

    # -- alert entity resolution (for scoping only; never mutates) --------
    def _alert_sede_id(self, alert: Alert) -> int | None:
        t, i = alert.related_entity_type, alert.related_entity_id
        if i is None:
            return None
        if t == "student":
            s = self.repos.students.get(i)
            return s.sede_id if s else None
        if t == "rotation_assignment":
            a = self.repos.assignments.get(i)
            return a.sede_id if a else None
        if t == "evaluation":
            ev = self.repos.evaluations.get(i)
            a = self.repos.assignments.get(ev.assignment_id) if ev and ev.assignment_id else None
            return a.sede_id if a else None
        if t == "student_activity":
            e = self.repos.student_activities.get(i)
            a = self.repos.assignments.get(e.assignment_id) if e and e.assignment_id else None
            return a.sede_id if a else None
        if t == "tutor":
            tu = self.repos.tutors.get(i)
            return tu.sede_id if tu else None
        if t in ("document", "incident"):
            repo = self.repos.documents if t == "document" else self.repos.incidents
            rec = repo.get(i)
            return rec.sede_id if rec else None
        return None

    def _alert_student_id(self, alert: Alert) -> int | None:
        t, i = alert.related_entity_type, alert.related_entity_id
        if i is None:
            return None
        if t == "student":
            return i
        if t == "rotation_assignment":
            a = self.repos.assignments.get(i)
            return a.student_id if a else None
        if t == "evaluation":
            ev = self.repos.evaluations.get(i)
            return ev.student_id if ev else None
        if t == "student_activity":
            e = self.repos.student_activities.get(i)
            return e.student_id if e else None
        if t in ("document", "incident"):
            repo = self.repos.documents if t == "document" else self.repos.incidents
            rec = repo.get(i)
            return rec.student_id if rec else None
        return None

    def _alert_tutor_id(self, alert: Alert) -> int | None:
        if alert.related_entity_type == "tutor":
            return alert.related_entity_id
        return None

    def refresh_from_rules(self, today: date | None = None) -> int:
        """Sync alerts with the current rule output.

        Creates alerts for new findings and **auto-resolves** open alerts whose
        underlying condition no longer fires (status → resolved, preserving the
        row as history). If the condition returns later, a new open alert is
        created. Returns the count of newly created alerts.
        """
        from app.agents.rule_engine import RULES

        findings = self.engine.run_all(today=today)
        # Signature set of currently-firing findings (category + entity).
        firing = {
            (f.code, f.entity_type or "", f.entity_id) for f in findings
        }

        created = 0
        for finding in findings:
            if self._alert_exists(finding):
                continue
            self.repos.alerts.add(self._to_alert(finding))
            created += 1

        # Auto-resolve: any open, rule-engine alert in a known rule category
        # that is no longer firing gets resolved.
        resolved = 0
        for alert in self.repos.alerts.open_alerts():
            if alert.source != "rule_engine" or alert.category not in RULES:
                continue
            sig = (alert.category, alert.related_entity_type or "", alert.related_entity_id)
            if sig not in firing:
                alert.status = AlertStatus.RESOLVED.value
                resolved += 1

        if created or resolved:
            self.db.commit()
            logger.info("AlertService: +%d created, %d auto-resolved", created, resolved)
        return created

    # -- helpers ----------------------------------------------------------
    def _alert_exists(self, finding: AgentFinding) -> bool:
        return self.repos.alerts.exists_open(
            category=finding.code,
            entity_type=finding.entity_type or "",
            entity_id=finding.entity_id,
        )

    def _to_alert(self, finding: AgentFinding) -> Alert:
        return Alert(
            category=finding.code,
            severity=_SEVERITY_MAP.get(finding.severity, AlertSeverity.WARNING.value),
            status=AlertStatus.OPEN.value,
            title=finding.title,
            message=finding.detail,
            source="rule_engine",
            related_entity_type=finding.entity_type,
            related_entity_id=finding.entity_id,
            requires_human_action=True,
        )
