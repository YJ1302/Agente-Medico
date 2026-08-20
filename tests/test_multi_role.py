"""Multi-role support: an account holding more than one role.

Covers the login role-picker, the mid-session role switcher, the admin
Users & Roles grant/revoke flow, and the bulk-import fix that lets a row
attach a role to an existing account (e.g. a Sede Coordinator who is also a
Tutor) instead of erroring on a duplicate email.

IMPORTANT: this file must never grant a second role to one of the 5 seeded
demo accounts (admin@/coordinator@/sede@/tutor@/student@internado360.demo).
The whole test session shares one database with no per-test rollback (see
conftest.py), and other test files' fixtures (``tutor_client``, `sede_client`
etc.) assume those specific accounts stay single-role and land straight on
/dashboard after login. Every test here creates its own disposable account
instead.
"""

from __future__ import annotations

import io
import json

import openpyxl

from app.database import SessionLocal
from app.models.user import ROLE_ADMIN, ROLE_SEDE_COORDINATOR, ROLE_TUTOR, ROLE_UNIVERSITY_COORDINATOR
from app.repositories.repositories import RepositoryBundle
from app.services.auth_service import Identity
from app.services.import_service import ImportService
from app.services.staff_service import TutorService
from app.services.user_admin_service import UserAdminService
from app.services.validators import ValidationError
from tests.conftest import csrf_token

_CT = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
_TEST_PASSWORD = "TestPass123!"
_counter = [0]


def _identity(email: str) -> Identity:
    db = SessionLocal()
    u = RepositoryBundle(db).users.get_by_email(email)
    ident = Identity(user_id=u.id, email=u.email, full_name=u.full_name,
                     role_code=u.role_code, role_name=u.role.name if u.role else "")
    db.close()
    return ident


def _first_sede_name() -> str:
    db = SessionLocal()
    name = RepositoryBundle(db).sedes.active()[0].name
    db.close()
    return name


def _new_tutor_account(*, second_role: str | None = None) -> str:
    """Create a brand-new, disposable Tutor account (known password) —
    never one of the shared seeded demo logins. Optionally grants a second,
    profile-free role (Admin/University Coordinator) on top, avoiding the
    Sede Coordinator "one active principal per sede" guard entirely, which
    this helper has no need to navigate."""
    _counter[0] += 1
    email = f"multirole.tutor.{_counter[0]}@demo.upeu.edu.pe"
    db = SessionLocal()
    admin_ident = _identity("admin@internado360.demo")
    repos = RepositoryBundle(db)
    sede_id = repos.sedes.active()[0].id
    data = {"full_name": f"Dedicated Test Tutor {_counter[0]}", "email": email,
            "phone": "999", "sede_id": str(sede_id), "specialty": "General",
            "password": _TEST_PASSWORD}
    tutor, _ = TutorService(db, admin_ident).create(data)
    if second_role is not None:
        role = repos.roles.get_by_code(second_role)
        repos.user_roles.grant(tutor.user_id, role.id)
        db.commit()
    db.close()
    return email


def _xlsx(sheet: str, headers: list, rows: list) -> bytes:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = sheet
    ws.append(headers)
    for r in rows:
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _run_import(ident, profile, raw, mode="valid_only"):
    db = SessionLocal()
    svc = ImportService(db, ident)
    batch = svc.create_batch(profile, "data.xlsx", _CT, raw)
    sheet = svc.sheets(batch)[0]
    svc.set_sheet(batch.id, sheet)
    b = svc.repos.import_batches.get(batch.id)
    svc.set_mapping(batch.id, json.loads(b.mapping_json), mode)
    svc.validate_batch(batch.id)
    svc.confirm_batch(batch.id)
    out = svc.repos.import_batches.get(batch.id)
    db.close()
    return out


# --- Login: single-role accounts are unaffected -----------------------------
def test_single_role_login_goes_straight_to_dashboard(client):
    email = _new_tutor_account()
    r = client.post("/login", data={"email": email, "password": _TEST_PASSWORD},
                    follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/dashboard"


# --- Login: multi-role accounts get a picker --------------------------------
def test_multi_role_login_shows_choose_role_page(client):
    email = _new_tutor_account(second_role=ROLE_UNIVERSITY_COORDINATOR)
    r = client.post("/login", data={"email": email, "password": _TEST_PASSWORD},
                    follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/login/choose-role"
    page = client.get("/login/choose-role")
    assert page.status_code == 200
    assert "Coordinador Universitario" in page.text and "Tutor" in page.text
    # Protected pages still redirect to /login — picking a role isn't optional.
    dash = client.get("/dashboard", follow_redirects=False)
    assert dash.status_code == 303
    assert dash.headers["location"] == "/login"


def test_choose_role_activates_selected_role_and_rejects_unheld_role(client):
    email = _new_tutor_account(second_role=ROLE_UNIVERSITY_COORDINATOR)
    # /login and /login/choose-role carry no CSRF field, same as the plain
    # login form — no session identity exists yet to protect.
    client.post("/login", data={"email": email, "password": _TEST_PASSWORD})
    r = client.post("/login/choose-role", data={"role_code": ROLE_TUTOR},
                    follow_redirects=True)
    assert r.status_code == 200
    assert "Tutor" in r.text

    # A role this account never held (e.g. admin) must not be assumable —
    # switch-role silently ignores it and the active role stays Tutor.
    token = csrf_token(client, "/dashboard")
    r2 = client.post("/switch-role", data={"role_code": ROLE_ADMIN, "csrf_token": token},
                     follow_redirects=True)
    assert "Administrador" not in r2.text
    assert "Tutor" in r2.text


def test_switch_role_moves_between_held_roles(client):
    email = _new_tutor_account(second_role=ROLE_UNIVERSITY_COORDINATOR)
    client.post("/login", data={"email": email, "password": _TEST_PASSWORD})
    # This account now holds 2 roles, so login lands on the picker, not the
    # dashboard directly — resolve it first.
    dash = client.post("/login/choose-role", data={"role_code": ROLE_TUTOR}, follow_redirects=True)
    assert "Tutor" in dash.text

    token = csrf_token(client, "/dashboard")
    r = client.post("/switch-role",
                    data={"role_code": ROLE_UNIVERSITY_COORDINATOR, "csrf_token": token},
                    follow_redirects=True)
    assert "Coordinador Universitario" in r.text
    # And back again.
    token2 = csrf_token(client, "/dashboard")
    r2 = client.post("/switch-role", data={"role_code": ROLE_TUTOR, "csrf_token": token2},
                     follow_redirects=True)
    assert "Tutor" in r2.text


# --- Grant/revoke service ----------------------------------------------------
def test_revoke_last_role_is_blocked():
    """student@internado360.demo is read here, never mutated: the revoke
    call must raise before touching any data."""
    db = SessionLocal()
    admin_ident = _identity("admin@internado360.demo")
    user = RepositoryBundle(db).users.get_by_email("student@internado360.demo")
    svc = UserAdminService(db, admin_ident)
    try:
        svc.revoke_role(user.id, "student")
        assert False, "should not allow revoking the only role"
    except ValidationError as e:
        assert "role" in e.errors
    db.close()


def test_grant_then_revoke_profile_free_role():
    email = _new_tutor_account()
    db = SessionLocal()
    admin_ident = _identity("admin@internado360.demo")
    user = RepositoryBundle(db).users.get_by_email(email)
    svc = UserAdminService(db, admin_ident)
    svc.grant_profile_free_role(user.id, ROLE_ADMIN)
    roles = {r.code for r in svc.roles_for(user)}
    assert ROLE_ADMIN in roles
    svc.revoke_role(user.id, ROLE_ADMIN)
    roles_after = {r.code for r in svc.roles_for(user)}
    assert ROLE_ADMIN not in roles_after
    db.close()


# --- Admin Users & Roles page -------------------------------------------------
def test_non_admin_cannot_access_users_page(sede_client):
    r = sede_client.get("/users")
    assert r.status_code == 403


def test_admin_can_grant_role_via_users_page(admin):
    email = _new_tutor_account()
    db = SessionLocal()
    target_user = RepositoryBundle(db).users.get_by_email(email)
    db.close()
    token = csrf_token(admin, "/users")
    r = admin.post(f"/users/{target_user.id}/roles/{ROLE_ADMIN}/grant",
                   data={"csrf_token": token}, follow_redirects=True)
    assert r.status_code == 200
    db = SessionLocal()
    roles = {role.code for role in RepositoryBundle(db).user_roles.roles_for_user(target_user.id)}
    db.close()
    assert ROLE_ADMIN in roles


# --- Bulk import: attach a second role instead of erroring on duplicate email
_STAFF_HEADERS = ["Nombre completo", "Correo", "Teléfono", "Especialidad", "Sede"]


def test_import_tutor_row_attaches_to_existing_coordinator_account():
    sede_name = _first_sede_name()
    email = "dualrole1@demo.upeu.edu.pe"
    coord_raw = _xlsx("Coordinadores", _STAFF_HEADERS,
                      [["Dual Role Person", email, "999", "Pediatría", sede_name]])
    _run_import(_identity("admin@internado360.demo"), "coordinators", coord_raw)

    db = SessionLocal()
    user = RepositoryBundle(db).users.get_by_email(email)
    assert user is not None
    assert user.sede_coordinator_profile is not None
    assert user.tutor_profile is None
    db.close()

    tutor_raw = _xlsx("Tutores", _STAFF_HEADERS,
                      [["Dual Role Person", email, "999", "Pediatría", sede_name]])
    batch = _run_import(_identity("admin@internado360.demo"), "tutors", tutor_raw)
    assert batch.failed_count == 0, "duplicate-email row should attach, not fail"

    db = SessionLocal()
    user = RepositoryBundle(db).users.get_by_email(email)
    assert user.sede_coordinator_profile is not None, "original role kept"
    assert user.tutor_profile is not None, "new role attached to the same account"
    role_codes = {r.code for r in RepositoryBundle(db).user_roles.roles_for_user(user.id)}
    assert role_codes == {ROLE_SEDE_COORDINATOR, ROLE_TUTOR}
    db.close()


def test_reimporting_same_tutor_updates_in_place_not_duplicated():
    sede_name = _first_sede_name()
    email = "reimporttutor1@demo.upeu.edu.pe"
    raw1 = _xlsx("Tutores", _STAFF_HEADERS,
                [["Original Name", email, "111", "Cirugía", sede_name]])
    _run_import(_identity("admin@internado360.demo"), "tutors", raw1)

    db = SessionLocal()
    user = RepositoryBundle(db).users.get_by_email(email)
    tutor_id_before = user.tutor_profile.id
    db.close()

    raw2 = _xlsx("Tutores", _STAFF_HEADERS,
                [["Updated Name", email, "222", "Cirugía", sede_name]])
    batch = _run_import(_identity("admin@internado360.demo"), "tutors", raw2)
    assert batch.failed_count == 0, "re-importing the same tutor should update, not error"

    db = SessionLocal()
    user = RepositoryBundle(db).users.get_by_email(email)
    assert user.tutor_profile.id == tutor_id_before, "same profile row, updated not duplicated"
    assert user.full_name == "Updated Name"
    assert user.tutor_profile.contact_phone == "222"
    db.close()
