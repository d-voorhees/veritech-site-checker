import uuid

import pytest
from fastapi.testclient import TestClient

from app.main import app as fastapi_app


@pytest.fixture()
def client():
    return TestClient(fastapi_app)


def _login(client, email, password="correct-horse-battery-staple"):
    resp = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert resp.status_code == 200, resp.text
    return resp


def _login_magic_link_user(db, organization, client):
    from app.models.user import User

    magic_link_user = User(
        organization_id=organization.id,
        email=f"magic-{uuid.uuid4().hex[:8]}@example.com",
        hashed_password=None,
        full_name="",
        role="member",
        is_active=True,
    )
    db.add(magic_link_user)
    db.commit()
    db.refresh(magic_link_user)

    from app.security.tokens import create_access_token

    token = create_access_token(magic_link_user.id)
    client.cookies.set("veritech_session", token)
    return magic_link_user


def test_me_reports_has_password_true_for_password_user(client, user):
    _login(client, user.email)
    resp = client.get("/api/v1/auth/me")
    assert resp.status_code == 200
    assert resp.json()["has_password"] is True


def test_me_reports_has_password_false_for_magic_link_user(client, db, organization):
    _login_magic_link_user(db, organization, client)
    resp = client.get("/api/v1/auth/me")
    assert resp.status_code == 200
    assert resp.json()["has_password"] is False


def test_set_password_requires_authentication(client):
    resp = client.post("/api/v1/auth/set-password", json={"password": "goodpassword1"})
    assert resp.status_code == 401


def test_set_password_rejects_too_short(client, db, organization):
    _login_magic_link_user(db, organization, client)
    resp = client.post("/api/v1/auth/set-password", json={"password": "short1"})
    assert resp.status_code == 400


def test_set_password_rejects_letters_only(client, db, organization):
    _login_magic_link_user(db, organization, client)
    resp = client.post("/api/v1/auth/set-password", json={"password": "onlylettershere"})
    assert resp.status_code == 400


def test_set_password_succeeds_and_enables_password_login(client, db, organization):
    magic_link_user = _login_magic_link_user(db, organization, client)
    resp = client.post("/api/v1/auth/set-password", json={"password": "goodpassword1"})
    assert resp.status_code == 200, resp.text

    me_resp = client.get("/api/v1/auth/me")
    assert me_resp.json()["has_password"] is True

    fresh_client = TestClient(fastapi_app)
    login_resp = fresh_client.post(
        "/api/v1/auth/login", json={"email": magic_link_user.email, "password": "goodpassword1"}
    )
    assert login_resp.status_code == 200, login_resp.text


def test_set_password_rejects_when_already_set(client, user):
    _login(client, user.email)
    resp = client.post("/api/v1/auth/set-password", json={"password": "anothergoodpass1"})
    assert resp.status_code == 400
