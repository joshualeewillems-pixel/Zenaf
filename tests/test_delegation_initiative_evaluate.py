"""Compiled delegation v1: initiative_evaluate strict JSON path."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from local_ai.delegation.initiative_evaluate import (
    build_initiative_evaluate_contract,
    synthesize_structured_initiative_prompt,
    validate_initiative_evaluate_json,
)
from local_ai.delegation.types import INITIATIVE_EVALUATE_INTENT, STRUCTURED_CLOUD_DELEGATION_V1
from local_ai.vision_execution.initiative_evaluate import evaluate_initiative


def _valid_payload():
    return {
        "estimated_cost_ai": "Low",
        "estimated_timeframe_ai": "2 weeks",
        "philosophical_alignment_ai": "Fits Q2 focus.",
        "recommendation": "Approve — clear scope.",
        "next_steps": ["Step one", "Step two", "Step three"],
        "evaluation_priority": 3,
        "strategic_value": 4,
        "energy_impact": 2,
    }


def test_validate_accepts_exact_contract():
    norm, err = validate_initiative_evaluate_json(_valid_payload())
    assert err is None
    assert norm is not None
    assert norm["next_steps"] == ["Step one", "Step two", "Step three"]
    assert norm["evaluation_priority"] == 3


def test_validate_rejects_extra_key():
    p = {**_valid_payload(), "foo": 1}
    norm, err = validate_initiative_evaluate_json(p)
    assert norm is None
    assert err is not None


def test_validate_rejects_float_score():
    p = {**_valid_payload(), "strategic_value": 3.0}
    norm, err = validate_initiative_evaluate_json(p)
    assert norm is None


def test_validate_rejects_string_score():
    p = {**_valid_payload(), "energy_impact": "3"}
    norm, err = validate_initiative_evaluate_json(p)
    assert norm is None


def test_validate_rejects_two_next_steps():
    p = {**_valid_payload(), "next_steps": ["a", "b"]}
    norm, err = validate_initiative_evaluate_json(p)
    assert norm is None


def test_validate_rejects_six_next_steps():
    p = {**_valid_payload(), "next_steps": ["a", "b", "c", "d", "e", "f"]}
    norm, err = validate_initiative_evaluate_json(p)
    assert norm is None


def test_synthesize_contains_intent_and_contract():
    c = build_initiative_evaluate_contract(title="T", brief="B", core_profile_summary=None)
    p = synthesize_structured_initiative_prompt(c)
    assert INITIATIVE_EVALUATE_INTENT in p
    assert "OUTPUT CONTRACT" in p
    assert "T" in p and "B" in p


def test_evaluate_initiative_structured_branch_openai(monkeypatch):
    """Routed OpenAI + initiative_evaluate intent uses strict path (single generate)."""
    calls: list[int] = []

    class _P:
        def generate(self, prompt: str, *, timeout: int | None = 60) -> str:
            calls.append(1)
            assert "OUTPUT CONTRACT" in prompt
            return json.dumps(_valid_payload())

    monkeypatch.setattr(
        "local_ai.vision_execution.llm_seam.ve_eval_provider_shim",
        lambda user_id, *, use_execution_seam=False: _P(),
    )

    out = evaluate_initiative(
        "My init",
        "Brief here",
        core_profile_summary=None,
        user_id="u1",
        use_execution_seam=True,
        routing_payload={
            "surface": "vision_execution",
            "action_kind": "structured_evaluation",
            "action_intent": INITIATIVE_EVALUATE_INTENT,
        },
        exec_meta={"provider_used": "openai", "model_used": "gpt-test"},
        initiative_id=None,
    )
    assert "error" not in out
    assert out.get("delegation_path") == STRUCTURED_CLOUD_DELEGATION_V1
    assert out["recommendation"] == "Approve — clear scope."
    assert len(out["next_steps"]) == 3
    assert calls == [1]
    assert out.get("externalization_integrity_ok") is None


def test_evaluate_initiative_structured_malformed_json(monkeypatch):
    class _P:
        def generate(self, prompt: str, *, timeout: int | None = 60) -> str:
            return "not json"

    monkeypatch.setattr(
        "local_ai.vision_execution.llm_seam.ve_eval_provider_shim",
        lambda user_id, *, use_execution_seam=False: _P(),
    )

    out = evaluate_initiative(
        "T",
        "B",
        use_execution_seam=True,
        routing_payload={"action_intent": INITIATIVE_EVALUATE_INTENT},
        exec_meta={"provider_used": "openai"},
    )
    assert out.get("error")
    assert "Structured delegation" in out["error"]
    assert out.get("delegation_path") == STRUCTURED_CLOUD_DELEGATION_V1


def test_evaluate_initiative_structured_externalization_roundtrip(monkeypatch):
    from local_ai.execution_policy.externalization import make_placeholder_token

    iid = "initiative-externalize-7f2a"
    tok = make_placeholder_token("initiative_id", iid)

    class _P:
        def generate(self, prompt: str, *, timeout: int | None = 60) -> str:
            assert iid not in prompt
            assert tok in prompt
            p = _valid_payload()
            p["recommendation"] = f"Follow up on {tok}"
            return json.dumps(p)

    monkeypatch.setattr(
        "local_ai.vision_execution.llm_seam.ve_eval_provider_shim",
        lambda user_id, *, use_execution_seam=False: _P(),
    )

    out = evaluate_initiative(
        "Title",
        f"Brief references initiative {iid} in context.",
        user_id="acct-99",
        use_execution_seam=True,
        routing_payload={"action_intent": INITIATIVE_EVALUATE_INTENT},
        exec_meta={"provider_used": "openai"},
        initiative_id=iid,
    )
    assert "error" not in out
    assert iid in out["recommendation"]
    assert tok not in out["recommendation"]
    assert out.get("externalization_integrity_ok") is True
    assert out.get("delegation_path") == STRUCTURED_CLOUD_DELEGATION_V1


def test_evaluate_initiative_structured_externalization_missing_echo_fails(monkeypatch):
    iid = "initiative-missing-echo-1111"

    class _P:
        def generate(self, prompt: str, *, timeout: int | None = 60) -> str:
            assert iid not in prompt
            return json.dumps(_valid_payload())

    monkeypatch.setattr(
        "local_ai.vision_execution.llm_seam.ve_eval_provider_shim",
        lambda user_id, *, use_execution_seam=False: _P(),
    )

    out = evaluate_initiative(
        "T",
        f"Context {iid} here.",
        use_execution_seam=True,
        routing_payload={"action_intent": INITIATIVE_EVALUATE_INTENT},
        exec_meta={"provider_used": "openai"},
        initiative_id=iid,
    )
    assert out.get("error")
    assert "Externalized response failed integrity" in out["error"]
    assert out.get("delegation_path") == STRUCTURED_CLOUD_DELEGATION_V1
    assert out.get("externalization_integrity_ok") is False


def test_evaluate_initiative_ollama_unchanged_retry_path(monkeypatch):
    """Ollama primary: legacy path with retry still allowed."""
    calls: list[str] = []

    class _P:
        def generate(self, prompt: str, *, timeout: int | None = 60) -> str:
            calls.append(prompt)
            if len(calls) == 1:
                return "bad"
            return json.dumps(_valid_payload())

    monkeypatch.setattr(
        "local_ai.vision_execution.llm_seam.ve_eval_provider_shim",
        lambda user_id, *, use_execution_seam=False: _P(),
    )

    out = evaluate_initiative(
        "T",
        "B",
        use_execution_seam=True,
        routing_payload={"action_intent": INITIATIVE_EVALUATE_INTENT},
        exec_meta={"provider_used": "ollama"},
    )
    assert "error" not in out
    assert out.get("delegation_path") is None
    assert len(calls) == 2
