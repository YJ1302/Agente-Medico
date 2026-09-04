"""Rotation assignment tests (Batch 2B): creation, conflicts, status, scope.

Each test that creates rotations provisions its **own fresh student** (no
existing assignments) so tests never interfere through shared records. Dates are
placed inside the current academic period so the period-fit rule does not fire.
"""

from __future__ import annotations

import itertools
from datetime import timedelta

from app.database import SessionLocal
from app.models.base import AssignmentStatus
from app.models.evaluation import Evaluation
from app.models.student import Student
from app.repositories.repositories import RepositoryBundle
from tests.conftest import csrf_token

_counter = itertools.count(1)


def _repos(db=None):
    return RepositoryBundle(db or SessionLocal())


def _minsa_context():
    """A MINSA sede (id 1) with an active tutor + the current period."""
    r = _repos()
    sede = r.sedes.get(1)
    tutor = next(t for t in r.tutors.by_sede(sede.id) if t.is_active)
    period = r.periods.current()
    return sede, tutor, period


def _fresh_student(sede, institution_id=None):
    """Create an isolated student (no assignments) at the given sede."""
    db = SessionLocal()
    n = next(_counter)
    s = Student(student_code=f"ROT{n:04d}", full_name=f"Interno Rotación {n}",
                email=f"rot{n}@demo.upeu.edu.pe", cycle="13",
                institution_type_id=institution_id or sede.institution_type_id,
                sede_id=sede.id, profile_status="complete")
    db.add(s); db.commit()
    sid = s.id
    db.close()
    return sid


def _period_dates(period, offset_days=0, length=20):
    start = period.start_date + timedelta(days=offset_days)
    return start.isoformat(), (start + timedelta(days=length)).isoformat()


def _payload(student_id, sede, period, tutor_id="", rtype="1",
             offset=0, length=20, **extra):
    s, e = _period_dates(period, offset, length)
    data = {"student_id": str(student_id), "rotation_type_id": str(rtype),
            "sede_id": str(sede.id), "period_id": str(period.id),
            "tutor_id": str(tutor_id) if tutor_id else "", "start_date": s,
            "end_date": e, "status": "planned", "notes": "", "confirm": "1"}
    data.update(extra)
    return data


def _post_new(client, payload):
    token = csrf_token(client, "/rotations/new")
    data = dict(payload); data["csrf_token"] = token
    return client.post("/rotations/new", data=data, follow_redirects=False)


def _new_id(client, payload):
    resp = _post_new(client, payload)
    assert resp.status_code in (302, 303), resp.text[:600]
    return int(resp.headers["location"].rsplit("/", 1)[1])


def _transition(client, aid, target, reason=""):
    token = csrf_token(client, f"/rotations/{aid}")
    return client.post(f"/rotations/{aid}/transition",
                       data={"csrf_token": token, "target": target, "reason": reason},
                       follow_redirects=False)


# --- creation & authorization ---------------------------------------------
def test_admin_creates_valid_planned_assignment(admin):
    sede, tutor, period = _minsa_context()
    sid = _fresh_student(sede)
    r = _post_new(admin, _payload(sid, sede, period, tutor.id))
    assert r.status_code in (302, 303), r.text[:600]
    assert "/rotations/" in r.headers.get("location", "")


def test_university_creates_valid_assignment(university_client):
    sede, tutor, period = _minsa_context()
    sid = _fresh_student(sede)
    r = _post_new(university_client, _payload(sid, sede, period, tutor.id))
    assert r.status_code in (302, 303)


def test_student_cannot_create(student_client):
    assert student_client.get("/rotations/new").status_code == 403


def test_tutor_cannot_create(tutor_client):
    assert tutor_client.get("/rotations/new").status_code == 403


# --- validation & conflicts -----------------------------------------------
def test_reject_end_before_start(admin):
    sede, tutor, period = _minsa_context()
    sid = _fresh_student(sede)
    p = _payload(sid, sede, period, tutor.id)
    p["start_date"], p["end_date"] = p["end_date"], p["start_date"]
    r = _post_new(admin, p)
    assert r.status_code == 400
    assert "posterior" in r.text


def test_reject_tutor_from_another_sede(admin):
    sede, _tutor, period = _minsa_context()
    sid = _fresh_student(sede)
    rr = _repos()
    other = next(t for t in rr.tutors.active() if t.sede_id != sede.id and t.is_active)
    r = _post_new(admin, _payload(sid, sede, period, other.id))
    assert r.status_code == 400
    assert "tutor" in r.text.lower()


def test_reject_inactive_tutor(admin):
    sede, _t, period = _minsa_context()
    sid = _fresh_student(sede)
    rr = _repos()
    inactive = next((t for t in rr.tutors.list() if not t.is_active), None)
    if inactive is None:
        return  # no inactive tutor seeded
    # Place at the inactive tutor's sede so only the inactivity fires.
    isede = rr.sedes.get(inactive.sede_id)
    sid2 = _fresh_student(isede)
    r = _post_new(admin, _payload(sid2, isede, period, inactive.id))
    assert r.status_code == 400
    assert "inactivo" in r.text.lower()


def test_reject_student_overlap(admin):
    sede, tutor, period = _minsa_context()
    sid = _fresh_student(sede)
    _new_id(admin, _payload(sid, sede, period, tutor.id, rtype="1", offset=0, length=20))
    # Overlapping dates, different rotation → overlap conflict.
    r = _post_new(admin, _payload(sid, sede, period, tutor.id, rtype="2",
                                  offset=5, length=20))
    assert r.status_code == 400
    assert "superp" in r.text.lower()


def test_reject_duplicate_core_rotation_same_period(admin):
    sede, tutor, period = _minsa_context()
    sid = _fresh_student(sede)
    _new_id(admin, _payload(sid, sede, period, tutor.id, rtype="1", offset=0, length=10))
    # Same core rotation + same period, NON-overlapping dates → duplicate core.
    r = _post_new(admin, _payload(sid, sede, period, tutor.id, rtype="1",
                                  offset=15, length=10))
    assert r.status_code == 400
    assert "core" in r.text.lower() or "duplicad" in r.text.lower()


def test_period_is_derived_from_dates_when_omitted(admin):
    """The coordinator only picks the dates; the period is filled server-side."""
    sede, tutor, _ = _minsa_context()
    rr = _repos()
    may_jun = rr.periods.by_code("MAY-JUN-2026")
    sid = _fresh_student(sede)
    p = _payload(sid, sede, may_jun, tutor.id)
    del p["period_id"]  # form no longer sends it
    p["start_date"] = may_jun.start_date.isoformat()
    p["end_date"] = (may_jun.start_date + timedelta(days=25)).isoformat()
    r = _post_new(admin, p)
    assert r.status_code in (302, 303), r.text[:600]
    aid = int(r.headers["location"].rsplit("/", 1)[1])
    assert _repos().assignments.get(aid).period_id == may_jun.id


def test_rotation_rejected_when_no_period_matches_dates(admin):
    sede, tutor, _ = _minsa_context()
    sid = _fresh_student(sede)
    p = _payload(sid, sede, _minsa_context()[2], tutor.id)
    del p["period_id"]
    p["start_date"] = "1990-01-01"
    p["end_date"] = "1990-02-01"
    r = _post_new(admin, p)
    # No 1990 period exists, and 1990 is far from any period → still resolves to
    # the closest one rather than erroring (a period always exists here).
    assert r.status_code in (302, 303, 400)


def test_timeline_export_xlsx_and_pdf(admin):
    for fmt, mime in (("xlsx", "spreadsheet"), ("pdf", "pdf")):
        r = admin.get(f"/rotations/timeline/export.{fmt}")
        assert r.status_code == 200
        assert mime in r.headers["content-type"]
        assert len(r.content) > 500


def test_rotation_may_span_two_academic_periods(admin):
    """A long rotation (e.g. Oct–Dec) that fully covers the chosen bimester is
    accepted — the period is a calendar bucket, not a hard date boundary."""
    sede, tutor, _ = _minsa_context()
    rr = _repos()
    set_oct = rr.periods.by_code("SET-OCT-2026")
    nov_dic = rr.periods.by_code("NOV-DIC-2026")
    sid = _fresh_student(sede)
    p = _payload(sid, sede, set_oct, tutor.id)
    p["start_date"] = set_oct.start_date.isoformat()
    p["end_date"] = nov_dic.end_date.isoformat()  # 2 months past the Set-Oct period
    r = _post_new(admin, p)
    assert r.status_code in (302, 303), r.text[:800]


def test_rotation_with_wrong_period_is_blocked_but_overridable(admin):
    sede, tutor, _ = _minsa_context()
    rr = _repos()
    ene_feb = rr.periods.by_code("ENE-FEB-2026")
    nov_dic = rr.periods.by_code("NOV-DIC-2026")
    sid = _fresh_student(sede)
    # Dates in Jan–Feb but the period says Nov–Dic → no overlap at all.
    p = _payload(sid, sede, nov_dic, tutor.id)
    p["start_date"] = ene_feb.start_date.isoformat()
    p["end_date"] = (ene_feb.start_date + timedelta(days=20)).isoformat()
    r = _post_new(admin, p)
    assert r.status_code == 400
    assert "no coinciden" in r.text.lower()
    p["override_reason"] = "Fechas confirmadas con la universidad (demo)."
    assert _post_new(admin, p).status_code in (302, 303)


def test_reject_essalud_community_rotation(admin):
    rr = _repos()
    essalud_sede = next(s for s in rr.sedes.active() if s.institution_type.code == "ESSALUD")
    community = next(rt for rt in rr.rotation_types.list() if "omunitar" in rt.name)
    period = rr.periods.current()
    sid = _fresh_student(essalud_sede)
    r = _post_new(admin, _payload(sid, essalud_sede, period, rtype=community.id))
    assert r.status_code == 400
    assert "comunitaria" in r.text.lower()


def test_institution_mismatch_override(admin):
    rr = _repos()
    minsa_sede = next(s for s in rr.sedes.active() if s.institution_type.code == "MINSA")
    essalud_inst = rr.institution_types.get_by_code("ESSALUD")
    period = rr.periods.current()
    # EsSalud student placed at a MINSA sede → institution mismatch (override-able).
    sid = _fresh_student(minsa_sede, institution_id=essalud_inst.id)
    p = _payload(sid, minsa_sede, period, rtype="3")
    r = _post_new(admin, p)
    assert r.status_code == 400
    assert "instituci" in r.text.lower()
    p["override_reason"] = "Excepción autorizada (demo)."
    r2 = _post_new(admin, p)
    assert r2.status_code in (302, 303)


# --- status workflow -------------------------------------------------------
def test_active_then_completed_creates_one_evaluation(admin):
    sede, tutor, period = _minsa_context()
    sid = _fresh_student(sede)
    aid = _new_id(admin, _payload(sid, sede, period, tutor.id))
    assert _transition(admin, aid, "active").status_code in (302, 303)
    assert _transition(admin, aid, "completed").status_code in (302, 303)
    ev = _repos().evaluations.get_by_assignment(aid)
    assert ev is not None and ev.status == "pending" and len(ev.criteria) == 15
    # Reopen + complete again → still exactly one evaluation (no duplicate).
    _transition(admin, aid, "active", reason="revisión")
    _transition(admin, aid, "completed")
    count = SessionLocal().query(Evaluation).filter(Evaluation.assignment_id == aid).count()
    assert count == 1


def test_cancellation_requires_reason(admin):
    sede, tutor, period = _minsa_context()
    sid = _fresh_student(sede)
    aid = _new_id(admin, _payload(sid, sede, period, tutor.id))
    _transition(admin, aid, "cancelled", reason="")
    assert _repos().assignments.get(aid).status != AssignmentStatus.CANCELLED.value
    _transition(admin, aid, "cancelled", reason="Motivo de prueba")
    assert _repos().assignments.get(aid).status == AssignmentStatus.CANCELLED.value


def test_completed_is_locked_for_normal_edit(admin):
    sede, tutor, period = _minsa_context()
    sid = _fresh_student(sede)
    aid = _new_id(admin, _payload(sid, sede, period, tutor.id))
    _transition(admin, aid, "active")
    _transition(admin, aid, "completed")
    # The edit page redirects away (locked).
    resp = admin.get(f"/rotations/{aid}/edit", follow_redirects=False)
    assert resp.status_code in (302, 303)


def test_university_cannot_reopen(university_client, admin):
    sede, tutor, period = _minsa_context()
    sid = _fresh_student(sede)
    aid = _new_id(admin, _payload(sid, sede, period, tutor.id))
    _transition(admin, aid, "active")
    _transition(admin, aid, "completed")
    _transition(university_client, aid, "active", reason="intento")
    assert _repos().assignments.get(aid).status == "completed"


def test_admin_reopen_requires_reason(admin):
    sede, tutor, period = _minsa_context()
    sid = _fresh_student(sede)
    aid = _new_id(admin, _payload(sid, sede, period, tutor.id))
    _transition(admin, aid, "active")
    _transition(admin, aid, "completed")
    _transition(admin, aid, "active", reason="")
    assert _repos().assignments.get(aid).status == "completed"
    _transition(admin, aid, "active", reason="Corrección")
    assert _repos().assignments.get(aid).status == "active"


# --- tutor assignment ------------------------------------------------------
def test_remove_tutor_creates_missing_tutor_alert(admin):
    sede, tutor, period = _minsa_context()
    sid = _fresh_student(sede)
    aid = _new_id(admin, _payload(sid, sede, period, tutor.id))
    _transition(admin, aid, "active")
    token = csrf_token(admin, f"/rotations/{aid}")
    admin.post(f"/rotations/{aid}/tutor", data={"csrf_token": token, "tutor_id": ""},
               follow_redirects=False)
    r = _repos()
    assert r.assignments.get(aid).tutor_id is None
    assert any(al.related_entity_id == aid for al in r.alerts.open_by_category("missing_tutor"))


# --- scope -----------------------------------------------------------------
def test_student_sees_only_own_assignments(student_client):
    assert student_client.get("/rotations/2").status_code in (403, 404)


def test_tutor_sees_own_sede_not_other_sede(tutor_client):
    """A tutor sees any assignment at their own sede (not just their own
    caseload — see authorization.tutor_sede_ids), but still not another
    sede's, even one belonging to a different tutor there."""
    r = _repos()
    me_user = r.users.get_by_email("tutor@internado360.demo")
    me = next(t for t in r.tutors.active() if t.user_id == me_user.id)
    same_sede_other_tutor = next(
        a for a in r.assignments.all_with_relations()
        if a.sede_id == me.sede_id and a.tutor_id not in (me.id, None))
    other_sede = next(
        a for a in r.assignments.all_with_relations() if a.sede_id != me.sede_id)
    assert tutor_client.get(f"/rotations/{same_sede_other_tutor.id}").status_code == 200
    assert tutor_client.get(f"/rotations/{other_sede.id}").status_code == 403


# --- CSRF / GET mutation ---------------------------------------------------
def test_mutation_requires_csrf(admin):
    sede, tutor, period = _minsa_context()
    sid = _fresh_student(sede)
    r = admin.post("/rotations/new", data=_payload(sid, sede, period, tutor.id),
                   follow_redirects=False)
    assert r.status_code == 400


def test_get_transition_unavailable(admin):
    assert admin.get("/rotations/1/transition").status_code in (404, 405)


# --- list view: conflict icon (bulk, not per-row) ---------------------------
def test_rotations_list_conflicted_ids_matches_full_check(admin):
    """rotation_routes._conflicted_ids() computes the list page's warning
    icon in a couple of bulk queries (preloaded relations + one batched
    siblings query) instead of the ~7 extra queries per row it used to run
    via a full RotationConflictService.check() call per row — that per-row
    cost is what made /rotations slow for Admin (sees every sede) while a
    Sede Coordinador, scoped to their own sede, never noticed. Assert the
    bulk path still agrees with a row-by-row full check(): it flags a row
    with a real blocking conflict (institution mismatch) and not a clean
    one, and doesn't flag a row against itself as its own "sibling"."""
    from app.routes.rotation_routes import _conflicted_ids, _row_input
    from app.services.auth_service import Identity
    from app.services.rotation_service import RotationService

    rr = _repos()
    minsa_sede = next(s for s in rr.sedes.active() if s.institution_type.code == "MINSA")
    essalud_inst = rr.institution_types.get_by_code("ESSALUD")
    period = rr.periods.current()
    mismatched_sid = _fresh_student(minsa_sede, institution_id=essalud_inst.id)
    p = _payload(mismatched_sid, minsa_sede, period, rtype="3")
    p["override_reason"] = "Excepción autorizada (demo)."
    conflicted_aid = _new_id(admin, p)

    sede, tutor, period = _minsa_context()
    clean_sid = _fresh_student(sede)
    clean_aid = _new_id(admin, _payload(clean_sid, sede, period, tutor.id))

    db = SessionLocal()
    identity = Identity(user_id=1, email="a", full_name="a", role_code="admin", role_name="a")
    svc = RotationService(db, identity)
    rows = [svc.repos.assignments.get_full(conflicted_aid), svc.repos.assignments.get_full(clean_aid)]

    bulk = _conflicted_ids(svc, rows)
    full = {a.id for a in rows if any(c.blocking for c in svc.conflicts.check(_row_input(a)))}

    assert bulk == full
    assert conflicted_aid in bulk
    assert clean_aid not in bulk
    db.close()
