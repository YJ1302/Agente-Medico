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
from app.logging_config import get_logger
from app.models.base import AlertSeverity, AlertStatus
from app.models.operations import Alert
from app.repositories.repositories import RepositoryBundle

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
