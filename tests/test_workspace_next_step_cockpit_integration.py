"""
Integration-style checks for workspace Next Step aligned with cockpit usage.

Mirrors ``frontend/src/App.tsx`` ``runNextStep``: always sends ``routing_context`` with
``surface=workspace_organizer``, ``action_kind=structured_evaluation``,
``action_intent=workspace_next_step`` (see ``WORKSPACE_ACTION_INTENTS.next_step``).

Run: python -m pytest tests/test_workspace_next_step_cockpit_integration.py -v
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from api.main import app
from local_ai.execution_policy.types import PolicyConfig
from local_ai.providers.ollama import OllamaProvider


def _policy_openai_next_step(model: str = "gpt-cockpit-test") -> PolicyConfig:
    return PolicyConfig.from_dict(
        {
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
            "overrides_by_action_intent": {
                "workspace_next_step": {"primary": {"provider": "openai", "model": model}},
            },
        }
    )


def _policy_ollama_next_step() -> PolicyConfig:
    return PolicyConfig.from_dict(
        {
            "schema_version": 1,
            "global_priority": "balanced",
            "defaults": {
                "local": {"provider": "ollama", "model": "local-m"},
                "cloud": {"provider": "openai", "model": "gpt-4.1-mini"},
                "allow_cloud_fallback": True,
                "max_fallback_steps": 3,
            },
            "priority_profiles": {"balanced": {}, "privacy": {"allow_cloud": False, "require_local": True}},
            "overrides_by_action_kind": {},
            "overrides_by_action_intent": {
                "workspace_next_step": {"primary": {"provider": "ollama", "model": "local-m"}},
            },
        }
    )


def _cockpit_routing_context() -> dict:
    """Same shape as ``workspaceRunRoutingContext(WORKSPACE_ACTION_INTENTS.next_step, false)``."""
    return {
        "surface": "workspace_organizer",
        "action_kind": "structured_evaluation",
        "action_intent": "workspace_next_step",
        "streaming": False,
        "privacy_mode": "normal",
    }


def _cockpit_body(*, folder_path: str, context_block: str | None, question: str | None) -> dict:
    """Subset of App.tsx ``runNextStep`` JSON body (context only when path or block exists)."""
    body: dict = {
        "mode": "next_step",
        "params": {"question": question} if question else {},
        "routing_context": _cockpit_routing_context(),
    }
    ctx: dict = {"folder_path": folder_path, "use_last_result": bool(context_block)}
    if context_block:
        ctx["context_block"] = context_block
    body["context"] = ctx
    return body


@pytest.fixture
def client():
    return TestClient(app)


def _stub_anonymous_openai_routes_to_ollama(monkeypatch: pytest.MonkeyPatch) -> None:
    """Policy primary OpenAI + anonymous /run uses Ollama substrate when local daemon is up."""
    monkeypatch.setattr(
        "local_ai.execution_policy.seam_routing._ollama_reachable_for_seam_fallback",
        lambda: True,
    )


def test_cockpit_shaped_openai_activates_structured_cloud_v1(client, monkeypatch):
    """Policy OpenAI primary + anonymous lane → Ollama substrate → structured JSON path."""
    _stub_anonymous_openai_routes_to_ollama(monkeypatch)

    monkeypatch.setattr(
        "local_ai.execution_policy.resolve.load_execution_policy_config",
        lambda policy_path=None: _policy_openai_next_step(),
    )

    payload = {
        "recommendation": "Pick a folder and run Analyze",
        "rationale": "You need structure before prioritizing.",
        "alternatives": ["Run Council", "Web research"],
        "caution": "Verify path exists.",
    }

    def fake_generate(self, prompt, *, timeout=None):
        assert "OUTPUT CONTRACT" in prompt or "OUTPUT CONTRACT (JSON ONLY)" in prompt
        assert "workspace_next_step" in prompt or "Task intent:" in prompt
        return json.dumps(payload)

    monkeypatch.setattr(OllamaProvider, "generate", fake_generate)

    r = client.post(
        "/run",
        json=_cockpit_body(
            folder_path="/tmp/workspace",
            context_block="Prior analyze: 3 files, low confidence on two.",
            question="What should I do next?",
        ),
    )
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert data.get("delegation_path") == "structured_cloud_v1"
    assert data.get("provider_used") == "ollama"
    assert data.get("anonymous_openai_fallback_ollama") is True
    res = data["result"]
    assert res["recommendation"] == payload["recommendation"]
    assert res["rationale"] == payload["rationale"]
    assert res["alternatives"] == payload["alternatives"]
    assert res["caution"] == payload["caution"]
    assert "error" not in res or not res.get("error")


def test_cockpit_shaped_malformed_model_json_fails_cleanly(client, monkeypatch):
    _stub_anonymous_openai_routes_to_ollama(monkeypatch)
    monkeypatch.setattr(
        "local_ai.execution_policy.resolve.load_execution_policy_config",
        lambda policy_path=None: _policy_openai_next_step(),
    )

    def fake_generate(self, prompt, *, timeout=None):
        return "Recommendation: not json\n"

    monkeypatch.setattr(OllamaProvider, "generate", fake_generate)

    r = client.post(
        "/run",
        json=_cockpit_body(folder_path="/x", context_block="ctx", question="q"),
    )
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is False
    assert "Structured delegation" in (data.get("error") or "")
    assert data.get("delegation_path") == "structured_cloud_v1"


def test_empty_prompt_openai_routing_sets_delegation_skip_reason(client, monkeypatch):
    """No context/question: suggest_next_step path; trace why structured_cloud_v1 did not run."""
    _stub_anonymous_openai_routes_to_ollama(monkeypatch)
    monkeypatch.setattr(
        "local_ai.execution_policy.resolve.load_execution_policy_config",
        lambda policy_path=None: _policy_openai_next_step(),
    )

    def fake_generate(self, prompt, *, timeout=None):
        return "Recommendation: x\nRationale: y\n"

    monkeypatch.setattr(OllamaProvider, "generate", fake_generate)

    r = client.post(
        "/run",
        json={
            "mode": "next_step",
            "params": {},
            "routing_context": _cockpit_routing_context(),
        },
    )
    assert r.status_code == 200
    data = r.json()
    assert data.get("ok") is True
    assert data.get("delegation_skip_reason") == "empty_next_step_context_and_question"
    assert data.get("delegation_path") is None


def test_cockpit_shaped_ollama_does_not_set_delegation_path(client, monkeypatch):
    """Policy primary Ollama: legacy line parse; no structured_cloud_v1 trace."""
    monkeypatch.setattr("local_ai.config.OLLAMA_MODEL", "local-m", raising=False)
    monkeypatch.setattr(
        "local_ai.execution_policy.resolve.load_execution_policy_config",
        lambda policy_path=None: _policy_ollama_next_step(),
    )

    from local_ai.providers.ollama import OllamaProvider

    def fake_generate(self, prompt, *, timeout=None):
        return "Recommendation: Use local line format\nRationale: ok\nAlternatives:\n"

    monkeypatch.setattr(OllamaProvider, "generate", fake_generate)

    r = client.post(
        "/run",
        json=_cockpit_body(folder_path="/data", context_block="Some context", question=None),
    )
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert data.get("provider_used") == "ollama"
    assert data.get("delegation_path") is None
    assert "local line format" in (data.get("result") or {}).get("recommendation", "")
