"""Formal document management tests (Batch 2E)."""

from __future__ import annotations

import re

from app.database import SessionLocal
from app.models.base import DocumentStatus
from app.repositories.repositories import RepositoryBundle
from tests.conftest import csrf_token

# Seeded document ids (see app/seed.py Batch 2E block; id == sequence number).
DOC_DRAFT_SEDE1 = 1          # draft, sede 1 (sede@'s sede), created by sede coord
DOC_SUBMITTED = 2            # submitted, sede 1
DOC_UNDER_REVIEW_SEDE2 = 3   # under_review, sede 2 (outside sede@)
DOC_APPROVED_SEDE2 = 4       # approved, sede 2
DOC_REJECTED_SEDE1 = 5       # rejected, sede 1
DOC_ARCHIVED_SEDE2 = 6       # archived, sede 2
DOC_RESIGNATION = 7          # approved resignation, sede 2, student 4
DOC_STUDENT_DRAFT = 8        # draft sede_change by demo student (student id 1)
DOC_OVERDUE = 9              # submitted overdue, sede 1


def _repos():
    return RepositoryBundle(SessionLocal())


def _create_draft(client, **over) -> int:
    tok = csrf_token(client, "/documents/new")
    data = {"csrf_token": tok, "title": "Documento de prueba",
            "doc_type": "official_communication", "body": "Contenido de prueba."}
    data.update(over)
    r = client.post("/documents", data=data, follow_redirects=False)
    assert r.status_code == 303, r.text
    return int(r.headers["location"].rstrip("/").split("/")[-1])


def _tok(client) -> str:
    return csrf_token(client, "/documents/new")


# --- Creation & numbering ----------------------------------------------------
def test_create_draft(admin):
    doc_id = _create_draft(admin)
    db = SessionLocal()
    doc = RepositoryBundle(db).documents.get_full(doc_id)
    assert doc.status == DocumentStatus.DRAFT.value
    assert doc.created_by_user_id is not None
    db.close()


def test_unique_sequential_code_generated(admin):
    id1 = _create_draft(admin)
    id2 = _create_draft(admin)
    db = SessionLocal()
    r = RepositoryBundle(db)
    c1, c2 = r.documents.get_full(id1).code, r.documents.get_full(id2).code
    db.close()
    assert c1 != c2
    assert re.match(r"^DOC-\d{4}-\d{4}$", c1) and re.match(r"^DOC-\d{4}-\d{4}$", c2)
    assert int(c2.split("-")[2]) == int(c1.split("-")[2]) + 1


def test_draft_editable(admin):
    doc_id = _create_draft(admin)
    tok = csrf_token(admin, f"/documents/{doc_id}/edit")
    r = admin.post(f"/documents/{doc_id}/edit",
                   data={"csrf_token": tok, "title": "Título editado",
                         "doc_type": "official_communication", "body": "Nuevo"},
                   follow_redirects=False)
    assert r.status_code == 303
    db = SessionLocal()
    assert RepositoryBundle(db).documents.get_full(doc_id).title == "Título editado"
    db.close()


def test_submitted_document_is_locked(admin):
    doc_id = _create_draft(admin)
    admin.post(f"/documents/{doc_id}/submit", data={"csrf_token": _tok(admin)})
    # Editing a submitted (locked) document is refused (403).
    tok = _tok(admin)
    r = admin.post(f"/documents/{doc_id}/edit",
                   data={"csrf_token": tok, "title": "x", "doc_type": "official_communication"},
                   follow_redirects=False)
    assert r.status_code == 403


def test_rejection_requires_reason(university_client, admin):
    doc_id = _create_draft(admin)
    admin.post(f"/documents/{doc_id}/submit", data={"csrf_token": _tok(admin)})
    university_client.post(f"/documents/{doc_id}/review", data={"csrf_token": _tok(university_client)})
    # Reject with empty reason -> flashed error, still under_review.
    university_client.post(f"/documents/{doc_id}/reject",
                           data={"csrf_token": _tok(university_client), "reason": ""})
    db = SessionLocal()
    assert RepositoryBundle(db).documents.get_full(doc_id).status == DocumentStatus.UNDER_REVIEW.value
    db.close()


def test_reject_then_return_to_draft(university_client, admin):
    doc_id = _create_draft(admin)
    admin.post(f"/documents/{doc_id}/submit", data={"csrf_token": _tok(admin)})
    university_client.post(f"/documents/{doc_id}/review", data={"csrf_token": _tok(university_client)})
    university_client.post(f"/documents/{doc_id}/reject",
                           data={"csrf_token": _tok(university_client), "reason": "Falta sustento"})
    db = SessionLocal()
    doc = RepositoryBundle(db).documents.get_full(doc_id)
    assert doc.status == DocumentStatus.REJECTED.value and doc.rejection_reason == "Falta sustento"
    db.close()
    admin.post(f"/documents/{doc_id}/return", data={"csrf_token": _tok(admin)})
    db = SessionLocal()
    assert RepositoryBundle(db).documents.get_full(doc_id).status == DocumentStatus.DRAFT.value
    db.close()


def test_approval_and_archive(university_client, admin):
    doc_id = _create_draft(admin)
    admin.post(f"/documents/{doc_id}/submit", data={"csrf_token": _tok(admin)})
    university_client.post(f"/documents/{doc_id}/review", data={"csrf_token": _tok(university_client)})
    university_client.post(f"/documents/{doc_id}/approve", data={"csrf_token": _tok(university_client), "note": "ok"})
    db = SessionLocal()
    assert RepositoryBundle(db).documents.get_full(doc_id).status == DocumentStatus.APPROVED.value
    db.close()
    university_client.post(f"/documents/{doc_id}/archive", data={"csrf_token": _tok(university_client)})
    db = SessionLocal()
    assert RepositoryBundle(db).documents.get_full(doc_id).status == DocumentStatus.ARCHIVED.value
    db.close()


def test_reopen_requires_admin_and_reason(university_client, admin):
    doc_id = _create_draft(admin)
    admin.post(f"/documents/{doc_id}/submit", data={"csrf_token": _tok(admin)})
    university_client.post(f"/documents/{doc_id}/review", data={"csrf_token": _tok(university_client)})
    university_client.post(f"/documents/{doc_id}/approve", data={"csrf_token": _tok(university_client)})
    # University cannot reopen (403).
    r = university_client.post(f"/documents/{doc_id}/reopen",
                               data={"csrf_token": _tok(university_client), "reason": "x"},
                               follow_redirects=False)
    assert r.status_code == 403
    # Admin reopen without reason -> stays approved.
    admin.post(f"/documents/{doc_id}/reopen", data={"csrf_token": _tok(admin), "reason": ""})
    db = SessionLocal()
    assert RepositoryBundle(db).documents.get_full(doc_id).status == DocumentStatus.APPROVED.value
    db.close()
    # Admin reopen with reason -> back to draft.
    admin.post(f"/documents/{doc_id}/reopen", data={"csrf_token": _tok(admin), "reason": "Corrección"})
    db = SessionLocal()
    assert RepositoryBundle(db).documents.get_full(doc_id).status == DocumentStatus.DRAFT.value
    db.close()


# --- Scope & visibility ------------------------------------------------------
def test_student_sees_only_own_documents(student_client):
    html = student_client.get("/documents").text
    # Demo student owns DOC-2026-0008; must not see sede-2 documents.
    assert "DOC-2026-0008" in html
    assert "DOC-2026-0004" not in html  # sede 2 coordinator designation


def test_student_cannot_open_other_document(student_client):
    r = student_client.get(f"/documents/{DOC_APPROVED_SEDE2}", follow_redirects=False)
    assert r.status_code == 403


def test_sede_coordinator_sees_only_own_sede(sede_client):
    html = sede_client.get("/documents").text
    assert "DOC-2026-0001" in html  # sede 1
    # A sede-2 document must not be visible by URL either.
    r = sede_client.get(f"/documents/{DOC_UNDER_REVIEW_SEDE2}", follow_redirects=False)
    assert r.status_code == 403


def test_student_cannot_create_institutional_type(student_client):
    tok = csrf_token(student_client, "/documents/new")
    r = student_client.post("/documents",
                            data={"csrf_token": tok, "title": "X",
                                  "doc_type": "coordinator_designation", "body": "b"},
                            follow_redirects=False)
    assert r.status_code == 403


def test_confidential_document_hidden_from_non_global(sede_client, admin):
    # Create a confidential document as admin.
    tok = csrf_token(admin, "/documents/new")
    r = admin.post("/documents",
                   data={"csrf_token": tok, "title": "Confidencial",
                         "doc_type": "official_communication", "body": "secreto",
                         "visibility": "confidential"},
                   follow_redirects=False)
    doc_id = int(r.headers["location"].rstrip("/").split("/")[-1])
    # Sede coordinator must not see it in list nor by URL.
    assert "Confidencial" not in sede_client.get("/documents").text or \
        sede_client.get(f"/documents/{doc_id}", follow_redirects=False).status_code == 403
    assert sede_client.get(f"/documents/{doc_id}", follow_redirects=False).status_code == 403


def test_pdf_export_returns_pdf(admin):
    r = admin.get(f"/documents/{DOC_RESIGNATION}/pdf")
    assert r.status_code == 200
    assert r.content[:4] == b"%PDF"
