"""Comunicados (announcement) routes.

Any authenticated role may read the list (scoped to their own sede, or
everything for admin/university — see AnnouncementService._read_scope).
Only admin, university coordinator, and sede coordinator may send one.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.authorization import Forbidden, is_global_viewer
from app.csrf import csrf_protect
from app.database import get_db
from app.dependencies import Identity, require_identity
from app.services.announcement_service import AnnouncementService
from app.services.audit_service import client_ip
from app.services.validators import ValidationError
from app.templating import render
from app.web import FLASH_SUCCESS, flash

router = APIRouter(tags=["announcements"])


async def _form(request: Request) -> dict:
    form = await request.form()
    return {k: v for k, v in form.multi_items()}


@router.get("/announcements")
def list_announcements(request: Request, identity: Identity = Depends(require_identity),
                       db: Session = Depends(get_db)):
    svc = AnnouncementService(db, identity)
    announcements = svc.list_visible()
    sede_ids = {a.sede_id for a in announcements if a.sede_id}
    sede_names = {}
    if sede_ids:
        for sid in sede_ids:
            sede = svc.repos.sedes.get(sid)
            if sede:
                sede_names[sid] = sede.short_name or sede.name
    sender_ids = {a.created_by_user_id for a in announcements if a.created_by_user_id}
    sender_names = {}
    for uid in sender_ids:
        user = svc.repos.users.get(uid)
        if user:
            sender_names[uid] = user.full_name
    return render(request, "pages/announcements_list.html", identity=identity,
                  page_title="Comunicados", page_subtitle="Avisos institucionales y de sede.",
                  page_icon="megaphone", announcements=announcements,
                  sede_names=sede_names, sender_names=sender_names,
                  can_create=svc.can_create())


@router.get("/announcements/new")
def new_announcement(request: Request, identity: Identity = Depends(require_identity),
                     db: Session = Depends(get_db)):
    svc = AnnouncementService(db, identity)
    if not svc.can_create():
        raise Forbidden(reason="create_announcement_denied")
    return render(request, "pages/announcement_form.html", identity=identity,
                  page_title="Nuevo comunicado", page_subtitle="Enviar un aviso a su sede.",
                  page_icon="megaphone", sede_options=svc.sede_options(),
                  is_global=is_global_viewer(identity),
                  form={}, errors={})


@router.post("/announcements/new")
async def create_announcement(request: Request, identity: Identity = Depends(require_identity),
                              db: Session = Depends(get_db), _: None = Depends(csrf_protect)):
    svc = AnnouncementService(db, identity)
    if not svc.can_create():
        raise Forbidden(reason="create_announcement_denied")
    form = await _form(request)
    try:
        svc.create(form, ip=client_ip(request))
    except ValidationError as e:
        return render(request, "pages/announcement_form.html", identity=identity,
                      page_title="Nuevo comunicado", page_subtitle="Enviar un aviso a su sede.",
                      page_icon="megaphone", sede_options=svc.sede_options(),
                      is_global=is_global_viewer(identity),
                      form=form, errors=e.errors, status_code=400)
    flash(request, "Comunicado enviado.", FLASH_SUCCESS)
    return RedirectResponse(url="/announcements", status_code=303)
