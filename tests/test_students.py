"""Student management tests — validation and CRUD."""

from __future__ import annotations

from tests.conftest import csrf_token

BASE = {
    "student_code": "T1000", "full_name": "Interno Prueba",
    "email": "t1000@demo.upeu.edu.pe", "document_id": "", "phone": "999888777",
    "cycle": "13", "institution_type_id": "1", "sede_id": "1",
    "internship_start": "2026-01-01", "internship_end": "2027-01-01",
    "profile_status": "complete",
}


def _submit(admin, overrides):
    token = csrf_token(admin, "/students/new")
    data = dict(BASE)
    data.update(overrides)
    data["csrf_token"] = token
    return admin.post("/students/new", data=data, follow_redirects=False)


def test_create_valid_student(admin):
    r = _submit(admin, {"student_code": "T1001", "email": "t1001@demo.upeu.edu.pe"})
    assert r.status_code in (302, 303)
    assert "/students/" in r.headers.get("location", "")


def test_reject_duplicate_student_code(admin):
    _submit(admin, {"student_code": "DUP01", "email": "dup1@demo.upeu.edu.pe"})
    r = _submit(admin, {"student_code": "DUP01", "email": "dup2@demo.upeu.edu.pe"})
    assert r.status_code == 400
    assert "ya existe" in r.text


def test_reject_invalid_cycle(admin):
    r = _submit(admin, {"student_code": "T1002", "email": "t1002@demo.upeu.edu.pe",
                        "cycle": "99"})
    assert r.status_code == 400
    assert "válida" in r.text or "obligatorio" in r.text


def test_reject_end_before_start(admin):
    r = _submit(admin, {"student_code": "T1003", "email": "t1003@demo.upeu.edu.pe",
                        "internship_start": "2026-06-01",
                        "internship_end": "2026-01-01"})
    assert r.status_code == 400
    assert "posterior" in r.text


def test_reject_duplicate_email(admin):
    _submit(admin, {"student_code": "EM01", "email": "same@demo.upeu.edu.pe"})
    r = _submit(admin, {"student_code": "EM02", "email": "same@demo.upeu.edu.pe"})
    assert r.status_code == 400
    assert "correo" in r.text.lower()


def test_list_search_and_filter(admin):
    assert admin.get("/students?q=Prueba").status_code == 200
    assert admin.get("/students?cycle=13&institution=MINSA").status_code == 200
