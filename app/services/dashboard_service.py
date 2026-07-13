"""Dashboard service — assembles the administrator dashboard view-model.

All the numbers, chart series and panels shown on the dashboard are computed
here (never in the template). Returns a plain dict consumed by Jinja2.
"""

from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy.orm import Session

from app.models.base import AssignmentStatus, InstitutionCode
from app.repositories.repositories import RepositoryBundle


class DashboardService:
    """Builds the data structure rendered by the admin dashboard."""

    def __init__(self, db: Session) -> None:
        self.repos = RepositoryBundle(db)

    def build_admin_dashboard(self, today: date | None = None) -> dict:
        today = today or date.today()
        repos = self.repos

        students = repos.students.active()
        assignments = repos.assignments.all_with_relations()
        active_assignments = [
            a for a in assignments if a.status == AssignmentStatus.ACTIVE.value
        ]

        minsa = repos.students.count_by_institution(InstitutionCode.MINSA.value)
        essalud = repos.students.count_by_institution(InstitutionCode.ESSALUD.value)

        pending_evals = repos.evaluations.pending()
        open_alerts = repos.alerts.open_alerts()

        # Rotations ending within 7 days (drives the "ending soon" table).
        cutoff = today + timedelta(days=7)
        ending_soon = [
            a
            for a in repos.assignments.ending_before(cutoff)
            if a.end_date and a.end_date >= today
        ]
        ending_soon.sort(key=lambda a: a.end_date)  # soonest first

        upcoming_changes = self._count_upcoming_changes(assignments, today)

        distribution = repos.assignments.rotation_distribution()
        current_period = repos.periods.current()
        recent_agent_runs = repos.agent_executions.recent(limit=5)

        stat_cards = [
            {"key": "active_interns", "label": "Internos activos",
             "value": len(students), "icon": "mortarboard", "tone": "primary"},
            {"key": "minsa", "label": "Internos MINSA",
             "value": minsa, "icon": "hospital", "tone": "info"},
            {"key": "essalud", "label": "Internos EsSalud",
             "value": essalud, "icon": "building", "tone": "info"},
            {"key": "active_sedes", "label": "Sedes activas",
             "value": len(repos.sedes.active()), "icon": "geo-alt", "tone": "secondary"},
            {"key": "active_rotations", "label": "Rotaciones activas",
             "value": len(active_assignments), "icon": "arrow-repeat", "tone": "primary"},
            {"key": "pending_evals", "label": "Evaluaciones pendientes",
             "value": len(pending_evals), "icon": "check2-square", "tone": "warning"},
            {"key": "open_alerts", "label": "Alertas abiertas",
             "value": len(open_alerts), "icon": "bell", "tone": "danger"},
            {"key": "upcoming_changes", "label": "Cambios de rotación próximos",
             "value": upcoming_changes, "icon": "calendar-event", "tone": "secondary"},
        ]

        return {
            "stat_cards": stat_cards,
            "rotation_distribution": distribution,
            "students_by_institution": {"MINSA": minsa, "EsSalud": essalud},
            "recent_alerts": open_alerts[:6],
            "ending_soon": ending_soon[:8],
            "recent_agent_runs": recent_agent_runs,
            "current_period": current_period,
            "system_status": self._system_status(),
            "quick_actions": self._quick_actions(),
        }

    def _count_upcoming_changes(self, assignments, today: date) -> int:
        """Rotations that start within the next 14 days (planned → active)."""
        horizon = today + timedelta(days=14)
        return sum(
            1
            for a in assignments
            if a.status == AssignmentStatus.PLANNED.value
            and a.start_date
            and today <= a.start_date <= horizon
        )

    def _system_status(self) -> dict:
        return {
            "database": "SQLite · operativo",
            "agents": "4 agentes registrados",
            "mode": "Prototipo · Demo",
            "healthy": True,
        }

    def _quick_actions(self) -> list[dict]:
        return [
            {"label": "Registrar interno", "href": "/students", "icon": "person-plus"},
            {"label": "Programar rotación", "href": "/rotations", "icon": "calendar-plus"},
            {"label": "Ejecutar agentes", "href": "/agents", "icon": "robot"},
            {"label": "Ver alertas", "href": "/alerts", "icon": "bell"},
        ]
