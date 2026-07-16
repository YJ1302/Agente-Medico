"""Incident management tests (Batch 2E)."""

from __future__ import annotations

from app.database import SessionLocal
from app.models.base import IncidentSeverity, IncidentStatus, VisibilityLevel
from app.models.operations import Incident
from app.repositories.repositories import RepositoryBundle
from app.services.auth_service import Identity
from app.services.incident_service import IncidentService
from tests.conftest import _logged_in_client, csrf_token

# Seeded incident ids (id == sequence number).
INC_OPEN_LOW = 1              # sede 4 (id 4)
INC_HIGH_SEDE1 = 2           # under_review high, sede 1 (sede@)
INC_CRITICAL_SEDE2 = 3       # action_required critical, sede 2
INC_RESOLVED = 4             # resolved, sede 1
INC_CONFIDENTIAL = 5         # under_review high confidential, sede 2, student 2
INC_OVERDUE = 6              # under_review overdue, sede 1


def _repos():
    return RepositoryBundle(SessionLocal())


def _tok(client) -> str:
    return csrf_token(client, "/incidents/new")


def _create(client, **over) -> int:
    tok = csrf_token(client, "/incidents/new")
    data = {"csrf_token": tok, "title": "Incidencia de prueba", "incident_type": "conduct",
            "severity": "medium", "description": "Descripción objetiva de la incidencia."}
    data.update(over)
    r = client.post("/incidents", data=data, follow_redirects=False)
    assert r.status_code == 303, r.text
    return int(r.headers["location"].rstrip("/").split("/")[-1])


# --- Creation ----------------------------------------------------------------
def test_create_valid_incident(admin):
    inc_id = _create(admin)
    db = SessionLocal()
    inc = RepositoryBundle(db).incidents.get_full(inc_id)
    assert inc.status == IncidentStatus.OPEN.value
    assert inc.code.startswith("INC-")
    db.close()


def test_high_severity_creates_alert(admin):
    inc_id = _create(admin, severity="high", title="Alta severidad")
    db = SessionLocal()
    alerts = RepositoryBundle(db).alerts.open_alerts()
    db.close()
    assert any(a.category == "high_severity_incident" and a.related_entity_id == inc_id
               for a in alerts)


def test_critical_severity_creates_alert(admin):
    inc_id = _create(admin, severity="critical", title="Crítica")
    db = SessionLocal()
    alerts = RepositoryBundle(db).alerts.open_alerts()
    db.close()
    assert any(a.category == "critical_incident" and a.related_entity_id == inc_id
               for a in alerts)


# --- Scope -------------------------------------------------------------------
def test_scope_enforced_sede_coordinator(sede_client):
    # sede@ coordinates sede 1: sees INC_HIGH_SEDE1, not INC_CRITICAL_SEDE2.
    assert sede_client.get(f"/incidents/{INC_HIGH_SEDE1}", follow_redirects=False).status_code == 200
    assert sede_client.get(f"/incidents/{INC_CRITICAL_SEDE2}", follow_redirects=False).status_code == 403


# --- Transitions -------------------------------------------------------------
def test_resolution_requires_comments(sede_client):
    inc_id = _create(sede_client, sede_id=str(_sede1_id()), student_id="", severity="low")
    sede_client.post(f"/incidents/{inc_id}/review", data={"csrf_token": _tok(sede_client)})
    # Resolve with empty resolution -> stays under_review.
    sede_client.post(f"/incidents/{inc_id}/resolve",
                     data={"csrf_token": _tok(sede_client), "resolution": ""})
    db = SessionLocal()
    assert RepositoryBundle(db).incidents.get_full(inc_id).status == IncidentStatus.UNDER_REVIEW.value
    db.close()


def test_close_requires_resolution(admin):
    inc_id = _create(admin, severity="low")
    admin.post(f"/incidents/{inc_id}/review", data={"csrf_token": _tok(admin)})
    admin.post(f"/incidents/{inc_id}/resolve",
               data={"csrf_token": _tok(admin), "resolution": "Atendida y verificada."})
    admin.post(f"/incidents/{inc_id}/close", data={"csrf_token": _tok(admin)})
    db = SessionLocal()
    assert RepositoryBundle(db).incidents.get_full(inc_id).status == IncidentStatus.CLOSED.value
    db.close()


def test_dismiss_requires_reason(admin):
    inc_id = _create(admin, severity="low")
    # Dismiss without reason -> stays open.
    admin.post(f"/incidents/{inc_id}/dismiss", data={"csrf_token": _tok(admin), "reason": ""})
    db = SessionLocal()
    assert RepositoryBundle(db).incidents.get_full(inc_id).status == IncidentStatus.OPEN.value
    db.close()
    admin.post(f"/incidents/{inc_id}/dismiss", data={"csrf_token": _tok(admin), "reason": "Duplicada"})
    db = SessionLocal()
    assert RepositoryBundle(db).incidents.get_full(inc_id).status == IncidentStatus.DISMISSED.value
    db.close()


def test_admin_reopen_requires_reason(admin):
    inc_id = _create(admin, severity="low")
    admin.post(f"/incidents/{inc_id}/review", data={"csrf_token": _tok(admin)})
    admin.post(f"/incidents/{inc_id}/resolve",
               data={"csrf_token": _tok(admin), "resolution": "Resuelta."})
    # Reopen without reason -> stays resolved.
    admin.post(f"/incidents/{inc_id}/reopen", data={"csrf_token": _tok(admin), "reason": ""})
    db = SessionLocal()
    assert RepositoryBundle(db).incidents.get_full(inc_id).status == IncidentStatus.RESOLVED.value
    db.close()
    admin.post(f"/incidents/{inc_id}/reopen", data={"csrf_token": _tok(admin), "reason": "Nueva evidencia"})
    db = SessionLocal()
    assert RepositoryBundle(db).incidents.get_full(inc_id).status == IncidentStatus.REOPENED.value
    db.close()


def test_non_admin_cannot_reopen(sede_client, admin):
    inc_id = _create(admin, severity="low", sede_id=str(_sede1_id()))
    admin.post(f"/incidents/{inc_id}/review", data={"csrf_token": _tok(admin)})
    admin.post(f"/incidents/{inc_id}/resolve",
               data={"csrf_token": _tok(admin), "resolution": "Resuelta."})
    r = sede_client.post(f"/incidents/{inc_id}/reopen",
                         data={"csrf_token": _tok(sede_client), "reason": "x"}, follow_redirects=False)
    assert r.status_code == 403


# --- Confidentiality ---------------------------------------------------------
def test_student_cannot_see_confidential_internal_comments(admin, student_client):
    # Admin creates a NORMAL incident about the demo student with internal notes.
    inc_id = _create(admin, student_id="1", sede_id=str(_demo_student_sede_id()),
                     internal_notes="Nota interna reservada NO-VISIBLE", severity="low")
    html = student_client.get(f"/incidents/{inc_id}").text
    assert "NO-VISIBLE" not in html
    # And a confidential incident about the student is not viewable at all.
    conf_id = _create(admin, student_id="1", sede_id=str(_demo_student_sede_id()),
                      visibility="confidential", severity="low")
    assert student_client.get(f"/incidents/{conf_id}", follow_redirects=False).status_code == 403


# --- Tutor scope -------------------------------------------------------------
def test_tutor_can_report_only_for_assigned_student(tutor_client):
    svc = IncidentService(SessionLocal(), _tutor_identity())
    assigned = svc._tutor_student_ids()
    assert assigned, "expected the demo tutor to supervise at least one student"
    all_ids = {s.id for s in svc.repos.students.search()}
    not_assigned = (all_ids - assigned)
    a_id = next(iter(assigned))
    # Assigned student -> allowed.
    r_ok = tutor_client.post("/incidents",
                             data={"csrf_token": _tok(tutor_client), "title": "T",
                                   "incident_type": "absence", "severity": "low",
                                   "description": "d", "student_id": str(a_id)},
                             follow_redirects=False)
    assert r_ok.status_code == 303
    if not_assigned:
        n_id = next(iter(not_assigned))
        r_bad = tutor_client.post("/incidents",
                                  data={"csrf_token": _tok(tutor_client), "title": "T",
                                        "incident_type": "absence", "severity": "low",
                                        "description": "d", "student_id": str(n_id)},
                                  follow_redirects=False)
        assert r_bad.status_code == 403


# --- helpers -----------------------------------------------------------------
def _sede1_id() -> int:
    db = SessionLocal()
    sede = RepositoryBundle(db).sedes.active()[0]
    db.close()
    return sede.id


def _demo_student_sede_id() -> int:
    db = SessionLocal()
    st = RepositoryBundle(db).students.get(1)
    sid = st.sede_id
    db.close()
    return sid


def _tutor_identity() -> Identity:
    db = SessionLocal()
    user = RepositoryBundle(db).users.get_by_email("tutor@internado360.demo")
    ident = Identity(user_id=user.id, email=user.email, full_name=user.full_name,
                     role_code=user.role_code, role_name=user.role.name if user.role else "")
    db.close()
    return ident
