"""Startup check: scream if any expected router fails to load (owed follow-up to PR #34).

PR #34 fixed a dangling ``soil_api`` import that silently killed the entire
vision-execution router — the try/except in api/main.py printed one line and
carried on with a crippled app. ``assert_routers_registered`` makes that
failure mode impossible to miss: every expected router prefix must be mounted.
"""
from __future__ import annotations

import re

import pytest
from fastapi import APIRouter, FastAPI


def _synthetic_app(prefixes) -> FastAPI:
    """Build a throwaway app mounting a dummy route under each given prefix."""
    synthetic = FastAPI()

    def _ping():  # pragma: no cover - never called, only routed
        return {"ok": True}

    for prefix in prefixes:
        router = APIRouter(prefix=prefix)
        router.add_api_route("/ping", _ping)
        synthetic.include_router(router)
    return synthetic


def test_real_app_has_all_expected_routers_mounted():
    from api.main import EXPECTED_ROUTER_PREFIXES, app, assert_routers_registered

    # 13 with steward increment D's /steward router (was 12 before D).
    # This count is a tripwire: any router added or removed must
    # update it deliberately, never silently.
    assert len(EXPECTED_ROUTER_PREFIXES) == 13
    # Must not raise: every router the app expects is actually mounted.
    assert_routers_registered(app)
    assert_routers_registered()  # default-arg form checks the module app too


def test_fully_mounted_synthetic_app_passes():
    from api.main import EXPECTED_ROUTER_PREFIXES, assert_routers_registered

    assert_routers_registered(_synthetic_app(EXPECTED_ROUTER_PREFIXES))


def test_missing_router_screams_with_prefix_named():
    """Simulates the PR #34 failure mode: a router that never got included."""
    from api.main import EXPECTED_ROUTER_PREFIXES, assert_routers_registered

    omitted = EXPECTED_ROUTER_PREFIXES[0]  # e.g. /vision-execution
    partial = _synthetic_app([p for p in EXPECTED_ROUTER_PREFIXES if p != omitted])
    with pytest.raises(RuntimeError, match=re.escape(omitted)):
        assert_routers_registered(partial)


def test_missing_router_message_includes_load_errors(monkeypatch):
    """The scream should say WHY, not just WHAT, when a cause was recorded."""
    import api.main as main_module

    monkeypatch.setattr(
        main_module, "_router_load_errors", ["vision_execution: No module named 'soil_api'"]
    )
    partial = _synthetic_app(
        [p for p in main_module.EXPECTED_ROUTER_PREFIXES if p != "/vision-execution"]
    )
    with pytest.raises(RuntimeError) as exc_info:
        main_module.assert_routers_registered(partial)
    assert "soil_api" in str(exc_info.value)


def test_empty_app_names_every_expected_prefix():
    from api.main import EXPECTED_ROUTER_PREFIXES, assert_routers_registered

    with pytest.raises(RuntimeError) as exc_info:
        assert_routers_registered(FastAPI())
    message = str(exc_info.value)
    for prefix in EXPECTED_ROUTER_PREFIXES:
        assert prefix in message
