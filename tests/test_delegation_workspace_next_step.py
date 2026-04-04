"""Unit tests: structured cloud delegation v1 (workspace_next_step JSON contract)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from api.main import app
from local_ai.delegation.json_extract import extract_json_object
from local_ai.delegation.workspace_next_step import (
    build_workspace_next_step_contract,
    synthesize_structured_cloud_prompt,
    validate_workspace_next_step_json,
)


@pytest.fixture
def client():
    return TestClient(app)


def test_validate_accepts_minimal_valid():
    raw = {
        "recommendation": "Do the thing",
        "rationale": "Because",
        "alternatives": ["Alt"],
        "caution": None,
    }
    norm, err = validate_workspace_next_step_json(raw)
    assert err is None
    assert norm is not None
    assert norm["recommendation"] == "Do the thing"
    assert norm["alternatives"] == ["Alt"]
    assert norm["caution"] is None


def test_validate_rejects_extra_keys():
    raw = {
        "recommendation": "x",
        "rationale": "y",
        "alternatives": [],
        "caution": None,
        "foo": 1,
    }
    norm, err = validate_workspace_next_step_json(raw)
    assert norm is None
    assert err is not None


def test_validate_rejects_alternatives_as_string():
    raw = {
        "recommendation": "x",
        "rationale": "y",
        "alternatives": "a,b",
        "caution": None,
    }
    norm, err = validate_workspace_next_step_json(raw)
    assert norm is None


def test_extract_json_object_strips_fence():
    inner = '{"recommendation":"a","rationale":"b","alternatives":[],"caution":null}'
    blob = extract_json_object(f"```json\n{inner}\n```")
    assert blob == inner


def test_synthesize_includes_contract_and_bounded_context():
    c = build_workspace_next_step_contract(
        bounded_context="CTX_LINE",
        question_goal="Q1",
        subject_id_hint=None,
    )
    p = synthesize_structured_cloud_prompt(c)
    assert "CTX_LINE" in p
    assert "Q1" in p
    assert "OUTPUT CONTRACT" in p
    assert "recommendation" in p.lower()


def _policy_base(**kwargs):
    from local_ai.execution_policy.types import PolicyConfig

    base = {
        "schema_version": 1,
        "global_priority": "balanced",
        "defaults": {
            "local": {"provider": "ollama", "model": None},
            "cloud": {"provider": "openai", "model": "gpt-4.1-mini"},
            "allow_cloud_fallback": True,
            "max_fallback_steps": 3,
        },
        "priority_profiles": {"balanced": {}, "privacy": {"allow_cloud": False, "require_local": True}},
        "overrides_by_action_kind": {},
        "overrides_by_action_intent": {},
    }
    base.update(kwargs)
    return PolicyConfig.from_dict(base)


def test_post_run_next_step_structured_rejects_line_format(client, monkeypatch):
    """OpenAI + routing + workspace_next_step must not fall back to line parser."""
    monkeypatch.setattr(
        "local_ai.execution_policy.seam_routing._ollama_reachable_for_seam_fallback",
        lambda: True,
    )

    def fake_load(policy_path=None):
        return _policy_base(
            overrides_by_action_intent={
                "workspace_next_step": {"primary": {"provider": "openai", "model": "gpt-x"}},
            },
        )

    monkeypatch.setattr("local_ai.execution_policy.resolve.load_execution_policy_config", fake_load)

    from local_ai.providers.ollama import OllamaProvider

    def fake_generate(self, prompt, *, timeout=None):
        return "Recommendation: Old format\nRationale: x\n"

    monkeypatch.setattr(OllamaProvider, "generate", fake_generate)

    r = client.post(
        "/run",
        json={
            "mode": "next_step",
            "params": {"question": "What next?"},
            "context": {"context_block": "Project alpha"},
            "routing_context": {
                "surface": "workspace_organizer",
                "action_kind": "structured_evaluation",
                "action_intent": "workspace_next_step",
            },
        },
    )
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is False
    assert "Structured delegation" in (data.get("error") or "")
    assert data.get("delegation_path") == "structured_cloud_v1"
    assert data.get("learning_record_id")
