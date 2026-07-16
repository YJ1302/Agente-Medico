"""Secure attachment tests (Batch 2E)."""

from __future__ import annotations

from app.config import settings
from app.database import SessionLocal
from app.models.operations import OWNER_DOCUMENT
from app.repositories.repositories import RepositoryBundle
from tests.conftest import csrf_token

PDF_BYTES = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"
PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 128
EXE_BYTES = b"MZ\x90\x00" + b"\x00" * 64


def _tok(client) -> str:
    return csrf_token(client, "/documents/new")


def _new_draft(client) -> int:
    tok = csrf_token(client, "/documents/new")
    r = client.post("/documents",
                    data={"csrf_token": tok, "title": "Doc adjuntos",
                          "doc_type": "official_communication", "body": "b"},
                    follow_redirects=False)
    return int(r.headers["location"].rstrip("/").split("/")[-1])


def _upload(client, doc_id, filename, content, content_type):
    return client.post(
        f"/documents/{doc_id}/attachments",
        data={"csrf_token": _tok(client)},
        files={"file": (filename, content, content_type)},
        follow_redirects=False,
    )


def _atts(doc_id):
    db = SessionLocal()
    rows = RepositoryBundle(db).attachments.for_owner(OWNER_DOCUMENT, doc_id)
    db.close()
    return rows


def test_allowed_file_accepted(admin):
    doc_id = _new_draft(admin)
    r = _upload(admin, doc_id, "informe.pdf", PDF_BYTES, "application/pdf")
    assert r.status_code == 303
    atts = _atts(doc_id)
    assert len(atts) == 1
    assert atts[0].original_filename == "informe.pdf"
    assert atts[0].stored_filename != "informe.pdf"  # server-generated name


def test_invalid_extension_rejected(admin):
    doc_id = _new_draft(admin)
    _upload(admin, doc_id, "malware.exe", EXE_BYTES, "application/octet-stream")
    assert len(_atts(doc_id)) == 0


def test_mime_mismatch_rejected(admin):
    doc_id = _new_draft(admin)
    # .pdf extension but declared image/png MIME.
    _upload(admin, doc_id, "fake.pdf", PDF_BYTES, "image/png")
    assert len(_atts(doc_id)) == 0


def test_content_magic_mismatch_rejected(admin):
    doc_id = _new_draft(admin)
    # .pdf extension + pdf MIME but PNG magic bytes.
    _upload(admin, doc_id, "spoof.pdf", PNG_BYTES, "application/pdf")
    assert len(_atts(doc_id)) == 0


def test_oversized_file_rejected(admin):
    doc_id = _new_draft(admin)
    original = settings.attachment_max_mb
    settings.attachment_max_mb = 1
    try:
        big = PDF_BYTES + b"0" * (2 * 1024 * 1024)
        _upload(admin, doc_id, "big.pdf", big, "application/pdf")
    finally:
        settings.attachment_max_mb = original
    assert len(_atts(doc_id)) == 0


def test_path_traversal_prevented(admin):
    doc_id = _new_draft(admin)
    _upload(admin, doc_id, "../../etc/evil.pdf", PDF_BYTES, "application/pdf")
    atts = _atts(doc_id)
    assert len(atts) == 1
    # Original filename is reduced to a basename; no path separators survive.
    assert "/" not in atts[0].original_filename and "\\" not in atts[0].original_filename
    # The stored file lives inside the configured storage root.
    stored = (settings.attachment_storage_path / atts[0].stored_filename).resolve()
    assert settings.attachment_storage_path in stored.parents


def test_unauthorized_download_rejected(admin, student_client):
    doc_id = _new_draft(admin)  # owned by admin; student cannot view
    _upload(admin, doc_id, "informe.pdf", PDF_BYTES, "application/pdf")
    att_id = _atts(doc_id)[0].id
    r = student_client.get(f"/documents/attachments/{att_id}/download", follow_redirects=False)
    assert r.status_code == 403


def test_download_is_audited(admin):
    doc_id = _new_draft(admin)
    _upload(admin, doc_id, "informe.pdf", PDF_BYTES, "application/pdf")
    att_id = _atts(doc_id)[0].id
    r = admin.get(f"/documents/attachments/{att_id}/download")
    assert r.status_code == 200 and r.content == PDF_BYTES
    db = SessionLocal()
    logs = RepositoryBundle(db).audit_logs.recent(limit=50)
    db.close()
    assert any(l.action == "download_document_attachment" for l in logs)


def test_draft_attachment_deletion_works(admin):
    doc_id = _new_draft(admin)
    _upload(admin, doc_id, "informe.pdf", PDF_BYTES, "application/pdf")
    att_id = _atts(doc_id)[0].id
    admin.post(f"/documents/attachments/{att_id}/delete", data={"csrf_token": _tok(admin)})
    assert len(_atts(doc_id)) == 0  # soft-deleted -> excluded


def test_approved_attachment_deletion_blocked_for_non_admin(admin, university_client):
    doc_id = _new_draft(admin)
    _upload(admin, doc_id, "informe.pdf", PDF_BYTES, "application/pdf")
    att_id = _atts(doc_id)[0].id
    admin.post(f"/documents/{doc_id}/submit", data={"csrf_token": _tok(admin)})
    university_client.post(f"/documents/{doc_id}/review", data={"csrf_token": _tok(university_client)})
    university_client.post(f"/documents/{doc_id}/approve", data={"csrf_token": _tok(university_client)})
    # University (non-admin) cannot delete an attachment on a locked document.
    r = university_client.post(f"/documents/attachments/{att_id}/delete",
                               data={"csrf_token": _tok(university_client)}, follow_redirects=False)
    assert r.status_code == 403
    assert len(_atts(doc_id)) == 1  # still present
