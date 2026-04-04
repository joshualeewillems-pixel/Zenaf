"""Meeting extraction execution policy gate."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from local_ai.execution_policy.types import PolicyConfig
from local_ai.vision_execution.meeting_extraction_execution import (
    INTENT_CHUNKS,
    meeting_extraction_execution_blocked,
)


def _policy_cloud_primary_for_meeting() -> PolicyConfig:
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
                "meeting_extract_single": {"primary": {"provider": "openai", "model": "gpt-test"}},
            },
        }
    )


def test_meeting_extraction_no_routing_context_no_gate():
    assert meeting_extraction_execution_blocked(action_intent=INTENT_CHUNKS, routing_context=None) is None


def test_meeting_extraction_local_only_blocks_cloud_primary(monkeypatch):
    monkeypatch.setattr(
        "local_ai.execution_policy.resolve.load_execution_policy_config",
        lambda policy_path=None: _policy_cloud_primary_for_meeting(),
    )
    err = meeting_extraction_execution_blocked(
        action_intent="meeting_extract_single",
        routing_context={
            "surface": "meeting_extraction",
            "action_kind": "suggestion_batch",
            "action_intent": "meeting_extract_single",
            "streaming": False,
            "privacy_mode": "local_only",
        },
    )
    assert err is not None
