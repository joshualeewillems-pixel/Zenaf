"""Cap-replacement gate tests (folded design, 2026-10-28).

Deterministic: generation is mocked — no live API calls, no real
key values anywhere. The 13-item implementation acceptance
checklist from the design doc, plus ledger/pricing/settlement
unit tests. Two pre-existing tests were updated to gate
equivalents under Joshua's 2026-10-28 authorization (tight
max_cost_usd instead of the retired 100-char cap); every other
existing test is untouched.
"""

from __future__ import annotations

import pytest

from local_ai.build_room import meeting as meeting_mod
from local_ai.build_room.meeting import (
    Budget,
    CapBudgetLedger,
    EvidencePacket,
    evaluate_admission,
    run_multi_model_meeting,
)
from local_ai.build_room.participants import SEAT_SPECS, Seat

NAMES = [name for name, _, _ in SEAT_SPECS]
_SENTENCE = (
    "The council weighs each claim on its merits, citing evidence "
    "and noting uncertainty. "
)


class FakeParticipant:
    """Duck-typed seat participant: generate(prompt, timeout=...)."""

    def __init__(self, name, *, opening="", response="", revision="",
                 raise_exc=None, usage=None):
        self.name = name
        self.provider_id = dict((n, p) for n, p, _ in SEAT_SPECS)[name]
        self.model = "fake-model"
        self.key_source = "settings"
        self._texts = {
            "revision": revision,
            "response": response,
            "opening": opening,
        }
        self._raise_exc = raise_exc
        self._usage = usage
        self.prompts: list[str] = []
        if usage is not None:
            # The usage channel exists ONLY when configured, mirroring
            # the real OpenAI seat (participants.py __getattr__):
            # other seats genuinely lack the attribute, so the
            # runner's hasattr check falls through to generate().
            # (A class-level method would make hasattr True for every
            # fake and turn every generation into a spurious failure.)
            self.generate_with_usage = self._generate_with_usage_impl

    def generate(self, prompt, *, timeout=120):
        self.prompts.append(prompt)
        if self._raise_exc is not None:
            raise self._raise_exc
        if "state the relationship explicitly" in prompt:
            return self._texts["revision"]
        if "Claim registry" in prompt:
            return self._texts["response"]
        return self._texts["opening"]

    def _generate_with_usage_impl(self, prompt, *, timeout=120):
        # Called INSTEAD of generate(), never in addition — one
        # generation, one usage report.
        self.prompts.append(prompt)
        if self._raise_exc is not None:
            raise self._raise_exc
        if "state the relationship explicitly" in prompt:
            return self._texts["revision"], dict(self._usage)
        if "Claim registry" in prompt:
            return self._texts["response"], dict(self._usage)
        return self._texts["opening"], dict(self._usage)


def _packet() -> EvidencePacket:
    return EvidencePacket(
        work_item="Test work item",
        question="What would make the Build-Council Room fail to function as a genuine deliberative council?",
        excerpts=("excerpt one",),
        constraints=("room deliberates, never decides",),
        source_refs=("local_ai/build_room/meeting.py",),
    )


def _seats(fakes: dict[str, FakeParticipant | None]) -> list[Seat]:
    seats = []
    for name, provider_id, model in SEAT_SPECS:
        fake = fakes.get(name, FakeParticipant(name, opening="1. Inferred: nothing yet."))
        if fake is None:
            seats.append(Seat(name, provider_id, model, None,
                              absence_note=f"absent: no {provider_id} api key present"))
        else:
            seats.append(Seat(name, provider_id, model, fake))
    return seats


def _standard_fakes() -> dict[str, FakeParticipant]:
    return {
        name: FakeParticipant(name, opening="1. Inferred: Some claim with substance.")
        for name in NAMES
    }


def _failures(result) -> list[str]:
    return [e.text for e in result.transcript.entries if e.kind == "failure"]


def _repeat_to(text: str, n: int) -> str:
    reps = (n + len(text) - 1) // len(text)
    return (text * reps)[:n]


# -- checklist: previously blocked prompt admitted ----------------

def test_blocked_49413_char_prompt_admitted():
    # The red-team response prompt (49,413 chars) died on the retired
    # 40,000-char cap. Under the gates it is admitted for every seat:
    # characters no longer gate anything.
    prompt = _repeat_to(_SENTENCE, 49_413)
    assert len(prompt) == 49_413 and len(prompt) > 40_000
    for _name, _provider, model in SEAT_SPECS:
        decision = evaluate_admission(
            model=model, prompt=prompt, budget=Budget(),
            remaining_budget=0.50)
        assert decision.admitted, (model, decision.reason)
        assert decision.prompt_chars == 49_413


def test_default_budget_meeting_completes(tmp_path):
    result = run_multi_model_meeting(
        _packet(), store_dir=tmp_path,
        seats=_seats(_standard_fakes()), budget=Budget(max_contributions=15))
    assert result.ok is True
    assert result.artifact["deliberation_complete"] is True
    assert result.artifact["record_complete"] is True
    cap = result.artifact["cap_budget"]
    assert cap["ceiling_usd"] == 0.50
    assert len(cap["settlements"]) == 10  # 5 openings + 5 responses
    assert all(s["reservation_status"] == "unverified" for s in cap["settlements"])
    assert cap["settled_verified_usd"] == 0.0
    assert abs(cap["retained_unverified_usd"]
               - sum(s["estimated_cost_usd"] for s in cap["settlements"])) < 0.001


# -- checklist: missing budget / window / tokenizer ---------------

def test_missing_budget_refused_before_call(tmp_path):
    result = run_multi_model_meeting(
        _packet(), store_dir=tmp_path, seats=_seats(_standard_fakes()),
        budget=Budget(max_contributions=15, max_cost_usd=None))
    assert result.artifact["deliberation_complete"] is False
    assert result.artifact["record_complete"] is True
    assert result.artifact["cap_budget"]["ceiling_usd"] is None
    # 5 gate refusals, plus the convene-level no-openings note (which
    # the parity check explicitly ignores as a generation record).
    gate_failures = [f for f in _failures(result) if "[gate=" in f]
    assert len(gate_failures) == 5
    assert all("[gate=budget]" in f for f in gate_failures)


def test_missing_budget_never_calls_provider(tmp_path):
    fakes = _standard_fakes()
    run_multi_model_meeting(
        _packet(), store_dir=tmp_path, seats=_seats(fakes),
        budget=Budget(max_contributions=15, max_cost_usd=None))
    assert all(fake.prompts == [] for fake in fakes.values())


def test_missing_window_refused(tmp_path):
    fakes = _standard_fakes()
    seats = _seats(fakes)
    seats[0] = Seat("GPT", "openai", "unlisted-model", fakes["GPT"])
    result = run_multi_model_meeting(
        _packet(), store_dir=tmp_path, seats=seats,
        budget=Budget(max_contributions=15))
    failures = _failures(result)
    gpt_failures = [f for f in failures if "unlisted-model" in f]
    assert len(gpt_failures) >= 1
    assert all("[gate=configuration]" in f for f in gpt_failures)
    assert fakes["GPT"].prompts == []
    # The other four seats still deliberate.
    assert sum(1 for e in result.transcript.entries if e.kind == "contribution") >= 4
    assert result.artifact["deliberation_complete"] is False
    assert result.artifact["record_complete"] is True


def test_missing_tokenizer_refused(monkeypatch, tmp_path):
    monkeypatch.setattr(meeting_mod, "count_tokens_exact", lambda text: None)
    fakes = _standard_fakes()
    result = run_multi_model_meeting(
        _packet(), store_dir=tmp_path, seats=_seats(fakes),
        budget=Budget(max_contributions=15))
    gate_failures = [f for f in _failures(result) if "[gate=" in f]
    assert len(gate_failures) == 5
    assert all("[gate=tokenizer]" in f for f in gate_failures)
    assert all(fake.prompts == [] for fake in fakes.values())


def test_stale_pricing_fails_closed(tmp_path):
    fakes = _standard_fakes()
    result = run_multi_model_meeting(
        _packet(), store_dir=tmp_path, seats=_seats(fakes),
        budget=Budget(max_contributions=15, pricing_expiry="2020-01-01"))
    gate_failures = [f for f in _failures(result) if "[gate=" in f]
    assert len(gate_failures) == 5
    assert all("[gate=configuration]" in f and "expired" in f
               for f in gate_failures)
    assert all(fake.prompts == [] for fake in fakes.values())


# -- checklist: capacity, budget fit, batch ------------------------

def test_prompt_exceeding_context_refused_without_truncation():
    prompt = _repeat_to(_SENTENCE, 800_000)
    decision = evaluate_admission(
        model="gpt-4o-mini", prompt=prompt, budget=Budget(),
        remaining_budget=0.50)
    assert decision.admitted is False
    assert decision.code == "capacity"
    assert "never truncated" in decision.reason


def test_prompt_exceeding_context_refused_e2e(monkeypatch, tmp_path):
    # Shrink GPT's window so its opening exceeds capacity; the other
    # seats are unaffected and the prompt is refused, never shortened.
    monkeypatch.setitem(meeting_mod.CAP_MODEL_WINDOWS, "gpt-4o-mini", 1000)
    fakes = _standard_fakes()
    result = run_multi_model_meeting(
        _packet(), store_dir=tmp_path, seats=_seats(fakes),
        budget=Budget(max_contributions=15))
    assert fakes["GPT"].prompts == []
    failures = [f for f in _failures(result) if "window" in f]
    assert any("[gate=capacity]" in f for f in failures)
    assert result.artifact["record_complete"] is True


def test_estimate_exceeding_remaining_refused(tmp_path):
    fakes = _standard_fakes()
    result = run_multi_model_meeting(
        _packet(), store_dir=tmp_path, seats=_seats(fakes),
        budget=Budget(max_contributions=15, max_cost_usd=0.001))
    gate_failures = [f for f in _failures(result) if "[gate=" in f]
    assert len(gate_failures) == 5
    assert all("[gate=budget]" in f for f in gate_failures)
    assert all(fake.prompts == [] for fake in fakes.values())


def test_five_concurrent_admissions_cannot_exceed_budget(tmp_path):
    # Openings (≈ $0.058) fit in $0.08; the response batch (≈ $0.059)
    # exceeds the remaining ≈ $0.022, so the WHOLE batch is refused
    # (none reserved, none dispatched) — combined reservations for
    # the batch are $0, never $0.059 against $0.022.
    result = run_multi_model_meeting(
        _packet(), store_dir=tmp_path, seats=_seats(_standard_fakes()),
        budget=Budget(max_contributions=15, max_cost_usd=0.08))
    failures = _failures(result)
    response_failures = [f for f in failures if "response" in f]
    assert len(response_failures) == 5
    assert all("[gate=budget]" in f and "batch" in f for f in response_failures)
    cap = result.artifact["cap_budget"]
    assert all(s["phase"] == "opening" for s in cap["settlements"])
    assert cap["retained_unverified_usd"] < 0.08


# -- checklist: settlement hierarchy -------------------------------

def test_timeout_after_dispatch_retains_uncertain(tmp_path):
    fakes = _standard_fakes()
    fakes["Grok"] = FakeParticipant(
        "Grok", opening="1. Inferred: Delta.",
        raise_exc=TimeoutError("timed out"))
    result = run_multi_model_meeting(
        _packet(), store_dir=tmp_path, seats=_seats(fakes),
        budget=Budget(max_contributions=15))
    cap = result.artifact["cap_budget"]
    grok = [s for s in cap["settlements"] if s["participant"] == "Grok"]
    assert len(grok) == 2  # opening + response, both dispatched then failed
    assert all(s["reservation_status"] == "uncertain" for s in grok)
    assert abs(cap["retained_uncertain_usd"]
               - sum(s["estimated_cost_usd"] for s in grok)) < 0.001
    assert result.artifact["deliberation_complete"] is False
    assert result.artifact["record_complete"] is True


def test_usage_exceeding_estimate_recorded_overrun(tmp_path):
    fakes = _standard_fakes()
    fakes["GPT"] = FakeParticipant(
        "GPT", opening="1. Inferred: Alpha.",
        response="1. Inferred: Alpha stands.",
        usage={"prompt_tokens": 500, "completion_tokens": 50000})
    result = run_multi_model_meeting(
        _packet(), store_dir=tmp_path, seats=_seats(fakes),
        budget=Budget(max_contributions=15))
    cap = result.artifact["cap_budget"]
    assert len(cap["overruns"]) >= 1
    overrun = cap["overruns"][0]
    assert overrun["participant"] == "GPT"
    assert overrun["overrun_usd"] > 0
    assert overrun["actual_usd"] > overrun["reserved_usd"]
    gpt_settled = [s for s in cap["settlements"]
                   if s["participant"] == "GPT"
                   and s["reservation_status"] == "settled"]
    assert gpt_settled
    assert all(s["verified_cost_usd"] > s["estimated_cost_usd"]
               for s in gpt_settled)


def test_output_limit_completion_marked_capped(tmp_path):
    fakes = _standard_fakes()
    fakes["GPT"] = FakeParticipant(
        "GPT", opening="1. Inferred: Alpha.",
        response="1. Inferred: Alpha stands.",
        usage={"prompt_tokens": 500, "completion_tokens": 100,
               "finish_reason": "length"})
    result = run_multi_model_meeting(
        _packet(), store_dir=tmp_path, seats=_seats(fakes),
        budget=Budget(max_contributions=15))
    capped = result.artifact["cap_budget"]["output_capped_generations"]
    assert {"phase": "opening", "participant": "GPT"} in capped
    assert {"phase": "response", "participant": "GPT"} in capped


def test_success_without_usage_retains_unverified(tmp_path):
    # Plain fakes have no usage channel: every dispatched generation
    # settles case 2 (retained, marked unverified, never $0).
    result = run_multi_model_meeting(
        _packet(), store_dir=tmp_path, seats=_seats(_standard_fakes()),
        budget=Budget(max_contributions=15))
    cap = result.artifact["cap_budget"]
    assert cap["settled_verified_usd"] == 0.0
    assert cap["retained_unverified_usd"] > 0
    assert abs(cap["available_usd"]
               - (0.50 - cap["retained_unverified_usd"])) < 0.001


# -- checklist: same gates all phases, legacy caps, accounting -----

def test_same_gate_logic_all_phases(tmp_path):
    # Mirror the proven revision pattern: Claude objects to C1, so
    # GPT is invited to revise. With the default budget all three
    # phases pass the same gates and settle through the same ledger.
    fakes = {
        "GPT": FakeParticipant(
            "GPT", opening="1. Inferred: Alpha.",
            revision="Relationship: defended.\nIn response to C1, I defend:\n"
                     "1. Inferred: Alpha stands."),
        "Claude": FakeParticipant(
            "Claude", opening="1. Inferred: Beta.",
            response="In response to C1, I object: alpha is overstated."),
        "Gemini": FakeParticipant("Gemini", opening="1. Inferred: Gamma."),
        "Grok": FakeParticipant("Grok", opening="1. Inferred: Delta."),
        "Muse": FakeParticipant("Muse", opening="1. Inferred: Epsilon."),
    }
    result = run_multi_model_meeting(
        _packet(), store_dir=tmp_path, seats=_seats(fakes),
        budget=Budget(max_contributions=15))
    phases = {s["phase"] for s in result.artifact["cap_budget"]["settlements"]}
    assert phases == {"opening", "response", "revision"}


def test_same_gate_blocks_revision_phase_when_budget_spent(tmp_path):
    # Same setup, tight budget: responses are batch-refused, so no
    # interactions exist, so no revision is ever invited — the gate
    # governs the revision phase by governing what reaches it.
    fakes = {
        "GPT": FakeParticipant(
            "GPT", opening="1. Inferred: Alpha.",
            revision="Relationship: defended.\nIn response to C1, I defend:\n"
                     "1. Inferred: Alpha stands."),
        "Claude": FakeParticipant(
            "Claude", opening="1. Inferred: Beta.",
            response="In response to C1, I object: alpha is overstated."),
        "Gemini": FakeParticipant("Gemini", opening="1. Inferred: Gamma."),
        "Grok": FakeParticipant("Grok", opening="1. Inferred: Delta."),
        "Muse": FakeParticipant("Muse", opening="1. Inferred: Epsilon."),
    }
    result = run_multi_model_meeting(
        _packet(), store_dir=tmp_path, seats=_seats(fakes),
        budget=Budget(max_contributions=15, max_cost_usd=0.08))
    phases = {s["phase"] for s in result.artifact["cap_budget"]["settlements"]}
    assert phases == {"opening"}
    assert result.artifact["deliberation_complete"] is False
    assert result.artifact["record_complete"] is True


def test_legacy_char_limits_no_longer_affect_admission(tmp_path):
    # Absurd char caps that would have blocked everything: R2 ignores
    # them entirely (the R1 path still uses max_prompt_chars, and its
    # tests are untouched).
    result = run_multi_model_meeting(
        _packet(), store_dir=tmp_path, seats=_seats(_standard_fakes()),
        budget=Budget(max_contributions=15, max_prompt_chars=10,
                      max_response_prompt_chars=10))
    assert result.ok is True
    assert result.artifact["deliberation_complete"] is True


def test_record_completeness_preserved_with_mixed_failures(tmp_path):
    fakes = _standard_fakes()
    fakes["Claude"] = FakeParticipant(
        "Claude", opening="1. Inferred: Beta.",
        raise_exc=RuntimeError("provider exploded"))
    result = run_multi_model_meeting(
        _packet(), store_dir=tmp_path, seats=_seats(fakes),
        budget=Budget(max_contributions=15))
    assert result.artifact["record_completeness"]["passed"] is True
    assert result.artifact["record_complete"] is True
    assert result.ok is False  # deliberation incomplete, record whole
    claude = [s for s in result.artifact["cap_budget"]["settlements"]
              if s["participant"] == "Claude"]
    assert claude and all(s["reservation_status"] == "uncertain" for s in claude)


# -- ledger unit tests ----------------------------------------------

def test_ledger_arithmetic_and_release():
    ledger = CapBudgetLedger(0.50)
    assert ledger.available_usd == 0.50
    ledger.reserve(("opening", "GPT"), 0.10)
    assert abs(ledger.available_usd - 0.40) < 1e-9
    overrun = ledger.settle_reported(("opening", "GPT"), 0.06)
    assert overrun == 0.0
    assert abs(ledger.available_usd - 0.44) < 1e-9  # freed 0.04
    ledger.reserve(("opening", "Claude"), 0.05)
    ledger.settle_unverified(("opening", "Claude"))
    assert abs(ledger.available_usd - 0.39) < 1e-9  # retained counts
    assert abs(ledger.estimated_expenditure_usd - 0.11) < 1e-9
    ledger.reserve(("response", "GPT"), 0.02)
    ledger.settle_uncertain(("response", "GPT"))
    assert abs(ledger.available_usd - 0.37) < 1e-9
    ledger.reserve(("response", "Claude"), 0.03)
    assert abs(ledger.release(("response", "Claude")) - 0.03) < 1e-9
    assert abs(ledger.available_usd - 0.37) < 1e-9
    ledger.reserve(("response", "Gemini"), 0.10)
    overrun = ledger.settle_reported(("response", "Gemini"), 0.15)
    assert abs(overrun - 0.05) < 1e-9
    assert len(ledger.overruns) == 1


def test_fleet_ceiling_reported_not_refusing():
    # 800K chars ≈ 200K tokens: over the 128K fleet ceiling but far
    # under Gemini's declared 1,048,576 window. Admitted, with the
    # ceiling exceedance REPORTED — the ceiling never refuses alone.
    prompt = _repeat_to(_SENTENCE, 800_000)
    decision = evaluate_admission(
        model="gemini-3.8-flash", prompt=prompt, budget=Budget(),
        remaining_budget=0.50)
    assert decision.admitted is True
    assert decision.fleet_ceiling_exceeded is True
    assert decision.window == 1_048_576
