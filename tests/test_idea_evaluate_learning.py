"""Idea evaluate: general-tier learning capture when routed OpenAI seam is active."""

from __future__ import annotations

import pytest

from local_ai.delegation.learning_capture import get_learning_buffer
from local_ai.vision_execution.idea_evaluate import evaluate_idea


@pytest.fixture(autouse=True)
def _clear_buffer():
    get_learning_buffer().clear()
    yield
    get_learning_buffer().clear()


def test_evaluate_idea_no_learning_without_routed_openai(monkeypatch):
    class P:
        def generate(self, prompt: str, *, timeout: int | None = 60) -> str:
            return (
                '{"estimated_cost_range":"low","time_to_build":"1w","time_to_roi":"1m",'
                '"roi_potential":"expected","required_roles":"","likely_dependencies":"",'
                '"major_risks":"","strategic_alignment":"","suggested_next_step":"",'
                '"recommendation":"Incubate"}'
            )

    monkeypatch.setattr(
        "local_ai.vision_execution.llm_seam.ve_eval_provider_shim",
        lambda uid, use_execution_seam=False: P(),
    )

    out = evaluate_idea("T", "Brief here", use_execution_seam=False)
    assert "error" not in out
    assert "learning_record_id" not in out
    assert get_learning_buffer().size() == 0


def test_evaluate_idea_learning_when_routed_openai(monkeypatch):
    class P:
        def generate(self, prompt: str, *, timeout: int | None = 60) -> str:
            return (
                '{"estimated_cost_range":"low","time_to_build":"1w","time_to_roi":"1m",'
                '"roi_potential":"expected","required_roles":"","likely_dependencies":"",'
                '"major_risks":"","strategic_alignment":"","suggested_next_step":"",'
                '"recommendation":"Incubate"}'
            )

    monkeypatch.setattr(
        "local_ai.vision_execution.llm_seam.ve_eval_provider_shim",
        lambda uid, use_execution_seam=False: P(),
    )

    rc = {"surface": "vision_execution", "action_intent": "idea_evaluate", "privacy_mode": "normal"}
    meta = {"provider_used": "openai", "model_used": "gpt-test"}
    out = evaluate_idea(
        "T",
        "Brief here",
        use_execution_seam=True,
        routing_context=rc,
        exec_meta=meta,
    )
    assert "error" not in out
    assert out.get("learning_record_id")
    rec = get_learning_buffer().recent(1)[0]
    assert rec["action_intent"] == "idea_evaluate"
    assert rec["delegation_tier"] == "general"
