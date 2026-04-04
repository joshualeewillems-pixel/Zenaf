"""Core profile execution policy gate (routing_context + privacy_mode)."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pytest

from local_ai.execution_policy.types import PolicyConfig
from local_ai.vision_execution.core_profile_execution import (
    INTENT_RECONCILE,
    core_profile_execution_blocked,
)


def _policy_cloud_primary_for_reconcile() -> PolicyConfig:
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
            "priority_profiles": {"balanced": {}},
            "overrides_by_action_kind": {},
            "overrides_by_action_intent": {
                "core_profile_reconcile": {"primary": {"provider": "openai", "model": "gpt-test"}},
            },
        }
    )


def test_core_profile_no_routing_context_no_gate():
    assert core_profile_execution_blocked(action_intent=INTENT_RECONCILE, routing_context=None) is None


def test_core_profile_local_only_blocks_cloud_primary(monkeypatch):
    monkeypatch.setattr(
        "local_ai.execution_policy.resolve.load_execution_policy_config",
        lambda policy_path=None: _policy_cloud_primary_for_reconcile(),
    )
    err = core_profile_execution_blocked(
        action_intent=INTENT_RECONCILE,
        routing_context={
            "surface": "core_profile",
            "action_kind": "structured_evaluation",
            "action_intent": INTENT_RECONCILE,
            "streaming": False,
            "privacy_mode": "local_only",
        },
    )
    assert err is not None
    assert "privacy" in err.lower() or "provider" in err.lower() or "model" in err.lower()
