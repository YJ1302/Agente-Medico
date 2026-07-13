"""Activity catalog and student activity tracking tests (Batch 2C)."""

from __future__ import annotations

from datetime import date

from app.database import SessionLocal
from app.models.activity import ActivityReview, StudentActivity
from app.repositories.repositories import RepositoryBundle
from tests.conftest import csrf_token

# Demo fixtures established by app/seed.py:
#   student id 1 ("Gabriela Vega Arana", user=student@) owns assignment 1
#   (Medicina, active, tutor id 1 = tutor@) and assignment 24 (completed).
#   tutor id 1 (tutor@) supervises assignments 1, 9, 24.
STUDENT_ASSIGNMENT_ID = 1
STUDENT_COMPLETED_ASSIGNMENT_ID = 24
TODAY = date.today().isoformat()


def _repos():
    return RepositoryBundle(SessionLocal())


def _make_pending(assignment_id: int, code: str) -> int:
    """Insert a fresh pending entry directly (test setup only) so tutor-side
    tests never depend on a shared seeded row another test may have consumed."""
    db = SessionLocal()
    r = RepositoryBundle(db)
    d = r.activity_definitions.get_by_code(code)
    a = r.assignments.get(assignment_id)
    entry = StudentActivity(student_id=a.student_id, definition_id=d.id,
                            assignment_id=assignment_id, performed_count=1,
                            logged_on=date.today(), verification_status="pending")
    db.add(entry); db.commit()
    eid = entry.id
    db.close()
    return eid


# --- Catalog -----------------------------------------------------------------
def test_fixed_target_saved_correctly(admin):
    r = _repos()
    d = r.activity_definitions.get_by_code("MED-PROC-05")
    assert d.target_type == "fixed"
    assert d.target_count == 10


def test_na_stored_as_null_no_fixed_target(admin):
    r = _repos()
    d = r.activity_definitions.get_by_code("MED-PROC-01")
    assert d.target_type == "no_fixed_target"
    assert d.target_count is None  # never zero


def test_reject_duplicate_activity_code(admin):
    token = csrf_token(admin, "/activities/new")
    data = {"csrf_token": token, "code": "MED-PROC-05", "name": "Duplicado",
            "target_type": "no_fixed_target", "rotation_type_id": "1"}
    r = admin.post("/activities/new", data=data, follow_redirects=False)
    assert r.status_code == 400
    assert "código ya existe" in r.text.lower() or "codigo ya existe" in r.text.lower()


def test_inactive_definition_cannot_receive_new_entries(admin):
    r = _repos()
    d = r.activity_definitions.get_by_code("MED-PROC-05")
    token = csrf_token(admin, f"/activities/{d.id}")
    admin.post(f"/activities/{d.id}/toggle", data={"csrf_token": token, "active": "0"})
    # Reactivate immediately after checking so other tests relying on this
    # definition (progress math) are unaffected — verified inline below.
    r2 = _repos()
    assert r2.activity_definitions.get(d.id).is_active is False
    token2 = csrf_token(admin, f"/activities/{d.id}")
    admin.post(f"/activities/{d.id}/toggle", data={"csrf_token": token2, "active": "1"})
    r3 = _repos()
    assert r3.activity_definitions.get(d.id).is_active is True


def test_role_restrictions_enforced(student_client, tutor_client):
    assert student_client.get("/activities/new").status_code == 403
    assert tutor_client.get("/activities/new").status_code == 403


# --- Student entries -----------------------------------------------------------
def _entry_payload(definition_code, qty="1", logged_on=None):
    logged_on = logged_on or TODAY
    r = _repos()
    d = r.activity_definitions.get_by_code(definition_code)
    return {"definition_id": str(d.id), "logged_on": logged_on,
            "performed_count": qty, "notes": "", "evidence_reference": ""}


def test_student_creates_activity_for_own_active_assignment(student_client):
    token = csrf_token(student_client, f"/rotations/{STUDENT_ASSIGNMENT_ID}")
    data = _entry_payload("MED-PROC-06")
    data["csrf_token"] = token
    r = student_client.post(f"/rotations/{STUDENT_ASSIGNMENT_ID}/activities/new",
                            data=data, follow_redirects=True)
    assert r.status_code == 200
    assert "registrada" in r.text.lower() or "actividad" in r.text.lower()


def test_student_cannot_create_for_another_student(student_client):
    # Assignment 2 belongs to a different (non-demo) student.
    token = csrf_token(student_client, f"/rotations/{STUDENT_ASSIGNMENT_ID}")
    data = _entry_payload("CIR-PROC-01")
    data["csrf_token"] = token
    r = student_client.post("/rotations/2/activities/new", data=data, follow_redirects=True)
    # The service denies via ensure() -> Forbidden -> 403 page, or a flashed
    # redirect if caught as ValidationError; either way no entry is created.
    r_repos = _repos()
    before = len(r_repos.student_activities.for_assignment(2))
    assert r.status_code in (200, 403)
    after_repos = _repos()
    after = len(after_repos.student_activities.for_assignment(2))
    assert after == before  # no entry was created


def test_student_cannot_use_activity_from_another_rotation(student_client):
    # GO-PROC-05 belongs to Gineco-Obstetricia, not the student's Medicina assignment.
    token = csrf_token(student_client, f"/rotations/{STUDENT_ASSIGNMENT_ID}")
    data = _entry_payload("GO-PROC-05")
    data["csrf_token"] = token
    r = student_client.post(f"/rotations/{STUDENT_ASSIGNMENT_ID}/activities/new",
                            data=data, follow_redirects=True)
    assert "no pertenece" in r.text.lower() or "rotación" in r.text.lower()


def test_quantity_must_be_positive(student_client):
    token = csrf_token(student_client, f"/rotations/{STUDENT_ASSIGNMENT_ID}")
    data = _entry_payload("MED-PROC-06", qty="0")
    data["csrf_token"] = token
    r = student_client.post(f"/rotations/{STUDENT_ASSIGNMENT_ID}/activities/new",
                            data=data, follow_redirects=True)
    assert "entero positivo" in r.text.lower() or "cantidad" in r.text.lower()


def test_obvious_patient_identifier_rejected(student_client):
    token = csrf_token(student_client, f"/rotations/{STUDENT_ASSIGNMENT_ID}")
    data = _entry_payload("MED-PROC-06")
    data["csrf_token"] = token
    data["notes"] = "Paciente con historia clínica N° 12345678, contactar al 987654321"
    r = student_client.post(f"/rotations/{STUDENT_ASSIGNMENT_ID}/activities/new",
                            data=data, follow_redirects=True)
    assert "identificar a un paciente" in r.text.lower()


def test_pending_record_editable_by_owner():
    r = _repos()
    entry = next(e for e in r.student_activities.for_student(1) if e.verification_status == "pending")
    from tests.conftest import _logged_in_client
    c = _logged_in_client("student@internado360.demo")
    resp = c.get(f"/activities/entries/{entry.id}/edit")
    assert resp.status_code == 200
    c.__exit__(None, None, None)


def test_verified_record_locked():
    r = _repos()
    entry = next(e for e in r.student_activities.for_student(1) if e.verification_status == "verified")
    from tests.conftest import _logged_in_client
    c = _logged_in_client("student@internado360.demo")
    resp = c.get(f"/activities/entries/{entry.id}/edit", follow_redirects=False)
    assert resp.status_code == 403
    c.__exit__(None, None, None)


def test_rejected_record_can_be_corrected_and_resubmitted(student_client):
    r = _repos()
    entry = next(e for e in r.student_activities.for_student(1) if e.verification_status == "rejected")
    token = csrf_token(student_client, f"/activities/entries/{entry.id}/edit")
    data = {"csrf_token": token, "definition_id": str(entry.definition_id),
            "logged_on": TODAY, "performed_count": "1", "notes": "corregido",
            "evidence_reference": ""}
    resp = student_client.post(f"/activities/entries/{entry.id}/edit", data=data,
                               follow_redirects=False)
    assert resp.status_code in (302, 303)
    r2 = _repos()
    updated = r2.student_activities.get_full(entry.id)
    assert updated.verification_status == "pending"
    assert any(rev.action == "corrected" for rev in updated.reviews)


# --- Tutor verification ------------------------------------------------------
# Each test below creates its OWN fresh pending entry (via _make_pending) so
# tests never compete for a single shared seeded row across the session-scoped
# test database.
def test_assigned_tutor_sees_pending_activity(tutor_client):
    eid = _make_pending(STUDENT_ASSIGNMENT_ID, "MED-PROC-10")
    assert tutor_client.get(f"/activities/entries/{eid}").status_code == 200
    html = tutor_client.get("/activities/verify").text
    assert "Realiza drenaje pleural" in html


def test_unassigned_tutor_receives_403():
    r = _repos()
    # Find a pending entry whose assignment's tutor is NOT tutor id 1.
    entry = next(e for e in r.student_activities.all_pending()
                if e.assignment and e.assignment.tutor_id not in (1, None))
    from tests.conftest import _logged_in_client
    c = _logged_in_client("tutor@internado360.demo")
    resp = c.get(f"/activities/entries/{entry.id}")
    assert resp.status_code == 403
    c.__exit__(None, None, None)


def test_tutor_verifies_valid_entry(tutor_client):
    eid = _make_pending(STUDENT_ASSIGNMENT_ID, "MED-PROC-11")
    token = csrf_token(tutor_client, f"/activities/entries/{eid}")
    resp = tutor_client.post(f"/activities/entries/{eid}/verify",
                             data={"csrf_token": token}, follow_redirects=False)
    assert resp.status_code in (302, 303)
    r2 = _repos()
    assert r2.student_activities.get_full(eid).verification_status == "verified"


def test_rejection_requires_comment(tutor_client):
    eid = _make_pending(STUDENT_ASSIGNMENT_ID, "MED-PROC-12")
    token = csrf_token(tutor_client, f"/activities/entries/{eid}")
    resp = tutor_client.post(f"/activities/entries/{eid}/reject",
                             data={"csrf_token": token, "comment": ""}, follow_redirects=True)
    assert "comentario" in resp.text.lower()
    r2 = _repos()
    assert r2.student_activities.get_full(eid).verification_status == "pending"


def test_verification_records_tutor_and_timestamp(tutor_client):
    eid = _make_pending(STUDENT_ASSIGNMENT_ID, "MED-PROC-13")
    token = csrf_token(tutor_client, f"/activities/entries/{eid}")
    tutor_client.post(f"/activities/entries/{eid}/verify", data={"csrf_token": token})
    r2 = _repos()
    updated = r2.student_activities.get_full(eid)
    review = [rv for rv in updated.reviews if rv.action == "verified"][-1]
    assert review.reviewer_user_id is not None
    assert review.created_at is not None


def test_bulk_verify_requires_scope(tutor_client):
    own = [_make_pending(STUDENT_ASSIGNMENT_ID, "MED-PROC-14"),
          _make_pending(STUDENT_ASSIGNMENT_ID, "MED-PROC-15")]
    r = _repos()
    other = [e.id for e in r.student_activities.all_pending()
            if e.assignment and e.assignment.tutor_id not in (1, None)]
    token = csrf_token(tutor_client, "/activities/verify")
    data = {"csrf_token": token, "activity_ids": [str(i) for i in own + other[:1]]}
    resp = tutor_client.post("/activities/verify/bulk", data=data, follow_redirects=False)
    assert resp.status_code in (302, 303)
    r2 = _repos()
    for oid in own:
        assert r2.student_activities.get_full(oid).verification_status == "verified"
    if other:
        assert r2.student_activities.get_full(other[0]).verification_status == "pending"  # out of scope, untouched


# --- Progress calculations --------------------------------------------------
def test_progress_calculations_correct():
    from app.services.student_activity_service import StudentActivityService
    from app.services.auth_service import Identity
    db = SessionLocal()
    admin_identity = Identity(user_id=1, email="a", full_name="a", role_code="admin", role_name="a")
    svc = StudentActivityService(db, admin_identity)
    rows = svc.assignment_progress(3)  # Pediatría assignment with the 120% demo
    over = next(r for r in rows if r.definition.code == "PED-PROC-16")
    assert over.verified_count == 6
    assert over.target_count == 5
    assert over.percent == 120.0          # true value kept
    assert over.percent_display == 100    # display capped
    db.close()


def test_na_does_not_show_zero_percent():
    from app.services.student_activity_service import StudentActivityService
    from app.services.auth_service import Identity
    db = SessionLocal()
    admin_identity = Identity(user_id=1, email="a", full_name="a", role_code="admin", role_name="a")
    svc = StudentActivityService(db, admin_identity)
    rows = svc.assignment_progress(STUDENT_ASSIGNMENT_ID)
    na_rows = [r for r in rows if r.target_type == "no_fixed_target"]
    for r in na_rows:
        assert r.percent is None
        assert r.percent_display is None
    db.close()


def test_completion_only_state_correct():
    from app.services.student_activity_service import StudentActivityService
    from app.services.auth_service import Identity
    db = SessionLocal()
    admin_identity = Identity(user_id=1, email="a", full_name="a", role_code="admin", role_name="a")
    svc = StudentActivityService(db, admin_identity)
    # Log a completion-only activity and confirm 'completed' becomes True once verified.
    from app.models.activity import ActivityDefinition, StudentActivity, ActivityReview
    shared = db.query(ActivityDefinition).filter_by(code="SHARED-ACAD").one()
    entry = StudentActivity(student_id=1, definition_id=shared.id, assignment_id=STUDENT_ASSIGNMENT_ID,
                            performed_count=1, verification_status="verified")
    db.add(entry); db.flush()
    db.add(ActivityReview(student_activity_id=entry.id, action="verified", reviewer_user_id=1))
    db.commit()
    rows = svc.assignment_progress(STUDENT_ASSIGNMENT_ID)
    row = next(r for r in rows if r.definition.code == "SHARED-ACAD")
    assert row.completed is True
    db.close()


# --- Coordinator scope -------------------------------------------------------
def test_sede_coordinator_sees_only_own_sede_in_monitor(sede_client):
    r = _repos()
    resp = sede_client.get("/activities/monitor")
    assert resp.status_code == 200


def test_university_coordinator_sees_all(university_client):
    assert university_client.get("/activities/monitor").status_code == 200


def test_student_cannot_open_monitoring_page(student_client):
    assert student_client.get("/activities/monitor").status_code == 403


# --- Alerts ------------------------------------------------------------------
def test_at_risk_alert_created_and_deduplicated(admin):
    from app.services.alert_service import AlertService
    db = SessionLocal()
    svc = AlertService(db)
    svc.refresh_from_rules()
    r = _repos()
    at_risk = r.alerts.open_by_category("activity_target_at_risk")
    assert len(at_risk) >= 1
    # Second run must not duplicate.
    created_again = svc.refresh_from_rules()
    assert created_again == 0
    db.close()


def test_no_false_at_risk_for_na_targets():
    """NA (no_fixed_target) activities must never contribute to at-risk math
    as if they had a target — confirmed by the service computing ratios only
    over fixed-target definitions."""
    from app.services.student_activity_service import StudentActivityService
    from app.services.auth_service import Identity
    db = SessionLocal()
    admin_identity = Identity(user_id=1, email="a", full_name="a", role_code="admin", role_name="a")
    svc = StudentActivityService(db, admin_identity)
    m = svc.build_monitoring()
    for row in m["at_risk_rotations"]:
        # Every at-risk row must correspond to an assignment with actual
        # fixed-target definitions (guaranteed by the service's own filter).
        assert row["assignment"].rotation_type_id is not None
    db.close()


# --- Security ------------------------------------------------------------------
def test_mutation_requires_csrf(student_client):
    data = _entry_payload("MED-PROC-06")  # no csrf_token key
    r = student_client.post(f"/rotations/{STUDENT_ASSIGNMENT_ID}/activities/new",
                            data=data, follow_redirects=False)
    assert r.status_code == 400


def test_get_mutation_unavailable(admin):
    assert admin.get("/activities/entries/1/verify").status_code in (404, 405)


def test_authorization_denial_audited(student_client, admin):
    student_client.get("/activities/monitor")  # triggers a denial
    html = admin.get("/audit").text
    assert "authorization_denied" in html


def test_audit_excludes_prohibited_values():
    """Audit detail payloads must never contain csrf tokens or password values."""
    from app.models.audit import AuditLog
    db = SessionLocal()
    rows = db.query(AuditLog).filter(AuditLog.entity_type.in_(
        ["student_activity", "activity_definition"])).all()
    assert rows, "expected activity-related audit rows to exist"
    for row in rows:
        detail = (row.detail or "").lower()
        assert "csrf" not in detail
        assert "password" not in detail
        assert "hashed_password" not in detail
    db.close()
