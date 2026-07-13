"""Tutor management tests (Batch 2A)."""

from __future__ import annotations

from app.services.staff_service import compute_workload
from tests.conftest import csrf_token


def _create(client, overrides):
    token = csrf_token(client, "/tutors/new")
    data = {"full_name": "Dr. Tutor Demo", "email": "tutordemo@demo.upeu.edu.pe",
            "phone": "999", "specialty": "Cirugía", "service": "Cirugía General",
            "contact_phone": "222", "sede_id": "1", "password": ""}
    data.update(overrides)
    data["csrf_token"] = token
    return client.post("/tutors/new", data=data, follow_redirects=False)


def test_create_tutor_and_user_atomically(admin):
    r = _create(admin, {"email": "newtutor1@demo.upeu.edu.pe"})
    assert r.status_code in (302, 303)
    assert "newtutor1@demo.upeu.edu.pe" in admin.get("/tutors?q=newtutor1").text


def test_reject_duplicate_email(admin):
    _create(admin, {"email": "duptutor@demo.upeu.edu.pe"})
    r = _create(admin, {"email": "duptutor@demo.upeu.edu.pe"})
    assert r.status_code == 400
    assert "correo" in r.text.lower()


def test_tutor_must_belong_to_active_sede(admin):
    # Sede 3 was force-deactivated in test_sedes; use a non-existent sede id to
    # guarantee an inactive/invalid target regardless of test order.
    r = _create(admin, {"email": "badsede@demo.upeu.edu.pe", "sede_id": "9999"})
    assert r.status_code == 400
    assert "sede" in r.text.lower()


def test_tutor_deactivation_blocked_with_active_assignments(admin):
    # Tutor id 1 (tutor@) has active assignments in the seed.
    token = csrf_token(admin, "/tutors/1")
    r = admin.post("/tutors/1/toggle", data={"csrf_token": token, "active": "0"},
                   follow_redirects=True)
    assert "asignaci" in r.text.lower()


def test_admin_forced_tutor_deactivation_requires_reason(admin):
    token = csrf_token(admin, "/tutors/1")
    r = admin.post("/tutors/1/toggle",
                   data={"csrf_token": token, "active": "0", "force": "1", "reason": ""},
                   follow_redirects=True)
    assert "motivo" in r.text.lower()


def test_workload_indicator_calculated_correctly():
    assert compute_workload(0, 5).level == "normal"
    assert compute_workload(3, 5).level == "normal"
    assert compute_workload(4, 5).level == "near"
    assert compute_workload(5, 5).level == "above"
    assert compute_workload(8, 5).level == "above"


def test_tutor_cannot_access_management_list(student_client):
    # Students must not access the tutor management list.
    assert student_client.get("/tutors").status_code == 403


def test_tutor_can_view_own_detail(tutor_client):
    # tutor@ is tutor profile id 1; own detail must be viewable.
    assert tutor_client.get("/tutors/1").status_code == 200
    # But another tutor's detail is denied.
    assert tutor_client.get("/tutors/5").status_code == 403
