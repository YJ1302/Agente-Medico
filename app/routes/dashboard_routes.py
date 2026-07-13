"""Dashboard routes.

Each role gets a dashboard scoped to what it is actually allowed to see
(Batch 2D). Admin and University Coordinator share the global dashboard
(``DashboardService`` — both have legitimate global visibility). Sede
Coordinator, Tutor and Student each get a dedicated scoped builder from
``RoleDashboardService`` and their own template — students in particular never
receive global MINSA/EsSalud/intern totals.
"""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import Identity, require_identity
from app.models.user import (
    ROLE_ADMIN,
    ROLE_SEDE_COORDINATOR,
    ROLE_STUDENT,
    ROLE_TUTOR,
    ROLE_UNIVERSITY_COORDINATOR,
)
from app.services.alert_service import AlertService
from app.services.dashboard_service import DashboardService
from app.services.role_dashboard_service import RoleDashboardService
from app.templating import render

router = APIRouter(tags=["dashboard"])

ROLE_WELCOME = {
    "admin": "Panel institucional completo del internado médico.",
    "university_coordinator": "Supervisión académica del internado a nivel universidad.",
    "sede_coordinator": "Gestión del internado en su sede docente hospitalaria.",
    "tutor": "Seguimiento y evaluación de sus internos por rotación.",
    "student": "Seguimiento de su internado, rotaciones y evaluaciones.",
}


@router.get("/dashboard")
def dashboard(
    request: Request,
    identity: Identity = Depends(require_identity),
    db: Session = Depends(get_db),
):
    # Keep alerts fresh from the deterministic rules on each dashboard load.
    AlertService(db).refresh_from_rules()

    role = identity.role_code
    if role in (ROLE_ADMIN, ROLE_UNIVERSITY_COORDINATOR):
        data = DashboardService(db).build_admin_dashboard()
        charts = {
            "rotation_labels": list(data["rotation_distribution"].keys()),
            "rotation_values": list(data["rotation_distribution"].values()),
            "institution_labels": list(data["students_by_institution"].keys()),
            "institution_values": list(data["students_by_institution"].values()),
        }
        return render(request, "dashboard.html", identity=identity, data=data,
                      charts_json=json.dumps(charts),
                      welcome=ROLE_WELCOME.get(role, ""))

    role_svc = RoleDashboardService(db, identity)
    if role == ROLE_SEDE_COORDINATOR:
        data = role_svc.build_sede_dashboard()
        return render(request, "dashboard_sede.html", identity=identity, data=data,
                      welcome=ROLE_WELCOME.get(role, ""))
    if role == ROLE_TUTOR:
        data = role_svc.build_tutor_dashboard()
        return render(request, "dashboard_tutor.html", identity=identity, data=data,
                      welcome=ROLE_WELCOME.get(role, ""))
    if role == ROLE_STUDENT:
        data = role_svc.build_student_dashboard()
        return render(request, "dashboard_student.html", identity=identity, data=data,
                      welcome=ROLE_WELCOME.get(role, ""))

    # Fallback (should not happen with the 5 defined roles).
    data = DashboardService(db).build_admin_dashboard()
    return render(request, "dashboard_role.html", identity=identity, data=data,
                  welcome=ROLE_WELCOME.get(role, ""))
