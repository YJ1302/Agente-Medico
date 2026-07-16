"""Pytest fixtures for UPeU Internado 360.

A **temporary** SQLite database is created for the whole test session and torn
down afterwards; the demo database is never touched (requirement N). The test
DB URL is set in the environment *before* importing the app so the engine binds
to it.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

# --- Point the app at a throwaway database BEFORE importing app modules. -----
_TMP_DIR = tempfile.mkdtemp(prefix="internado360_test_")
_TEST_DB = Path(_TMP_DIR) / "test.db"
os.environ["DATABASE_URL"] = f"sqlite:///{_TEST_DB.as_posix()}"
os.environ["DEMO_MODE"] = "true"
os.environ["SECRET_KEY"] = "test-secret-key-not-for-production"
# Force the AI Coordinator Assistant off regardless of a developer's local
# .env (which may carry a real, working provider key) — tests must never make
# real external API calls. Individual tests opt into "enabled" behavior via
# monkeypatch on the `settings` object, never via ambient environment state.
os.environ["AI_ASSISTANT_ENABLED"] = "false"
os.environ["ANTHROPIC_API_KEY"] = ""
os.environ["GEMINI_API_KEY"] = ""

from fastapi.testclient import TestClient  # noqa: E402

from app.database import Base, engine  # noqa: E402
from app.main import app  # noqa: E402
from app import seed as seed_module  # noqa: E402

DEMO_PASSWORD = "Demo123!"


@pytest.fixture(scope="session", autouse=True)
def _build_database():
    """Create schema and load the demo dataset once for the test session."""
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    seed_module.seed(reset=True)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def client():
    """A fresh TestClient (own cookie jar) per test."""
    with TestClient(app) as c:
        yield c


def _logged_in_client(email: str) -> TestClient:
    """Build an INDEPENDENT TestClient logged in as ``email``.

    Role fixtures use this (instead of sharing the single ``client`` fixture) so
    a test may request several roles at once — e.g. ``admin`` and
    ``university_client`` — without them clobbering each other's session, since
    pytest caches one instance of a shared fixture per test.
    """
    c = TestClient(app)
    c.__enter__()
    login(c, email)
    return c


def login(client: TestClient, email: str, password: str = DEMO_PASSWORD):
    """Log in and return the response (follows the redirect to the dashboard)."""
    return client.post(
        "/login",
        data={"email": email, "password": password},
        follow_redirects=True,
    )


def csrf_token(client: TestClient, path: str) -> str:
    """Fetch a page and extract its CSRF token."""
    import re
    html = client.get(path).text
    m = re.search(r'name="csrf_token" value="([^"]+)"', html)
    assert m, f"No CSRF token found on {path}"
    return m.group(1)


@pytest.fixture
def admin():
    c = _logged_in_client("admin@internado360.demo")
    yield c
    c.__exit__(None, None, None)


@pytest.fixture
def student_client():
    c = _logged_in_client("student@internado360.demo")
    yield c
    c.__exit__(None, None, None)


@pytest.fixture
def tutor_client():
    c = _logged_in_client("tutor@internado360.demo")
    yield c
    c.__exit__(None, None, None)


@pytest.fixture
def sede_client():
    c = _logged_in_client("sede@internado360.demo")
    yield c
    c.__exit__(None, None, None)


@pytest.fixture
def university_client():
    c = _logged_in_client("coordinator@internado360.demo")
    yield c
    c.__exit__(None, None, None)
