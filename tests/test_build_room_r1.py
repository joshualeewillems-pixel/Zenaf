"""R1 tests: single-model meeting. Generation is mocked — no live API
calls, no real key values anywhere. A fake key value is used to prove
it never leaks into transcripts, artifacts, or usage logs."""

from __future__ import annotations

import json

import pytest

from local_ai.build_room import meeting as meeting_mod
from local_ai.build_room.meeting import Budget, EvidencePacket, run_single_model_meeting
from local_ai.build_room import participants as part_mod

FAKE_KEY = "FAKE-KEY-VALUE-12345"


def _packet() -> EvidencePacket:
    return EvidencePacket(
        work_item="Test work item",
        question="Is this sound?",
        excerpts=("excerpt one",),
        constraints=("keep it small",),
        source_refs=("local_ai/build_room/meeting.py",),
    )


def _fake_resolve_ok(principal, provider_id):
    return FAKE_KEY, "system_env"


def _read(path):
    return path.read_text(encoding="utf-8")


def test_happy_path_persists_transcript_and_draft(monkeypatch, tmp_path):
    monkeypatch.setattr(part_mod, "resolve_cloud_api_key", _fake_resolve_ok)
    seen: dict = {}

    def fake_generate(api_key, prompt, *, model=None, timeout=120):
        seen["api_key"] = api_key
        seen["timeout"] = timeout
        assert "Test work item" in prompt and "Is this sound?" in prompt
        return "Canned deliberation: observed X, proposed Y."

    monkeypatch.setattr(part_mod._openai, "generate", fake_generate)
    result = run_single_model_meeting(_packet(), store_dir=tmp_path)
    assert result.ok is True
    assert seen["api_key"] == FAKE_KEY
    kinds = [e.kind for e in result.transcript.entries]
    assert kinds == ["convene", "contribution"]
    assert result.transcript.entries[1].text == "Canned deliberation: observed X, proposed Y."
    artifact = json.loads(_read(result.artifact_path))
    assert artifact["status"] == "DRAFT_EXPERIMENTAL"
    assert artifact["is_review_item"] is False
    assert artifact["experimental_area"] is True
    assert "RECOMMENDS ONLY" in artifact["authorization"]
    assert artifact["recommendation"] == "Canned deliberation: observed X, proposed Y."
    assert artifact["provenance"]["provider"] == "openai"
    usage = json.loads(_read(tmp_path / "usage.jsonl").strip())
    assert usage["outcome"] == "generated"
    assert usage["key_source"] == "system_env"
    for path in (result.transcript_path, result.artifact_path, tmp_path / "usage.jsonl"):
        assert FAKE_KEY not in _read(path)


def test_absent_key_recorded_not_silent(monkeypatch, tmp_path):
    monkeypatch.setattr(part_mod, "resolve_cloud_api_key", lambda p, pid: (None, "none"))
    calls: list = []
    monkeypatch.setattr(part_mod._openai, "generate", lambda *a, **k: calls.append(1))
    result = run_single_model_meeting(_packet(), store_dir=tmp_path)
    assert result.ok is False
    assert calls == []
    kinds = [e.kind for e in result.transcript.entries]
    assert kinds == ["convene", "absence"]
    artifact = json.loads(_read(result.artifact_path))
    assert artifact["provenance"]["status"] == "absent"
    assert artifact["recommendation"] is None
    usage = json.loads(_read(tmp_path / "usage.jsonl").strip())
    assert usage["outcome"] == "absent" and usage["key_source"] == "none"


def test_budget_zero_blocks_generation(monkeypatch, tmp_path):
    monkeypatch.setattr(part_mod, "resolve_cloud_api_key", _fake_resolve_ok)
    calls: list = []
    monkeypatch.setattr(part_mod._openai, "generate", lambda *a, **k: calls.append(1))
    result = run_single_model_meeting(_packet(), store_dir=tmp_path,
                                      budget=Budget(max_contributions=0))
    assert result.ok is False and calls == []
    assert "budget_exceeded" in result.transcript.entries[-1].text


def test_prompt_too_long_blocks_generation(monkeypatch, tmp_path):
    monkeypatch.setattr(part_mod, "resolve_cloud_api_key", _fake_resolve_ok)
    calls: list = []
    monkeypatch.setattr(part_mod._openai, "generate", lambda *a, **k: calls.append(1))
    result = run_single_model_meeting(_packet(), store_dir=tmp_path,
                                      budget=Budget(max_prompt_chars=10))
    assert result.ok is False and calls == []
    assert "budget_exceeded" in result.transcript.entries[-1].text


def test_generation_failure_recorded_not_raised(monkeypatch, tmp_path):
    monkeypatch.setattr(part_mod, "resolve_cloud_api_key", _fake_resolve_ok)

    def boom(api_key, prompt, *, model=None, timeout=120):
        raise RuntimeError("provider exploded")

    monkeypatch.setattr(part_mod._openai, "generate", boom)
    result = run_single_model_meeting(_packet(), store_dir=tmp_path)
    assert result.ok is False
    assert result.transcript.entries[-1].kind == "failure"
    assert "RuntimeError" in result.transcript.entries[-1].text
    artifact = json.loads(_read(result.artifact_path))
    assert artifact["failure"] is not None


def test_timeout_passed_through(monkeypatch, tmp_path):
    monkeypatch.setattr(part_mod, "resolve_cloud_api_key", _fake_resolve_ok)
    seen: dict = {}

    def fake_generate(api_key, prompt, *, model=None, timeout=120):
        seen["timeout"] = timeout
        return "ok"

    monkeypatch.setattr(part_mod._openai, "generate", fake_generate)
    run_single_model_meeting(_packet(), store_dir=tmp_path,
                             budget=Budget(timeout_seconds=42))
    assert seen["timeout"] == 42


def test_packet_immutable_and_rendered():
    packet = _packet()
    with pytest.raises(Exception):
        packet.work_item = "mutated"
    rendered = packet.render_prompt()
    for needle in ("Test work item", "Is this sound?", "excerpt one",
                   "keep it small", "local_ai/build_room/meeting.py"):
        assert needle in rendered


def test_participant_repr_hides_key(monkeypatch):
    monkeypatch.setattr(part_mod, "resolve_cloud_api_key", _fake_resolve_ok)
    participant, note = part_mod.resolve_openai_participant()
    assert participant is not None and note == ""
    assert FAKE_KEY not in repr(participant)
    present, source = part_mod.check_openai_key_present()
    assert present is True and source == "system_env"
