"""
Two-plane execution identity: system scope vs account scope.

Resolution order for HTTP runs:
1. Declare execution_scope (explicit; default is account — never implicit system).
2. Validate system scope credentials when scope is system.
3. Resolve account principal (session user or explicit anonymous account lane).

Provider/credential resolution consumes ExecutionPrincipal after this module runs.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Literal

from starlette.requests import Request

ExecutionScope = Literal["account", "system"]

# Stable principal_ref for traces and policy attachment (no PII in system ref).
SYSTEM_PRINCIPAL_REF = "system"
ANONYMOUS_ACCOUNT_PRINCIPAL_REF = "account:anonymous"


@dataclass(frozen=True)
class ExecutionPrincipal:
    """
    Unified execution identity for the provider substrate.

    - scope: which plane (platform vs tenant/user).
    - principal_ref: stable string for logs and RunResponse (never empty).
    - account_user_id: set only for authenticated account scope; None for system or anonymous account.
    - credential_namespace / policy_namespace: distinct keys for vault + policy extension (same vendor keys allowed today).
    """

    scope: ExecutionScope
    principal_ref: str
    account_user_id: str | None
    credential_namespace: str
    policy_namespace: str

    @property
    def gate_user_id(self) -> str | None:
        """User id for per-user provider enable/disable prefs; None for system and anonymous account."""
        if self.scope == "system":
            return None
        return self.account_user_id


def anonymous_account_principal() -> ExecutionPrincipal:
    """Explicit unauthenticated account lane (not a silent fallback from system)."""
    return ExecutionPrincipal(
        scope="account",
        principal_ref=ANONYMOUS_ACCOUNT_PRINCIPAL_REF,
        account_user_id=None,
        credential_namespace="account:anonymous",
        policy_namespace="account:anonymous",
    )


def authenticated_account_principal(user_id: str) -> ExecutionPrincipal:
    uid = (user_id or "").strip()
    if not uid:
        return anonymous_account_principal()
    return ExecutionPrincipal(
        scope="account",
        principal_ref=f"account:{uid}",
        account_user_id=uid,
        credential_namespace=f"account:{uid}",
        policy_namespace=f"account:{uid}",
    )


def system_principal() -> ExecutionPrincipal:
    return ExecutionPrincipal(
        scope="system",
        principal_ref=SYSTEM_PRINCIPAL_REF,
        account_user_id=None,
        credential_namespace="system",
        policy_namespace="system",
    )


def execution_principal_from_legacy_user_id(user_id: str | None) -> ExecutionPrincipal:
    """Backward-compatible bridge: optional session user id → account principal."""
    if user_id and str(user_id).strip():
        return authenticated_account_principal(str(user_id).strip())
    return anonymous_account_principal()


def _system_execution_key_from_request(request: Request) -> str:
    h = request.headers.get("X-Zenaf-System-Execution-Key") or request.headers.get("X-Zenaf-System-Key")
    if h and h.strip():
        return h.strip()
    auth = request.headers.get("Authorization") or ""
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return ""


def resolve_execution_principal_for_run_http(
    *,
    request: Request,
    execution_scope_raw: str | None,
) -> tuple[ExecutionPrincipal | None, str | None]:
    """
    Resolve principal for POST /run and POST /run/stream.

    Returns (principal, error_detail). error_detail set => caller should return 4xx response.
    """
    raw = (execution_scope_raw or "").strip().lower()
    if raw in ("", "account"):
        # Explicit default plane: account (session optional). Cookie name matches api.routes.auth_routes.
        from local_ai.vision_execution import service as S

        # Same-origin browser clients use HttpOnly cookie. Scripted/API clients (curl, urllib) can pass
        # the raw session token via X-Zenaf-Session when cookies are not practical.
        token = request.cookies.get("zenaf_session") or (request.headers.get("X-Zenaf-Session") or "").strip()
        if not token:
            return anonymous_account_principal(), None
        user = S.get_session_user(token)
        if not user:
            return anonymous_account_principal(), None
        uid = user.get("id")
        if not uid:
            return anonymous_account_principal(), None
        return authenticated_account_principal(str(uid).strip()), None

    if raw == "system":
        expected = (os.environ.get("ZENAF_SYSTEM_EXECUTION_KEY") or "").strip()
        if not expected:
            return None, (
                "System execution scope was requested but the API is not configured for it "
                "(set ZENAF_SYSTEM_EXECUTION_KEY on the server)."
            )
        got = _system_execution_key_from_request(request)
        if not got or got != expected:
            return None, "Invalid or missing system execution credentials (X-Zenaf-System-Execution-Key)."
        return system_principal(), None

    return None, f"Invalid execution_scope {execution_scope_raw!r}; use 'account' or 'system'."


def principal_for_vision_execution_user(user_id: str) -> ExecutionPrincipal:
    """Vision Execution routes are always account-scoped to the authenticated user."""
    return authenticated_account_principal(user_id)
