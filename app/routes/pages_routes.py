"""Management pages.

Several pages render real seeded data (students, sedes, tutors, rotations,
evaluations, alerts, agent executions, audit). The remaining pages render a
consistent placeholder/empty-state that Parts 2 and 3 will replace with full
CRUD workflows. Every page uses the shared authenticated layout.
"""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.authorization import (
    require_admin,
    require_admin_or_university,
    require_management,
)
from app.database import get_db
from app.dependencies import Identity, require_identity
from app.repositories.repositories import RepositoryBundle
from app.services.alert_service import AlertService
from app.templating import render

router = APIRouter(tags=["pages"])


def _page(request, identity, title, subtitle, icon, **ctx):
    return render(
        request,
        ctx.pop("template", "pages/placeholder.html"),
        identity=identity,
        page_title=title,
        page_subtitle=subtitle,
        page_icon=icon,
        **ctx,
    )


@router.get("/alerts")
def alerts(request: Request, identity: Identity = Depends(require_identity),
           db: Session = Depends(get_db)):
    AlertService(db).refresh_from_rules()
    repos = RepositoryBundle(db)
    return _page(request, identity, "Alertas",
                 "Detección automática de riesgos operativos (requiere decisión humana).",
                 "bell", template="pages/alerts.html",
                 alerts=repos.alerts.open_alerts())


@router.get("/agent-executions")
def agent_executions(request: Request,
                     identity: Identity = Depends(require_admin_or_university),
                     db: Session = Depends(get_db)):
    repos = RepositoryBundle(db)
    runs = repos.agent_executions.recent(limit=50)
    parsed = []
    for r in runs:
        parsed.append({
            "row": r,
            "findings": json.loads(r.findings_json or "[]"),
            "actions": json.loads(r.recommended_actions_json or "[]"),
        })
    return _page(request, identity, "Ejecuciones de Agentes",
                 "Historial auditable de cada ejecución de agente.",
                 "cpu", template="pages/agent_executions.html", runs=parsed)


@router.get("/audit")
def audit(request: Request, identity: Identity = Depends(require_admin),
          db: Session = Depends(get_db)):
    repos = RepositoryBundle(db)
    return _page(request, identity, "Auditoría",
                 "Registro de acciones importantes del sistema.",
                 "shield-check", template="pages/audit.html",
                 logs=repos.audit_logs.recent(limit=100))


# --- Placeholder pages (full workflows arrive in Parts 2 & 3) --------------
# Each entry: path -> (title, subtitle, icon, guard-dependency).
# The guard enforces role access server-side, not just via the hidden sidebar.
_PLACEHOLDERS = {
    "/documents": ("Documentos",
                   "Comunicaciones formales con estados trazables.",
                   "file-earmark-text", require_identity),
    "/incidents": ("Incidencias",
                   "Situaciones que afectan el desarrollo del internado.",
                   "exclamation-triangle", require_identity),
    "/reports": ("Reportes", "Reportes académicos y de gestión.",
                 "bar-chart", require_management),
    "/users": ("Usuarios y Roles", "Gestión de cuentas y permisos.",
               "person-badge", require_admin),
    "/periods": ("Periodos Académicos", "Bimestres del año de internado.",
                 "calendar3", require_admin_or_university),
    "/settings": ("Configuración", "Parámetros del sistema.",
                  "gear", require_admin),
}


def _make_placeholder(path: str, title: str, subtitle: str, icon: str, guard):
    @router.get(path)
    def _view(request: Request, identity: Identity = Depends(guard),
              _title=title, _subtitle=subtitle, _icon=icon):
        return _page(request, identity, _title, _subtitle, _icon)
    return _view


for _path, (_t, _s, _i, _guard) in _PLACEHOLDERS.items():
    _make_placeholder(_path, _t, _s, _i, _guard)
