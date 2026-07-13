"""Sidebar navigation model and per-role visibility.

Defines the full navigation tree once and filters it by role. This keeps menu
structure out of templates and enforces role-based visibility in one place.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.models.user import (
    ROLE_ADMIN,
    ROLE_SEDE_COORDINATOR,
    ROLE_STUDENT,
    ROLE_TUTOR,
    ROLE_UNIVERSITY_COORDINATOR,
)

ALL_ROLES = {
    ROLE_ADMIN,
    ROLE_UNIVERSITY_COORDINATOR,
    ROLE_SEDE_COORDINATOR,
    ROLE_TUTOR,
    ROLE_STUDENT,
}


@dataclass
class NavItem:
    """A single sidebar link."""

    label: str
    endpoint: str  # URL path
    icon: str  # Bootstrap Icons class name
    roles: set[str] = field(default_factory=lambda: set(ALL_ROLES))


@dataclass
class NavSection:
    """A titled group of sidebar links."""

    title: str
    items: list[NavItem]


# The complete navigation tree. ``roles`` on each item controls visibility.
NAV_SECTIONS: list[NavSection] = [
    NavSection(
        "GENERAL",
        [NavItem("Dashboard", "/dashboard", "speedometer2")],
    ),
    NavSection(
        "GESTIÓN DEL INTERNADO",
        [
            NavItem("Internos", "/students", "mortarboard"),
            NavItem("Sedes", "/sedes", "hospital"),
            NavItem(
                "Coordinadores de Sede",
                "/coordinators",
                "person-badge",
                roles={ROLE_ADMIN, ROLE_UNIVERSITY_COORDINATOR, ROLE_SEDE_COORDINATOR},
            ),
            NavItem(
                "Tutores",
                "/tutors",
                "people",
                roles={ROLE_ADMIN, ROLE_UNIVERSITY_COORDINATOR, ROLE_SEDE_COORDINATOR},
            ),
            NavItem("Rotaciones", "/rotations", "arrow-repeat"),
            NavItem("Catálogo de Actividades", "/activities", "clipboard-check"),
            NavItem("Mis Actividades", "/activities/mine", "journal-check",
                    roles={ROLE_STUDENT}),
            NavItem("Bandeja de Verificación", "/activities/verify", "inbox",
                    roles={ROLE_ADMIN, ROLE_UNIVERSITY_COORDINATOR, ROLE_TUTOR}),
            NavItem("Monitoreo de Actividades", "/activities/monitor", "graph-up",
                    roles={ROLE_ADMIN, ROLE_UNIVERSITY_COORDINATOR, ROLE_SEDE_COORDINATOR}),
            NavItem("Evaluaciones", "/evaluations", "check2-square"),
        ],
    ),
    NavSection(
        "GESTIÓN INSTITUCIONAL",
        [
            NavItem("Documentos", "/documents", "file-earmark-text"),
            NavItem("Incidencias", "/incidents", "exclamation-triangle"),
            NavItem("Reportes", "/reports", "bar-chart"),
        ],
    ),
    NavSection(
        "AUTOMATIZACIÓN INTELIGENTE",
        [
            NavItem("Centro de Agentes", "/agents", "robot"),
            NavItem("Alertas", "/alerts", "bell"),
            NavItem(
                "Ejecuciones de Agentes",
                "/agent-executions",
                "cpu",
                roles={ROLE_ADMIN, ROLE_UNIVERSITY_COORDINATOR},
            ),
        ],
    ),
    NavSection(
        "ADMINISTRACIÓN",
        [
            NavItem("Usuarios y Roles", "/users", "person-badge", roles={ROLE_ADMIN}),
            NavItem(
                "Periodos Académicos",
                "/periods",
                "calendar3",
                roles={ROLE_ADMIN, ROLE_UNIVERSITY_COORDINATOR},
            ),
            NavItem("Configuración", "/settings", "gear", roles={ROLE_ADMIN}),
            NavItem("Auditoría", "/audit", "shield-check", roles={ROLE_ADMIN}),
        ],
    ),
]


def sections_for_role(role_code: str) -> list[NavSection]:
    """Return navigation sections filtered to items visible for the role."""
    visible: list[NavSection] = []
    for section in NAV_SECTIONS:
        items = [i for i in section.items if role_code in i.roles]
        if items:
            visible.append(NavSection(section.title, items))
    return visible
