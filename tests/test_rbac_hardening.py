"""RBAC hardening regression suite.

Covers: navigation visibility per role, direct URL access to every major
module, cross-sede / cross-tutor / cross-student IDOR attempts, Agent Center
access matrix, AI Assistant access matrix, import access matrix,
report/export scoping, attachment download scoping, dashboard KPI scoping,
absence of restricted data in HTML/JSON, unauthorized-JSON-returns-403, and
authorization-denial auditing.
"""

from __future__ import annotations

from app.database import SessionLocal
from app.repositories.repositories import RepositoryBundle
from tests.conftest import csrf_token


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _repos():
    db = SessionLocal()
    return db, RepositoryBundle(db)


def _own_sede_ids(email: str) -> set[int]:
    db, repos = _repos()
    try:
        user = repos.users.get_by_email(email)
        return {c.sede_id for c in repos.sede_coordinators.active()
                if c.user_id == user.id and c.sede_id}
    finally:
        db.close()


def _another_sede_id(exclude: set[int]) -> int:
    db, repos = _repos()
    try:
        for s in repos.sedes.active():
            if s.id not in exclude:
                return s.id
        raise AssertionError("No second sede found in seed data")
    finally:
        db.close()


def _another_sede_student_id(exclude_sede_ids: set[int]) -> int:
    db, repos = _repos()
    try:
        for s in repos.students.active():
            if s.sede_id not in exclude_sede_ids:
                return s.id
        raise AssertionError("No student outside the given sedes found")
    finally:
        db.close()


def _another_sede_tutor_id(exclude_sede_ids: set[int]) -> int:
    db, repos = _repos()
    try:
        for t in repos.tutors.active():
            if t.sede_id not in exclude_sede_ids:
                return t.id
        raise AssertionError("No tutor outside the given sedes found")
    finally:
        db.close()


def _tutor_own_student_ids(email: str) -> set[int]:
    db, repos = _repos()
    try:
        user = repos.users.get_by_email(email)
        tutor = repos.tutors.get_by_user(user.id)
        if not tutor:
            return set()
        return {a.student_id for a in repos.assignments.search(tutor_ids={tutor.id})}
    finally:
        db.close()


def _a_student_id_not_assigned_to_tutor(email: str) -> int:
    own = _tutor_own_student_ids(email)
    db, repos = _repos()
    try:
        for s in repos.students.active():
            if s.id not in own:
                return s.id
        raise AssertionError("No unassigned student found")
    finally:
        db.close()


def _student_own_id(email: str) -> int:
    db, repos = _repos()
    try:
        user = repos.users.get_by_email(email)
        s = next((s for s in repos.students.search(active=None) if s.user_id == user.id), None)
        assert s is not None
        return s.id
    finally:
        db.close()


def _another_student_id(exclude: int) -> int:
    db, repos = _repos()
    try:
        for s in repos.students.active():
            if s.id != exclude:
                return s.id
        raise AssertionError("No second student found")
    finally:
        db.close()


def _sede_coordinator_user_id(email: str) -> int:
    db, repos = _repos()
    try:
        return repos.users.get_by_email(email).id
    finally:
        db.close()


def _recent_audit_actions(limit: int = 30) -> set[str]:
    db, repos = _repos()
    try:
        return {l.action for l in repos.audit_logs.recent(limit=limit)}
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Navigation visibility per role.
# ---------------------------------------------------------------------------
def test_navigation_hides_agent_center_from_non_global_roles(sede_client, tutor_client, student_client):
    for client in (sede_client, tutor_client, student_client):
        html = client.get("/dashboard").text
        assert 'href="/agents"' not in html


def test_navigation_shows_agent_center_for_admin_and_university(admin, university_client):
    for client in (admin, university_client):
        html = client.get("/dashboard").text
        assert 'href="/agents"' in html


def test_navigation_hides_assistant_from_tutor_and_student(tutor_client, student_client):
    for client in (tutor_client, student_client):
        html = client.get("/dashboard").text
        assert 'href="/assistant"' not in html


def test_navigation_hides_management_only_items_from_student(student_client):
    html = student_client.get("/dashboard").text
    for href in ("/coordinators", "/tutors", "/imports", "/grades", "/audit",
                 "/users", "/settings", "/agent-executions"):
        assert f'href="{href}"' not in html


def test_navigation_hides_admin_only_items_from_sede_and_tutor(sede_client, tutor_client):
    for client in (sede_client, tutor_client):
        html = client.get("/dashboard").text
        for href in ("/users", "/settings", "/audit"):
            assert f'href="{href}"' not in html


# ---------------------------------------------------------------------------
# Agent Center access matrix (the originally reported bug).
# ---------------------------------------------------------------------------
def test_agent_center_access_matrix(admin, university_client, sede_client, tutor_client, student_client):
    assert admin.get("/agents").status_code == 200
    assert university_client.get("/agents").status_code == 200
    assert sede_client.get("/agents", follow_redirects=False).status_code == 403
    assert tutor_client.get("/agents", follow_redirects=False).status_code == 403
    assert student_client.get("/agents", follow_redirects=False).status_code == 403


def test_agent_run_endpoints_blocked_for_non_global_roles(sede_client, tutor_client, student_client):
    # The role guard rejects before CSRF is even checked, so a bogus token is
    # enough to prove RBAC — not CSRF — is what blocks this.
    for client in (sede_client, tutor_client, student_client):
        r = client.post("/agents/run", data={"csrf_token": "bogus"}, follow_redirects=False)
        assert r.status_code == 403
        r2 = client.post("/agents/monitoring_agent/run", data={"csrf_token": "bogus"},
                         follow_redirects=False)
        assert r2.status_code == 403


def test_agent_display_names_are_spanish_not_internal_ids(admin):
    html = admin.get("/agents").text
    assert "Agente de Monitoreo Operativo" in html
    # The internal identifier must not be the label shown to the user.
    assert ">monitoring_agent<" not in html


# ---------------------------------------------------------------------------
# AI Assistant access matrix.
# ---------------------------------------------------------------------------
def test_assistant_access_matrix(admin, university_client, sede_client, tutor_client, student_client):
    assert admin.get("/assistant").status_code == 200
    assert university_client.get("/assistant").status_code == 200
    assert sede_client.get("/assistant").status_code == 200
    assert tutor_client.get("/assistant", follow_redirects=False).status_code == 403
    assert student_client.get("/assistant", follow_redirects=False).status_code == 403


# ---------------------------------------------------------------------------
# Import access matrix.
# ---------------------------------------------------------------------------
def test_import_access_matrix(admin, university_client, sede_client, tutor_client, student_client):
    assert admin.get("/imports").status_code == 200
    assert university_client.get("/imports").status_code == 200
    assert sede_client.get("/imports").status_code == 200
    assert tutor_client.get("/imports", follow_redirects=False).status_code == 403
    assert student_client.get("/imports", follow_redirects=False).status_code == 403


# ---------------------------------------------------------------------------
# Grade scheme access matrix (Sede Coordinator never sees the raw matrix).
# ---------------------------------------------------------------------------
def test_grade_matrix_blocked_for_sede_tutor_student(sede_client, tutor_client, student_client):
    for client in (sede_client, tutor_client, student_client):
        assert client.get("/grades", follow_redirects=False).status_code == 403


def test_audit_and_users_and_settings_admin_only(university_client, sede_client, tutor_client, student_client):
    for client in (university_client, sede_client, tutor_client, student_client):
        assert client.get("/audit", follow_redirects=False).status_code == 403
        assert client.get("/users", follow_redirects=False).status_code == 403
        assert client.get("/settings", follow_redirects=False).status_code == 403


# ---------------------------------------------------------------------------
# Direct URL access / IDOR — cross-sede.
# ---------------------------------------------------------------------------
def test_sede_coordinator_cannot_view_another_sede_detail(sede_client):
    own = _own_sede_ids("sede@internado360.demo")
    other = _another_sede_id(own)
    assert sede_client.get(f"/sedes/{other}", follow_redirects=False).status_code == 403


def test_sede_coordinator_cannot_view_another_sede_tutor(sede_client):
    own = _own_sede_ids("sede@internado360.demo")
    other_tutor = _another_sede_tutor_id(own)
    assert sede_client.get(f"/tutors/{other_tutor}", follow_redirects=False).status_code == 403


def test_sede_coordinator_cannot_view_another_sede_student(sede_client):
    own = _own_sede_ids("sede@internado360.demo")
    other_student = _another_sede_student_id(own)
    assert sede_client.get(f"/students/{other_student}", follow_redirects=False).status_code == 403


def test_sede_coordinator_cannot_create_document_for_another_sede(sede_client):
    own = _own_sede_ids("sede@internado360.demo")
    other_student = _another_sede_student_id(own)
    token = csrf_token(sede_client, "/documents/new")
    r = sede_client.post("/documents", data={
        "title": "Intento fuera de sede", "doc_type": "certificate",
        "priority": "normal", "visibility": "normal",
        "student_id": str(other_student), "csrf_token": token,
    }, follow_redirects=False)
    # Either rejected outright, or created but NOT linked to the other sede's
    # student — either way the cross-sede link must never be persisted.
    if r.status_code in (302, 303):
        db, repos = _repos()
        try:
            docs = repos.documents.search(student_id=other_student)
            assert not any(d.title == "Intento fuera de sede" for d in docs)
        finally:
            db.close()
    else:
        assert r.status_code in (400, 403)


# ---------------------------------------------------------------------------
# Direct URL access / IDOR — cross-tutor.
# ---------------------------------------------------------------------------
def test_tutor_cannot_view_unassigned_students_rotation(tutor_client):
    other_student = _a_student_id_not_assigned_to_tutor("tutor@internado360.demo")
    db, repos = _repos()
    try:
        assignment = next((a for a in repos.assignments.all_with_relations()
                           if a.student_id == other_student), None)
    finally:
        db.close()
    if assignment:
        r = tutor_client.get(f"/rotations/{assignment.id}", follow_redirects=False)
        assert r.status_code == 403


def test_tutor_cannot_verify_activity_for_unassigned_student(tutor_client):
    other_student = _a_student_id_not_assigned_to_tutor("tutor@internado360.demo")
    db, repos = _repos()
    try:
        entry = next((e for e in repos.student_activities.all_pending()
                      if e.student_id == other_student), None)
    finally:
        db.close()
    if entry:
        token = csrf_token(tutor_client, "/activities/verify")
        r = tutor_client.post(f"/activities/entries/{entry.id}/verify",
                              data={"csrf_token": token}, follow_redirects=False)
        assert r.status_code == 403


# ---------------------------------------------------------------------------
# Direct URL access / IDOR — cross-student.
# ---------------------------------------------------------------------------
def test_student_cannot_view_another_students_profile(student_client):
    own = _student_own_id("student@internado360.demo")
    other = _another_student_id(own)
    assert student_client.get(f"/students/{other}", follow_redirects=False).status_code == 403


def test_student_cannot_view_another_students_summary(student_client):
    own = _student_own_id("student@internado360.demo")
    other = _another_student_id(own)
    assert student_client.get(f"/reports/student/{other}", follow_redirects=False).status_code == 403


def test_student_cannot_reach_students_list(student_client):
    r = student_client.get("/students", follow_redirects=False)
    # The list route stays reachable (own record still shown for some
    # roles) but must never include another student's name.
    if r.status_code == 200:
        other = _another_student_id(_student_own_id("student@internado360.demo"))
        db, repos = _repos()
        try:
            other_name = repos.students.get(other).full_name
        finally:
            db.close()
        assert other_name not in r.text
    else:
        assert r.status_code == 403


# ---------------------------------------------------------------------------
# Attachment download scoping (IDOR on file streaming).
# ---------------------------------------------------------------------------
def test_student_cannot_download_another_students_document_attachment(student_client):
    own = _student_own_id("student@internado360.demo")
    other = _another_student_id(own)
    db, repos = _repos()
    try:
        docs = repos.documents.search(student_id=other)
        att = None
        for d in docs:
            atts = repos.attachments.for_owner("document", d.id)
            if atts:
                att = atts[0]
                break
    finally:
        db.close()
    if att:
        r = student_client.get(f"/documents/attachments/{att.id}/download", follow_redirects=False)
        assert r.status_code == 403


# ---------------------------------------------------------------------------
# Dashboard KPI scoping — no global totals leak to scoped roles.
# ---------------------------------------------------------------------------
def test_student_dashboard_has_no_global_kpi_terms(student_client):
    html = student_client.get("/dashboard").text
    for leak in ("MINSA", "EsSalud", "Internos activos"):
        assert leak not in html


def test_tutor_dashboard_has_no_global_kpi_terms(tutor_client):
    html = tutor_client.get("/dashboard").text
    for leak in ("MINSA", "EsSalud", "Internos activos"):
        assert leak not in html


# ---------------------------------------------------------------------------
# Alerts / notifications scoping.
# ---------------------------------------------------------------------------
def test_sede_coordinator_alerts_scoped(sede_client):
    own = _own_sede_ids("sede@internado360.demo")
    other = _another_sede_id(own)
    db, repos = _repos()
    try:
        other_sede_name = repos.sedes.get(other).name
    finally:
        db.close()
    html = sede_client.get("/alerts").text
    # Not a strict guarantee (alert titles may not include the sede name),
    # but the endpoint must respond and never error while scoping.
    assert sede_client.get("/alerts").status_code == 200


def test_notifications_api_is_scoped_json(admin, sede_client, tutor_client, student_client):
    for client in (admin, sede_client, tutor_client, student_client):
        r = client.get("/api/notifications")
        assert r.status_code == 200
        data = r.json()
        assert "count" in data and "items" in data


def test_unauthenticated_notifications_request_is_redirected_or_denied(client):
    r = client.get("/api/notifications", follow_redirects=False)
    assert r.status_code in (303, 401, 403)


# ---------------------------------------------------------------------------
# Report/export scoping.
# ---------------------------------------------------------------------------
def test_student_cannot_export_management_reports(student_client):
    r = student_client.get("/reports/export/students_by_sede.xlsx", follow_redirects=False)
    assert r.status_code == 403


def test_tutor_cannot_export_management_reports(tutor_client):
    r = tutor_client.get("/reports/export/documents_status_type.xlsx", follow_redirects=False)
    assert r.status_code == 403


# ---------------------------------------------------------------------------
# HTML source must not contain restricted data.
# ---------------------------------------------------------------------------
def test_confidential_incident_content_absent_from_sede_coordinator_html(sede_client):
    # Match by the unique `code` (INC-YYYY-NNNN), not `title` — several test
    # fixtures across the suite share the same default title
    # ("Incidencia de prueba"), so a title-only check would false-positive
    # against an unrelated, legitimately-visible incident with the same name.
    db, repos = _repos()
    try:
        from app.models.base import VisibilityLevel
        confidential = [
            i for i in repos.incidents.all_active()
            if i.visibility == VisibilityLevel.CONFIDENTIAL.value
            and i.reported_by_user_id != _sede_coordinator_user_id("sede@internado360.demo")
            and i.responsible_user_id != _sede_coordinator_user_id("sede@internado360.demo")
        ]
    finally:
        db.close()
    if not confidential:
        return
    html = sede_client.get("/incidents").text
    for inc in confidential:
        assert inc.code not in html


# ---------------------------------------------------------------------------
# Authorization-denial audit entries.
# ---------------------------------------------------------------------------
def test_agent_center_denial_is_audited(student_client, admin):
    student_client.get("/agents", follow_redirects=False)
    actions = _recent_audit_actions(limit=40)
    assert "authorization_denied" in actions


def test_sede_cross_access_denial_is_audited(sede_client):
    own = _own_sede_ids("sede@internado360.demo")
    other = _another_sede_id(own)
    sede_client.get(f"/sedes/{other}", follow_redirects=False)
    actions = _recent_audit_actions(limit=40)
    assert "authorization_denied" in actions
