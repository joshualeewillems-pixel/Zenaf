"""Moneyball role-only comparison build tests. OFFLINE ONLY.

No live API calls, no real key values, no provider spending, no
meeting runs against real models anywhere in this file. Meetings
run through fake participants; the program runner runs through a
stub meeting function. What these tests prove is the build
machinery: brief injection is the only per-seat difference,
Phase 1 base prompts are byte-identical across conditions, the cap
runner enforces real allocations with a persistent ledger, and the
evaluation machinery strips labels and counts grouped contributions
once.
"""

from __future__ import annotations

import hashlib
import json
from types import SimpleNamespace

import pytest

from local_ai.build_room import comparison_eval as eval_mod
from local_ai.build_room.meeting import (
    EvidencePacket,
    run_multi_model_meeting,
)
from local_ai.build_room.participants import SEAT_SPECS, Seat
from local_ai.build_room.program_runner import (
    MeetingSpec,
    ProgramLedger,
    allocation_for,
    build_meeting_capture,
    committed_from_cap_budget,
    pricing_expired,
    reserve_needed,
    run_program,
)
from local_ai.build_room.role_briefs import (
    BRIEFED_SEATS,
    ROLE_BRIEF_VERSION,
    ROLE_BRIEFS,
    UNBRIEFED_SEATS,
    role_prompt_extras,
)

FAKE_KEY = "FAKE-KEY-MONEYBALL-12345"
NAMES = [name for name, _, _ in SEAT_SPECS]


class FakeParticipant:
    """Duck-typed seat participant: generate(prompt, timeout=...)."""

    def __init__(self, name, *, opening="", response=""):
        self.name = name
        self.provider_id = dict((n, p) for n, p, _ in SEAT_SPECS)[name]
        self.model = "fake-model"
        self.key_source = "settings"
        self._texts = {"response": response, "opening": opening}
        self.prompts: list[str] = []

    def generate(self, prompt, *, timeout=120):
        self.prompts.append(prompt)
        if "Claim registry" in prompt:
            return self._texts["response"]
        return self._texts["opening"]


def _packet() -> EvidencePacket:
    return EvidencePacket(
        work_item="Test work item",
        question="What would make the room fail as a council?",
        excerpts=("excerpt one",),
        constraints=("room deliberates, never decides",),
        source_refs=("local_ai/build_room/meeting.py",),
    )


def _seats(fakes):
    seats = []
    for name, provider_id, model in SEAT_SPECS:
        fake = fakes.get(name, FakeParticipant(name, opening="1. Observed: A stable fact."))
        seats.append(Seat(name, provider_id, model, fake))
    return seats, fakes


def _run_meeting(tmp_path, subdir, extras, fakes):
    seats, _ = _seats(fakes)
    return run_multi_model_meeting(
        _packet(), store_dir=tmp_path / subdir, seats=seats,
        role_prompt_extras=extras, role_brief_version=ROLE_BRIEF_VERSION,
    )


# --- Role briefs ---

def test_role_briefs_cover_four_seats_and_not_gpt():
    assert set(ROLE_BRIEFS) == set(BRIEFED_SEATS)
    assert set(UNBRIEFED_SEATS) == {"GPT"}
    assert "GPT" not in ROLE_BRIEFS
    extras = role_prompt_extras()
    assert set(extras) == set(BRIEFED_SEATS)
    for name, section in extras.items():
        assert section.startswith("\n\n")
        assert section.strip() == ROLE_BRIEFS[name]
    # No identity wording: a brief says what to DO, never what to BE.
    for brief in ROLE_BRIEFS.values():
        assert "you are the" not in brief.lower()
        assert "you are an" not in brief.lower()
    assert ROLE_BRIEF_VERSION


# --- Injection: the role-only guarantee, end to end ---

def test_brief_injection_is_only_per_seat_difference(tmp_path):
    fakes_a = {n: FakeParticipant(n, opening="1. Observed: A stable fact.",
                                   response="No further comment.")
               for n in NAMES}
    fakes_b = {n: FakeParticipant(n, opening="1. Observed: A stable fact.",
                                   response="No further comment.")
               for n in NAMES}
    result_a = _run_meeting(tmp_path, "store_a", None, fakes_a)
    result_b = _run_meeting(tmp_path, "store_b", role_prompt_extras(), fakes_b)

    cap_a = result_a.artifact["comparison_capture"]
    cap_b = result_b.artifact["comparison_capture"]
    assert cap_a["role_brief_seats"] == []
    assert cap_a["role_brief_version"] == ROLE_BRIEF_VERSION
    assert cap_b["role_brief_seats"] == sorted(BRIEFED_SEATS)
    # Phase 1 base prompts byte-identical across conditions.
    eval_mod.assert_phase1_base_prompts_equal(cap_a, cap_b)
    # GPT (unbriefed) sees byte-identical opening prompts in A and B.
    assert fakes_a["GPT"].prompts[0] == fakes_b["GPT"].prompts[0]
    # A briefed seat sees base + brief and nothing else.
    for name in BRIEFED_SEATS:
        assert fakes_b[name].prompts[0] == (
            fakes_a[name].prompts[0] + "\n\n" + ROLE_BRIEFS[name]
        )


def test_transcript_retains_full_preparse_text(tmp_path):
    long_text = (
        "1. Observed: A distinctive multi-line claim with unusual "
        "tokens ZQX-9911 and a second sentence that must survive "
        "parsing verbatim, including punctuation! And a trailing clause."
    )
    fakes = {n: FakeParticipant(n, opening=long_text, response=long_text)
             for n in NAMES}
    result = _run_meeting(tmp_path, "store_raw", None, fakes)
    contributions = [e for e in result.transcript.entries if e.kind == "contribution"]
    assert contributions, "expected contribution entries"
    assert all(e.text == long_text for e in contributions), (
        "transcript must retain full pre-parse generation text verbatim; "
        "a dropped/truncated text would break the capture contract"
    )


# --- Program runner: pure cap logic ---

def test_allocation_math():
    assert allocation_for(2.0, 1.8) == pytest.approx(0.20)
    assert allocation_for(0.50, 0.50) == 0.0
    assert allocation_for(0.10, 0.50) == 0.0  # exhausted: never negative
    assert allocation_for(10.0, 0.0) == 0.50  # per-meeting ceiling binds


def test_reserve_needed_defaults_missing_to_meeting_budget():
    assert reserve_needed([0.25, None]) == pytest.approx(0.75)
    assert reserve_needed([]) == 0.0


def test_committed_from_cap_budget_counts_outstanding():
    assert committed_from_cap_budget({
        "estimated_expenditure_usd": 0.10,
        "outstanding_reserved_usd": 0.02,
    }) == pytest.approx(0.12)


def test_pricing_expiry():
    assert pricing_expired("2000-01-01", today="2026-10-29")
    assert not pricing_expired("2027-01-01", today="2026-10-29")


def _stub_meeting_factory(calls, committed=0.12):
    def stub(packet, **kwargs):
        calls.append((packet.work_item, kwargs.get("budget").max_cost_usd))
        return SimpleNamespace(
            meeting_id=f"stub{len(calls)}",
            ok=True,
            artifact_path="/tmp/stub.json",
            artifact={
                "claim_registry": [],
                "cap_budget": {
                    "estimated_expenditure_usd": committed,
                    "outstanding_reserved_usd": 0.0,
                },
                "comparison_capture": {
                    "role_brief_seats": [],
                    "base_prompt_hashes": {"opening": "abc"},
                },
            },
        )
    return stub


def test_runner_refuses_without_cap(tmp_path):
    with pytest.raises(ValueError, match="cap is required"):
        run_program([], cap_usd=None, ledger_path=tmp_path / "ledger.json",
                    store_dir=tmp_path / "store")
    with pytest.raises(ValueError, match="positive"):
        run_program([], cap_usd=0.0, ledger_path=tmp_path / "ledger.json",
                    store_dir=tmp_path / "store")


def test_runner_refuses_expired_pricing(tmp_path):
    calls: list = []
    result = run_program(
        [MeetingSpec(packet=_packet(), condition="A")],
        cap_usd=5.0, ledger_path=tmp_path / "ledger.json",
        store_dir=tmp_path / "store", pricing_expiry="2000-01-01",
        today="2026-10-29", meeting_fn=_stub_meeting_factory(calls),
    )
    assert result.status == "refused"
    assert calls == []


def test_runner_stops_before_meeting_that_cannot_meet_allocation(tmp_path):
    calls: list = []
    specs = [
        MeetingSpec(packet=_packet(), condition="A", estimated_reservation_usd=0.10),
        MeetingSpec(packet=_packet(), condition="B", estimated_reservation_usd=0.10),
    ]
    result = run_program(
        specs, cap_usd=0.21, ledger_path=tmp_path / "ledger.json",
        store_dir=tmp_path / "store", require_completion=True,
        meeting_fn=_stub_meeting_factory(calls, committed=0.12),
    )
    # Meeting 1 runs (0.21 >= 0.20 needed); meeting 2 stops (0.09 < 0.10).
    assert result.status == "stopped"
    assert len(calls) == 1
    assert result.cumulative_reserved_usd == pytest.approx(0.12)
    assert "reserve shortfall" in result.reason
    # Ledger persisted: a fresh ledger on the same path sees the same total.
    ledger = ProgramLedger(tmp_path / "ledger.json", 0.21)
    assert ledger.cumulative_reserved_usd == pytest.approx(0.12)
    assert len(ledger.meetings) == 1


def test_runner_stops_on_exhaustion_without_completion_requirement(tmp_path):
    calls: list = []
    specs = [
        MeetingSpec(packet=_packet(), condition="A"),
        MeetingSpec(packet=_packet(), condition="B"),
    ]
    result = run_program(
        specs, cap_usd=0.12, ledger_path=tmp_path / "ledger.json",
        store_dir=tmp_path / "store", require_completion=False,
        meeting_fn=_stub_meeting_factory(calls, committed=0.12),
    )
    assert result.status == "stopped"
    assert len(calls) == 1
    assert "exhausted" in result.reason


def test_runner_allocates_min_meeting_budget_or_remaining(tmp_path):
    calls: list = []
    specs = [MeetingSpec(packet=_packet(), condition="A")]
    run_program(
        specs, cap_usd=0.30, ledger_path=tmp_path / "ledger.json",
        store_dir=tmp_path / "store", require_completion=False,
        meeting_fn=_stub_meeting_factory(calls),
    )
    # Allocation is min($0.50, remaining=$0.30) = $0.30, enforced by
    # admission — the estimate is never the enforcement ceiling.
    assert calls[0][1] == pytest.approx(0.30)


def test_ledger_cap_mismatch_refuses(tmp_path):
    ledger_path = tmp_path / "ledger.json"
    ledger_path.write_text(json.dumps({"cap_usd": 2.0, "cumulative_reserved_usd": 0.5,
                                       "meetings": []}), encoding="utf-8")
    with pytest.raises(ValueError, match="cap mismatch"):
        ProgramLedger(ledger_path, 3.0)


def test_capture_shape_from_real_meeting(tmp_path):
    fakes = {n: FakeParticipant(n, opening="1. Observed: A stable fact.") for n in NAMES}
    result = _run_meeting(tmp_path, "store_cap", role_prompt_extras(), fakes)
    spec = MeetingSpec(packet=_packet(), condition="B",
                       role_prompt_extras=role_prompt_extras(),
                       role_brief_version=ROLE_BRIEF_VERSION)
    capture = build_meeting_capture(result, spec, allocation_usd=0.50,
                                    committed_usd=0.0)
    assert capture["packet_hash"] == hashlib.sha256(
        _packet().render_prompt().encode("utf-8")).hexdigest()
    assert capture["condition"] == "B"
    assert capture["role_brief_version"] == ROLE_BRIEF_VERSION
    assert capture["base_prompt_hashes"]["opening"]
    assert capture["raw_text_retained"] is True
    assert capture["raw_responses"], "raw contribution texts must be captured"
    assert capture["claim_registry"]


# --- Evaluation machinery ---

def _claims():
    return [
        {"id": "C1", "participant": "Muse", "phase": "opening",
         "text": "The loop has no terminal transition.", "status": "Observed"},
        {"id": "C2", "participant": "Gemini", "phase": "opening",
         "text": "A missing terminal transition loops forever.", "status": "Inferred"},
        {"id": "C3", "participant": "Gemini", "phase": "response",
         "text": "Also: the loop has no terminal transition.", "status": "Observed"},
    ]


def test_strip_labels_keeps_mapping_private():
    rows, mapping = eval_mod.strip_labels(_claims())
    assert [r["blind_id"] for r in rows] == ["B001", "B002", "B003"]
    for row in rows:
        for key in ("participant", "model", "provider", "seat", "author"):
            assert key not in row
        assert row["text"]
    assert mapping == {"B001": "Muse", "B002": "Gemini", "B003": "Gemini"}


def test_grouping_counts_one_insight_once_and_two_views():
    scored = [
        {"blind_id": "B001", "claim_id": "C1", "participant": "Muse",
         "condition": "B", "group_id": "g1", "useful_unique": True,
         "grounding": "grounded", "actionability": True,
         "failure_mode_validity": "", "redundant": False,
         "highest_impact": True, "judge_disagreement": False},
        {"blind_id": "B002", "claim_id": "C2", "participant": "Muse",
         "condition": "B", "group_id": "g1", "useful_unique": True,
         "grounding": "grounded", "actionability": False,
         "failure_mode_validity": "", "redundant": False,
         "highest_impact": False, "judge_disagreement": False},
        {"blind_id": "B003", "claim_id": "C3", "participant": "Muse",
         "condition": "B", "group_id": "g1", "useful_unique": False,
         "grounding": "grounded", "actionability": False,
         "failure_mode_validity": "", "redundant": True,
         "highest_impact": False, "judge_disagreement": False},
        {"blind_id": "B004", "claim_id": "C4", "participant": "Muse",
         "condition": "B", "group_id": "g2", "useful_unique": True,
         "grounding": "grounded", "actionability": True,
         "failure_mode_validity": "", "redundant": False,
         "highest_impact": False, "judge_disagreement": False},
    ]
    views = eval_mod.compute_views(scored, {("Muse", "B"): 0.50})
    view = views["Muse|B"]
    # Three claims, one insight: g1 counts ONCE; g2 once. Total 2,
    # not 4 — volume must not masquerade as contribution.
    assert view["distinct_useful_nonredundant"] == 2
    assert view["distinct_per_reservation_dollar"] == pytest.approx(4.0)
    # Highest-impact validated: only the flagged, validated group.
    assert view["highest_impact_validated_claim_ids"] == [["C1", "C2", "C3"]]


def test_compute_views_never_divides_by_missing_cost():
    scored = [
        {"blind_id": "B001", "claim_id": "C1", "participant": "Gemini",
         "condition": "A", "group_id": "g1", "useful_unique": True,
         "grounding": "grounded", "actionability": True,
         "failure_mode_validity": "", "redundant": False,
         "highest_impact": False, "judge_disagreement": False},
    ]
    views = eval_mod.compute_views(scored, {})
    assert views["Gemini|A"]["distinct_per_reservation_dollar"] is None


def test_phase1_assert_and_later_phase_traceability():
    cap_a = {"packet_work_item": "W", "base_prompt_hashes": {
        "opening": "aaa", "response": "rrr-a", "revision": "vvv-a"}}
    cap_b = {"packet_work_item": "W", "base_prompt_hashes": {
        "opening": "aaa", "response": "rrr-b", "revision": "vvv-b"}}
    # Same Phase 1 hash passes even though later phases differ —
    # later-phase difference is the effect, not a failure.
    eval_mod.assert_phase1_base_prompts_equal(cap_a, cap_b)
    assert eval_mod.later_phase_hashes(cap_b) == {
        "response": "rrr-b", "revision": "vvv-b"}
    cap_c = {"packet_work_item": "W", "base_prompt_hashes": {
        "opening": "different"}}
    with pytest.raises(AssertionError, match="Phase 1 base-prompt mismatch"):
        eval_mod.assert_phase1_base_prompts_equal(cap_a, cap_c)


def test_scoring_sheet_has_grouping_columns():
    rows, _ = eval_mod.strip_labels(_claims())
    sheet = eval_mod.new_scoring_sheet(rows)
    header = sheet.splitlines()[0]
    for column in ("blind_id", "group_id", "useful_unique", "grounding",
                   "actionability", "failure_mode_validity", "redundant",
                   "highest_impact"):
        assert column in header
    # No model identity anywhere in the sheet.
    assert "Muse" not in sheet and "Gemini" not in sheet
