"""Sede management tests (Batch 2A)."""

from __future__ import annotations

from tests.conftest import csrf_token

BASE = {"name": "Hospital Demo Uno", "short_name": "H. Demo 1",
        "sede_type": "hospital", "institution_type_id": "1", "city": "Lima",
        "address": "Av. Demo 123"}


def _create(client, overrides):
    token = csrf_token(client, "/sedes/new")
    data = dict(BASE)
    data.update(overrides)
    data["csrf_token"] = token
    return client.post("/sedes/new", data=data, follow_redirects=False)


def test_admin_creates_valid_sede(admin):
    r = _create(admin, {"name": "Hospital Nuevo Válido", "short_name": "H. Nuevo Val"})
    assert r.status_code in (302, 303)
    assert "/sedes/" in r.headers.get("location", "")


def test_reject_duplicate_full_name(admin):
    _create(admin, {"name": "Hospital Repetido X", "short_name": "H. Rep X1"})
    r = _create(admin, {"name": "Hospital Repetido X", "short_name": "H. Rep X2"})
    assert r.status_code == 400
    assert "nombre" in r.text.lower()


def test_reject_duplicate_short_name(admin):
    _create(admin, {"name": "Hospital Corto A", "short_name": "H. CortoDup"})
    r = _create(admin, {"name": "Hospital Corto B", "short_name": "H. CortoDup"})
    assert r.status_code == 400
    assert "corto" in r.text.lower()


def test_reject_invalid_sede_type(admin):
    r = _create(admin, {"name": "Hospital Tipo Malo", "short_name": "H. TipoMalo",
                        "sede_type": "clinica"})
    assert r.status_code == 400


def test_normal_deactivation_blocked_with_active_rotations(admin):
    # Sede id 1 (H. Vitarte) has active/planned rotations in the seed.
    token = csrf_token(admin, "/sedes/1")
    r = admin.post("/sedes/1/toggle",
                   data={"csrf_token": token, "active": "0"},
                   follow_redirects=True)
    assert "rotación" in r.text.lower() or "no se puede desactivar" in r.text.lower()
    # It must remain active.
    assert "Activa" in admin.get("/sedes/1").text


def test_admin_forced_deactivation_requires_reason(admin):
    token = csrf_token(admin, "/sedes/1")
    r = admin.post("/sedes/1/toggle",
                   data={"csrf_token": token, "active": "0", "force": "1", "reason": ""},
                   follow_redirects=True)
    assert "motivo" in r.text.lower()


def test_admin_forced_deactivation_succeeds_with_reason(admin):
    token = csrf_token(admin, "/sedes/3")
    r = admin.post("/sedes/3/toggle",
                   data={"csrf_token": token, "active": "0", "force": "1",
                         "reason": "Cierre temporal por auditoría"},
                   follow_redirects=True)
    assert "Inactiva" in r.text


def test_university_cannot_force_deactivate(university_client):
    # Reactivate scenario aside, university coordinator forcing must be denied.
    token = csrf_token(university_client, "/sedes/2")
    r = university_client.post("/sedes/2/toggle",
                               data={"csrf_token": token, "active": "0",
                                     "force": "1", "reason": "intento"},
                               follow_redirects=False)
    assert r.status_code == 403


def test_soft_delete_restricted_to_admin(university_client):
    token = csrf_token(university_client, "/sedes/5")
    r = university_client.post("/sedes/5/delete",
                               data={"csrf_token": token, "reason": "x"},
                               follow_redirects=False)
    assert r.status_code == 403


def test_sede_coordinator_cannot_view_other_sede(sede_client):
    # The demo sede coordinator (sede@) coordinates sede 1; other sedes are 403.
    assert sede_client.get("/sedes/4").status_code == 403
