"""Admin-only "Usuarios y Roles" page: list accounts, grant/revoke roles.

Replaces the former placeholder at /users. See
``app.services.user_admin_service`` for why Student isn't managed here.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.authorization import require_admin
from app.csrf import csrf_protect
from app.database import get_db
from app.dependencies import Identity
from app.models.user import ROLE_SEDE_COORDINATOR, ROLE_TUTOR
from app.services.audit_service import client_ip
from app.services.staff_service import CoordinatorService, TutorService
from app.services.user_admin_service import (
    MANAGED_ROLE_CODES,
    PROFILE_FREE_ROLES,
    PROFILE_ROLES,
    UserAdminService,
)
from app.services.validators import ValidationError
from app.templating import render
from app.web import FLASH_SUCCESS, flash

router = APIRouter(tags=["user_admin"])

_ROLE_SERVICE = {ROLE_SEDE_COORDINATOR: CoordinatorService, ROLE_TUTOR: TutorService}


@router.get("/users")
def list_users(request: Request, identity: Identity = Depends(require_admin),
               db: Session = Depends(get_db), q: str = ""):
    svc = UserAdminService(db, identity)
    users = svc.list_users(q or None)
    roles_by_user = {u.id: svc.roles_for(u) for u in users}
    role_names = {r.code: r.name for r in svc.repos.roles.all_ordered()}
    return render(request, "pages/users_list.html", identity=identity,
                  page_title="Usuarios y Roles", page_subtitle="Gestión de cuentas y permisos.",
                  page_icon="person-badge", users=users, roles_by_user=roles_by_user,
                  managed_roles=MANAGED_ROLE_CODES, profile_free_roles=PROFILE_FREE_ROLES,
                  profile_roles=PROFILE_ROLES, role_names=role_names, q=q)


@router.post("/users/{user_id}/roles/{role_code}/grant")
async def grant_role(user_id: int, role_code: str, request: Request,
                     identity: Identity = Depends(require_admin),
                     db: Session = Depends(get_db), _: None = Depends(csrf_protect)):
    svc = UserAdminService(db, identity)
    try:
        svc.grant_profile_free_role(user_id, role_code, ip=client_ip(request))
    except ValidationError as e:
        flash(request, list(e.errors.values())[0], "warning")
        return RedirectResponse(url="/users", status_code=303)
    flash(request, "Rol otorgado correctamente.", FLASH_SUCCESS)
    return RedirectResponse(url="/users", status_code=303)


@router.post("/users/{user_id}/roles/{role_code}/revoke")
async def revoke_role(user_id: int, role_code: str, request: Request,
                      identity: Identity = Depends(require_admin),
                      db: Session = Depends(get_db), _: None = Depends(csrf_protect)):
    svc = UserAdminService(db, identity)
    try:
        svc.revoke_role(user_id, role_code, ip=client_ip(request))
    except ValidationError as e:
        flash(request, list(e.errors.values())[0], "warning")
        return RedirectResponse(url="/users", status_code=303)
    flash(request, "Rol retirado correctamente.", FLASH_SUCCESS)
    return RedirectResponse(url="/users", status_code=303)


@router.get("/users/{user_id}/roles/add")
def add_role_form(user_id: int, role: str, request: Request,
                  identity: Identity = Depends(require_admin),
                  db: Session = Depends(get_db)):
    svc = UserAdminService(db, identity)
    user = svc.get(user_id)
    if user is None or role not in PROFILE_ROLES:
        flash(request, "Solicitud inválida.", "warning")
        return RedirectResponse(url="/users", status_code=303)
    role_svc = _ROLE_SERVICE[role](db, identity)
    role_label = "Coordinador de Sede" if role == ROLE_SEDE_COORDINATOR else "Tutor"
    return render(request, "pages/user_add_role.html", identity=identity,
                  page_title=f"Agregar rol · {role_label}",
                  page_subtitle=f"{user.full_name} — nueva asignación como {role_label}.",
                  page_icon="person-plus", user=user, role=role, role_label=role_label,
                  options=role_svc.form_options(), errors={}, form={})


@router.post("/users/{user_id}/roles/add")
async def add_role_submit(user_id: int, request: Request,
                          identity: Identity = Depends(require_admin),
                          db: Session = Depends(get_db), _: None = Depends(csrf_protect),
                          role: str = Form(...), sede_id: str = Form(""),
                          specialty: str = Form(""), phone: str = Form("")):
    svc = UserAdminService(db, identity)
    user = svc.get(user_id)
    role_label = "Coordinador de Sede" if role == ROLE_SEDE_COORDINATOR else "Tutor"
    if user is None or role not in PROFILE_ROLES:
        flash(request, "Solicitud inválida.", "warning")
        return RedirectResponse(url="/users", status_code=303)
    role_svc = _ROLE_SERVICE[role](db, identity)
    data = {"full_name": user.full_name, "email": user.email, "phone": phone or user.phone,
            "sede_id": sede_id, "specialty": specialty}
    try:
        if role == ROLE_SEDE_COORDINATOR:
            role_svc.create({**data, "office_phone": phone or user.phone},
                            ip=client_ip(request), existing_user=user)
        else:
            role_svc.create(data, ip=client_ip(request), existing_user=user)
    except ValidationError as e:
        return render(request, "pages/user_add_role.html", identity=identity,
                      page_title=f"Agregar rol · {role_label}",
                      page_subtitle=f"{user.full_name} — nueva asignación como {role_label}.",
                      page_icon="person-plus", user=user, role=role, role_label=role_label,
                      options=role_svc.form_options(), errors=e.errors, form=data,
                      status_code=400)
    flash(request, f"Rol de {role_label} agregado a «{user.full_name}».", FLASH_SUCCESS)
    return RedirectResponse(url="/users", status_code=303)
