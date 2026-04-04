"""
Execution policy resolver (Phase 0). Run from repo root:
  python -m pytest tests/test_execution_policy.py -v --tb=short
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from local_ai.execution_policy import (
    ActionRoutingContext,
    ExecutionPolicyBlocked,
    PolicyConfig,
    PrivacyPolicyInputPartial,
    ProviderModelRef,
    apply_trace_privacy_redaction,
    resolve_execution_policy_for_action,
)


def _unwrap(res):
    assert not isinstance(res, ExecutionPolicyBlocked), res
    return res


def _policy(**kwargs) -> PolicyConfig:
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
            "speed": {"prefer_cloud": False},
        },
        "overrides_by_action_kind": {},
        "overrides_by_action_intent": {},
    }
    base.update(kwargs)
    return PolicyConfig.from_dict(base)


def test_null_context_matches_default_ollama_model(monkeypatch):
    monkeypatch.setattr("local_ai.config.OLLAMA_MODEL", "unit-test-default-model", raising=False)
    r = _unwrap(resolve_execution_policy_for_action(None, policy_config=_policy()))
    assert r.primary == ProviderModelRef("ollama", "unit-test-default-model")
    assert r.flags.get("routing_context_absent") is True
    assert r.allow_cloud is True


def test_null_context_council_route_uses_council_model(monkeypatch):
    monkeypatch.delenv("ATRIA_COUNCIL_MODEL", raising=False)
    monkeypatch.setattr("local_ai.config.OLLAMA_MODEL", "default-m", raising=False)
    monkeypatch.setattr("local_ai.config.OLLAMA_COUNCIL_MODEL", "council-m", raising=False)
    r = resolve_execution_policy_for_action(None, legacy_route="council", policy_config=_policy())
    assert r.primary.model == "council-m"
    assert r.flags.get("legacy_route") == "council"


def test_null_context_council_env_overrides_config(monkeypatch):
    monkeypatch.setenv("ATRIA_COUNCIL_MODEL", "env-council-model")
    monkeypatch.setattr("local_ai.config.OLLAMA_MODEL", "default-m", raising=False)
    monkeypatch.setattr("local_ai.config.OLLAMA_COUNCIL_MODEL", "council-m", raising=False)
    r = _unwrap(resolve_execution_policy_for_action(None, legacy_route="council", policy_config=_policy()))
    assert r.primary.model == "env-council-model"
    monkeypatch.delenv("ATRIA_COUNCIL_MODEL", raising=False)


def test_empty_overrides_same_as_implicit_default(monkeypatch):
    monkeypatch.setattr("local_ai.config.OLLAMA_MODEL", "same-model", raising=False)
    ctx = ActionRoutingContext(
        surface="workspace_organizer",
        action_kind="structured_evaluation",
        action_intent="workspace_analyze",
    )
    r = _unwrap(resolve_execution_policy_for_action(ctx, policy_config=_policy()))
    assert r.primary == ProviderModelRef("ollama", "same-model")
    assert r.flags.get("routing_context_absent") is False
    assert r.fallback_chain == ()


def test_kind_override_applies_when_no_intent_conflict(monkeypatch):
    monkeypatch.setattr("local_ai.config.OLLAMA_MODEL", "base-m", raising=False)
    cfg = _policy(
        overrides_by_action_kind={
            "field_text_rewrite": {
                "primary": {"provider": "ollama", "model": "kind-override-m"},
            }
        }
    )
    ctx = ActionRoutingContext(surface="vision_execution", action_kind="field_text_rewrite", action_intent=None)
    r = _unwrap(resolve_execution_policy_for_action(ctx, policy_config=cfg))
    assert r.primary.model == "kind-override-m"


def test_intent_override_beats_kind(monkeypatch):
    monkeypatch.setattr("local_ai.config.OLLAMA_MODEL", "base-m", raising=False)
    cfg = _policy(
        overrides_by_action_kind={
            "structured_evaluation": {
                "primary": {"provider": "ollama", "model": "from-kind"},
            }
        },
        overrides_by_action_intent={
            "workspace_council": {
                "primary": {"provider": "ollama", "model": "from-intent"},
            }
        },
    )
    ctx = ActionRoutingContext(
        surface="workspace_organizer",
        action_kind="structured_evaluation",
        action_intent="workspace_council",
    )
    r = resolve_execution_policy_for_action(ctx, policy_config=cfg)
    assert r.primary.model == "from-intent"


def test_merge_precedence_fallback_chain_from_intent_replaces_kind(monkeypatch):
    monkeypatch.setattr("local_ai.config.OLLAMA_MODEL", "base-m", raising=False)
    cfg = _policy(
        overrides_by_action_kind={
            "structured_evaluation": {
                "fallback_chain": [{"provider": "openai", "model": "kind-fb"}],
            }
        },
        overrides_by_action_intent={
            "workspace_next_step": {
                "fallback_chain": [{"provider": "anthropic", "model": "intent-fb"}],
            }
        },
    )
    ctx = ActionRoutingContext(
        surface="workspace_organizer",
        action_kind="structured_evaluation",
        action_intent="workspace_next_step",
    )
    r = _unwrap(resolve_execution_policy_for_action(ctx, policy_config=cfg))
    assert len(r.fallback_chain) == 1
    assert r.fallback_chain[0].provider == "anthropic"


def test_default_shipped_policy_no_overrides_behaves_like_legacy(monkeypatch):
    """Loading real config/ai_execution_policy.json: null context vs a routed context without a distinct override share the same primary."""
    monkeypatch.setattr("local_ai.config.OLLAMA_MODEL", "shipped-default", raising=False)
    path = ROOT / "config" / "ai_execution_policy.json"
    r_null = _unwrap(resolve_execution_policy_for_action(None, policy_path=path))
    ctx = ActionRoutingContext(
        surface="workspace_organizer",
        action_kind="structured_evaluation",
        action_intent="workspace_recommend",
    )
    r_ctx = _unwrap(resolve_execution_policy_for_action(ctx, policy_path=path))
    assert r_null.primary == r_ctx.primary == ProviderModelRef("ollama", "shipped-default")


def test_privacy_profile_filters_non_local_fallback_only_when_configured(monkeypatch):
    monkeypatch.setattr("local_ai.config.OLLAMA_MODEL", "local-m", raising=False)
    cfg = _policy(
        global_priority="balanced",
        overrides_by_action_intent={
            "private_flow": {
                "inherit_priority": "privacy",
                "fallback_chain": [
                    {"provider": "openai", "model": "cloud-a"},
                    {"provider": "ollama", "model": "local-fb"},
                ],
            }
        },
    )
    ctx = ActionRoutingContext(
        surface="content",
        action_kind="structured_evaluation",
        action_intent="private_flow",
    )
    r = _unwrap(resolve_execution_policy_for_action(ctx, policy_config=cfg))
    assert r.allow_cloud is False
    assert r.flags.get("privacy_require_local") is True
    assert len(r.fallback_chain) == 1
    assert r.fallback_chain[0].provider == "ollama"


def test_balanced_default_does_not_set_privacy_filter(monkeypatch):
    monkeypatch.setattr("local_ai.config.OLLAMA_MODEL", "local-m", raising=False)
    cfg = _policy(
        overrides_by_action_intent={
            "x": {
                "fallback_chain": [
                    {"provider": "openai", "model": "cloud-a"},
                ],
            }
        },
    )
    ctx = ActionRoutingContext(surface="content", action_kind="structured_evaluation", action_intent="x")
    r = _unwrap(resolve_execution_policy_for_action(ctx, policy_config=cfg))
    assert r.flags.get("privacy_require_local") is False
    assert len(r.fallback_chain) == 1
    assert r.fallback_chain[0].provider == "openai"


def test_privacy_explicit_blocks_when_approved_providers_omit_ollama(monkeypatch):
    monkeypatch.setattr("local_ai.config.OLLAMA_MODEL", "local-m", raising=False)
    ctx = ActionRoutingContext(surface="content", action_kind="structured_evaluation", action_intent="x")
    out = resolve_execution_policy_for_action(
        ctx,
        policy_config=_policy(),
        privacy=PrivacyPolicyInputPartial(approved_providers=("openai",)),
    )
    assert isinstance(out, ExecutionPolicyBlocked)
    assert out.reason == "privacy_constraints"


def test_trace_privacy_redaction_scrubs_snapshot_and_output():
    snap, out = apply_trace_privacy_redaction(
        input_snapshot="brief_id:abc\n" + "x" * 200,
        output='{"x": 1}',
        redact_trace_snapshot=True,
        suppress_trace_output=True,
    )
    assert snap.startswith("[redacted]")
    assert "len=" in snap
    assert "suppressed" in out
