"""Core profile conversation: general delegation lane when execution seam is on."""

from __future__ import annotations

import pytest

from local_ai.vision_execution import core_profile_conversation as cp


def test_converse_execution_seam_uses_general_lane(monkeypatch):
    calls: list[dict] = []

    def fake_lane(**kwargs):
        calls.append({"keys": sorted(kwargs.keys())})
        return {
            "ok": True,
            "text": "  Model reply paragraph.  ",
            "parsed": None,
            "error": None,
            "learning_record_id": "abc123def456",
        }

    monkeypatch.setattr(
        "local_ai.delegation.general_lane.run_general_delegation_custom_prompt",
        fake_lane,
    )

    class _P:
        def generate(self, prompt: str, *, timeout: int = 90) -> str:
            return "unused"

    monkeypatch.setattr(
        "local_ai.vision_execution.llm_seam.ve_eval_provider_shim",
        lambda uid, use_execution_seam=True: _P(),
    )

    out = cp.converse(
        raw_notes="",
        conversation_turns=[{"role": "user", "content": "hello"}],
        current_structured={},
        routing_context={"surface": "core_profile", "action_intent": "core_profile_conversation"},
        use_execution_seam=True,
        exec_meta={"provider_used": "openai", "model_used": "gpt-test"},
        user_id="user-1",
    )
    assert out.get("reply") == "Model reply paragraph."
    assert out.get("learning_record_id") == "abc123def456"
    assert out.get("provider_used") == "openai"
    assert calls and "compiled_prompt" in calls[0]["keys"]
