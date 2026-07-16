"""Audit service — append-only recording of important actions.

Wires the ``AuditLog`` model (defined in Part 1, previously unused) into the
application. Services call ``AuditService.record(...)`` after a successful
mutation or a denied authorization attempt.

Safety (SECURITY_AND_PRIVACY_RULES.md §8): the ``detail`` payload must never
contain passwords, session cookies, CSRF tokens, full sensitive form bodies or
prohibited patient data. ``record`` serializes only the caller-provided,
already-sanitized ``detail`` dict and drops any key on a denylist as a
defense-in-depth measure.
"""

from __future__ import annotations

import json

from sqlalchemy.orm import Session

from app.logging_config import get_logger
from app.models.audit import AuditLog
from app.services.auth_service import Identity

logger = get_logger(__name__)

# Canonical audit action names (single source of truth for Part 2).
LOGIN_SUCCESS = "login_success"
LOGIN_FAILED = "login_failed"
LOGOUT = "logout"
CREATE_STUDENT = "create_student"
UPDATE_STUDENT = "update_student"
DEACTIVATE_STUDENT = "deactivate_student"
CREATE_SEDE = "create_sede"
UPDATE_SEDE = "update_sede"
DEACTIVATE_SEDE = "deactivate_sede"
REACTIVATE_SEDE = "reactivate_sede"
FORCE_DEACTIVATE_SEDE = "force_deactivate_sede"
SOFT_DELETE_SEDE = "soft_delete_sede"
CREATE_SEDE_COORDINATOR = "create_sede_coordinator"
UPDATE_SEDE_COORDINATOR = "update_sede_coordinator"
REASSIGN_SEDE_COORDINATOR = "reassign_sede_coordinator"
DEACTIVATE_SEDE_COORDINATOR = "deactivate_sede_coordinator"
REACTIVATE_SEDE_COORDINATOR = "reactivate_sede_coordinator"
REPLACE_SEDE_COORDINATOR = "replace_sede_coordinator"
CREATE_TUTOR = "create_tutor"
UPDATE_TUTOR = "update_tutor"
REASSIGN_TUTOR = "reassign_tutor"
DEACTIVATE_TUTOR = "deactivate_tutor"
REACTIVATE_TUTOR = "reactivate_tutor"
FORCE_DEACTIVATE_TUTOR = "force_deactivate_tutor"
CREATE_ROTATION_ASSIGNMENT = "create_rotation_assignment"
UPDATE_ROTATION_ASSIGNMENT = "update_rotation_assignment"
ASSIGN_TUTOR = "assign_tutor"
REASSIGN_TUTOR_ROTATION = "reassign_tutor"
REMOVE_TUTOR = "remove_tutor"
ACTIVATE_ROTATION_ASSIGNMENT = "activate_rotation_assignment"
CANCEL_ROTATION_ASSIGNMENT = "cancel_rotation_assignment"
COMPLETE_ROTATION_ASSIGNMENT = "complete_rotation_assignment"
REOPEN_ROTATION_ASSIGNMENT = "reopen_rotation_assignment"
OVERRIDE_ROTATION_CONFLICT = "override_rotation_conflict"
CONFLICT_VALIDATION_FAILED = "conflict_validation_failed"
CREATE_PENDING_EVALUATION = "create_pending_evaluation"

# Batch 2C — activity/procedure tracking.
CREATE_ACTIVITY_DEFINITION = "create_activity_definition"
UPDATE_ACTIVITY_DEFINITION = "update_activity_definition"
DEACTIVATE_ACTIVITY_DEFINITION = "deactivate_activity_definition"
CREATE_STUDENT_ACTIVITY = "create_student_activity"
UPDATE_STUDENT_ACTIVITY = "update_student_activity"
SUBMIT_STUDENT_ACTIVITY = "submit_student_activity"
CANCEL_STUDENT_ACTIVITY = "cancel_student_activity"
VERIFY_STUDENT_ACTIVITY = "verify_student_activity"
REJECT_STUDENT_ACTIVITY = "reject_student_activity"
CORRECT_STUDENT_ACTIVITY = "correct_student_activity"
REOPEN_STUDENT_ACTIVITY = "reopen_student_activity"
BULK_VERIFY_STUDENT_ACTIVITIES = "bulk_verify_student_activities"
IMPORT_ACTIVITY_CATALOG_PREVIEW = "import_activity_catalog_preview"
IMPORT_ACTIVITY_CATALOG_CONFIRMED = "import_activity_catalog_confirmed"
CREATE_ACTIVITY = "create_activity"
UPDATE_ACTIVITY = "update_activity"
VERIFY_ACTIVITY = "verify_activity"
REJECT_ACTIVITY = "reject_activity"
START_EVALUATION = "start_evaluation"
SAVE_EVALUATION_DRAFT = "save_evaluation_draft"
SUBMIT_EVALUATION = "submit_evaluation"
RETURN_EVALUATION = "return_evaluation"
APPROVE_EVALUATION = "approve_evaluation"
REOPEN_EVALUATION = "reopen_evaluation"

# Batch 2E — documents.
CREATE_DOCUMENT = "create_document"
UPDATE_DOCUMENT = "update_document"
SUBMIT_DOCUMENT = "submit_document"
START_DOCUMENT_REVIEW = "start_document_review"
APPROVE_DOCUMENT = "approve_document"
REJECT_DOCUMENT = "reject_document"
ARCHIVE_DOCUMENT = "archive_document"
REOPEN_DOCUMENT = "reopen_document"
UPLOAD_DOCUMENT_ATTACHMENT = "upload_document_attachment"
DOWNLOAD_DOCUMENT_ATTACHMENT = "download_document_attachment"
DELETE_DOCUMENT_ATTACHMENT = "delete_document_attachment"
GENERATE_DOCUMENT_PDF = "generate_document_pdf"

# Batch 2E — incidents.
CREATE_INCIDENT = "create_incident"
UPDATE_INCIDENT = "update_incident"
ASSIGN_INCIDENT = "assign_incident"
CHANGE_INCIDENT_STATUS = "change_incident_status"
RESOLVE_INCIDENT = "resolve_incident"
CLOSE_INCIDENT = "close_incident"
DISMISS_INCIDENT = "dismiss_incident"
REOPEN_INCIDENT = "reopen_incident"
UPLOAD_INCIDENT_ATTACHMENT = "upload_incident_attachment"
DOWNLOAD_INCIDENT_ATTACHMENT = "download_incident_attachment"
DELETE_INCIDENT_ATTACHMENT = "delete_incident_attachment"
DOWNLOAD_INCIDENT_ATTACHMENT = "download_incident_attachment"
DELETE_INCIDENT_ATTACHMENT = "delete_incident_attachment"

# Batch 2E — reports.
GENERATE_REPORT = "generate_report"
EXPORT_REPORT_EXCEL = "export_report_excel"
EXPORT_REPORT_PDF = "export_report_pdf"
GENERATE_STUDENT_SUMMARY = "generate_student_summary"

# Batch 2F — bulk import & grade foundation.
UPLOAD_IMPORT_FILE = "upload_import_file"
CREATE_IMPORT_BATCH = "create_import_batch"
MAP_IMPORT_COLUMNS = "map_import_columns"
VALIDATE_IMPORT_BATCH = "validate_import_batch"
CONFIRM_IMPORT_BATCH = "confirm_import_batch"
CANCEL_IMPORT_BATCH = "cancel_import_batch"
IMPORT_ROW_CREATED = "import_row_created"
IMPORT_ROW_UPDATED = "import_row_updated"
IMPORT_ROW_SKIPPED = "import_row_skipped"
IMPORT_ROW_FAILED = "import_row_failed"
DOWNLOAD_IMPORT_ERROR_REPORT = "download_import_error_report"
IMPORT_GRADE_COMPONENT = "import_grade_component"
UPDATE_GRADE_COMPONENT_FROM_IMPORT = "update_grade_component_from_import"

# Phase 3A — AI Coordinator Assistant.
AI_ASSISTANT_QUERY = "ai_assistant_query"
AI_ASSISTANT_RESPONSE = "ai_assistant_response"
AI_ASSISTANT_RATE_LIMITED = "ai_assistant_rate_limited"

AUTHORIZATION_DENIED = "authorization_denied"

# Keys never allowed inside an audit detail payload.
_DENYLIST = {
    "password", "hashed_password", "csrf_token", "csrf", "cookie",
    "session", "token", "document_id",
}


class AuditService:
    """Creates append-only audit-log entries."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def record(
        self,
        action: str,
        *,
        identity: Identity | None = None,
        actor_label: str | None = None,
        entity_type: str | None = None,
        entity_id: int | None = None,
        detail: dict | None = None,
        reason: str | None = None,
        ip_address: str | None = None,
        commit: bool = True,
    ) -> AuditLog:
        """Persist a single audit entry.

        ``reason`` (for overrides, rejections, cancellations, reopens) is merged
        into the detail payload. The payload is sanitized against the denylist.
        """
        safe_detail = self._sanitize(detail or {})
        if reason:
            safe_detail["reason"] = reason

        entry = AuditLog(
            actor_user_id=identity.user_id if identity else None,
            actor_label=actor_label or (identity.email if identity else "system"),
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            detail=json.dumps(safe_detail, ensure_ascii=False) if safe_detail else None,
            ip_address=ip_address,
        )
        self.db.add(entry)
        if commit:
            self.db.commit()
        logger.info("AUDIT %s by %s on %s#%s", action, entry.actor_label,
                    entity_type or "-", entity_id or "-")
        return entry

    @staticmethod
    def _sanitize(detail: dict) -> dict:
        """Drop denylisted keys (defense-in-depth); keep only JSON-safe values."""
        clean: dict = {}
        for key, value in detail.items():
            if key.lower() in _DENYLIST:
                continue
            if isinstance(value, (str, int, float, bool)) or value is None:
                clean[key] = value
            else:
                clean[key] = str(value)
        return clean


def client_ip(request) -> str | None:
    """Best-effort client IP for audit entries."""
    if request is None:
        return None
    return request.client.host if request.client else None
