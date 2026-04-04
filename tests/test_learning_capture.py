"""Learning buffer + privacy behavior for delegated calls."""

from __future__ import annotations

import pytest

from local_ai.delegation.general_lane import compile_general_delegation_prompt, run_general_delegation_lane
from local_ai.delegation.learning_capture import (
    capture_general_delegation_outcome,
    capture_structured_delegation_outcome,
    get_learning_buffer,
    update_learning_record_user_outcome,
)


@pytest.fixture(autouse=True)
def _clear_learning_buffer():
    get_learning_buffer().clear()
    yield
    get_learning_buffer().clear()


def test_structured_capture_full_privacy_stores_snapshot_and_output():
    rid = capture_structured_delegation_outcome(
        surface="workspace_next_step",
        action_intent="workspace_next_step",
        privacy_mode="normal",
        provider_used="openai",
        model_used="gpt-4o-mini",
        delegation_tier="structured",
        input_snapshot="hello context",
        compiled_prompt="full prompt body " * 10,
        validation_passed=True,
        validation_error=None,
        output_payload={"recommendation": "x", "rationale": "y"},
        delegation_path="structured_cloud_v1",
        externalization_mapping_active=False,
    )
    assert rid and len(rid) >= 8
    buf = get_learning_buffer()
    assert buf.size() == 1
    rec = buf.recent(1)[0]
    assert rec["record_id"] == rid
    assert rec["validation_passed"] is True
    assert rec["action_intent"] == "workspace_next_step"
    assert rec["compiled_prompt_sha256_prefix"]
    assert rec["compiled_prompt_char_len"] > 0
    assert "hello context" in rec["input_snapshot_redacted"]
    assert "recommendation" in rec["model_output_redacted"]
    assert rec["capture_mode"] == "full"


def test_structured_capture_restricted_redacts_payload():
    capture_structured_delegation_outcome(
        surface="s",
        action_intent="i",
        privacy_mode="restricted",
        provider_used="openai",
        model_used="m",
        delegation_tier="strict_secure",
        input_snapshot="secret user text",
        compiled_prompt="prompt",
        validation_passed=True,
        validation_error=None,
        output_payload={"a": 1, "b": 2},
        delegation_path="structured_cloud_v1",
        externalization_mapping_active=True,
    )
    rec = get_learning_buffer().recent(1)[0]
    assert rec["input_snapshot_redacted"] == ""
    assert rec["capture_mode"] == "minimal"
    assert "[redacted]" in rec["model_output_redacted"]
    assert "secret" not in rec["model_output_redacted"]


def test_general_lane_invokes_provider_and_captures():
    def run_provider(p: str) -> str:
        assert "Surface: meeting_prep" in p
        return '{"ok": true}'

    out = run_general_delegation_lane(
        surface="meeting_prep",
        action_intent="summarize_agenda",
        bounded_context="ctx",
        destination_hint="sidebar",
        task_instruction="Summarize.",
        privacy_mode="normal",
        exec_meta={},
        run_provider=run_provider,
        provider_used="openai",
        model_used="x",
        try_parse_json=True,
    )
    assert out["ok"] is True
    assert out["parsed"] == {"ok": True}
    assert out.get("learning_record_id")
    assert update_learning_record_user_outcome(out["learning_record_id"], "applied", privacy_mode="normal")
    rec = get_learning_buffer().recent(1)[0]
    assert rec["delegation_tier"] == "general"
    assert rec["validation_passed"] is True
    assert rec["user_outcome"] == "applied"
    assert rec.get("delegation_path") == "general_lane_v1"


def test_general_lane_json_parse_failure_still_captures():
    run_general_delegation_lane(
        surface="s",
        action_intent="a",
        bounded_context="c",
        destination_hint="d",
        task_instruction="t",
        privacy_mode="normal",
        exec_meta={},
        run_provider=lambda _: "not json",
        try_parse_json=True,
    )
    rec = get_learning_buffer().recent(1)[0]
    assert rec["validation_passed"] is False
    assert rec["validation_error"] == "expected_json_not_found"


def test_compile_general_prompt_stable_prefix():
    p1 = compile_general_delegation_prompt(
        surface="s",
        action_intent="a",
        bounded_context="b",
        destination_hint="d",
        task_instruction="t",
    )
    assert p1.startswith("You are assisting the Atria local-first assistant.")
    assert "Surface: s" in p1


def test_update_user_outcome_drops_diff_under_restricted():
    rid = capture_general_delegation_outcome(
        surface="s",
        action_intent="a",
        privacy_mode="normal",
        provider_used="p",
        model_used="m",
        input_snapshot="x",
        compiled_prompt="p",
        validation_passed=True,
        validation_error=None,
        raw_or_parsed_output="o",
    )
    assert rid
    assert update_learning_record_user_outcome(
        rid,
        "copied",
        outcome_diff_summary="secret diff",
        privacy_mode="restricted",
    )
    rec = get_learning_buffer().recent(1)[0]
    assert rec["user_outcome"] == "copied"
    assert rec.get("outcome_diff_summary") is None


def test_capture_general_local_only_minimal():
    capture_general_delegation_outcome(
        surface="s",
        action_intent="a",
        privacy_mode="local_only",
        provider_used="p",
        model_used="m",
        input_snapshot="secret",
        compiled_prompt="long " * 100,
        validation_passed=True,
        validation_error=None,
        raw_or_parsed_output="model secret out",
    )
    rec = get_learning_buffer().recent(1)[0]
    assert rec["input_snapshot_redacted"] == ""
    assert rec["model_output_redacted"] == "[redacted]"
