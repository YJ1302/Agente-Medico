"""Role-scoped dashboard builders (Batch 2D).

``DashboardService.build_admin_dashboard`` (Batch 1) remains the single
source of **global** KPIs and is reused as-is for Admin and University
Coordinator — both have legitimate global visibility per
USER_ROLES_AND_PERMISSIONS.md. This module adds the three genuinely scoped
dashboards:

* Sede Coordinator — **own sede only**.
* Tutor — assigned students/rotations/evaluations/verification queue only.
* Student — **no global totals at all**: only their own rotation, tutor,
  sede, evaluation and activity progress.

Never include a global count (total interns, MINSA/EsSalud split, etc.) in the
tutor or student dashboards — that is the specific requirement this batch
must satisfy.
"""

from __future__ import annotations

from datetime import date

from sqlalchemy.orm import Session

from app.models.base import AssignmentStatus, EvaluationStatus
from app.repositories.repositories import RepositoryBundle
from app.services.staff_service import compute_workload
from app.services.student_activity_service import StudentActivityService


class RoleDashboardService:
    def __init__(self, db: Session, identity) -> None:
        self.db = db
        self.identity = identity
        self.repos = RepositoryBundle(db)

    # -- Sede Coordinator ---------------------------------------------------
    def build_sede_dashboard(self, today: date | None = None) -> dict:
        today = today or date.today()
        sede_ids = {c.sede_id for c in self.repos.sede_coordinators.active()
                   if c.user_id == self.identity.user_id and c.sede_id}
        sede = self.repos.sedes.get(next(iter(sede_ids))) if sede_ids else None

        students = [s for s in self.repos.students.active() if s.sede_id in sede_ids]
        assignments = [a for a in self.repos.assignments.all_with_relations()
                       if a.sede_id in sede_ids]
        active_assignments = [a for a in assignments if a.status == AssignmentStatus.ACTIVE.value]
        tutors = [t for t in self.repos.tutors.active() if t.sede_id in sede_ids]
        pending_evals = [e for e in self.repos.evaluations.search(sede_ids=sede_ids)
                         if e.status in (EvaluationStatus.PENDING.value, EvaluationStatus.IN_PROGRESS.value)]
        submitted_evals = self.repos.evaluations.search(
            sede_ids=sede_ids, status=EvaluationStatus.SUBMITTED.value)
        open_alerts = [a for a in self.repos.alerts.open_alerts()
                      if self._alert_in_sede(a, sede_ids)]

        stat_cards = [
            {"key": "sede_students", "label": "Internos en la sede",
             "value": len(students), "icon": "mortarboard", "tone": "primary"},
            {"key": "sede_tutors", "label": "Tutores en la sede",
             "value": len(tutors), "icon": "people", "tone": "secondary"},
            {"key": "sede_active_rotations", "label": "Rotaciones activas",
             "value": len(active_assignments), "icon": "arrow-repeat", "tone": "primary"},
            {"key": "sede_pending_evals", "label": "Evaluaciones pendientes",
             "value": len(pending_evals), "icon": "hourglass-split", "tone": "warning"},
            {"key": "sede_submitted_evals", "label": "Esperando aprobación",
             "value": len(submitted_evals), "icon": "check2-square", "tone": "info"},
            {"key": "sede_open_alerts", "label": "Alertas abiertas",
             "value": len(open_alerts), "icon": "bell", "tone": "danger"},
        ]
        return {
            "sede": sede, "stat_cards": stat_cards, "recent_alerts": open_alerts[:6],
            "submitted_evaluations": submitted_evals[:8],
            "current_period": self.repos.periods.current(),
            "quick_actions": [
                {"label": "Ver internos de mi sede", "href": "/students", "icon": "mortarboard"},
                {"label": "Ver tutores", "href": "/tutors", "icon": "people"},
                {"label": "Evaluaciones por aprobar", "href": "/evaluations?status=submitted", "icon": "check2-square"},
                {"label": "Monitoreo de actividades", "href": "/activities/monitor", "icon": "graph-up"},
            ],
        }

    def _alert_in_sede(self, alert, sede_ids: set[int]) -> bool:
        if alert.related_entity_type == "sede":
            return alert.related_entity_id in sede_ids
        if alert.related_entity_type == "rotation_assignment":
            a = self.repos.assignments.get(alert.related_entity_id)
            return bool(a) and a.sede_id in sede_ids
        if alert.related_entity_type == "student":
            s = self.repos.students.get(alert.related_entity_id)
            return bool(s) and s.sede_id in sede_ids
        return False

    # -- Tutor ---------------------------------------------------------------
    def build_tutor_dashboard(self, today: date | None = None) -> dict:
        today = today or date.today()
        tutor = next((t for t in self.repos.tutors.active()
                     if t.user_id == self.identity.user_id), None)
        if tutor is None:
            return {"tutor": None, "stat_cards": [], "assignments": [],
                    "pending_evaluations": [], "pending_activities": [],
                    "workload": compute_workload(0)}

        assignments = [a for a in self.repos.assignments.all_with_relations()
                       if a.tutor_id == tutor.id]
        active_assignments = [a for a in assignments if a.status == AssignmentStatus.ACTIVE.value]
        students = {a.student_id: a.student for a in assignments if a.student}
        pending_evals = self.repos.evaluations.search(tutor_id=tutor.id)
        pending_evals = [e for e in pending_evals
                         if e.status in (EvaluationStatus.PENDING.value,
                                        EvaluationStatus.IN_PROGRESS.value,
                                        EvaluationStatus.RETURNED_FOR_CORRECTION.value)]
        act_svc = StudentActivityService(self.db, self.identity)
        pending_activities = act_svc.inbox()
        workload = compute_workload(self.repos.tutors.workload_count(tutor.id))

        stat_cards = [
            {"key": "tutor_students", "label": "Internos asignados",
             "value": len(students), "icon": "mortarboard", "tone": "primary"},
            {"key": "tutor_active", "label": "Rotaciones activas",
             "value": len(active_assignments), "icon": "arrow-repeat", "tone": "secondary"},
            {"key": "tutor_pending_evals", "label": "Evaluaciones por completar",
             "value": len(pending_evals), "icon": "check2-square", "tone": "warning"},
            {"key": "tutor_pending_activities", "label": "Actividades por verificar",
             "value": len(pending_activities), "icon": "inbox", "tone": "info"},
        ]
        return {
            "tutor": tutor, "stat_cards": stat_cards,
            "assignments": active_assignments[:8],
            "pending_evaluations": pending_evals[:8],
            "pending_activities": pending_activities[:8],
            "workload": workload,
            "quick_actions": [
                {"label": "Bandeja de verificación", "href": "/activities/verify", "icon": "inbox"},
                {"label": "Mis evaluaciones", "href": "/evaluations", "icon": "check2-square"},
                {"label": "Mis rotaciones", "href": "/rotations", "icon": "arrow-repeat"},
            ],
        }

    # -- Student --------------------------------------------------------------
    def build_student_dashboard(self, today: date | None = None) -> dict:
        """Strictly personal data — never a global total (MINSA/EsSalud/interns)."""
        today = today or date.today()
        student = next((s for s in self.repos.students.search(active=None)
                        if s.user_id == self.identity.user_id), None)
        if student is None:
            return {"student": None}

        assignments = sorted(
            [a for a in self.repos.assignments.all_with_relations()
             if a.student_id == student.id and not a.is_deleted],
            key=lambda a: (a.start_date or date.min),
        )
        current = next((a for a in assignments if a.status == AssignmentStatus.ACTIVE.value), None)
        upcoming = next((a for a in assignments if a.status == AssignmentStatus.PLANNED.value
                        and (a.start_date or date.max) >= today), None)
        days_remaining = (current.end_date - today).days if current and current.end_date else None

        evaluations = self.repos.evaluations.search(student_id=student.id)
        approved_evals = [e for e in evaluations if e.status == EvaluationStatus.APPROVED.value]
        pending_own_evals = [e for e in evaluations
                             if e.status not in (EvaluationStatus.APPROVED.value,)]

        act_svc = StudentActivityService(self.db, self.identity)
        activity_summary = act_svc.assignment_summary(current.id) if current else None

        alerts = [a for a in self.repos.alerts.open_alerts()
                 if (a.related_entity_type == "student" and a.related_entity_id == student.id)
                 or (a.related_entity_type == "rotation_assignment" and current
                    and a.related_entity_id == current.id)]

        return {
            "student": student, "current": current, "upcoming": upcoming,
            "days_remaining": days_remaining, "approved_evaluations": approved_evals,
            "pending_evaluations_count": len(pending_own_evals),
            "activity_summary": activity_summary, "alerts": alerts,
            "current_period": self.repos.periods.current(),
        }
