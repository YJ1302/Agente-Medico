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


def test_tutor_cannot_view_unassigned_student(tutor_client):
    # A high student id the tutor is not assigned to.
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
