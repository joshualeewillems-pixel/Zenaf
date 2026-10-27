"""Build-Council Room B2: candidate token cap + fixture infrastructure.

Code + tests + fixtures only. No model is called here (route tests
mock generation), no meeting runs, no production cap change:
production meetings still enforce the 40,000-character gate, and
the candidate cap governs only the harness route's B2 fixtures.

Covers the amended B2 design: Section 2 cap values, Section 2.4
gate-migration specification (all five points), Section 3.4
fixture infrastructure, and instruction byte-identity.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path

import pytest
from fastapi import FastAPI

from api.routes import build_room_routes as br_routes
from api.routes.auth_routes import get_current_user
from local_ai.build_room import candidate_cap
from local_ai.build_room import harness_fixtures as hf
from local_ai.build_room.meeting import (
    Budget,
    _SYNTHESIS_INSTRUCTION,
    _telemetry_block,
    build_synthesis_state,
)
from local_ai.llm.tokenizer import count_tokens

FIXTURES_DIR = Path(__file__).parent / "fixtures"
RECORDED_DIR = Path(hf.__file__).resolve().parent

INSTRUCTION_SHA256 = (
    "41925066d601380a3fd35e29a6232a22ef4fdcfc1006ed4d8e77d905e163b177")
STRESS_SHA256 = (
    "a8093c6ee28481f6f8a5db7ad29c51d8ec8d226263e786a96e3b41d4305cf65e")


def _telemetry():
    return _telemetry_block(**hf.TELEMETRY)


def _assembled(builder):
    packet, reg, unresolved, chains = builder()
    tel = _telemetry()
    state = build_synthesis_state(
        packet, reg, unresolved, chains,
        cap_chars=candidate_cap.VERIFICATION_BUILD_CHAR_CAP, telemetry=tel)
    assert state["prompt"] is not None
    return state, tel, state["prompt"] + "\n\n" + tel


# ---------------------------------------------------------------------------
# Section 2: cap values + candidate-vs-production distinction
# ---------------------------------------------------------------------------

def test_cap_values():
    assert candidate_cap.CANDIDATE_SYNTHESIS_PROMPT_TOKENS == 12500
    assert candidate_cap.CANDIDATE_OUTPUT_RESERVATION_TOKENS == 4000
    assert candidate_cap.CANDIDATE_TOTAL_BUDGET_TOKENS == 16500


def test_production_cap_unchanged_and_candidate_distinct():
    # Production still enforces 40,000 chars (B1 pin, repeated here
    # because the distinction is the point of this change).
    assert Budget().max_response_prompt_chars == 40000
    assert candidate_cap.PRODUCTION_SYNTHESIS_PROMPT_CHARS == (
        Budget().max_response_prompt_chars)
    # Synthesis removal stage 1: the meeting no longer reaches
    # the candidate gate by ANY path — the experimental-flag
    # branch lived in the removed synthesis phase, and the
    # parameter is now inert. Pin: no candidate_cap reference
    # in meeting.py at all (the gate machinery itself stays
    # until stage 3, but the meeting path cannot reach it).
    meeting_src = (Path(hf.__file__).resolve().parent / "meeting.py").read_text()
    assert "candidate_cap" not in meeting_src


# ---------------------------------------------------------------------------
# Section 2.4: gate-migration specification
# ---------------------------------------------------------------------------

def test_gate_admits_at_and_below_cap_refuses_above():
    state, tel, assembled = _assembled(hf.fixture_fitting_state)
    gate = candidate_cap.evaluate_candidate_gate(state, tel)
    assert gate["admitted"] is True
    assert gate["total_tokens"] == 6928
    assert gate["total_chars"] == 36577
    assert gate["excess_tokens"] == 0
    # Exact boundary: at-cap admits, one token over refuses.
    assert candidate_cap.evaluate_candidate_gate(
        state, tel, cap_tokens=6928)["admitted"] is True
    over = candidate_cap.evaluate_candidate_gate(
        state, tel, cap_tokens=6927)
    assert over["admitted"] is False
    assert over["excess_tokens"] == 1
    assert "candidate_cap_exceeded" in over["reason"]
    assert "nothing was truncated" in over["reason"]


def test_gate_governs_assembled_prompt_including_telemetry_and_separators():
    # Section 2.4.1: the gate counts mandatory + optional +
    # disclosure + instruction + telemetry + join separators.
    state, tel, assembled = _assembled(hf.fixture_failed_state)
    gate = candidate_cap.evaluate_candidate_gate(state, tel)
    assert gate["admitted"] is True
    assert gate["total_tokens"] == 8410
    assert gate["total_chars"] == 44058
    comps = gate["components"]
    assert set(comps) == {"mandatory", "optional", "disclosure",
                          "instruction", "telemetry", "separators"}
    # Character components sum exactly to the assembled length.
    assert sum(c["chars"] for c in comps.values()) == len(assembled)
    assert comps["telemetry"]["chars"] == 421
    assert comps["separators"]["chars"] == 8
    assert comps["instruction"]["chars"] == 4165
    # Token total is the exact count of the assembled string itself.
    assert gate["total_tokens"] == count_tokens(assembled)
    assert comps["instruction"]["tokens"] == 824
    assert comps["telemetry"]["tokens"] == 82


def test_diagnostic_reports_chars_and_tokens_tokens_enforce():
    # Section 2.4.4: both counts reported, tokens identified as
    # the enforcement unit.
    state, tel, _ = _assembled(hf.fixture_stress_state)
    gate = candidate_cap.evaluate_candidate_gate(state, tel)
    assert gate["enforcement_unit"] == "tokens"
    assert gate["total_chars"] == 60977
    assert gate["total_tokens"] == 11935
    assert gate["prompt_sha256"] == STRESS_SHA256
    for comp in gate["components"].values():
        assert comp["chars"] is not None and comp["tokens"] is not None


def test_gate_fails_closed_without_exact_measurement(monkeypatch):
    # Section 2.4.5 / measurement discipline: no exact count means
    # no admission, never an estimate.
    monkeypatch.setattr(candidate_cap, "count_tokens_exact",
                        lambda text: None)
    state, tel, _ = _assembled(hf.fixture_fitting_state)
    gate = candidate_cap.evaluate_candidate_gate(state, tel)
    assert gate["admitted"] is False
    assert gate["measurement_available"] is False
    assert gate["total_tokens"] is None
    assert "unavailable" in gate["reason"]
    assert "estimate" in gate["reason"]


def test_model_tokenizer_agreement_default_and_disagreements():
    # Section 2.4.5: verified, not assumed. Live defaults agree.
    ok = candidate_cap.verify_model_tokenizer_agreement()
    assert ok["agrees"] is True
    assert ok["tokenizer_model"] == "gpt-4o-mini"
    assert ok["synthesizer_model"] == "gpt-4o-mini"
    assert ok["encoding"] == "o200k_base"
    assert ok["expected_encoding"] == "o200k_base"
    assert ok["tiktoken_available"] is True
    # A different tokenizer model disagrees even when its encoding
    # happens to match (model identity is part of agreement).
    assert candidate_cap.verify_model_tokenizer_agreement(
        tokenizer_model="gpt-4o")["agrees"] is False
    # A different synthesizer model disagrees.
    assert candidate_cap.verify_model_tokenizer_agreement(
        synthesizer_model="gpt-4o")["agrees"] is False
    # A model with a different encoding disagrees.
    assert candidate_cap.verify_model_tokenizer_agreement(
        tokenizer_model="gpt-3.5-turbo")["agrees"] is False


def test_other_character_budgets_untouched():
    # Section 2.4.3: only the synthesis gate migrates. Individual
    # contribution budgets keep their values.
    assert Budget().max_prompt_chars == 20000
    assert Budget().max_contributions == 1
    assert Budget().timeout_seconds == 120


# ---------------------------------------------------------------------------
# Instruction byte-identity (refinement deferred; Section 3.3)
# ---------------------------------------------------------------------------

def test_instruction_pinned_fidelity_revision():
    # Pinned to the fidelity-correction revision (design:
    # zenaf-build-council-fidelity-correction-design.md), not to the
    # pre-correction text. Any future instruction change must
    # re-pin these values deliberately, never silently.
    assert len(_SYNTHESIS_INSTRUCTION) == 4165
    assert count_tokens(_SYNTHESIS_INSTRUCTION) == 824
    assert hashlib.sha256(
        _SYNTHESIS_INSTRUCTION.encode()).hexdigest() == INSTRUCTION_SHA256


# ---------------------------------------------------------------------------
# Section 3.4: fixture infrastructure (deterministic, hashed)
# ---------------------------------------------------------------------------

def test_packaged_recorded_fixtures_identical_to_test_fixtures():
    for name in ("recorded_fitting_run.json", "recorded_failed_run.json"):
        packaged = (RECORDED_DIR / name).read_bytes()
        original = (FIXTURES_DIR / name.replace("recorded_", "b1_")).read_bytes()
        assert packaged == original


def test_replay_fixtures_pinned():
    state, tel, assembled = _assembled(hf.fixture_fitting_state)
    assert len(assembled) == 36577
    assert count_tokens(assembled) == 6928
    assert hashlib.sha256(assembled.encode()).hexdigest()[:16] == "ed0d28b45cc896e3"
    state, tel, assembled = _assembled(hf.fixture_failed_state)
    assert len(assembled) == 44058
    assert count_tokens(assembled) == 8410


def test_zero_contestation_assembly_tier1_only():
    # Full-state assembly, hash recorded, no generation: the builder
    # exists but is deliberately NOT routable — and since stage 1
    # there is no harness route at all.
    state, tel, assembled = _assembled(hf.fixture_zero_contestation_state)
    assert len(assembled) == 6270
    assert count_tokens(assembled) == 1256
    assert hashlib.sha256(assembled.encode()).hexdigest()[:16] == "c5e59bc3da82b566"
    assert not hasattr(br_routes, "harness_synthesis_call")


def test_stress_fixture_in_band_and_genuine():
    packet, reg, unresolved, chains = hf.fixture_stress_state()
    assert len(reg.claims) == 114
    # Five seats, all three phases, competing positions (unresolved
    # objections) and revision chains.
    assert sorted({c.participant for c in reg.claims}) == [
        "Claude", "GPT", "Gemini", "Grok", "Muse"]
    assert sorted({c.phase for c in reg.claims}) == [
        "opening", "response", "revision"]
    assert len(unresolved) == 9
    assert len(chains) == 12
    # No filler repetition: every claim body is unique, and every
    # referenced ID exists in the registry.
    bodies = [c.text for c in reg.claims]
    assert len(set(bodies)) == len(bodies)
    ids = {c.id for c in reg.claims}
    assert all(u["claim_id"] in ids and u["source_claim_id"] in ids
               for u in unresolved)
    assert all(ch["original_claim_id"] in ids
               and ch["challenge_claim_id"] in ids
               and ch["revision_claim_id"] in ids for ch in chains)
    # Token band: the point of the fixture.
    state, tel, assembled = _assembled(hf.fixture_stress_state)
    assert 11500 <= count_tokens(assembled) <= 12500
    assert count_tokens(assembled) == 11935
    assert len(assembled) == 60977
    assert hashlib.sha256(assembled.encode()).hexdigest() == STRESS_SHA256
    # And the candidate gate admits it.
    gate = candidate_cap.evaluate_candidate_gate(state, tel)
    assert gate["admitted"] is True
