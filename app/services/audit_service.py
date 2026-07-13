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
