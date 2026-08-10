"""Authorization tests — server-side RBAC and record-level scope."""

from __future__ import annotations


def test_student_cannot_access_admin_pages(student_client):
    for path in ("/users", "/audit", "/settings", "/agent-executions"):
        r = student_client.get(path)
        assert r.status_code == 403, f"{path} should be forbidden for a student"


def test_university_cannot_access_admin_settings(university_client):
    assert university_client.get("/users").status_code == 403
    assert university_client.get("/settings").status_code == 403
    assert university_client.get("/audit").status_code == 403
    # But may access academic records / agent executions.
    assert university_client.get("/agent-executions").status_code == 200
    assert university_client.get("/students").status_code == 200


def test_student_cannot_view_another_student(student_client):
    # Student demo is the first seeded student (id 1). Others must be forbidden.
    assert student_client.get("/students/2").status_code == 403
    assert student_client.get("/students/5").status_code == 403


def test_tutor_sees_own_sede_student_not_other_sede(tutor_client):
    """A tutor sees any student at their own sede — not just their personal
    caseload (see authorization.tutor_sede_ids) — but still not one at a
    different sede. Student #12 is seeded at a different sede than
    tutor@internado360.demo's own (sede 4 vs 1)."""
    from app.database import SessionLocal
    from app.repositories.repositories import RepositoryBundle
    r = RepositoryBundle(SessionLocal())
    me_user = r.users.get_by_email("tutor@internado360.demo")
    me = next(t for t in r.tutors.active() if t.user_id == me_user.id)
    same_sede_student = next(s for s in r.students.search(active=None) if s.sede_id == me.sede_id)
    assert tutor_client.get(f"/students/{same_sede_student.id}").status_code == 200
    assert tutor_client.get("/students/12").status_code == 403


def test_hidden_menu_is_not_the_boundary(student_client):
    """Even though the sidebar hides /users, the route itself enforces access."""
    assert student_client.get("/users").status_code == 403


def test_unauthorized_mutation_blocked(student_client):
    # A student cannot open the create-student form.
    assert student_client.get("/students/new").status_code == 403


def test_authorization_denied_is_audited(student_client, admin):
    student_client.get("/users")  # triggers a denial
    audit_html = admin.get("/audit").text
    assert "authorization_denied" in audit_html
