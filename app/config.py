"""Centralized application configuration.

All configuration is read from environment variables (loaded from a local
`.env` file in development). This keeps secrets and environment-specific
values out of the source tree, per SECURITY_AND_PRIVACY_RULES.md.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# Absolute path to the project root (the folder that contains `app/`).
BASE_DIR = Path(__file__).resolve().parent.parent
APP_DIR = BASE_DIR / "app"


class Settings(BaseSettings):
    """Strongly-typed application settings.

    Values are sourced from environment variables / the `.env` file. Defaults
    are safe for local development only.
    """

    # Application ---------------------------------------------------------
    app_name: str = "UPeU Internado 360"
    app_subtitle: str = (
        "Agentic platform for the planning, monitoring and evaluation "
        "of the Medical Internship"
    )
    app_env: str = "development"
    debug: bool = True

    # Demo mode controls whether the seeded credentials are shown on login.
    demo_mode: bool = True

    # Security ------------------------------------------------------------
    secret_key: str = "change-me-in-production-please-use-a-long-random-value"
    session_cookie_name: str = "internado360_session"
    session_max_age: int = 60 * 60 * 8  # 8 hours, in seconds

    # Database ------------------------------------------------------------
    database_url: str = "sqlite:///./app/data/internado360.db"

    # Server --------------------------------------------------------------
    host: str = "127.0.0.1"
    port: int = 8000

    # Logging -------------------------------------------------------------
    log_level: str = "INFO"

    # Operational thresholds ---------------------------------------------
    # Number of active/planned assignments above which a tutor's workload is
    # flagged as a WARNING (not a hard block). Configurable per deployment.
    tutor_assignment_warning_threshold: int = 5

    # Rotation duration tolerance: an assignment whose length differs from the
    # rotation type's expected duration by more than this ratio triggers an
    # "unusual duration" warning (not a block).
    rotation_duration_tolerance_ratio: float = 0.4
    # Period/date fit: dates outside the academic period by up to this many days
    # produce a WARNING; beyond the hard limit they are BLOCKED (override-able).
    rotation_period_warning_days: int = 14
    rotation_period_block_days: int = 60

    # Activity tracking (Batch 2C) ----------------------------------------
    # Retrospective grace window: an activity date may fall this many days
    # before the rotation start / after its end without being rejected.
    activity_retrospective_grace_days: int = 7
    # A pending activity older than this many days triggers the
    # old_pending_activity rule.
    activity_old_pending_days: int = 5
    # A rejected activity not corrected within this many days triggers
    # rejected_activity_requires_correction.
    activity_rejected_correction_days: int = 5
    # A rotation ending within this many days with a fixed-target activity
    # below the ratio below triggers activity_target_at_risk.
    activity_at_risk_rotation_days: int = 10
    activity_at_risk_threshold_ratio: float = 0.5
    # A tutor with more old pending activities than this triggers
    # tutor_verification_backlog.
    tutor_verification_backlog_threshold: int = 8

    # Documents & incidents (Batch 2E) ------------------------------------
    # A document waiting review longer than this many days triggers
    # document_overdue (also honoured against an explicit due_date).
    document_overdue_days: int = 5
    # An incident due within this many days triggers incident_due_soon.
    incident_due_soon_days: int = 3
    # An unresolved incident whose rotation ends within this many days triggers
    # unresolved_incident_near_rotation_end.
    incident_rotation_end_days: int = 7

    # Secure attachments (Batch 2E) ---------------------------------------
    # Maximum upload size in megabytes (configurable per deployment).
    attachment_max_mb: int = 10
    # Directory (relative to the project root) where uploaded files are stored.
    # Intentionally OUTSIDE app/static so files are never publicly served.
    attachment_storage_dir: str = "var/attachments"

    # Bulk import (Batch 2F) ----------------------------------------------
    # Maximum import file size in megabytes.
    import_max_mb: int = 8
    # Maximum data rows processed per import batch (safety/limits).
    import_max_rows: int = 2000
    # Temp directory (relative to project root) for uploaded import files;
    # OUTSIDE app/static. Files are deleted after import unless retention is on.
    import_storage_dir: str = "var/imports"
    # Retain the uploaded file after import (audit retention). Default: delete.
    import_retain_files: bool = False

    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    @property
    def is_production(self) -> bool:
        """True when running outside development environments."""
        return self.app_env.lower() in {"production", "prod"}

    @property
    def institution_name(self) -> str:
        return "Universidad Peruana Unión"

    @property
    def attachment_max_bytes(self) -> int:
        return self.attachment_max_mb * 1024 * 1024

    @property
    def attachment_storage_path(self) -> Path:
        """Absolute path to the private attachment storage directory."""
        p = self.attachment_storage_dir
        path = Path(p) if Path(p).is_absolute() else (BASE_DIR / p)
        return path.resolve()

    @property
    def import_max_bytes(self) -> int:
        return self.import_max_mb * 1024 * 1024

    @property
    def import_storage_path(self) -> Path:
        """Absolute path to the private import upload directory."""
        p = self.import_storage_dir
        path = Path(p) if Path(p).is_absolute() else (BASE_DIR / p)
        return path.resolve()


@lru_cache
def get_settings() -> Settings:
    """Return a cached Settings instance (single source of truth)."""
    return Settings()


settings = get_settings()

# Ensure the SQLite data directory exists for the prototype.
if settings.database_url.startswith("sqlite"):
    (APP_DIR / "data").mkdir(parents=True, exist_ok=True)
