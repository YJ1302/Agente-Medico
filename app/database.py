"""Database engine, session factory and declarative base.

Design decisions (see SYSTEM_ARCHITECTURE.md and DECISIONS_LOG.md):

* SQLite is used for the prototype. The engine is created with a URL from
  configuration so switching to PostgreSQL in production is a one-line change.
* ``check_same_thread=False`` is required for SQLite under a threaded ASGI
  server; it is ignored for other backends.
* A scoped, request-bound session is provided through the ``get_db`` FastAPI
  dependency so routes/services never manage engine state directly.
"""

from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import settings

# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------
_is_sqlite = settings.database_url.startswith("sqlite")

engine = create_engine(
    settings.database_url,
    echo=False,
    future=True,
    connect_args={"check_same_thread": False} if _is_sqlite else {},
)

SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False,
    expire_on_commit=False,
    class_=Session,
)


class Base(DeclarativeBase):
    """Declarative base shared by every ORM model."""


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency that yields a request-scoped database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@contextmanager
def get_db_session() -> Generator[Session, None, None]:
    """Context-managed session for use outside request handlers.

    Used by exception handlers and background tasks that need a session without
    the FastAPI dependency machinery.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """Create all tables. Safe to call multiple times (idempotent).

    Importing ``app.models`` registers every model on ``Base.metadata`` so a
    single ``create_all`` builds the full schema.
    """
    import app.models  # noqa: F401  (side-effect: register model tables)

    Base.metadata.create_all(bind=engine)
