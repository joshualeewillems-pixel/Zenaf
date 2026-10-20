from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response

from local_ai.vision_execution import keystone_seeding
from local_ai.vision_execution import models as M
from local_ai.vision_execution import service as S

SESSION_COOKIE_NAME = "zenaf_session"

router = APIRouter(prefix="/auth", tags=["auth"])


def _session_cookie_settings() -> dict:
    # Production (ZENAF_PROD=1): Secure=True — the platform terminates TLS.
    # Local dev default: Secure=False (plain http://127.0.0.1).
    from local_ai.hosted_config import session_cookie_secure

    return {
        "httponly": True,
        "samesite": "lax",
        "secure": session_cookie_secure(),
        "path": "/",
    }


def get_current_user(request: Request) -> dict:
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    user = S.get_session_user(token)
    if not user:
        raise HTTPException(status_code=401, detail="Session invalid or expired")
    return user


def get_current_admin_user(request: Request) -> dict:
    user = get_current_user(request)
    if not user.get("is_admin"):
        raise HTTPException(status_code=403, detail="Admin access required")
    return user


@router.post("/login")
def login(body: M.LoginRequest, response: Response):
    user = S.authenticate_user(body.email, body.password)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid email or password")
    session_token = S.create_session(user["id"])
    response.set_cookie(SESSION_COOKIE_NAME, session_token, **_session_cookie_settings())
    return {
        "ok": True,
        "user": {
            "id": user["id"],
            "email": user["email"],
            "display_name": user["display_name"],
            "is_admin": bool(user.get("is_admin")),
            "avatar_data_url": user.get("avatar_data_url"),
        },
    }


@router.post("/logout")
def logout(request: Request, response: Response):
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if token:
        S.revoke_session(token)
    response.delete_cookie(SESSION_COOKIE_NAME, path="/")
    return {"ok": True}


@router.get("/me")
def me(current_user: dict = Depends(get_current_user)):
    return {
        "id": current_user["id"],
        "email": current_user["email"],
        "display_name": current_user["display_name"],
        "is_admin": bool(current_user.get("is_admin")),
        "avatar_data_url": current_user.get("avatar_data_url"),
    }


@router.patch("/me")
def patch_me(body: M.UserSelfUpdate, current_user: dict = Depends(get_current_user)):
    data = body.model_dump(exclude_unset=True)
    if not data:
        raise HTTPException(status_code=400, detail="No fields to update")
    try:
        row = S.patch_user_profile(current_user["id"], data)
    except ValueError as e:
        code = str(e)
        if code == "invalid_avatar":
            raise HTTPException(
                status_code=400,
                detail="Avatar must be a data URL for a small jpeg, png, webp, or gif image.",
            ) from e
        if code == "avatar_too_large":
            raise HTTPException(status_code=400, detail="Avatar image is too large.") from e
        if code == "display_name_invalid":
            raise HTTPException(status_code=400, detail="Display name cannot be empty.") from e
        raise HTTPException(status_code=400, detail="Invalid update.") from e
    if row is None:
        raise HTTPException(status_code=404, detail="User not found")
    return {
        "id": row["id"],
        "email": row["email"],
        "display_name": row["display_name"],
        "is_admin": bool(row.get("is_admin")),
        "avatar_data_url": row.get("avatar_data_url"),
    }


@router.post("/admin/users")
def admin_create_user(body: M.AdminUserCreate, _admin: dict = Depends(get_current_admin_user)):
    try:
        user = S.create_user_account(
            body.email,
            body.password,
            body.display_name,
            is_admin=body.is_admin,
        )
    except ValueError as e:
        code = str(e)
        if code == "user_exists":
            raise HTTPException(status_code=409, detail="User with this email already exists") from e
        if code == "invalid_email":
            raise HTTPException(status_code=400, detail="Invalid email") from e
        raise HTTPException(status_code=400, detail=code) from e
    return {"ok": True, "user": user}


# ---------------------------------------------------------------- invites
# Minimal invite system: an admin mints a single-use code/link; the invitee
# opens ?invite=CODE, picks email + password, and lands logged in. Store
# follows the DemoClaimStore convention (per-domain SQLite under data/,
# one connection guarded by a lock, CREATE TABLE IF NOT EXISTS on init).

import secrets
import sqlite3
import threading
import time
from pathlib import Path

#: Invite-code alphabet: no 0/O, 1/I/l (same as demo claim codes).
_INVITE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
_INVITE_CODE_LEN = 8
#: Invite TTL: 7 days by default, 30 days max.
_INVITE_DEFAULT_TTL_S = 7 * 86400
_INVITE_MAX_TTL_S = 30 * 86400

_INVITE_DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "auth"
_INVITE_DB = _INVITE_DATA_DIR / "invites.db"

_INVITE_SCHEMA = """
CREATE TABLE IF NOT EXISTS invites (
  code TEXT PRIMARY KEY,
  display_name TEXT NOT NULL DEFAULT '',
  created_at REAL NOT NULL,
  expires_at REAL NOT NULL,
  used_at REAL,
  used_by_email TEXT
);
"""

#: Sliding-window IP throttle for invite validation + signup endpoints.
_INVITE_IP_WINDOW_S = 3600
_INVITE_IP_MAX = 20
_invite_ip_hits: dict[str, list[float]] = {}


def _invite_client_ip(request: Request) -> str:
    fwd = (request.headers.get("x-forwarded-for") or "").split(",")[0].strip()
    if fwd:
        return fwd
    return request.client.host if request.client else "unknown"


def _check_invite_ip_limit(ip: str) -> None:
    now = time.time()
    hits = [t for t in _invite_ip_hits.get(ip, []) if now - t < _INVITE_IP_WINDOW_S]
    if len(hits) >= _INVITE_IP_MAX:
        raise HTTPException(
            status_code=429,
            detail="Too many attempts. Come back in a bit.",
        )
    hits.append(now)
    _invite_ip_hits[ip] = hits


class InviteStore:
    """SQLite-backed store for single-use invite codes.

    Follows the per-domain sqlite convention (demo claims, conversations,
    followthrough): one connection guarded by a lock, schema on init.
    Single-use and TTL are enforced against the table; used rows are kept
    (used_at / used_by_email) so a spent code is auditable, and a signup
    that fails on a fixable form error can release its code back.
    """

    def __init__(self, db_path: str | Path | None = None) -> None:
        self.db_path = Path(db_path) if db_path else _INVITE_DB
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.executescript(_INVITE_SCHEMA)
            self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def exists(self, code: str) -> bool:
        with self._lock:
            row = self._conn.execute(
                "SELECT 1 FROM invites WHERE code = ?", (code,)
            ).fetchone()
            return row is not None

    def issue(
        self, code: str, display_name: str, created_at: float, expires_at: float
    ) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO invites (code, display_name, created_at, expires_at)"
                " VALUES (?, ?, ?, ?)",
                (code, display_name, created_at, expires_at),
            )
            self._conn.commit()

    def _valid_row(self, code: str, now: float):
        row = self._conn.execute(
            "SELECT * FROM invites WHERE code = ?", (code,)
        ).fetchone()
        if row is None or row["used_at"] is not None or now > row["expires_at"]:
            return None
        return row

    def peek(self, code: str, now: float | None = None):
        """Return the invite row if the code is valid, without consuming it."""
        ts = time.time() if now is None else now
        with self._lock:
            return self._valid_row(code, ts)

    def consume(self, code: str, email: str, now: float | None = None):
        """Atomically validate + mark used. Returns the row, or None."""
        ts = time.time() if now is None else now
        with self._lock:
            row = self._valid_row(code, ts)
            if row is None:
                return None
            self._conn.execute(
                "UPDATE invites SET used_at = ?, used_by_email = ? WHERE code = ?",
                (ts, email, code),
            )
            self._conn.commit()
            return row

    def release(self, code: str) -> None:
        """Undo a consume (signup failed on a fixable error — don't burn it)."""
        with self._lock:
            self._conn.execute(
                "UPDATE invites SET used_at = NULL, used_by_email = NULL"
                " WHERE code = ?",
                (code,),
            )
            self._conn.commit()


_invite_store: InviteStore | None = None
_invite_store_lock = threading.Lock()


def _get_invite_store() -> InviteStore:
    global _invite_store
    if _invite_store is None:
        with _invite_store_lock:
            if _invite_store is None:
                _invite_store = InviteStore()
    return _invite_store


def _new_invite_code(store: InviteStore) -> str:
    for _ in range(16):
        code = "".join(
            secrets.choice(_INVITE_ALPHABET) for _ in range(_INVITE_CODE_LEN)
        )
        if not store.exists(code):
            return code
    raise HTTPException(status_code=500, detail="Could not generate an invite code")


@router.post("/admin/invites")
def admin_create_invite(
    body: M.InviteCreate,
    request: Request,
    _admin: dict = Depends(get_current_admin_user),
):
    store = _get_invite_store()
    code = _new_invite_code(store)
    ttl_s = _INVITE_DEFAULT_TTL_S
    if body.ttl_hours is not None:
        ttl_s = min(max(body.ttl_hours * 3600.0, 3600.0), _INVITE_MAX_TTL_S)
    now = time.time()
    store.issue(code, (body.display_name or "").strip(), now, now + ttl_s)
    return {
        "ok": True,
        "code": code,
        "invite_url": f"{request.base_url}?invite={code}",
        "expires_at": now + ttl_s,
    }


@router.get("/invite/{code}")
def check_invite(code: str, request: Request):
    """Public: validate an invite code without consuming it."""
    _check_invite_ip_limit(_invite_client_ip(request))
    row = _get_invite_store().peek(code.strip().upper())
    if row is None:
        return {"valid": False, "display_name": None}
    return {"valid": True, "display_name": row["display_name"] or None}


@router.post("/signup")
def signup(body: M.SignupRequest, request: Request, response: Response):
    """Public: create an account from a valid invite code; lands logged in."""
    _check_invite_ip_limit(_invite_client_ip(request))
    code = (body.invite_code or "").strip().upper()
    store = _get_invite_store()
    row = store.consume(code, (body.email or "").strip().lower())
    if row is None:
        raise HTTPException(
            status_code=400,
            detail="That invite link is invalid, expired, or already used.",
        )
    try:
        user = S.create_user_account(
            body.email, body.password, body.display_name or row["display_name"]
        )
    except ValueError as e:
        # Don't burn the invite on a fixable form error (taken email, typos).
        store.release(code)
        err = str(e)
        if err == "user_exists":
            raise HTTPException(
                status_code=409, detail="An account with this email already exists"
            ) from e
        if err == "invalid_email":
            raise HTTPException(status_code=400, detail="Invalid email") from e
        raise HTTPException(status_code=400, detail="Could not create the account") from e
    # Every new account starts with the "Meet your council" keystone
    # initiative. Best-effort: the account exists and the invite is spent, so
    # a seeding failure must not fail the signup — the admin backfill
    # endpoint (POST /auth/admin/seed-keystones) is the repair path.
    try:
        keystone_seeding.seed_meet_your_council(user["id"])
    except Exception:  # noqa: BLE001 — never break signup over seeding
        pass
    session_token = S.create_session(user["id"])
    response.set_cookie(SESSION_COOKIE_NAME, session_token, **_session_cookie_settings())
    return {
        "ok": True,
        "user": {
            "id": user["id"],
            "email": user["email"],
            "display_name": user["display_name"],
            "is_admin": bool(user.get("is_admin")),
            "avatar_data_url": user.get("avatar_data_url"),
        },
    }


@router.post("/admin/seed-keystones")
def admin_seed_keystones(
    body: M.SeedKeystonesRequest, _admin: dict = Depends(get_current_admin_user)
):
    """Admin-only: backfill the "Meet your council" keystone initiative.

    With an email: seed that one user. Without: seed every user missing it.
    Idempotent — users who already have it are skipped.
    """
    email = (body.email or "").strip().lower()
    if email:
        user = S.get_user_by_email(email)
        if user is None:
            raise HTTPException(status_code=404, detail="No account with that email")
        targets = [user]
    else:
        targets = S.list_users()
    seeded: list[dict] = []
    for target in targets:
        result = keystone_seeding.seed_meet_your_council(target["id"])
        seeded.append(
            {
                "email": target.get("email"),
                "created": result["created"],
                "initiative_id": result["initiative"]["id"],
            }
        )
    return {"ok": True, "seeded": seeded}
