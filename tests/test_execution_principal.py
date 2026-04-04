"""Execution scope + principal resolution (two-plane substrate)."""
from __future__ import annotations

import sys
from pathlib import Path

from starlette.requests import Request

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from local_ai.llm.execution_principal import (
    anonymous_account_principal,
    authenticated_account_principal,
    resolve_execution_principal_for_run_http,
    system_principal,
)


def test_anonymous_vs_authenticated_namespaces():
    a = anonymous_account_principal()
    assert a.scope == "account"
    assert a.principal_ref == "account:anonymous"
    assert a.credential_namespace == "account:anonymous"
    assert a.policy_namespace == "account:anonymous"

    b = authenticated_account_principal("u-42")
    assert b.account_user_id == "u-42"
    assert b.credential_namespace == "account:u-42"
    assert b.policy_namespace == "account:u-42"

    s = system_principal()
    assert s.scope == "system"
    assert s.credential_namespace == "system"


def test_resolve_account_no_cookie():
    asgi_scope: dict = {"type": "http", "headers": [], "method": "POST", "path": "/run"}

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    req = Request(asgi_scope, receive)
    p, err = resolve_execution_principal_for_run_http(request=req, execution_scope_raw=None)
    assert err is None
    assert p.principal_ref == "account:anonymous"


def test_resolve_account_x_atria_session_header(monkeypatch):
    """Scripted clients can pass session token when cookies are not sent."""
    from local_ai.vision_execution import service as S

    monkeypatch.setattr(
        S,
        "get_session_user",
        lambda token: {"id": "user-99"} if token == "tok-ok" else None,
    )

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    req = Request(
        {
            "type": "http",
            "headers": [(b"x-atria-session", b"tok-ok")],
            "method": "POST",
            "path": "/run",
        },
        receive,
    )
    p, err = resolve_execution_principal_for_run_http(request=req, execution_scope_raw=None)
    assert err is None
    assert p.principal_ref == "account:user-99"


def test_resolve_system_requires_config_and_header(monkeypatch):
    monkeypatch.delenv("ATRIA_SYSTEM_EXECUTION_KEY", raising=False)

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    req = Request({"type": "http", "headers": [], "method": "POST", "path": "/run"}, receive)
    p, err = resolve_execution_principal_for_run_http(request=req, execution_scope_raw="system")
    assert p is None
    assert "not configured" in (err or "").lower()

    monkeypatch.setenv("ATRIA_SYSTEM_EXECUTION_KEY", "secret-sys")
    req2 = Request(
        {
            "type": "http",
            "headers": [(b"x-atria-system-execution-key", b"wrong")],
            "method": "POST",
            "path": "/run",
        },
        receive,
    )
    p2, err2 = resolve_execution_principal_for_run_http(request=req2, execution_scope_raw="system")
    assert p2 is None
    assert err2 and "Invalid" in err2

    req3 = Request(
        {
            "type": "http",
            "headers": [(b"x-atria-system-execution-key", b"secret-sys")],
            "method": "POST",
            "path": "/run",
        },
        receive,
    )
    p3, err3 = resolve_execution_principal_for_run_http(request=req3, execution_scope_raw="system")
    assert err3 is None
    assert p3 is not None
    assert p3.scope == "system"
