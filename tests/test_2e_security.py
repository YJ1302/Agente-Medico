"""Cross-cutting security tests for documents/incidents/reports (Batch 2E)."""

from __future__ import annotations

import json

from app.database import SessionLocal
from app.repositories.repositories import RepositoryBundle
from tests.conftest import csrf_token


def _new_draft(admin) -> int:
    tok = csrf_token(admin, "/documents/new")
    r = admin.post("/documents",
                   data={"csrf_token": tok, "title": "Sec", "doc_type": "official_communication",
                         "body": "cuerpo confidencial de prueba"},
                   follow_redirects=False)
    return int(r.headers["location"].rstrip("/").split("/")[-1])


def test_csrf_required_on_document_mutation(admin):
    doc_id = _new_draft(admin)
    # POST without a csrf token is rejected (400).
    r = admin.post(f"/documents/{doc_id}/submit", data={}, follow_redirects=False)
    assert r.status_code == 400


def test_csrf_required_on_incident_mutation(admin):
    r = admin.post("/incidents",
                   data={"title": "x", "incident_type": "conduct", "severity": "low",
                         "description": "d"},
                   follow_redirects=False)
    assert r.status_code == 400


def test_get_does_not_mutate_documents(admin):
    doc_id = _new_draft(admin)
    # GET on a transition endpoint is not allowed (only POST).
    r = admin.get(f"/documents/{doc_id}/submit")
    assert r.status_code == 405
    r2 = admin.get(f"/documents/{doc_id}/approve")
    assert r2.status_code == 405


def test_get_does_not_mutate_incidents(admin):
    r = admin.get("/incidents/1/resolve")
    assert r.status_code == 405


def test_authorization_denial_is_audited(student_client):
    # Student accesses a sede-2 document -> 403 + authorization_denied audit entry.
    before = _count_denials()
    r = student_client.get("/documents/4", follow_redirects=False)
    assert r.status_code == 403
    assert _count_denials() > before


def test_confidential_data_absent_from_unauthorized_html(sede_client):
    # The confidential seeded incident (id 5, sede 2) must not leak to sede@.
    html = sede_client.get("/incidents").text
    assert "Asunto de confidencialidad" not in html


def test_audit_detail_excludes_sensitive_values(admin):
    _new_draft(admin)
    db = SessionLocal()
    logs = RepositoryBundle(db).audit_logs.recent(limit=40)
    db.close()
    for log in logs:
        if not log.detail:
            continue
        payload = json.loads(log.detail)
        keys = {k.lower() for k in payload}
        assert "password" not in keys and "csrf_token" not in keys
        # The document body/confidential content is never stored in the audit detail.
        assert "cuerpo confidencial" not in json.dumps(payload).lower()


def _count_denials() -> int:
    db = SessionLocal()
    logs = RepositoryBundle(db).audit_logs.recent(limit=200)
    db.close()
    return sum(1 for l in logs if l.action == "authorization_denied")
