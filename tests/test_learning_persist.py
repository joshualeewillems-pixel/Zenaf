"""Append-only JSONL persistence for learning records."""

from __future__ import annotations

import json

import pytest

from local_ai.delegation import learning_capture as LC


@pytest.fixture(autouse=True)
def _reset_persist_and_buffer():
    LC.reset_learning_persistence_for_tests()
    LC.get_learning_buffer().clear()
    yield
    LC.reset_learning_persistence_for_tests()
    LC.get_learning_buffer().clear()


def test_append_and_file_contents(tmp_path, monkeypatch):
    p = tmp_path / "learn.jsonl"
    monkeypatch.setenv("ZENAF_LEARNING_PERSIST_PATH", str(p))
    LC.init_learning_persistence_from_env()
    rid = LC.capture_general_delegation_outcome(
        surface="s",
        action_intent="a1",
        privacy_mode="normal",
        provider_used="openai",
        model_used="m",
        input_snapshot="ctx",
        compiled_prompt="prompt",
        validation_passed=True,
        validation_error=None,
        raw_or_parsed_output="out",
    )
    assert rid
    assert p.is_file()
    lines = p.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    row = json.loads(lines[0])
    assert row["record_id"] == rid
    assert row["action_intent"] == "a1"


def test_replay_last_line_wins_per_record_id(tmp_path, monkeypatch):
    p = tmp_path / "learn.jsonl"
    row1 = {
        "record_id": "abc",
        "ts_ms": 100,
        "action_intent": "x",
        "surface": "s",
        "delegation_tier": "general",
        "provider_used": "p",
        "model_used": "m",
        "validation_passed": True,
        "validation_error": None,
        "input_snapshot_redacted": "",
        "compiled_prompt_sha256_prefix": "",
        "compiled_prompt_char_len": 0,
        "model_output_redacted": "",
        "delegation_path": "general_lane_v1",
        "externalization_mapping_active": False,
        "user_outcome": None,
        "outcome_diff_summary": None,
        "capture_mode": "minimal",
    }
    row2 = {**row1, "ts_ms": 200, "user_outcome": "applied"}
    p.write_text(json.dumps(row1) + "\n" + json.dumps(row2) + "\n", encoding="utf-8")
    monkeypatch.setenv("ZENAF_LEARNING_PERSIST_PATH", str(p))
    LC.init_learning_persistence_from_env()
    buf = LC.get_learning_buffer()
    assert buf.size() == 1
    assert buf.recent(1)[0]["user_outcome"] == "applied"


def test_replay_skips_corrupt_lines(tmp_path, monkeypatch):
    p = tmp_path / "learn.jsonl"
    good = {
        "record_id": "ok1",
        "ts_ms": 50,
        "action_intent": "a",
        "surface": "s",
        "delegation_tier": "general",
        "provider_used": None,
        "model_used": None,
        "validation_passed": True,
        "validation_error": None,
        "input_snapshot_redacted": "",
        "compiled_prompt_sha256_prefix": "",
        "compiled_prompt_char_len": 0,
        "model_output_redacted": "",
        "delegation_path": None,
        "externalization_mapping_active": False,
        "capture_mode": "full",
    }
    p.write_text("not-json\n" + json.dumps(good) + "\n", encoding="utf-8")
    monkeypatch.setenv("ZENAF_LEARNING_PERSIST_PATH", str(p))
    LC.init_learning_persistence_from_env()
    assert LC.get_learning_buffer().size() == 1


def test_user_outcome_appends_second_line(tmp_path, monkeypatch):
    p = tmp_path / "learn.jsonl"
    monkeypatch.setenv("ZENAF_LEARNING_PERSIST_PATH", str(p))
    LC.init_learning_persistence_from_env()
    rid = LC.capture_general_delegation_outcome(
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
    assert LC.update_learning_record_user_outcome(rid, "dismissed", privacy_mode="normal")
    lines = [ln for ln in p.read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert len(lines) == 2
    assert json.loads(lines[1])["user_outcome"] == "dismissed"


def test_rotation_before_append(tmp_path, monkeypatch):
    p = tmp_path / "learn.jsonl"
    # Pre-fill file larger than cap (~0.001 MiB ≈ 1048 bytes)
    p.write_bytes(b"x" * 2000)
    monkeypatch.setenv("ZENAF_LEARNING_PERSIST_PATH", str(p))
    monkeypatch.setenv("ZENAF_LEARNING_PERSIST_MAX_MB", "0.001")
    LC.init_learning_persistence_from_env()
    LC.capture_general_delegation_outcome(
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
    assert p.is_file()
    assert p.stat().st_size < 2000
    rotated = list(tmp_path.glob("*.rotated"))
    assert len(rotated) == 1
