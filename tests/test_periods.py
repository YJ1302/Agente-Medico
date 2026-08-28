"""Academic period management tests (year rollover).

Covers the CRUD workflow, the "generate full year" action, the current-period
flag, deletion guards, role scope, and the top-bar ``/set-period`` switcher
feeding the rotations list default filter.
"""

from __future__ import annotations

from app.database import SessionLocal
from app.repositories.repositories import RepositoryBundle
from tests.conftest import csrf_token

# A far-future year no other test or the seed touches.
ROLLOVER_YEAR = 2091


def _repos():
    return RepositoryBundle(SessionLocal())


def _post(client, path, **data):
    token = csrf_token(client, "/periods")
    return client.post(path, data={"csrf_token": token, **data}, follow_redirects=False)


# -- visibility / scope ---------------------------------------------------

def test_periods_page_visible_to_admin(admin):
    r = admin.get("/periods")
    assert r.status_code == 200
    assert "Periodos Académicos" in r.text


def test_periods_page_visible_to_university(university_client):
    assert university_client.get("/periods").status_code == 200


def test_periods_page_forbidden_for_tutor_and_student(tutor_client, student_client):
    assert tutor_client.get("/periods").status_code == 403
    assert student_client.get("/periods").status_code == 403


def test_generate_year_forbidden_for_sede_coordinator(sede_client):
    # Sede coordinators never see /periods; mint a CSRF token from a page they
    # do have (their own sede) so the failure is the role guard, not CSRF.
    sede_client.get("/dashboard")  # ensure a session exists
    r = sede_client.post("/periods/generate-year",
                         data={"csrf_token": "x", "year": str(ROLLOVER_YEAR)},
                         follow_redirects=False)
    # The role guard resolves before csrf_protect, so this is a clean 403.
    assert r.status_code == 403


# -- generate full year -------------------------------------------------

def test_generate_year_creates_six_bimesters(admin):
    r = _post(admin, "/periods/generate-year", year=str(ROLLOVER_YEAR))
    assert r.status_code == 303
    created = _repos().periods.for_year(ROLLOVER_YEAR)
    assert len(created) == 6
    assert {p.ordinal for p in created} == {1, 2, 3, 4, 5, 6}
    assert all(p.code.endswith(str(ROLLOVER_YEAR)) for p in created)


def test_generate_year_twice_is_idempotent(admin):
    _post(admin, "/periods/generate-year", year=str(ROLLOVER_YEAR + 1))
    r = _post(admin, "/periods/generate-year", year=str(ROLLOVER_YEAR + 1))
    assert r.status_code == 303  # redirects back with a warning, no crash
    assert len(_repos().periods.for_year(ROLLOVER_YEAR + 1)) == 6


def test_generate_year_can_set_current(admin):
    _post(admin, "/periods/generate-year", year=str(ROLLOVER_YEAR + 2), set_current="1")
    current = _repos().periods.current()
    assert current is not None and current.year == ROLLOVER_YEAR + 2
    assert current.ordinal == 1
    # exactly one current period platform-wide
    assert sum(1 for p in _repos().periods.ordered() if p.is_current) == 1


# -- single period CRUD -----------------------------------------------

def test_create_single_period_and_reject_duplicate_code(admin):
    payload = dict(name="Periodo Especial 2099", code="ESP-2099", year="2099",
                   ordinal="1", start_date="2099-01-01", end_date="2099-02-28")
    assert _post(admin, "/periods/new", **payload).status_code == 303
    assert _repos().periods.by_code("ESP-2099") is not None

    dup = _post(admin, "/periods/new", **payload)
    assert dup.status_code == 400
    assert "Ya existe un periodo con ese código" in dup.text


def test_edit_period_changes_dates(admin):
    _post(admin, "/periods/new", name="Editable 2098", code="EDIT-2098", year="2098",
          ordinal="3", start_date="2098-05-01", end_date="2098-06-30")
    pid = _repos().periods.by_code("EDIT-2098").id
    r = _post(admin, f"/periods/{pid}/edit", name="Editable 2098", code="EDIT-2098",
              year="2098", ordinal="3", start_date="2098-05-01", end_date="2098-07-15")
    assert r.status_code == 303
    assert _repos().periods.get(pid).end_date.isoformat() == "2098-07-15"


# -- current flag + deletion guard ----------------------------------

def test_set_current_moves_the_flag(admin):
    _post(admin, "/periods/generate-year", year=str(ROLLOVER_YEAR + 3))
    target = _repos().periods.for_year(ROLLOVER_YEAR + 3)[4]  # ordinal 5
    r = _post(admin, f"/periods/{target.id}/set-current")
    assert r.status_code == 303
    assert _repos().periods.current().id == target.id


def test_delete_empty_period_ok_but_blocked_when_in_use(admin):
    _post(admin, "/periods/new", name="Borrable 2097", code="DEL-2097", year="2097",
          ordinal="1", start_date="2097-01-01", end_date="2097-02-28")
    pid = _repos().periods.by_code("DEL-2097").id
    assert _post(admin, f"/periods/{pid}/delete").status_code == 303
    assert _repos().periods.get(pid) is None

    # A seeded period with rotations cannot be deleted.
    r = _repos()
    used = next(p for p in r.periods.ordered() if r.periods.assignment_count(p.id) > 0)
    resp = _post(admin, f"/periods/{used.id}/delete")
    assert resp.status_code == 303  # redirect with warning
    assert _repos().periods.get(used.id) is not None


# -- top-bar period switcher -----------------------------------------

def test_set_period_scopes_rotations_list(admin):
    _post(admin, "/periods/generate-year", year=str(ROLLOVER_YEAR + 4))
    empty_period = _repos().periods.for_year(ROLLOVER_YEAR + 4)[0]

    admin.get(f"/set-period?period={empty_period.id}&next=/rotations",
              follow_redirects=False)
    scoped = admin.get("/rotations")
    assert "0 resultado(s)" in scoped.text

    # Clearing the selection brings every period back.
    admin.get("/set-period?period=all&next=/rotations", follow_redirects=False)
    assert "0 resultado(s)" not in admin.get("/rotations").text
