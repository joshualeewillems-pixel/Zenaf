"""
Single server-side resolution for OpenAI API keys used by the execution seam (apply_seam_routing).

**Authenticated account** (``user_id`` set): resolution order is
``OPENAI_API_KEY`` (server env) then encrypted key in Settings.

**Anonymous account** (``account_user_id`` absent): no key is returned — the anonymous lane
does **not** read ``OPENAI_API_KEY`` (Option B).

**System** scope uses only ``ATRIA_SYSTEM_OPENAI_KEY`` via ``resolve_openai_api_key_for_principal``.
"""

from __future__ import annotations

import os
from typing import Literal, Tuple

OpenAiKeySource = Literal["env", "settings", "none", "system_env", "anonymous_blocked"]


def openai_env_key_present() -> bool:
    return bool((os.environ.get("OPENAI_API_KEY") or "").strip())


def openai_settings_key_present(user_id: str) -> bool:
    """True if a credential row exists for OpenAI (mask only; does not decrypt)."""
    from local_ai.vision_execution import storage as St

    creds = St.list_llm_credentials_mask(user_id)
    return bool(creds.get("openai"))


def resolve_openai_api_key(user_id: str | None) -> Tuple[str | None, OpenAiKeySource]:
    """
    Return (api_key_or_none, source) for **authenticated** account user ids only.

    When ``user_id`` is None, does **not** read ``OPENAI_API_KEY`` (Option B: anonymous lane
    must not inherit deployment keys). Callers for anonymous identity must use
    ``resolve_openai_api_key_for_principal``.
    """
    if not user_id:
        return None, "anonymous_blocked"
    env = (os.environ.get("OPENAI_API_KEY") or "").strip()
    if env:
        return env, "env"
    from local_ai.vision_execution import storage as St

    stored = St.get_decrypted_llm_api_key(user_id, "openai")
    if stored and stored.strip():
        return stored.strip(), "settings"
    return None, "none"


def resolve_openai_api_key_for_principal(principal) -> Tuple[str | None, OpenAiKeySource]:
    """
    Namespace-aware OpenAI key resolution for the execution seam.

    - **system** scope: ``ATRIA_SYSTEM_OPENAI_KEY`` only (no ``OPENAI_API_KEY``, no user Settings).
    - **account (authenticated)**: ``OPENAI_API_KEY`` then saved Settings key for that user.
    - **account (anonymous)**: **no key** — does **not** use ``OPENAI_API_KEY`` (Option B).
    """
    from local_ai.llm.execution_principal import ExecutionPrincipal

    if not isinstance(principal, ExecutionPrincipal):
        return None, "anonymous_blocked"

    if principal.scope == "system":
        sys_k = (os.environ.get("ATRIA_SYSTEM_OPENAI_KEY") or "").strip()
        if sys_k:
            return sys_k, "system_env"
        return None, "none"

    if principal.scope == "account" and not principal.account_user_id:
        return None, "anonymous_blocked"

    return resolve_openai_api_key(principal.account_user_id)


def describe_missing_openai_key_for_anonymous() -> str:
    """Explicit copy for unauthenticated account lane (Option B — no OPENAI_API_KEY inheritance)."""
    return (
        "No OpenAI API key is available for anonymous requests. "
        "The anonymous account lane does not use the server's OPENAI_API_KEY. "
        "Sign in and save an OpenAI key in Settings, use local Ollama, or use a system-scoped "
        "request with ATRIA_SYSTEM_OPENAI_KEY when appropriate."
    )


def describe_missing_openai_key(user_id: str | None) -> str:
    """User-facing detail when no key is available for routed OpenAI."""
    if user_id:
        return (
            "No OpenAI API key available for this request. "
            "Set OPENAI_API_KEY on the API server, or save an OpenAI key in Settings (sign in required). "
            "The server uses the environment variable first, then your saved Settings key."
        )
    return describe_missing_openai_key_for_anonymous()


def describe_missing_openai_key_for_principal(principal) -> str:
    from local_ai.llm.execution_principal import ExecutionPrincipal

    if isinstance(principal, ExecutionPrincipal) and principal.scope == "system":
        return (
            "No OpenAI API key available for system execution. "
            "Set ATRIA_SYSTEM_OPENAI_KEY on the API server (system credential namespace)."
        )
    if isinstance(principal, ExecutionPrincipal):
        if principal.scope == "account" and not principal.account_user_id:
            return describe_missing_openai_key_for_anonymous()
        return describe_missing_openai_key(principal.account_user_id)
    return describe_missing_openai_key(None)


def classify_openai_http_error(status_code: int, response_text: str) -> str:
    """Map common OpenAI HTTP failures to clear messages (no raw key exposure)."""
    low = (response_text or "").lower()
    if status_code == 401:
        return (
            "OpenAI returned 401 Unauthorized. The API key may be invalid, revoked, or for the wrong project. "
            "Update OPENAI_API_KEY or the key saved in Settings."
        )
    if status_code == 429:
        if "quota" in low or "billing" in low or "insufficient" in low:
            return (
                "OpenAI quota or billing limit reached (429). Check your OpenAI account billing and usage limits; "
                "this is not a missing-key issue if the request reached the API."
            )
        return "OpenAI rate limit (429). Retry shortly or reduce request frequency."
    if status_code == 402:
        return "OpenAI payment required (402). Check billing on your OpenAI account."
    return f"OpenAI request failed (HTTP {status_code}). See server logs for details."
