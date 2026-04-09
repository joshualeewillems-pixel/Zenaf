"""
POST /run optional routing_context (Phase 1). Run from repo root:
  python -m pytest tests/test_run_routing_context.py -v --tb=short
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pytest
from fastapi.testclient import TestClient

from api.main import (
    RunRequest,
    RunRoutingContext,
    _begin_run_routing,
    _end_run_routing,
    app,
)
from local_ai.execution_policy import ActionRoutingContext, ExecutionPolicyBlocked, resolve_execution_policy_for_action
from local_ai.execution_policy.types import PolicyConfig
from local_ai.llm.execution_principal import anonymous_account_principal, authenticated_account_principal
from local_ai.llm.resolver import get_llm_adapter_for_principal
from local_ai.providers.openai import OpenAIProvider


def _policy_base(**kwargs) -> PolicyConfig:
    base = {
        "schema_version": 1,
        "global_priority": "balanced",
        "defaults": {
            "local": {"provider": "ollama", "model": None},
            "cloud": {"provider": "openai", "model": "gpt-4.1-mini"},
            "allow_cloud_fallback": True,
            "max_fallback_steps": 3,
        },
        "priority_profiles": {
            "balanced": {},
            "privacy": {"allow_cloud": False, "require_local": True},
        },
        "overrides_by_action_kind": {},
        "overrides_by_action_intent": {},
    }
    base.update(kwargs)
    return PolicyConfig.from_dict(base)


@pytest.fixture
def client():
    return TestClient(app)


def test_run_without_routing_context_no_model_metadata(client, monkeypatch):
    monkeypatch.setattr("api.main._run_analyze", lambda p: {"folder_path": getattr(p, "folder_path", None) or "/x"})
    monkeypatch.setattr("local_ai.config.OLLAMA_MODEL", "legacy-m", raising=False)
    r = client.post("/run", json={"mode": "analyze", "params": {"folder_path": "/tmp"}})
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert data.get("model_used") is None
    assert data.get("provider_used") is None
    assert data.get("routing_override_active") is None


def test_run_with_routing_empty_overrides_same_effective_model(client, monkeypatch):
    monkeypatch.setattr("api.main._run_analyze", lambda p: {"folder_path": "/tmp"})
    monkeypatch.setattr("local_ai.config.OLLAMA_MODEL", "effective-m", raising=False)
    r = client.post(
        "/run",
        json={
            "mode": "analyze",
            "params": {"folder_path": "/tmp"},
            "routing_context": {
                "surface": "workspace_organizer",
                "action_kind": "structured_evaluation",
                "action_intent": "workspace_analyze",
                "streaming": False,
            },
        },
    )
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert data.get("model_used") == "effective-m"
    assert data.get("provider_used") == "ollama"
    assert data.get("routing_override_active") is True


def test_run_intent_override_beats_kind_override(client, monkeypatch):
    monkeypatch.setattr("api.main._run_analyze", lambda p: {"folder_path": "/tmp"})
    monkeypatch.setattr("local_ai.config.OLLAMA_MODEL", "base-m", raising=False)

    def fake_load(policy_path=None):
        return _policy_base(
            overrides_by_action_kind={
                "structured_evaluation": {"primary": {"provider": "ollama", "model": "from-kind"}},
            },
            overrides_by_action_intent={
                "workspace_analyze": {"primary": {"provider": "ollama", "model": "from-intent"}},
            },
        )

    monkeypatch.setattr("local_ai.execution_policy.resolve.load_execution_policy_config", fake_load)
    r = client.post(
        "/run",
        json={
            "mode": "analyze",
            "params": {"folder_path": "/tmp"},
            "routing_context": {
                "surface": "workspace_organizer",
                "action_kind": "structured_evaluation",
                "action_intent": "workspace_analyze",
            },
        },
    )
    assert r.status_code == 200
    assert r.json().get("model_used") == "from-intent"


def test_require_local_filters_fallback_at_resolution_workspace(monkeypatch):
    monkeypatch.setattr("local_ai.config.OLLAMA_MODEL", "local-m", raising=False)

    def fake_load(policy_path=None):
        return _policy_base(
            overrides_by_action_intent={
                "workspace_recommend": {
                    "inherit_priority": "privacy",
                    "fallback_chain": [
                        {"provider": "openai", "model": "cloud-a"},
                        {"provider": "ollama", "model": "local-fb"},
                    ],
                }
            },
        )

    monkeypatch.setattr("local_ai.execution_policy.resolve.load_execution_policy_config", fake_load)
    ctx = ActionRoutingContext(
        surface="workspace_organizer",
        action_kind="structured_evaluation",
        action_intent="workspace_recommend",
    )
    res = resolve_execution_policy_for_action(ctx, legacy_route="default")
    assert not isinstance(res, ExecutionPolicyBlocked)
    assert res.flags.get("privacy_require_local") is True
    assert len(res.fallback_chain) == 1
    assert res.fallback_chain[0].provider == "ollama"
    assert res.fallback_chain[0].model == "local-fb"


def test_privacy_mode_local_only_blocks_cloud_primary(client, monkeypatch):
    """routing_context.privacy_mode=local_only filters non-local primary → execution_blocked."""
    monkeypatch.setattr("local_ai.config.OLLAMA_MODEL", "local-m", raising=False)

    def fake_load(policy_path=None):
        return _policy_base(
            overrides_by_action_intent={
                "workspace_analyze": {"primary": {"provider": "openai", "model": "gpt-test"}},
            },
        )

    monkeypatch.setattr("local_ai.execution_policy.resolve.load_execution_policy_config", fake_load)
    r = client.post(
        "/run",
        json={
            "mode": "analyze",
            "params": {"folder_path": "/tmp"},
            "routing_context": {
                "surface": "workspace_organizer",
                "action_kind": "structured_evaluation",
                "action_intent": "workspace_analyze",
                "streaming": False,
                "privacy_mode": "local_only",
            },
        },
    )
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is False
    assert data.get("execution_blocked") is True
    assert data.get("model_used") is None
    assert data.get("provider_used") is None
    assert data.get("error")


def test_begin_run_routing_council_mode_uses_ollama_when_policy_primary_ollama(monkeypatch):
    """When policy explicitly sets workspace_council -> Ollama, routing pushes council Ollama model (no OpenAI key)."""

    def fake_load(policy_path=None):
        return _policy_base(
            overrides_by_action_intent={
                "workspace_council": {"primary": {"provider": "ollama", "model": None}},
            },
        )

    monkeypatch.setattr("local_ai.execution_policy.resolve.load_execution_policy_config", fake_load)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ZENAF_COUNCIL_MODEL", raising=False)
    monkeypatch.setattr("local_ai.config.OLLAMA_MODEL", "def-m", raising=False)
    monkeypatch.setattr("local_ai.config.OLLAMA_COUNCIL_MODEL", "council-legacy-m", raising=False)
    req = RunRequest(
        mode="council",
        params=None,
        routing_context=RunRoutingContext(
            surface="workspace_organizer",
            action_kind="structured_evaluation",
            action_intent="workspace_council",
            streaming=True,
        ),
    )
    teardown, meta = _begin_run_routing(req, execution_principal=anonymous_account_principal())
    try:
        assert meta.get("provider_used") == "ollama"
        assert meta.get("model_used") == "council-legacy-m"
        assert meta.get("routing_override_active") is True
    finally:
        _end_run_routing(teardown)


def test_apply_seam_routing_openai_prefers_env_over_settings(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-env")

    def fake_load(policy_path=None):
        return _policy_base(
            overrides_by_action_intent={
                "workspace_next_step": {"primary": {"provider": "openai", "model": "gpt-4.1-mini"}},
            },
        )

    monkeypatch.setattr("local_ai.execution_policy.resolve.load_execution_policy_config", fake_load)

    def fake_get_key(uid, prov):
        raise AssertionError("should not read settings when env is set")

    monkeypatch.setattr("local_ai.vision_execution.storage.get_decrypted_llm_api_key", fake_get_key)
    from local_ai.execution_policy.run_context import end_execution_routing
    from local_ai.execution_policy.seam_routing import apply_seam_routing

    rc = {
        "surface": "workspace_organizer",
        "action_kind": "structured_evaluation",
        "action_intent": "workspace_next_step",
        "streaming": False,
    }
    teardown, meta = apply_seam_routing(mode="next_step", routing_context=rc, user_id="user-1")
    try:
        assert meta.get("provider_used") == "openai"
        assert meta.get("openai_key_source") == "env"
    finally:
        end_execution_routing(teardown)


def test_apply_seam_routing_openai_uses_saved_settings_key_when_no_env(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    def fake_load(policy_path=None):
        return _policy_base(
            overrides_by_action_intent={
                "workspace_next_step": {"primary": {"provider": "openai", "model": "gpt-4.1-mini"}},
            },
        )

    monkeypatch.setattr("local_ai.execution_policy.resolve.load_execution_policy_config", fake_load)

    def fake_get_key(uid, prov):
        if prov == "openai" and uid == "user-1":
            return "sk-from-settings"
        return None

    monkeypatch.setattr("local_ai.vision_execution.storage.get_decrypted_llm_api_key", fake_get_key)
    from local_ai.execution_policy.run_context import end_execution_routing
    from local_ai.execution_policy.seam_routing import apply_seam_routing

    rc = {
        "surface": "workspace_organizer",
        "action_kind": "structured_evaluation",
        "action_intent": "workspace_next_step",
        "streaming": False,
    }
    teardown, meta = apply_seam_routing(mode="next_step", routing_context=rc, user_id="user-1")
    try:
        assert meta.get("provider_used") == "openai"
        assert meta.get("openai_key_source") == "settings"
    finally:
        end_execution_routing(teardown)


def test_begin_run_routing_council_workspace_council_falls_back_ollama_when_openai_key_missing(monkeypatch):
    """Council with policy OpenAI but no key: seam falls back to Ollama so per-seat cloud providers can still run."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    def fake_load(policy_path=None):
        return _policy_base(
            overrides_by_action_intent={
                "workspace_council": {"primary": {"provider": "openai", "model": "gpt-4.1-mini"}},
            },
        )

    monkeypatch.setattr("local_ai.execution_policy.resolve.load_execution_policy_config", fake_load)
    req = RunRequest(
        mode="council",
        params=None,
        routing_context=RunRoutingContext(
            surface="workspace_organizer",
            action_kind="structured_evaluation",
            action_intent="workspace_council",
            streaming=True,
        ),
    )
    teardown, meta = _begin_run_routing(req, execution_principal=anonymous_account_principal())
    try:
        assert meta.get("execution_blocked") is not True
        assert meta.get("provider_used") == "ollama"
        assert meta.get("council_seam_fallback_ollama") is True
        assert meta.get("routing_override_active") is True
    finally:
        _end_run_routing(teardown)


def test_begin_run_routing_council_mode_uses_openai_when_policy_override_openai_and_key(monkeypatch):
    """Policy can still target OpenAI for council when key is present."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-not-real")
    monkeypatch.delenv("ZENAF_COUNCIL_MODEL", raising=False)
    monkeypatch.setattr("local_ai.config.OLLAMA_MODEL", "def-m", raising=False)
    monkeypatch.setattr("local_ai.config.OLLAMA_COUNCIL_MODEL", "council-legacy-m", raising=False)

    def fake_load(policy_path=None):
        return _policy_base(
            overrides_by_action_intent={
                "workspace_council": {"primary": {"provider": "openai", "model": "gpt-4.1-mini"}},
            },
        )

    monkeypatch.setattr("local_ai.execution_policy.resolve.load_execution_policy_config", fake_load)
    req = RunRequest(
        mode="council",
        params=None,
        routing_context=RunRoutingContext(
            surface="workspace_organizer",
            action_kind="structured_evaluation",
            action_intent="workspace_council",
            streaming=True,
        ),
    )
    teardown, meta = _begin_run_routing(req, execution_principal=authenticated_account_principal("user-council-openai"))
    try:
        assert meta.get("provider_used") == "openai"
        assert meta.get("model_used") == "gpt-4.1-mini"
        assert meta.get("routing_override_active") is True
    finally:
        _end_run_routing(teardown)


def test_begin_run_routing_council_anonymous_ignores_openai_env_for_primary_openai(monkeypatch):
    """Option B: OPENAI_API_KEY must not unlock policy OpenAI for account:anonymous (council falls back to Ollama)."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-should-not-apply-to-anon")
    monkeypatch.delenv("ZENAF_COUNCIL_MODEL", raising=False)
    monkeypatch.setattr("local_ai.config.OLLAMA_MODEL", "def-m", raising=False)
    monkeypatch.setattr("local_ai.config.OLLAMA_COUNCIL_MODEL", "council-legacy-m", raising=False)

    def fake_load(policy_path=None):
        return _policy_base(
            overrides_by_action_intent={
                "workspace_council": {"primary": {"provider": "openai", "model": "gpt-4.1-mini"}},
            },
        )

    monkeypatch.setattr("local_ai.execution_policy.resolve.load_execution_policy_config", fake_load)
    req = RunRequest(
        mode="council",
        params=None,
        routing_context=RunRoutingContext(
            surface="workspace_organizer",
            action_kind="structured_evaluation",
            action_intent="workspace_council",
            streaming=True,
        ),
    )
    teardown, meta = _begin_run_routing(req, execution_principal=anonymous_account_principal())
    try:
        assert meta.get("provider_used") == "ollama"
        assert meta.get("council_seam_fallback_ollama") is True
        assert meta.get("openai_key_source") == "anonymous_blocked"
        assert "anonymous" in (meta.get("council_seam_fallback_reason") or "").lower()
    finally:
        _end_run_routing(teardown)


def test_openai_primary_missing_key_execution_blocked(client, monkeypatch):
    monkeypatch.setattr(
        "local_ai.llm.execution_principal.resolve_execution_principal_for_run_http",
        lambda **kwargs: (authenticated_account_principal("pytest-openai-missing"), None),
    )
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    def fake_load(policy_path=None):
        return _policy_base(
            overrides_by_action_intent={
                "workspace_next_step": {"primary": {"provider": "openai", "model": "gpt-4o-mini"}},
            },
        )

    monkeypatch.setattr("local_ai.execution_policy.resolve.load_execution_policy_config", fake_load)
    r = client.post(
        "/run",
        json={
            "mode": "next_step",
            "params": {"question": "What next?"},
            "context": {"context_block": "Some context"},
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
    assert data.get("execution_blocked") is True
    assert "No OpenAI API key available" in (data.get("error") or "")


def test_openai_primary_uses_openai_provider_and_meta(client, monkeypatch):
    monkeypatch.setattr(
        "local_ai.llm.execution_principal.resolve_execution_principal_for_run_http",
        lambda **kwargs: (authenticated_account_principal("pytest-openai-ok"), None),
    )
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-not-real")

    def fake_load(policy_path=None):
        return _policy_base(
            overrides_by_action_intent={
                "workspace_next_step": {"primary": {"provider": "openai", "model": "gpt-test-model"}},
            },
        )

    monkeypatch.setattr("local_ai.execution_policy.resolve.load_execution_policy_config", fake_load)

    def fake_generate(self, prompt, *, timeout=None):
        import json

        return json.dumps(
            {
                "recommendation": "Ship it",
                "rationale": "Policy path",
                "alternatives": ["A", "B"],
                "caution": None,
            }
        )

    monkeypatch.setattr(OpenAIProvider, "generate", fake_generate)

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
    assert data["ok"] is True
    assert data.get("provider_used") == "openai"
    assert data.get("model_used") == "gpt-test-model"
    assert data.get("routing_override_active") is True
    assert data.get("result", {}).get("recommendation") == "Ship it"
    assert data.get("delegation_path") == "structured_cloud_v1"


def test_unsupported_provider_primary_blocks_with_clear_message(client, monkeypatch):
    """Policy primary must not claim e.g. anthropic while code runs Ollama — block instead."""
    monkeypatch.setattr("local_ai.config.OLLAMA_MODEL", "m1", raising=False)

    def fake_load(policy_path=None):
        return _policy_base(
            overrides_by_action_intent={
                "workspace_next_step": {"primary": {"provider": "anthropic", "model": "claude-3-opus"}},
            },
        )

    monkeypatch.setattr("local_ai.execution_policy.resolve.load_execution_policy_config", fake_load)
    r = client.post(
        "/run",
        json={
            "mode": "next_step",
            "params": {"question": "x"},
            "context": {"context_block": "ctx"},
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
    assert data.get("execution_blocked") is True
    assert "not supported" in (data.get("error") or "").lower()
    assert data.get("provider_used") is None


def test_begin_run_routing_openai_push_resolver_sees_openai(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "k")
    monkeypatch.setattr("local_ai.config.OLLAMA_MODEL", "def-m", raising=False)

    def fake_load(policy_path=None):
        return _policy_base(
            overrides_by_action_intent={
                "workspace_next_step": {"primary": {"provider": "openai", "model": "gpt-xyz"}},
            },
        )

    monkeypatch.setattr("local_ai.execution_policy.resolve.load_execution_policy_config", fake_load)
    req = RunRequest(
        mode="next_step",
        params=None,
        routing_context=RunRoutingContext(
            surface="workspace_organizer",
            action_kind="structured_evaluation",
            action_intent="workspace_next_step",
        ),
    )
    pr = authenticated_account_principal("user-next-step-openai")
    teardown, meta = _begin_run_routing(req, execution_principal=pr)
    try:
        adapter = get_llm_adapter_for_principal(pr)
        inner = getattr(adapter, "_inner", None)
        assert isinstance(inner, OpenAIProvider)
        assert inner.model == "gpt-xyz"
        assert meta.get("provider_used") == "openai"
    finally:
        _end_run_routing(teardown)
