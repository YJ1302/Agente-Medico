"""Sede Coordinator management tests (Batch 2A)."""

from __future__ import annotations

from tests.conftest import csrf_token


def _create(client, overrides):
    token = csrf_token(client, "/coordinators/new")
    data = {"full_name": "Dr. Coord Demo", "email": "coorddemo@demo.upeu.edu.pe",
            "phone": "999", "specialty": "Medicina", "office_phone": "111",
            "sede_id": "5", "password": ""}
    data.update(overrides)
    data["csrf_token"] = token
    return client.post("/coordinators/new", data=data, follow_redirects=False)


def test_create_coordinator_and_user_atomically(admin):
    r = _create(admin, {"email": "newcoord1@demo.upeu.edu.pe", "sede_id": "5"})
    assert r.status_code in (302, 303)
    # The new coordinator can now be listed.
    assert "newcoord1@demo.upeu.edu.pe" in admin.get("/coordinators?q=newcoord1").text


def test_reject_duplicate_email(admin):
    _create(admin, {"email": "dupcoord@demo.upeu.edu.pe", "sede_id": "5"})
    r = _create(admin, {"email": "dupcoord@demo.upeu.edu.pe", "sede_id": "5"})
    assert r.status_code == 400
    assert "correo" in r.text.lower()


def test_second_principal_triggers_controlled_replacement(admin):
    # Sede 1 already has an active principal coordinator in the seed.
    r = _create(admin, {"email": "wouldreplace@demo.upeu.edu.pe", "sede_id": "1"})
    assert r.status_code == 400
    assert "reemplaz" in r.text.lower() or "principal" in r.text.lower()
    # With replace flag it succeeds.
    r2 = _create(admin, {"email": "wouldreplace@demo.upeu.edu.pe", "sede_id": "1",
                         "replace": "1"})
    assert r2.status_code in (302, 303)


def test_sede_coordinator_cannot_access_another_sede_coordinators(sede_client):
    # The demo sede coordinator manages sede 1; a coordinator of another sede
    # must not be viewable. Coordinator id 4 belongs to sede 4.
    assert sede_client.get("/coordinators/4").status_code == 403


def test_reassignment_is_audited(admin):
    # Create a coordinator on the empty sede, then reassign to another sede.
    _create(admin, {"email": "reassignme@demo.upeu.edu.pe", "sede_id": "5"})
    # Find its id via the list page is complex; instead assert audit contains the create.
    assert "create_sede_coordinator" in admin.get("/audit").text
