"""CSRF protection and safe-method tests."""

from __future__ import annotations

from tests.conftest import csrf_token

VALID = {
    "student_code": "CSRF01", "full_name": "Csrf Prueba",
    "email": "csrf01@demo.upeu.edu.pe", "document_id": "", "phone": "",
    "cycle": "13", "institution_type_id": "1", "sede_id": "1",
    "internship_start": "2026-01-01", "internship_end": "2027-01-01",
    "profile_status": "complete",
}


def test_valid_csrf_succeeds(admin):
    token = csrf_token(admin, "/students/new")
    data = dict(VALID)
    data["csrf_token"] = token
    r = admin.post("/students/new", data=data, follow_redirects=False)
    assert r.status_code in (302, 303)


def test_missing_csrf_rejected(admin):
    data = dict(VALID)
    data["student_code"] = "CSRF02"
    data["email"] = "csrf02@demo.upeu.edu.pe"
    r = admin.post("/students/new", data=data, follow_redirects=False)
    assert r.status_code == 400


def test_invalid_csrf_rejected(admin):
    data = dict(VALID)
    data["student_code"] = "CSRF03"
    data["email"] = "csrf03@demo.upeu.edu.pe"
    data["csrf_token"] = "not-a-real-token"
    r = admin.post("/students/new", data=data, follow_redirects=False)
    assert r.status_code == 400


def test_mutation_via_get_unavailable(admin):
    # Deletion must not be reachable through GET.
    r = admin.get("/students/1/delete")
    assert r.status_code in (404, 405)
