"""
"Sign in with OpenRouter" — one-click OAuth (PKCE) onboarding.

Flow:
1. POST /settings/llm/openrouter/oauth/initiate {"callback_url": "<this app's URL>"}
   → {auth_url, code_verifier, code_challenge}. The frontend keeps the verifier in
   sessionStorage and redirects the browser to ``auth_url``.
2. The user signs in on openrouter.ai; OpenRouter redirects back to ``callback_url?code=...``.
3. POST /settings/llm/openrouter/oauth/exchange {"code": ..., "code_verifier": ...}
   → the backend exchanges the code at https://openrouter.ai/api/v1/auth/keys and stores
   the minted user-owned key encrypted via the same path as manual key saves
   (``St.upsert_llm_provider_credential``) — no new storage mechanism.

NOT live-tested: no OpenRouter credentials and no browser in this environment.
"""

from __future__ import annotations

import base64
import hashlib
import secrets
from urllib.parse import urlparse

import requests
from fastapi import APIRouter, Depends, HTTPException

from api.routes.auth_routes import get_current_user
from local_ai.vision_execution import models as M
from local_ai.vision_execution import storage as St

router = APIRouter(tags=["settings"])

OPENROUTER_AUTH_URL = "https://openrouter.ai/auth"
OPENROUTER_KEYS_URL = "https://openrouter.ai/api/v1/auth/keys"


def _b64url_nopad(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _new_code_verifier() -> str:
    # 32 random bytes → 43-char base64url string (RFC 7636 compliant).
    return _b64url_nopad(secrets.token_bytes(32))


def _code_challenge_s256(verifier: str) -> str:
    return _b64url_nopad(hashlib.sha256(verifier.encode("ascii")).digest())


def _validate_callback_url(raw: str) -> str:
    cb = (raw or "").strip()
    try:
        p = urlparse(cb)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid callback_url.")
    if p.scheme not in ("http", "https") or not p.netloc:
        raise HTTPException(status_code=400, detail="callback_url must be an http(s) URL.")
    if p.username or p.password:
        raise HTTPException(status_code=400, detail="callback_url must not embed credentials.")
    return cb


def _require_encryption() -> None:
    if not St.settings_encryption_available():
        raise HTTPException(
            status_code=503,
            detail="Cannot encrypt API keys: install cryptography, or fix ZENAF_SETTINGS_ENCRYPTION_KEY / ~/.zenaf/settings_encryption.key.",
        )


@router.post("/llm/openrouter/oauth/initiate")
def initiate_openrouter_oauth(
    body: M.OpenRouterOAuthInitiateBody,
    current_user: dict = Depends(get_current_user),
):
    """Mint a PKCE pair and return the OpenRouter sign-in URL (fail early if keys can't be stored)."""
    _require_encryption()
    callback_url = _validate_callback_url(body.callback_url)
    verifier = _new_code_verifier()
    challenge = _code_challenge_s256(verifier)
    from urllib.parse import urlencode

    auth_url = (
        f"{OPENROUTER_AUTH_URL}?"
        + urlencode(
            {
                "callback_url": callback_url,
                "code_challenge": challenge,
                "code_challenge_method": "S256",
            }
        )
    )
    # The verifier goes back to the caller (kept in browser sessionStorage) and is
    # presented again at exchange time — no server-side pending state needed.
    return {"auth_url": auth_url, "code_verifier": verifier, "code_challenge": challenge}


@router.post("/llm/openrouter/oauth/exchange")
def exchange_openrouter_oauth(
    body: M.OpenRouterOAuthExchangeBody,
    current_user: dict = Depends(get_current_user),
):
    """Exchange the authorization code for the user's OpenRouter key and store it encrypted."""
    _require_encryption()
    code = (body.code or "").strip()
    verifier = (body.code_verifier or "").strip()
    if not code or not verifier:
        raise HTTPException(status_code=400, detail="code and code_verifier are required.")
    try:
        r = requests.post(
            OPENROUTER_KEYS_URL,
            json={"code": code, "code_verifier": verifier, "code_challenge_method": "S256"},
            timeout=25,
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"OpenRouter key exchange failed: {e}")
    if not r.ok:
        detail = (r.text or "")[:300] or f"HTTP {r.status_code}"
        raise HTTPException(status_code=502, detail=f"OpenRouter rejected the exchange (HTTP {r.status_code}): {detail}")
    try:
        data = r.json()
    except Exception:
        raise HTTPException(status_code=502, detail="OpenRouter returned a non-JSON key response.")
    key = str((data or {}).get("key") or "").strip()
    if not key.startswith("sk-or-"):
        raise HTTPException(status_code=502, detail="OpenRouter did not return a usable API key.")
    try:
        St.upsert_llm_provider_credential(current_user["id"], "openrouter", key)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"ok": True}
