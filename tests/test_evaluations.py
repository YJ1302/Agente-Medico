"""Digital evaluation workflow tests (Batch 2D)."""

from __future__ import annotations

from app.database import SessionLocal
from app.models.academic import RotationAssignment
from app.models.base import AssignmentStatus, EvaluationStatus
from app.models.evaluation import Evaluation
from app.repositories.repositories import RepositoryBundle
from app.services.evaluation_catalog import seed_criteria
from tests.conftest import _logged_in_client, csrf_token

# Fixed seeded evaluation ids (see app/seed.py Batch 2D block):
EVAL_PENDING_OWN_TUTOR = 2       # tutor id 1 (tutor@), sede 1 (sede@'s sede)
EVAL_RETURNED_OTHER_SEDE1 = 5    # sede 1
EVAL_APPROVED_DEMO_STUDENT = 6   # belongs to student id 1 (student@)
EVAL_SUBMITTED_SEDE2 = 3         # sede 2 — outside sede@'s scope


def _repos():
    return RepositoryBundle(SessionLocal())


def _make_fresh_evaluation(status: str = "pending") -> int:
    """Create an isolated assignment + evaluation for the demo tutor (id 1),
    sede 1, so lifecycle tests never compete over a single shared seeded row."""
    db = SessionLocal()
    r = RepositoryBundle(db)
    period = r.periods.current()
    rt = r.rotation_types.list()[0]
    a = RotationAssignment(student_id=1, rotation_type_id=rt.id, sede_id=1,
                           period_id=period.id, tutor_id=1,
                           start_date=period.start_date, end_date=period.end_date,
                           status=AssignmentStatus.ACTIVE.value)
    db.add(a); db.flush()
    ev = Evaluation(assignment_id=a.id, student_id=1, tutor_id=1, status=status)
    db.add(ev); db.flush()
    seed_criteria(db, ev)
    db.commit()
    eid = ev.id
    db.close()
    return eid


def _payload_for(eval_id: int, vals: list[int] | None = None) -> dict:
    """Return a {score_<criterion_id>: value, comments} dict for all 15 criteria."""
    db = SessionLocal()
    r = RepositoryBundle(db)
    ev = r.evaluations.get_full(eval_id)
    payload: dict = {}
    scores = vals or [4, 3, 4, 3, 4, 3, 4, 4, 3, 4, 4, 4, 3, 4, 4]
    for i, c in enumerate(sorted(ev.criteria, key=lambda c: (c.area, c.order_index))):
        payload[f"score_{c.id}"] = str(scores[i % len(scores)])
    db.close()
    payload["comments"] = "Evaluación de prueba."
    return payload


# --- Criteria & scoring rules ------------------------------------------------
def test_all_15_criteria_required_before_submit(admin):
    eid = _make_fresh_evaluation()
    tutor = _logged_in_client("tutor@internado360.demo")
    token = csrf_token(tutor, f"/evaluations/{eid}")
    # Submit with only 1 of 15 criteria scored.
    db = SessionLocal()
    r = RepositoryBundle(db)
    ev = r.evaluations.get_full(eid)
    first = sorted(ev.criteria, key=lambda c: (c.area, c.order_index))[0]
    db.close()
    data = {"csrf_token": token, f"score_{first.id}": "4", "comments": ""}
    resp = tutor.post(f"/evaluations/{eid}/submit", data=data, follow_redirects=True)
    assert "15" in resp.text or "calificar" in resp.text.lower()
    r2 = _repos()
    assert r2.evaluations.get_full(eid).status != EvaluationStatus.SUBMITTED.value
    tutor.__exit__(None, None, None)


def test_score_range_0_to_4(admin):
    eid = _make_fresh_evaluation()
    tutor = _logged_in_client("tutor@internado360.demo")
    token = csrf_token(tutor, f"/evaluations/{eid}")
    db = SessionLocal()
    r = RepositoryBundle(db)
    ev = r.evaluations.get_full(eid)
    first = sorted(ev.criteria, key=lambda c: (c.area, c.order_index))[0]
    db.close()
    data = {"csrf_token": token, f"score_{first.id}": "9", "comments": ""}
    resp = tutor.post(f"/evaluations/{eid}/save", data=data, follow_redirects=True)
    assert "0 y 4" in resp.text or "entre 0" in resp.text.lower()
    tutor.__exit__(None, None, None)


def test_correct_area_totals_and_final_score(admin):
    eid = _make_fresh_evaluation()
    tutor = _logged_in_client("tutor@internado360.demo")
    token = csrf_token(tutor, f"/evaluations/{eid}")
    payload = _payload_for(eid, [4, 4, 4, 3, 3,  # conocimientos sum -> depends on area order
                                 3, 3, 3, 4, 4,
                                 4, 4, 4, 4, 4])
    payload["csrf_token"] = token
    resp = tutor.post(f"/evaluations/{eid}/submit", data=payload, follow_redirects=False)
    assert resp.status_code in (302, 303), resp.text[:400]
    r = _repos()
    ev = r.evaluations.get_full(eid)
    # Recompute expected sums directly from stored criteria (authoritative).
    from app.models.evaluation import AREA_ATTITUDE, AREA_KNOWLEDGE, AREA_PERFORMANCE
    k = sum(c.score for c in ev.criteria if c.area == AREA_KNOWLEDGE)
    p = sum(c.score for c in ev.criteria if c.area == AREA_PERFORMANCE)
    a = sum(c.score for c in ev.criteria if c.area == AREA_ATTITUDE)
    assert ev.score_knowledge == float(k)
    assert ev.score_performance == float(p)
    assert ev.score_attitude == float(a)
    assert ev.final_score == round((k + p + a) / 3, 2)
    tutor.__exit__(None, None, None)


def test_server_recomputes_ignores_client_totals(admin):
    """Server must recompute from criteria — a forged total field is ignored."""
    eid = _make_fresh_evaluation()
    tutor = _logged_in_client("tutor@internado360.demo")
    token = csrf_token(tutor, f"/evaluations/{eid}")
    payload = _payload_for(eid)
    payload["csrf_token"] = token
    payload["final_score"] = "999"  # forged — not a real field the service reads
    payload["score_knowledge"] = "999"
    resp = tutor.post(f"/evaluations/{eid}/submit", data=payload, follow_redirects=False)
    assert resp.status_code in (302, 303)
    r = _repos()
    ev = r.evaluations.get_full(eid)
    assert ev.final_score < 21  # never the forged value; real 0-20 scale
    tutor.__exit__(None, None, None)


# --- Scope -------------------------------------------------------------------
def test_tutor_scope_cannot_access_other_tutor_evaluation(tutor_client):
    # eval 3 belongs to tutor id 2, not tutor id 1 (tutor@).
    assert tutor_client.get("/evaluations/3").status_code == 403


def test_tutor_can_access_own_evaluation(tutor_client):
    assert tutor_client.get(f"/evaluations/{EVAL_PENDING_OWN_TUTOR}").status_code == 200


def test_coordinator_own_sede_approval_only(sede_client):
    # sede@ coordinates sede 1; eval 3 is sede 2 -> forbidden to review/approve.
    resp = sede_client.get(f"/evaluations/{EVAL_SUBMITTED_SEDE2}")
    # Viewing may be scoped to 403 since assignment.sede_id not in own scope.
    assert resp.status_code == 403


def test_coordinator_can_view_own_sede_evaluation(sede_client):
    assert sede_client.get(f"/evaluations/{EVAL_RETURNED_OTHER_SEDE1}").status_code == 200


def test_student_sees_only_approved_own_evaluation(student_client):
    assert student_client.get(f"/evaluations/{EVAL_APPROVED_DEMO_STUDENT}").status_code == 200
    # A pending evaluation of their own must NOT be visible (not yet approved).
    assert student_client.get(f"/evaluations/{EVAL_PENDING_OWN_TUTOR}").status_code == 403


def test_student_cannot_see_others_evaluation(student_client):
    assert student_client.get(f"/evaluations/{EVAL_RETURNED_OTHER_SEDE1}").status_code == 403


def test_university_and_admin_see_all(admin, university_client):
    for eid in (EVAL_PENDING_OWN_TUTOR, EVAL_RETURNED_OTHER_SEDE1, EVAL_SUBMITTED_SEDE2,
                EVAL_APPROVED_DEMO_STUDENT):
        assert admin.get(f"/evaluations/{eid}").status_code == 200
        assert university_client.get(f"/evaluations/{eid}").status_code == 200


# --- Status workflow -----------------------------------------------------------
def test_submitted_locks_editing_for_tutor():
    eid = _make_fresh_evaluation()
    tutor = _logged_in_client("tutor@internado360.demo")
    token = csrf_token(tutor, f"/evaluations/{eid}")
    payload = _payload_for(eid); payload["csrf_token"] = token
    tutor.post(f"/evaluations/{eid}/submit", data=payload, follow_redirects=False)
    # Now try to save again — should be denied (not editable once submitted).
    # The CSRF token is per-session (not per-page), so the same token scraped
    # earlier remains valid even though the now-submitted page has no form.
    resp = tutor.post(f"/evaluations/{eid}/save",
                      data={"csrf_token": token, "comments": "intento"},
                      follow_redirects=False)
    assert resp.status_code == 403
    tutor.__exit__(None, None, None)


def test_return_for_correction_flow():
    eid = _make_fresh_evaluation()
    tutor = _logged_in_client("tutor@internado360.demo")
    token = csrf_token(tutor, f"/evaluations/{eid}")
    payload = _payload_for(eid); payload["csrf_token"] = token
    tutor.post(f"/evaluations/{eid}/submit", data=payload, follow_redirects=False)
    tutor.__exit__(None, None, None)

    sede = _logged_in_client("sede@internado360.demo")
    token2 = csrf_token(sede, f"/evaluations/{eid}")
    # Return without a comment must fail.
    resp = sede.post(f"/evaluations/{eid}/return",
                     data={"csrf_token": token2, "comments": ""}, follow_redirects=True)
    assert "motivo" in resp.text.lower()
    r = _repos()
    assert r.evaluations.get_full(eid).status == EvaluationStatus.SUBMITTED.value
    # Return with a comment succeeds.
    token3 = csrf_token(sede, f"/evaluations/{eid}")
    sede.post(f"/evaluations/{eid}/return",
             data={"csrf_token": token3, "comments": "Corregir actitudinal"},
             follow_redirects=False)
    r2 = _repos()
    ev = r2.evaluations.get_full(eid)
    assert ev.status == EvaluationStatus.RETURNED_FOR_CORRECTION.value
    assert ev.review_comments == "Corregir actitudinal"
    sede.__exit__(None, None, None)

    # Tutor can now correct (edit while returned_for_correction) and resubmit.
    tutor2 = _logged_in_client("tutor@internado360.demo")
    token4 = csrf_token(tutor2, f"/evaluations/{eid}")
    payload2 = _payload_for(eid); payload2["csrf_token"] = token4
    resp2 = tutor2.post(f"/evaluations/{eid}/submit", data=payload2, follow_redirects=False)
    assert resp2.status_code in (302, 303)
    r3 = _repos()
    assert r3.evaluations.get_full(eid).status == EvaluationStatus.SUBMITTED.value
    tutor2.__exit__(None, None, None)


def test_approve_locks_evaluation():
    eid = _make_fresh_evaluation()
    tutor = _logged_in_client("tutor@internado360.demo")
    token = csrf_token(tutor, f"/evaluations/{eid}")
    payload = _payload_for(eid); payload["csrf_token"] = token
    tutor.post(f"/evaluations/{eid}/submit", data=payload, follow_redirects=False)
    tutor.__exit__(None, None, None)

    sede = _logged_in_client("sede@internado360.demo")
    token2 = csrf_token(sede, f"/evaluations/{eid}")
    sede.post(f"/evaluations/{eid}/approve", data={"csrf_token": token2, "comments": ""})
    sede.__exit__(None, None, None)
    r = _repos()
    assert r.evaluations.get_full(eid).status == EvaluationStatus.APPROVED.value

    # A university coordinator (non-admin) cannot reopen. The approved page has
    # no reopen form/CSRF field for them (they have no action there), so scrape
    # a valid session token from a page they CAN act on instead (same session
    # token works everywhere — it's per-session, not per-page).
    uni = _logged_in_client("coordinator@internado360.demo")
    token3 = csrf_token(uni, "/students/new")
    uni.post(f"/evaluations/{eid}/reopen", data={"csrf_token": token3, "reason": "intento"})
    uni.__exit__(None, None, None)
    r2 = _repos()
    assert r2.evaluations.get_full(eid).status == EvaluationStatus.APPROVED.value  # still locked


def test_admin_reopen_requires_reason():
    eid = _make_fresh_evaluation()
    tutor = _logged_in_client("tutor@internado360.demo")
    token = csrf_token(tutor, f"/evaluations/{eid}")
    payload = _payload_for(eid); payload["csrf_token"] = token
    tutor.post(f"/evaluations/{eid}/submit", data=payload, follow_redirects=False)
    tutor.__exit__(None, None, None)
    sede = _logged_in_client("sede@internado360.demo")
    token2 = csrf_token(sede, f"/evaluations/{eid}")
    sede.post(f"/evaluations/{eid}/approve", data={"csrf_token": token2, "comments": ""})
    sede.__exit__(None, None, None)

    admin = _logged_in_client("admin@internado360.demo")
    token3 = csrf_token(admin, f"/evaluations/{eid}")
    resp = admin.post(f"/evaluations/{eid}/reopen", data={"csrf_token": token3, "reason": ""},
                      follow_redirects=True)
    assert "motivo" in resp.text.lower()
    r = _repos()
    assert r.evaluations.get_full(eid).status == EvaluationStatus.APPROVED.value
    token4 = csrf_token(admin, f"/evaluations/{eid}")
    admin.post(f"/evaluations/{eid}/reopen",
              data={"csrf_token": token4, "reason": "Corrección administrativa"})
    r2 = _repos()
    ev = r2.evaluations.get_full(eid)
    assert ev.status == EvaluationStatus.IN_PROGRESS.value
    assert ev.reopened_reason == "Corrección administrativa"
    admin.__exit__(None, None, None)


# --- Security & audit ----------------------------------------------------------
def test_mutation_requires_csrf():
    eid = _make_fresh_evaluation()
    tutor = _logged_in_client("tutor@internado360.demo")
    resp = tutor.post(f"/evaluations/{eid}/save", data={"comments": "x"}, follow_redirects=False)
    assert resp.status_code == 400
    tutor.__exit__(None, None, None)


def test_get_mutation_unavailable(admin):
    assert admin.get(f"/evaluations/{EVAL_PENDING_OWN_TUTOR}/submit").status_code in (404, 405)


def test_evaluation_actions_audited(admin):
    html = admin.get("/audit").text
    assert any(a in html for a in ["submit_evaluation", "approve_evaluation", "return_evaluation"])


# --- Dashboard scoping -----------------------------------------------------------
def test_student_dashboard_has_no_global_totals(student_client):
    html = student_client.get("/dashboard").text
    assert "Internos MINSA" not in html
    assert "Internos EsSalud" not in html
    assert "Sedes activas" not in html


def test_tutor_dashboard_scoped(tutor_client):
    resp = tutor_client.get("/dashboard")
    assert resp.status_code == 200
    assert "Internos MINSA" not in resp.text


def test_sede_dashboard_scoped(sede_client):
    resp = sede_client.get("/dashboard")
    assert resp.status_code == 200
    assert "Internos MINSA" not in resp.text


def test_admin_and_university_dashboard_show_global(admin, university_client):
    assert "Internos MINSA" in admin.get("/dashboard").text
    assert "Internos MINSA" in university_client.get("/dashboard").text
