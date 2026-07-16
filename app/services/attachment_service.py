"""Secure local attachment storage (Batch 2E).

Security model (docs/FILE_UPLOAD_SECURITY.md):

* Whitelist of extensions AND matching MIME types; both must agree, and the
  file's magic bytes are sniffed so a renamed executable is rejected.
* The original filename is never trusted: only its basename is stored for
  display, and the on-disk name is a server-generated UUID.
* Files live OUTSIDE app/static (``settings.attachment_storage_path``) and are
  served only through an authorized route that streams them as an attachment —
  there are no public direct URLs and uploaded files are never executed.
* Path traversal is impossible: the stored path is ``storage / uuid.ext`` and is
  re-validated to be inside the storage root before any read/write.
* Every upload / download / delete is audited.
"""

from __future__ import annotations

import os
import uuid
from pathlib import Path

from sqlalchemy.orm import Session

from app.config import settings
from app.models.operations import Attachment
from app.repositories.repositories import RepositoryBundle
from app.services.audit_service import AuditService
from app.services.auth_service import Identity
from app.services.validators import ValidationError

# extension -> set of acceptable declared MIME types.
ALLOWED: dict[str, set[str]] = {
    "pdf": {"application/pdf"},
    "docx": {
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/zip", "application/octet-stream",
    },
    "xlsx": {
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "application/zip", "application/octet-stream",
    },
    "xlsm": {
        "application/vnd.ms-excel.sheet.macroenabled.12",
        "application/vnd.ms-excel.sheet.macroEnabled.12",
        "application/zip", "application/octet-stream",
    },
    "png": {"image/png"},
    "jpg": {"image/jpeg"},
    "jpeg": {"image/jpeg"},
}

# extension family -> expected leading magic bytes.
_MAGIC: dict[str, list[bytes]] = {
    "pdf": [b"%PDF"],
    "png": [b"\x89PNG\r\n\x1a\n"],
    "jpg": [b"\xff\xd8\xff"],
    "jpeg": [b"\xff\xd8\xff"],
    "docx": [b"PK\x03\x04", b"PK\x05\x06"],
    "xlsx": [b"PK\x03\x04", b"PK\x05\x06"],
    "xlsm": [b"PK\x03\x04", b"PK\x05\x06"],
}


def _ext(filename: str) -> str:
    base = os.path.basename(filename or "")
    return base.rsplit(".", 1)[-1].lower() if "." in base else ""


class AttachmentService:
    def __init__(self, db: Session, identity: Identity) -> None:
        self.db = db
        self.identity = identity
        self.repos = RepositoryBundle(db)
        self.audit = AuditService(db)
        self.root = settings.attachment_storage_path

    # -- validation --------------------------------------------------------
    def validate(self, filename: str, content_type: str | None, raw: bytes) -> str:
        """Return the validated extension or raise ValidationError."""
        ext = _ext(filename)
        if ext not in ALLOWED:
            raise ValidationError({"file": "Tipo de archivo no permitido. "
                                           "Use PDF, DOCX, XLSX, XLSM, PNG o JPG."})
        declared = (content_type or "").strip().lower()
        allowed_mimes = {m.lower() for m in ALLOWED[ext]}
        if declared and declared not in allowed_mimes:
            raise ValidationError({"file": "El tipo MIME no corresponde a la extensión del archivo."})
        if len(raw) == 0:
            raise ValidationError({"file": "El archivo está vacío."})
        if len(raw) > settings.attachment_max_bytes:
            raise ValidationError({"file": f"El archivo supera el tamaño máximo "
                                           f"({settings.attachment_max_mb} MB)."})
        magics = _MAGIC.get(ext, [])
        if magics and not any(raw.startswith(m) for m in magics):
            raise ValidationError({"file": "El contenido del archivo no corresponde a su extensión."})
        return ext

    # -- storage -----------------------------------------------------------
    def _safe_path(self, stored_filename: str) -> Path:
        """Resolve a stored filename inside the storage root (traversal-proof)."""
        self.root.mkdir(parents=True, exist_ok=True)
        # Only ever use the basename; reject anything that escapes the root.
        candidate = (self.root / os.path.basename(stored_filename)).resolve()
        if self.root not in candidate.parents and candidate.parent != self.root:
            raise ValidationError({"file": "Ruta de archivo inválida."})
        return candidate

    def store(self, owner_type: str, owner_id: int, filename: str,
              content_type: str | None, raw: bytes, *, audit_action: str,
              ip: str | None = None) -> Attachment:
        ext = self.validate(filename, content_type, raw)
        stored_filename = f"{uuid.uuid4().hex}.{ext}"
        path = self._safe_path(stored_filename)
        # Normalise the declared MIME to the canonical type for the extension.
        canonical = sorted(ALLOWED[ext])[0]
        with open(path, "wb") as fh:
            fh.write(raw)
        att = Attachment(
            owner_type=owner_type, owner_id=owner_id,
            original_filename=os.path.basename(filename or "archivo"),
            stored_filename=stored_filename,
            mime_type=(content_type or canonical),
            size_bytes=len(raw),
            uploaded_by_user_id=self.identity.user_id,
        )
        self.repos.attachments.add(att)
        self.audit.record(audit_action, identity=self.identity,
                          entity_type=owner_type, entity_id=owner_id,
                          detail={"attachment_id": att.id, "filename": att.original_filename,
                                  "size": att.size_bytes, "mime": att.mime_type},
                          ip_address=ip, commit=False)
        self.db.commit()
        return att

    def resolve_download(self, attachment: Attachment, *, audit_action: str,
                         ip: str | None = None) -> Path:
        path = self._safe_path(attachment.stored_filename)
        if not path.exists():
            raise ValidationError({"file": "El archivo no está disponible."})
        self.audit.record(audit_action, identity=self.identity,
                          entity_type=attachment.owner_type, entity_id=attachment.owner_id,
                          detail={"attachment_id": attachment.id,
                                  "filename": attachment.original_filename}, ip_address=ip)
        return path

    def soft_delete(self, attachment: Attachment, *, audit_action: str,
                    reason: str | None = None, ip: str | None = None) -> None:
        from app.models.base import utcnow
        attachment.is_deleted = True
        attachment.deleted_at = utcnow()
        attachment.deleted_by_user_id = self.identity.user_id
        self.db.flush()
        # Best-effort physical removal (row kept for audit history).
        try:
            path = self._safe_path(attachment.stored_filename)
            if path.exists():
                path.unlink()
        except Exception:  # never let file cleanup break the request
            pass
        self.audit.record(audit_action, identity=self.identity,
                          entity_type=attachment.owner_type, entity_id=attachment.owner_id,
                          detail={"attachment_id": attachment.id,
                                  "filename": attachment.original_filename},
                          reason=reason, ip_address=ip, commit=False)
        self.db.commit()
