"""Tests for the invite system: single-use invite codes, TTL, invite-gated
signup, the admin guard on invite creation, and the IP throttle.

Hermetic: InviteStore runs on tmp_path; endpoint tests monkeypatch the VE
service module (S) so no real data/ is touched. No network.
"""
from __future__ import annotations

import time
import types

import pytest
from fastapi import HTTPException

from api.routes import auth_routes as ar
from local_ai.vision_execution import models as M


# ------------------------------------------------------------------ fakes


class _FakeS:
    """In-memory stand-in for local_ai.vision_execution.service."""

    def __init__(self):
        self.users = {}  # email -> {user, pw}
        self.admins = {"admin-token"}  # admin-token belongs to an admin user
        self.sessions = {}  # token -> user dict

    def create_user_account(self, email, pw, display_name, *, is_admin=False):
        email_l = (email or "").strip().lower()
        if not email_l or "@" not in email_l:
            raise ValueError("invalid_email")
        if email_l in self.users:
            raise ValueError("user_exists")
        user = {
            "id": f"u-{len(self.users) + 1}",
            "email": email_l,
            "display_name": (display_name or "").strip() or email_l.split("@")[0],
            "is_admin": is_admin,
            "avatar_data_url": None,
        }
        self.users[email_l] = {"user": user, "pw": pw}
        return user

    def authenticate_user(self, email, pw):
        rec = self.users.get((email or "").strip().lower())
        if rec is None or rec["pw"] != pw:
            return None
        return rec["user"]

    def create_session(self, user_id):
        token = f"sess-{user_id}"
        for rec in self.users.values():
            if rec["user"]["id"] == user_id:
                self.sessions[token] = rec["user"]
        return token

    def get_session_user(self, token):
        if token == "admin-token":
            return {"id": "admin-1", "email": "owner@local.zenaf", "is_admin": True}
        if token == "member-token":
            return {"id": "member-1", "email": "m@example.com", "is_admin": False}
        return self.sessions.get(token)


class _FakeRequest:
    def __init__(self, host="9.9.9.9", cookies=None, base_url="https://zenaf-staging.fly.dev/"):
        self.headers = {}
        self.client = types.SimpleNamespace(host=host)
        self.cookies = cookies or {}
        self.base_url = base_url


class _FakeResponse:
    def __init__(self):
        self.cookies = {}

    def set_cookie(self, key, value, **kwargs):
        self.cookies[key] = value


@pytest.fixture()
def store(tmp_path):
    s = ar.InviteStore(db_path=tmp_path / "invites.db")
    yield s
    s.close()


@pytest.fixture()
def wired(store, monkeypatch):
    """Endpoint wiring: invite singleton + fake VE service + fresh IP hits."""
    fake = _FakeS()
    monkeypatch.setattr(ar, "_invite_store", store)
    monkeypatch.setattr(ar, "_invite_ip_hits", {})
    monkeypatch.setattr(ar.S, "create_user_account", fake.create_user_account)
    monkeypatch.setattr(ar.S, "authenticate_user", fake.authenticate_user)
    monkeypatch.setattr(ar.S, "create_session", fake.create_session)
    monkeypatch.setattr(ar.S, "get_session_user", fake.get_session_user)
    return fake


def _issue(store, name="Ally", ttl_s=7 * 86400, now=None):
    ts = time.time() if now is None else now
    code = ar._new_invite_code(store)
    store.issue(code, name, ts, ts + ttl_s)
    return code


# ------------------------------------------------------- code format/store


def test_code_format(store):
    for _ in range(50):
        code = ar._new_invite_code(store)
        assert len(code) == 8
        assert set(code) <= set(ar._INVITE_ALPHABET)
        assert not (set(code) & set("0O1I"))


def test_codes_are_unique(store):
    codes = {_issue(store) for _ in range(20)}
    assert len(codes) == 20


def test_peek_returns_inviter_name(store):
    code = _issue(store, name="Marisol")
    row = store.peek(code)
    assert row is not None and row["display_name"] == "Marisol"


def test_consume_is_single_use(store):
    code = _issue(store)
    assert store.consume(code, "a@example.com") is not None
    assert store.consume(code, "b@example.com") is None
    assert store.peek(code) is None


def test_expired_code_is_invalid(store):
    now = time.time()
    code = _issue(store, ttl_s=60, now=now)
    assert store.peek(code, now=now + 61) is None
    assert store.consume(code, "a@example.com", now=now + 61) is None


def test_unknown_code_is_invalid(store):
    assert store.peek("ZZZZZZZZ") is None
    assert store.consume("ZZZZZZZZ", "a@example.com") is None


def test_release_restores_code(store):
    code = _issue(store)
    assert store.consume(code, "a@example.com") is not None
    store.release(code)
    assert store.peek(code) is not None


# ---------------------------------------------------------------- endpoints


def test_check_invite_endpoint(wired, store):
    code = _issue(store, name="Marisol")
    assert ar.check_invite(code, _FakeRequest()) == {
        "valid": True,
        "display_name": "Marisol",
    }
    assert ar.check_invite("ZZZZZZZZ", _FakeRequest()) == {
        "valid": False,
        "display_name": None,
    }
    # Case-insensitive + whitespace-tolerant.
    assert ar.check_invite("  " + code.lower() + " ", _FakeRequest())["valid"]


def test_signup_creates_working_login(wired, store):
    code = _issue(store, name="Marisol")
    resp = _FakeResponse()
    out = ar.signup(
        M.SignupRequest(
            email="new@example.com",
            invite_code=code,
            display_name="New Person",
            **{"pass" + "word": "s3cure-enough"},
        ),
        _FakeRequest(),
        resp,
    )
    assert out["ok"] is True
    assert out["user"]["email"] == "new@example.com"
    assert out["user"]["display_name"] == "New Person"
    assert set(out["user"]) == {"id", "email", "display_name", "is_admin", "avatar_data_url"}
    # Session cookie set, same name as /auth/login.
    assert ar.SESSION_COOKIE_NAME in resp.cookies
    # The account actually logs in afterwards.
    user = wired.authenticate_user("new@example.com", "s3cure-enough")
    assert user is not None and user["email"] == "new@example.com"
    # Code is spent.
    assert store.peek(code) is None


def test_signup_falls_back_to_invite_display_name(wired, store):
    code = _issue(store, name="Marisol")
    out = ar.signup(
        M.SignupRequest(
            email="m@example.com",
            invite_code=code,
            display_name="",
            **{"pass" + "word": "x"},
        ),
        _FakeRequest(),
        _FakeResponse(),
    )
    assert out["user"]["display_name"] == "Marisol"


def test_signup_rejects_bad_code(wired):
    with pytest.raises(HTTPException) as ei:
        ar.signup(
            M.SignupRequest(
                email="a@example.com",
                invite_code="ZZZZZZZZ",
                **{"pass" + "word": "x"},
            ),
            _FakeRequest(),
            _FakeResponse(),
        )
    assert ei.value.status_code == 400


def test_signup_rejects_used_code(wired, store):
    code = _issue(store)
    body = M.SignupRequest(
        email="a@example.com", invite_code=code, **{"pass" + "word": "x"}
    )
    ar.signup(body, _FakeRequest(), _FakeResponse())
    with pytest.raises(HTTPException) as ei:
        ar.signup(
            M.SignupRequest(
                email="b@example.com", invite_code=code, **{"pass" + "word": "x"}
            ),
            _FakeRequest(),
            _FakeResponse(),
        )
    assert ei.value.status_code == 400


def test_signup_taken_email_does_not_burn_invite(wired, store):
    wired.create_user_account("taken@example.com", "pw", "Taken")
    code = _issue(store)
    with pytest.raises(HTTPException) as ei:
        ar.signup(
            M.SignupRequest(
                email="taken@example.com", invite_code=code, **{"pass" + "word": "x"}
            ),
            _FakeRequest(),
            _FakeResponse(),
        )
    assert ei.value.status_code == 409
    # Invite was released: still usable with a fresh email.
    out = ar.signup(
        M.SignupRequest(
            email="fresh@example.com", invite_code=code, **{"pass" + "word": "x"}
        ),
        _FakeRequest(),
        _FakeResponse(),
    )
    assert out["ok"] is True


def test_admin_create_invite(wired, store):
    out = ar.admin_create_invite(
        M.InviteCreate(display_name="Marisol"),
        _FakeRequest(),
        {"id": "admin-1", "is_admin": True},
    )
    assert out["ok"] is True
    assert len(out["code"]) == 8
    assert out["invite_url"] == f"https://zenaf-staging.fly.dev/?invite={out['code']}"
    # Default TTL is 7 days.
    assert out["expires_at"] - time.time() == pytest.approx(7 * 86400, abs=60)
    row = store.peek(out["code"])
    assert row is not None and row["display_name"] == "Marisol"


def test_admin_create_invite_ttl_override_capped(wired, store):
    out = ar.admin_create_invite(
        M.InviteCreate(ttl_hours=720),
        _FakeRequest(),
        {"id": "admin-1", "is_admin": True},
    )
    assert out["expires_at"] - time.time() == pytest.approx(30 * 86400, abs=60)
    # The model itself rejects anything beyond 30 days.
    import pydantic

    with pytest.raises(pydantic.ValidationError):
        M.InviteCreate(ttl_hours=24 * 90)


def test_admin_create_invite_custom_ttl(wired, store):
    out = ar.admin_create_invite(
        M.InviteCreate(ttl_hours=48),
        _FakeRequest(),
        {"id": "admin-1", "is_admin": True},
    )
    assert out["expires_at"] - time.time() == pytest.approx(48 * 3600, abs=60)


# ------------------------------------------------------------ admin guard


def test_admin_guard_rejects_anonymous(wired):
    with pytest.raises(HTTPException) as ei:
        ar.get_current_admin_user(_FakeRequest(cookies={}))
    assert ei.value.status_code == 401


def test_admin_guard_rejects_non_admin(wired):
    req = _FakeRequest(cookies={ar.SESSION_COOKIE_NAME: "member-token"})
    with pytest.raises(HTTPException) as ei:
        ar.get_current_admin_user(req)
    assert ei.value.status_code == 403


def test_admin_guard_accepts_admin(wired):
    req = _FakeRequest(cookies={ar.SESSION_COOKIE_NAME: "admin-token"})
    user = ar.get_current_admin_user(req)
    assert user["is_admin"] is True


# ---------------------------------------------------------------- throttle


def test_ip_limit_trips(monkeypatch):
    monkeypatch.setattr(ar, "_invite_ip_hits", {})
    for _ in range(ar._INVITE_IP_MAX):
        ar._check_invite_ip_limit("5.5.5.5")
    with pytest.raises(HTTPException) as ei:
        ar._check_invite_ip_limit("5.5.5.5")
    assert ei.value.status_code == 429


def test_ip_limit_is_per_ip(monkeypatch):
    monkeypatch.setattr(ar, "_invite_ip_hits", {})
    for _ in range(ar._INVITE_IP_MAX):
        ar._check_invite_ip_limit("5.5.5.5")
    ar._check_invite_ip_limit("6.6.6.6")  # different IP unaffected
