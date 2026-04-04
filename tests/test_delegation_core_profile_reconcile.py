"""Compiled delegation: core_profile_reconcile strict JSON path."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from local_ai.delegation.core_profile_reconcile import (
    build_core_profile_reconcile_contract,
    validate_core_profile_reconcile_json,
)
from local_ai.delegation.types import CORE_PROFILE_RECONCILE_INTENT, STRUCTURED_CLOUD_DELEGATION_V1
from local_ai.vision_execution.core_profile_execution import INTENT_RECONCILE
from local_ai.vision_execution.core_profile_reconcile import STRUCTURED_KEYS, reconcile


def _valid_proposed():
    return {k: f"v_{k}"[:20] for k in STRUCTURED_KEYS}


def test_intent_constant_matches_substrate():
    assert CORE_PROFILE_RECONCILE_INTENT == INTENT_RECONCILE


def test_validate_exact_keys_strings_only():
    raw = _valid_proposed()
    norm, err = validate_core_profile_reconcile_json(raw)
    assert err is None
    assert norm is not None
    assert len(norm) == 11


def test_validate_rejects_extra_key():
    raw = {**_valid_proposed(), "x": "y"}
    norm, err = validate_core_profile_reconcile_json(raw)
    assert norm is None


def test_validate_rejects_null():
    raw = _valid_proposed()
    raw["name"] = None  # type: ignore[assignment]
    norm, err = validate_core_profile_reconcile_json(raw)
    assert norm is None


def test_validate_rejects_number():
    raw = _valid_proposed()
    raw["name"] = 3  # type: ignore[assignment]
    norm, err = validate_core_profile_reconcile_json(raw)
    assert norm is None


def test_reconcile_structured_openai_single_generate(monkeypatch):
    calls: list[int] = []

    class _P:
        def generate(self, prompt: str, *, timeout: int | None = 90) -> str:
            calls.append(1)
            assert "OUTPUT CONTRACT" in prompt
            assert CORE_PROFILE_RECONCILE_INTENT in prompt
            return json.dumps(_valid_proposed())

    monkeypatch.setattr(
        "local_ai.vision_execution.llm_seam.ve_eval_provider_shim",
        lambda user_id, *, use_execution_seam=False: _P(),
    )

    cur = {k: "" for k in STRUCTURED_KEYS}
    out = reconcile(
        "notes",
        [],
        cur,
        routing_context={
            "surface": "core_profile",
            "action_kind": "structured_evaluation",
            "action_intent": INTENT_RECONCILE,
        },
        use_execution_seam=True,
        exec_meta={"provider_used": "openai", "model_used": "gpt-x"},
        profile_id="p1",
        user_id="u1",
    )
    assert "error" not in out
    assert out.get("delegation_path") == STRUCTURED_CLOUD_DELEGATION_V1
    assert out["proposed"]["name"] == "v_name"
    assert calls == [1]


def test_reconcile_structured_rejects_non_json(monkeypatch):
    class _P:
        def generate(self, prompt: str, *, timeout: int | None = 90) -> str:
            return "not json"

    monkeypatch.setattr(
        "local_ai.vision_execution.llm_seam.ve_eval_provider_shim",
        lambda user_id, *, use_execution_seam=False: _P(),
    )

    cur = {k: "keep" for k in STRUCTURED_KEYS}
    out = reconcile(
        "n",
        [],
        cur,
        routing_context={"action_intent": INTENT_RECONCILE},
        use_execution_seam=True,
        exec_meta={"provider_used": "openai"},
    )
    assert out.get("error")
    assert "Structured delegation" in out["error"]
    assert out.get("delegation_path") == STRUCTURED_CLOUD_DELEGATION_V1


def test_reconcile_legacy_no_routing_untouched(monkeypatch):
    """No routing_context at route level => use_execution_seam False => permissive legacy parse."""
    calls: list[str] = []

    class _P:
        def generate(self, prompt: str, *, timeout: int | None = 90) -> str:
            calls.append("legacy")
            # Legacy allows coerced types in Python path — return minimal JSON
            d = {k: ("x" if k == "name" else "") for k in STRUCTURED_KEYS}
            return json.dumps(d)

    monkeypatch.setattr(
        "local_ai.llm.resolver.get_provider_shim_for_legacy_generate",
        lambda principal: _P(),
    )

    cur = {k: "prior" for k in STRUCTURED_KEYS}
    out = reconcile(
        "notes",
        [],
        cur,
        routing_context=None,
        use_execution_seam=False,
    )
    assert "error" not in out
    assert out.get("delegation_path") is None
    assert out["proposed"]["name"] == "x"
    assert calls == ["legacy"]
