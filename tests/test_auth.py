"""Authentication tests."""

from __future__ import annotations

from tests.conftest import login


def test_valid_login(client):
    r = login(client, "admin@internado360.demo")
    assert r.status_code == 200
    assert "Dashboard" in r.text or "dashboard" in str(r.url)


def test_invalid_login(client):
    r = client.post("/login", data={"email": "admin@internado360.demo",
                                    "password": "wrong"}, follow_redirects=True)
    assert "inválidas" in r.text.lower() or "invalid" in r.text.lower()


def test_logout(admin):
    r = admin.get("/logout", follow_redirects=False)
    assert r.status_code in (302, 303)
    # After logout, a protected page redirects to login.
    r2 = admin.get("/dashboard", follow_redirects=False)
    assert r2.status_code in (302, 303)
    assert "/login" in r2.headers.get("location", "")


def test_protected_route_redirects_when_anonymous(client):
    r = client.get("/dashboard", follow_redirects=False)
    assert r.status_code in (302, 303)
    assert "/login" in r.headers.get("location", "")
