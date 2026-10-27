"""Tool-access stage-1 increment B tests: GPT channel + read_file loop.

Harness tests over temp snapshot directories plus full-meeting runs
with fake seats. No live API calls, no real key values, no staging
access. The Fly workflow patch is NOT needed for any test here (the
snapshot is built locally); staging confirmation of the deployed
snapshot is a separate, post-merge item in the PR report.

Injection guarantee under test (stated narrowly): structured calling
stops the runner mistaking text for a request. It does NOT stop a
model being influenced by file text — no test here claims that.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from local_ai.build_room import tool_access
from local_ai.build_room.meeting import (
    EvidencePacket,
    run_multi_model_meeting,
)
from local_ai.build_room.participants import Seat
from local_ai.build_room.tool_access import (
    ToolLoopContext,
    execute_read_file,
    normalize_snapshot_path,
    parse_structured_tool_call,
    run_tool_loop,
    tools_prompt_section,
)
from local_ai.build_room.tool_snapshot import (
    build_snapshot,
    load_manifest,
    sha256_file,
)

COMMIT = "a" * 40
TARGET_LINES = [f"line {i} of target" for i in range(1, 11)]
TARGET_TEXT = "\n".join(TARGET_LINES) + "\n"


@pytest.fixture()
def snap_dir(tmp_path: Path) -> Path:
    """A real snapshot built from a small source tree."""
    src = tmp_path / "local_ai"
    (src / "build_room").mkdir(parents=True)
    (src / "build_room" / "target.py").write_text(TARGET_TEXT, encoding="utf-8")
    (src / "build_room" / "other.py").write_text("other = 1\n", encoding="utf-8")
    (src / "build_room" / "big.py").write_text(
        "".join(f"big line {i:04d} " + "x" * 90 + "\n" for i in range(120)),
        encoding="utf-8",
    )
    (src / "llm").mkdir()
    (src / "llm" / "credentials.py").write_text(
        "KEY_NAME = 'OPENAI_API_KEY'\n", encoding="utf-8"
    )
    dest = tmp_path / "tool_snapshot"
    build_snapshot(src, dest, COMMIT)
    return dest


@pytest.fixture()
def ctx(snap_dir: Path) -> ToolLoopContext:
    return ToolLoopContext(
        nominated_paths=frozenset({
            "build_room/target.py",
            "build_room/big.py",
            "llm/credentials.py",
        }),
        snapshot_dir=snap_dir,
        manifest=load_manifest(snap_dir),
        revision=COMMIT,
    )


# ---------------------------------------------------------------------------
# Path normalization + strict schema parsing
# ---------------------------------------------------------------------------

def test_normalize_snapshot_path_strips_repo_prefix_forms():
    assert normalize_snapshot_path("local_ai/build_room/target.py") == "build_room/target.py"
    assert normalize_snapshot_path("./build_room/target.py") == "build_room/target.py"
    assert normalize_snapshot_path("/build_room/target.py") == "build_room/target.py"
    assert normalize_snapshot_path("build_room/target.py") == "build_room/target.py"


def test_parse_rejects_unknown_tool_and_unknown_keys():
    call, reason = parse_structured_tool_call(
        {"id": "c1", "name": "search_code", "arguments": {"query": "x"}}, 0)
    assert call is None and "unknown_tool" in reason
    call, reason = parse_structured_tool_call(
        {"id": "c1", "name": "read_file",
         "arguments": {"path": "a.py", "bogus": 1}}, 0)
    assert call is None and "malformed_arguments" in reason


def test_parse_rejects_bad_ranges_and_non_json_arguments():
    call, reason = parse_structured_tool_call(
        {"id": "c1", "name": "read_file",
         "arguments": {"path": "a.py", "line_start": 5, "line_end": 2}}, 0)
    assert call is None and "malformed_arguments" in reason
    call, reason = parse_structured_tool_call(
        {"id": "c1", "name": "read_file", "arguments_raw": "{not json"}, 0)
    assert call is None and "malformed_arguments" in reason
    call, reason = parse_structured_tool_call(
        {"id": "c1", "name": "read_file",
         "arguments": {"path": "a.py", "line_start": 2, "line_end": 4}}, 0)
    assert call is not None and reason is None
    assert (call.path, call.line_start, call.line_end) == ("a.py", 2, 4)


# ---------------------------------------------------------------------------
# execute_read_file: the harness cases
# ---------------------------------------------------------------------------

def test_in_root_nominated_read_ok(ctx: ToolLoopContext):
    result = execute_read_file(ctx, "build_room/target.py", 2, 4)
    assert result.outcome == "returned"
    assert result.text == "\n".join(TARGET_LINES[1:4])
    assert result.lines == "2-4"
    assert result.rel_path == "build_room/target.py"
    assert result.revision == COMMIT
    assert result.truncated is False


def test_read_with_repo_prefixed_path_ok(ctx: ToolLoopContext):
    result = execute_read_file(ctx, "local_ai/build_room/target.py", 1, 1)
    assert result.outcome == "returned"
    assert result.text == "line 1 of target"


def test_not_in_manifest_refused(ctx: ToolLoopContext):
    result = execute_read_file(ctx, "build_room/nope.py", None, None)
    assert result.outcome == "refused"
    assert "not_found" in (result.reason or "")


def test_traversal_attempt_refused(ctx: ToolLoopContext):
    result = execute_read_file(ctx, "build_room/../../etc/passwd", None, None)
    assert result.outcome == "refused"


def test_symlink_escape_refused(tmp_path: Path, ctx: ToolLoopContext):
    outside = tmp_path / "outside.txt"
    outside.write_text("secret outside\n", encoding="utf-8")
    link = ctx.snapshot_dir / "escape.py"
    link.symlink_to(outside)
    manifest = load_manifest(ctx.snapshot_dir)
    manifest["allowlist"] = sorted(set(manifest["allowlist"]) | {"escape.py"})
    manifest["files"]["escape.py"] = sha256_file(link)
    (ctx.snapshot_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    ctx2 = ToolLoopContext(
        nominated_paths=ctx.nominated_paths,
        snapshot_dir=ctx.snapshot_dir,
        manifest=load_manifest(ctx.snapshot_dir),
        revision=COMMIT,
    )
    result = execute_read_file(ctx2, "escape.py", None, None)
    assert result.outcome == "refused"
    assert "escape_refused" in (result.reason or "")


def test_denylisted_refused(tmp_path: Path, ctx: ToolLoopContext):
    planted = ctx.snapshot_dir / "secrets.yaml"
    planted.write_text("token: abc\n", encoding="utf-8")
    manifest = load_manifest(ctx.snapshot_dir)
    manifest["allowlist"] = sorted(set(manifest["allowlist"]) | {"secrets.yaml"})
    manifest["files"]["secrets.yaml"] = sha256_file(planted)
    (ctx.snapshot_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    ctx2 = ToolLoopContext(
        nominated_paths=ctx.nominated_paths,
        snapshot_dir=ctx.snapshot_dir,
        manifest=load_manifest(ctx.snapshot_dir),
        revision=COMMIT,
    )
    result = execute_read_file(ctx2, "secrets.yaml", None, None)
    assert result.outcome == "refused"
    assert "denylisted" in (result.reason or "")


def test_credential_code_file_stays_readable(ctx: ToolLoopContext):
    # Increment-A judgment call: code that HANDLES keys is not key
    # material. A credentials.py module must remain verifiable.
    result = execute_read_file(ctx, "llm/credentials.py", None, None)
    assert result.outcome == "returned"
    assert "OPENAI_API_KEY" in (result.text or "")


def test_oversize_truncated_with_flag(ctx: ToolLoopContext):
    result = execute_read_file(ctx, "build_room/big.py", None, None)
    assert result.outcome == "returned"
    assert result.truncated is True
    assert result.chars == 4000
    assert len(result.text or "") == 4000


def test_line_range_beyond_end_refused(ctx: ToolLoopContext):
    result = execute_read_file(ctx, "build_room/target.py", 99, None)
    assert result.outcome == "refused"
    assert "line_range_out_of_range" in (result.reason or "")


def test_tools_prompt_section_names_mode_and_paths(ctx: ToolLoopContext):
    section = tools_prompt_section(sorted(ctx.nominated_paths), COMMIT)
    assert "packet-named-path" in section
    assert "build_room/target.py" in section
    assert "path@revision:lines" in section
    assert "not_inspected" in section
    assert COMMIT in section


# ---------------------------------------------------------------------------
# run_tool_loop with scripted seats
# ---------------------------------------------------------------------------

class ScriptedToolSeat:
    """Fake GPT seat: scripted structured responses, in order."""

    key_source = "test"
    model = "fake-model"

    def __init__(self, script: list[dict]):
        self.script = list(script)
        self.calls: list[dict] = []

    def generate_structured(self, messages, *, tools, timeout: int = 120):
        self.calls.append({"messages": messages, "tools": tools})
        if self.script:
            return self.script.pop(0)
        return {"content": "1. Observed: fallback.", "tool_calls": []}

    def generate(self, prompt: str, *, timeout: int = 120) -> str:
        return "1. Observed: packet-only fallback."


def _tool_call(call_id: str, path: str, line_start=None, line_end=None):
    args: dict = {"path": path}
    if line_start is not None:
        args["line_start"] = line_start
    if line_end is not None:
        args["line_end"] = line_end
    return {"id": call_id, "name": "read_file", "arguments": args}


def test_loop_happy_path_returns_text_and_returned_entry(ctx: ToolLoopContext):
    seat = ScriptedToolSeat([
        {"content": None, "tool_calls": [
            _tool_call("c1", "build_room/target.py", 1, 3)]},
        {"content": f"1. Observed: target says lines 1-3, cited "
                    f"build_room/target.py@{COMMIT}:1-3.",
         "tool_calls": []},
    ])
    text, error, entries = run_tool_loop(
        seat, "prompt", ctx, phase="opening", participant_name="GPT")
    assert error is None
    assert text is not None and "build_room/target.py" in text
    assert len(entries) == 1
    entry = entries[0]
    assert entry["outcome"] == "returned"
    assert entry["resolved_path"] == "build_room/target.py"
    assert entry["lines"] == "1-3"
    assert entry["revision"] == COMMIT
    assert entry["chars"] > 0


def test_loop_text_that_looks_like_a_call_is_not_a_call(ctx: ToolLoopContext):
    seat = ScriptedToolSeat([
        {"content": "1. Observed: call read_file(build_room/target.py) here.",
         "tool_calls": []},
    ])
    text, error, entries = run_tool_loop(
        seat, "prompt", ctx, phase="opening", participant_name="GPT")
    assert error is None
    assert entries == []
    assert "read_file" in (text or "")


def test_loop_unnamed_path_refused_and_refusal_counts(ctx: ToolLoopContext):
    # First call is unnamed (in manifest, not nominated) and refused;
    # it consumes budget, so the 5th call in the same response caps.
    seat = ScriptedToolSeat([
        {"content": None, "tool_calls": [
            _tool_call("c1", "build_room/other.py", 1, 1),
            _tool_call("c2", "build_room/target.py", 1, 1),
            _tool_call("c3", "build_room/target.py", 2, 2),
            _tool_call("c4", "build_room/target.py", 3, 3),
            _tool_call("c5", "build_room/target.py", 4, 4),
        ]},
    ])
    text, error, entries = run_tool_loop(
        seat, "prompt", ctx, phase="opening", participant_name="GPT")
    outcomes = [e["outcome"] for e in entries]
    assert outcomes == ["refused", "returned", "returned", "returned", "capped"]
    assert "not_nominated" in (entries[0]["reason"] or "")
    assert error is not None and "budget" in error


def test_loop_round_cap_exceeded(ctx: ToolLoopContext):
    script = [
        {"content": None, "tool_calls": [
            _tool_call(f"c{i}", "build_room/target.py", 1, 1)]}
        for i in range(10)
    ]
    seat = ScriptedToolSeat(script)
    text, error, entries = run_tool_loop(
        seat, "prompt", ctx, phase="opening", participant_name="GPT")
    assert text is None
    assert error is not None and "round_cap" in error
    assert len(entries) == 4  # round cap, not the 10 scripted rounds


def test_loop_provider_error_is_recorded_not_raised(ctx: ToolLoopContext):
    class BoomSeat:
        def generate_structured(self, messages, *, tools, timeout: int = 120):
            raise RuntimeError("provider down")

    text, error, entries = run_tool_loop(
        BoomSeat(), "prompt", ctx, phase="opening", participant_name="GPT")
    assert text is None
    assert error is not None and "tool_loop_error" in error
    assert entries == []


def test_loop_timeout_is_recorded(ctx: ToolLoopContext):
    class SlowSeat:
        def generate_structured(self, messages, *, tools, timeout: int = 120):
            time.sleep(1.2)
            return {"content": None, "tool_calls": [
                _tool_call("c1", "build_room/target.py", 1, 1)]}

    text, error, entries = run_tool_loop(
        SlowSeat(), "prompt", ctx, phase="opening", participant_name="GPT",
        timeout_seconds=1)
    assert text is None
    assert error is not None and "timeout" in error


# ---------------------------------------------------------------------------
# Full meetings with fake seats
# ---------------------------------------------------------------------------

class FakeSeat:
    """Packet-only fake: generate() only, no structured channel."""

    key_source = "test"
    model = "fake-model"

    def __init__(self, text: str):
        self.text = text
        self.prompts: list[str] = []

    def generate(self, prompt: str, *, timeout: int = 120) -> str:
        self.prompts.append(prompt)
        return self.text


class FakeToolSeat(ScriptedToolSeat):
    """Fake GPT seat: structured channel + generate() fallback."""

    def __init__(self, script: list[dict]):
        super().__init__(script)
        self.prompts: list[str] = []

    def generate(self, prompt: str, *, timeout: int = 120) -> str:
        self.prompts.append(prompt)
        return "1. Observed: packet-only fallback."


def _seats(gpt_fake, others_text="1. Observed: other claim."):
    seats = [Seat(name="GPT", provider_id="openai", model="gpt-4o-mini",
                  participant=gpt_fake)]
    for name, provider_id, model in (
        ("Claude", "anthropic", "claude-haiku-4-5"),
        ("Gemini", "google", "gemini-3.8-flash"),
        ("Grok", "xai", "grok-4-1-fast-reasoning"),
        ("Muse", "meta", "muse-spark-1.3"),
    ):
        seats.append(Seat(name=name, provider_id=provider_id, model=model,
                          participant=FakeSeat(others_text)))
    return seats


def _packet():
    return EvidencePacket(work_item="Check target", question="What does it say?")


def test_meeting_tool_enabled_end_to_end(snap_dir: Path, tmp_path: Path):
    gpt = FakeToolSeat([
        {"content": None, "tool_calls": [
            _tool_call("c1", "build_room/target.py", 1, 3)]},
        {"content": "1. Observed: target lines 1-3 verified.",
         "tool_calls": []},
    ])
    result = run_multi_model_meeting(
        _packet(), store_dir=tmp_path / "store", seats=_seats(gpt),
        tools_enabled=True,
        nominated_paths=["build_room/target.py"],
        snapshot_dir=snap_dir,
        deployed_version=COMMIT,
    )
    tool_access = result.artifact["tool_access"]
    assert tool_access["enabled"] is True
    assert tool_access["tool_capable_seats"] == ["GPT"]
    assert tool_access["packet_only_seats"] == ["Claude", "Gemini", "Grok", "Muse"]
    assert tool_access["nominated_paths"] == ["build_room/target.py"]
    assert tool_access["revision"] == COMMIT
    assert len(tool_access["tool_calls"]) >= 1
    assert tool_access["tool_calls"][0]["outcome"] == "returned"
    kinds = [e.kind for e in result.transcript.entries]
    assert "tool_call" in kinds
    convene_notes = [e.text for e in result.transcript.entries
                     if e.kind == "note" and "Tool access enabled" in e.text]
    assert convene_notes and "packet-only" in convene_notes[0]
    # The GPT prompt carried the tools section; other seats never saw it.
    assert gpt.calls and "read_file" in gpt.calls[0]["messages"][0]["content"]
    assert gpt.calls[0]["messages"][0]["content"].count("build_room/target.py") >= 1
    # Record-completeness still holds with tool entries in the record.
    assert result.artifact["record_completeness"]["passed"] is True
    assert result.ok is True


def test_meeting_tools_section_not_shown_to_packet_only_seats(
        snap_dir: Path, tmp_path: Path):
    gpt = FakeToolSeat([
        {"content": "1. Observed: no tools needed.", "tool_calls": []},
    ])
    seats = _seats(gpt)
    run_multi_model_meeting(
        _packet(), store_dir=tmp_path / "store", seats=seats,
        tools_enabled=True,
        nominated_paths=["build_room/target.py"],
        snapshot_dir=snap_dir,
        deployed_version=COMMIT,
    )
    for seat in seats[1:]:
        assert seat.participant is not None
        for prompt in seat.participant.prompts:
            assert "Tool verification" not in prompt


def test_meeting_snapshot_failure_disables_tools_packet_only(
        tmp_path: Path):
    gpt = FakeToolSeat([
        {"content": "1. Observed: never used.", "tool_calls": []},
    ])
    result = run_multi_model_meeting(
        _packet(), store_dir=tmp_path / "store", seats=_seats(gpt),
        tools_enabled=True,
        nominated_paths=["build_room/target.py"],
        snapshot_dir=tmp_path / "no-such-snapshot",
        deployed_version=COMMIT,
    )
    tool_access = result.artifact["tool_access"]
    assert tool_access["enabled"] is False
    assert tool_access["reason"] == "snapshot-missing"
    assert tool_access["tool_calls"] == []
    assert gpt.calls == []  # no structured call was ever attempted
    assert not any(e.kind == "tool_call" for e in result.transcript.entries)
    assert result.ok is True  # packet-only meeting still completes


def test_meeting_flag_off_is_default_and_never_calls_structured(
        snap_dir: Path, tmp_path: Path):
    gpt = FakeToolSeat([
        {"content": "1. Observed: never used.", "tool_calls": []},
    ])
    result = run_multi_model_meeting(
        _packet(), store_dir=tmp_path / "store", seats=_seats(gpt),
        snapshot_dir=snap_dir,
        deployed_version=COMMIT,
    )
    assert result.artifact["tool_access"]["enabled"] is False
    assert gpt.calls == []
    assert not any(e.kind == "tool_call" for e in result.transcript.entries)


def test_participant_structured_channel_only_for_openai_seat():
    from local_ai.build_room.participants import SeatParticipant

    gpt = SeatParticipant("GPT", "openai", "key", model="gpt-4o-mini")
    other = SeatParticipant("Claude", "anthropic", "key", model="claude-haiku-4-5")
    assert hasattr(gpt, "generate_structured")
    assert not hasattr(other, "generate_structured")


# ---------------------------------------------------------------------------
# Increment C: citation validation (mark, never strip)
# ---------------------------------------------------------------------------

from local_ai.build_room.citation_validation import (
    find_tool_citations,
    validate_tool_citations,
)
from local_ai.build_room.measurement import summarize_tool_round_usage
from local_ai.build_room.tool_access import ToolLoopBudgets


def _returned_entry(path, revision, lines):
    return {
        "phase": "opening", "participant": "GPT", "tool": "read_file",
        "requested_path": path, "resolved_path": path, "revision": revision,
        "lines": lines, "chars": 10, "truncated": False, "duration_s": 0.01,
        "outcome": "returned", "reason": None,
    }


def test_find_tool_citations_parses_range_and_single_line():
    found = find_tool_citations(
        "see build_room/target.py@abc123:2-4 and other.py@abc123:7.")
    assert [(f["path"], f["line_start"], f["line_end"]) for f in found] == [
        ("build_room/target.py", 2, 4), ("other.py", 7, 7)]
    assert find_tool_citations("no citations here") == []
    # Email-like text is not a citation: the revision group is
    # alphanumeric-only, so a dotted domain cannot match.
    assert find_tool_citations("mail me at joe@example.com:9") == []


def test_citation_grounded_on_subset_and_repo_prefixed_path():
    entries = [_returned_entry("build_room/target.py", COMMIT, "1-10")]
    anns = validate_tool_citations(
        "per local_ai/build_room/target.py@" + COMMIT + ":2-4.", entries)
    assert len(anns) == 1
    assert anns[0]["status"] == "grounded" and anns[0]["reason"] is None


def test_citation_over_range_wrong_revision_refused_unverified():
    entries = [_returned_entry("build_room/target.py", COMMIT, "1-3")]
    anns = validate_tool_citations(
        "a build_room/target.py@" + COMMIT + ":2-9 "
        "b build_room/target.py@" + "b" * 40 + ":1-2 "
        "c build_room/other.py@" + COMMIT + ":1-1.", entries)
    assert [a["status"] for a in anns] == ["unverified"] * 3
    assert [a["reason"] for a in anns] == [
        "range_not_covered", "revision_mismatch", "no_matching_returned_read"]


def test_citation_refused_or_capped_entries_never_ground():
    refused = dict(_returned_entry("build_room/target.py", COMMIT, "1-3"))
    refused["outcome"] = "refused"
    refused["reason"] = "not_nominated: path is outside the nominated set"
    refused["resolved_path"] = None
    capped = dict(_returned_entry("build_room/target.py", COMMIT, "1-3"))
    capped["outcome"] = "capped"
    anns = validate_tool_citations(
        "x build_room/target.py@" + COMMIT + ":1-2.", [refused, capped])
    assert anns[0]["status"] == "unverified"
    assert anns[0]["reason"] == "no_matching_returned_read"
    assert validate_tool_citations(
        "x build_room/target.py@" + COMMIT + ":1-2.", [])[0]["status"] == "unverified"


# ---------------------------------------------------------------------------
# Increment C: cumulative budgets (pure accounting)
# ---------------------------------------------------------------------------

def test_budgets_reserve_and_result_and_tripwire_boundaries():
    budgets = ToolLoopBudgets(
        turn_input_token_budget=60000, reserve_fraction=0.75,
        aggregate_result_token_budget=2000, round_token_tripwire=6000)
    assert budgets.reserve_limit == 45000
    assert budgets.request_fits(45000) is True
    assert budgets.request_fits(45001) is False
    budgets.record_request(45000)
    assert budgets.request_fits(1) is False
    assert budgets.result_fits(2000) is True
    assert budgets.result_fits(2001) is False
    assert budgets.round_tripwire_hit(3000, 3000) is False
    assert budgets.round_tripwire_hit(3000, 3001) is True


def _len_counter(text: str):
    return len(text), "test"


def _ctx_with(ctx: ToolLoopContext, **overrides) -> ToolLoopContext:
    import dataclasses

    return dataclasses.replace(ctx, **overrides)


def test_loop_aggregate_result_token_budget_withholds_delivery(
        ctx: ToolLoopContext):
    ctx2 = _ctx_with(
        ctx, aggregate_result_token_budget=50, token_counter=_len_counter)
    seat = ScriptedToolSeat([
        {"content": None, "tool_calls": [
            _tool_call("c1", "build_room/target.py", 1, 3)]},
        {"content": "1. Observed: delivery withheld, still final.",
         "tool_calls": []},
    ])
    text, error, entries = run_tool_loop(
        seat, "prompt", ctx2, phase="opening", participant_name="GPT")
    assert error is None
    assert text is not None and "still final" in text
    assert entries[0]["outcome"] == "refused"
    assert "aggregate_token_budget_exceeded" in (entries[0]["reason"] or "")


def test_loop_per_call_timeout_refuses_pathological_read(
        ctx: ToolLoopContext):
    ctx2 = _ctx_with(ctx, per_call_timeout_seconds=0)
    seat = ScriptedToolSeat([
        {"content": None, "tool_calls": [
            _tool_call("c1", "build_room/target.py", 1, 1)]},
        {"content": "1. Observed: read refused on time, still final.",
         "tool_calls": []},
    ])
    text, error, entries = run_tool_loop(
        seat, "prompt", ctx2, phase="opening", participant_name="GPT")
    assert error is None
    assert entries[0]["outcome"] == "refused"
    assert "tool_call_timeout" in (entries[0]["reason"] or "")


def test_loop_reserve_forces_final_text(ctx: ToolLoopContext):
    ctx2 = _ctx_with(
        ctx, turn_input_token_budget=60, reserve_fraction=0.75,
        token_counter=_len_counter)
    seat = ScriptedToolSeat([
        {"content": "draft final", "tool_calls": [
            _tool_call("c1", "build_room/target.py", 1, 1)]},
        {"content": "1. Observed: should never be reached.", "tool_calls": []},
    ])
    text, error, entries = run_tool_loop(
        seat, "prompt", ctx2, phase="opening", participant_name="GPT")
    assert error is None
    assert text == "draft final"
    assert len(seat.calls) == 1  # second request never sent


def test_loop_reserve_without_final_text_is_budget_failure(
        ctx: ToolLoopContext):
    ctx2 = _ctx_with(
        ctx, turn_input_token_budget=60, reserve_fraction=0.75,
        token_counter=_len_counter)
    seat = ScriptedToolSeat([
        {"content": None, "tool_calls": [
            _tool_call("c1", "build_room/target.py", 1, 1)]},
    ])
    text, error, entries = run_tool_loop(
        seat, "prompt", ctx2, phase="opening", participant_name="GPT")
    assert text is None
    assert error is not None and "participant_turn_input_budget_exceeded" in error


def test_loop_round_tripwire_fires_and_records(ctx: ToolLoopContext):
    sink: list = []
    ctx2 = _ctx_with(
        ctx, round_token_tripwire=10, token_counter=_len_counter,
        usage_sink=sink)
    seat = ScriptedToolSeat([
        {"content": "short", "tool_calls": [
            _tool_call("c1", "build_room/target.py", 1, 1)]},
        {"content": "1. Observed: should never be reached.", "tool_calls": []},
    ])
    text, error, entries = run_tool_loop(
        seat, "prompt", ctx2, phase="opening", participant_name="GPT")
    assert error is None
    assert text == "short"
    assert len(sink) == 1
    assert sink[0]["tripwire_fired"] is True
    assert sink[0]["tripwire"]["round_total_tokens"] > 10


def test_loop_wall_clock_ceiling_binds_tighter_than_timeout(
        ctx: ToolLoopContext):
    class SlowSeat:
        def generate_structured(self, messages, *, tools, timeout: int = 120):
            time.sleep(1.2)
            return {"content": None, "tool_calls": [
                _tool_call("c1", "build_room/target.py", 1, 1)]}

    ctx2 = _ctx_with(ctx, wall_clock_ceiling_seconds=1)
    text, error, entries = run_tool_loop(
        SlowSeat(), "prompt", ctx2, phase="opening", participant_name="GPT",
        timeout_seconds=120)
    assert text is None
    assert error is not None and "timeout" in error


def test_loop_usage_record_keyed_by_generation(ctx: ToolLoopContext):
    sink: list = []
    ctx2 = _ctx_with(ctx, usage_sink=sink, token_counter=_len_counter)
    seat = ScriptedToolSeat([
        {"content": None, "tool_calls": [
            _tool_call("c1", "build_room/target.py", 1, 3)]},
        {"content": "1. Observed: done.", "tool_calls": []},
    ])
    text, error, entries = run_tool_loop(
        seat, "prompt", ctx2, phase="opening", participant_name="GPT")
    assert error is None
    assert len(sink) == 1
    record = sink[0]
    assert (record["phase"], record["participant"]) == ("opening", "GPT")
    assert record["generations"] == 1
    assert record["structured_requests"] == 2
    assert record["tool_invocations"] == 1
    assert record["tool_calls_returned"] == 1
    assert record["cumulative_input_tokens"] > 0
    assert record["max_single_request_input_tokens"] > 0
    assert record["outcome"] == "final_text"


def test_summarize_tool_round_usage_states_separately():
    summary = summarize_tool_round_usage([
        {"structured_requests": 2, "tool_invocations": 1,
         "tool_calls_returned": 1, "tool_calls_refused": 0,
         "tool_calls_capped": 0, "cumulative_input_tokens": 100,
         "cumulative_output_tokens": 50, "max_single_request_input_tokens": 80,
         "aggregate_result_tokens": 40, "tripwire_fired": True},
        {"structured_requests": 1, "tool_invocations": 0,
         "tool_calls_returned": 0, "tool_calls_refused": 0,
         "tool_calls_capped": 0, "cumulative_input_tokens": 30,
         "cumulative_output_tokens": 10, "max_single_request_input_tokens": 30,
         "aggregate_result_tokens": 0, "tripwire_fired": False},
    ])
    assert summary["generations_with_tool_loops"] == 2
    assert summary["structured_requests"] == 3
    assert summary["tool_invocations"] == 1
    assert summary["cumulative_input_tokens"] == 130
    assert summary["max_single_request_input_tokens"] == 80
    assert summary["tripwire_fired_count"] == 1
    assert summarize_tool_round_usage([])["generations_with_tool_loops"] == 0


def test_tools_prompt_section_states_narrow_guarantee_and_scope_rule(
        ctx: ToolLoopContext):
    section = tools_prompt_section(sorted(ctx.nominated_paths), COMMIT)
    assert "stops the runner mistaking text for a request" in section
    assert "does NOT stop" in section
    assert "verified_present" in section
    assert "not_found_within_scope" in section
    assert "without its cited scope is not_inspected" in section
    assert "checked against the tool-call log" in section
    assert "marked unverified" in section
    assert "4 tool rounds" in section


# ---------------------------------------------------------------------------
# Increment C: meeting-level citation validation + usage reporting
# ---------------------------------------------------------------------------

def test_meeting_citation_validation_marks_not_strips(
        snap_dir: Path, tmp_path: Path):
    grounded = f"build_room/target.py@{COMMIT}:1-2"
    over_range = f"build_room/target.py@{COMMIT}:4-5"
    gpt = FakeToolSeat([
        {"content": None, "tool_calls": [
            _tool_call("c1", "build_room/target.py", 1, 3)]},
        {"content": "1. Observed: lines 1-2 per " + grounded
                    + ", and lines 4-5 per " + over_range + ".",
         "tool_calls": []},
    ])
    result = run_multi_model_meeting(
        _packet(), store_dir=tmp_path / "store", seats=_seats(gpt),
        tools_enabled=True,
        nominated_paths=["build_room/target.py"],
        snapshot_dir=snap_dir,
        deployed_version=COMMIT,
    )
    opening = [i for i in result.artifact["interactions"]
               if i["participant"] == "GPT" and i["phase"] == "opening"][0]
    statuses = {a["citation"]: a["status"]
                for a in opening["tool_citations"]}
    assert statuses[grounded] == "grounded"
    assert statuses[over_range] == "unverified"
    assert opening["grounded_tool_citations"] == 1
    assert opening["unverified_tool_citations"] == 1
    totals = result.artifact["tool_access"]["citation_validation"]
    assert totals["grounded"] == 1 and totals["unverified"] == 1
    # Mark, never strip: the registry claim text still carries BOTH
    # citations verbatim.
    claim_texts = [c["text"] for c in result.artifact["claim_registry"]
                   if c["participant"] == "GPT" and c["phase"] == "opening"]
    assert claim_texts and grounded in claim_texts[0]
    assert over_range in claim_texts[0]
    notes = [e.text for e in result.transcript.entries
             if e.kind == "note" and "Tool citations:" in e.text]
    assert notes and "grounded" in notes[0] and "unverified" in notes[0]
    # Usage states generations and tool-round calls separately.
    usage = result.artifact["tool_access"]["usage"]
    assert usage["generations_with_tool_loops"] == 2  # opening + response
    assert usage["structured_requests"] >= 3
    assert usage["tool_invocations"] >= 1
    assert result.artifact["record_completeness"]["passed"] is True
    assert result.ok is True
    # The generation's usage.jsonl row carries its tool record,
    # keyed by generation — not "unavailable".
    rows = [json.loads(line) for line in
            (tmp_path / "store" / "usage.jsonl").read_text(
                encoding="utf-8").splitlines()]
    gpt_opening = [r for r in rows if r["participant"] == "GPT"
                   and r["phase"] == "opening"
                   and r["outcome"] == "generated"]
    assert gpt_opening and isinstance(gpt_opening[0]["token_usage"], dict)
    assert gpt_opening[0]["token_usage"]["tool_calls_returned"] == 1
