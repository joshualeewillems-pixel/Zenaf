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
    # Phase C spec §5.5 (authorized experimental selection) REFINES
    # the B2 boundary rather than removing it: the meeting module
    # may reach the candidate gate ONLY under the explicit
    # experimental flag — never by default, never by import. So
    # this pin now asserts: no top-level candidate import, exactly
    # one lazy import, and that import (plus every candidate_cap
    # use) sits inside the experimental-flag branch. Behavioral
    # tests (gate_selection: default meetings never produce a
    # candidate record) prove the same boundary at runtime.
    meeting_src = (Path(hf.__file__).resolve().parent / "meeting.py").read_text()
    lines = meeting_src.splitlines()
    for line in lines:
        stripped = line.strip()
        assert not stripped.startswith("import candidate_cap")
        assert not stripped.startswith(
            "from local_ai.build_room.candidate_cap import")
    import_lines = [i for i, line in enumerate(lines)
                    if line.strip().startswith(
                        "from local_ai.build_room import candidate_cap")]
    assert len(import_lines) == 1
    flag_line = next(i for i, line in enumerate(lines)
                     if "if experimental_candidate_gate:" in line)
    assert flag_line < import_lines[0]
    flag_indent = len(lines[flag_line]) - len(lines[flag_line].lstrip())
    for i in range(flag_line + 1, import_lines[0] + 1):
        if lines[i].strip():
            assert len(lines[i]) - len(lines[i].lstrip()) > flag_indent
    for i, line in enumerate(lines):
        if "candidate_cap." in line:
            assert i > flag_line


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
    # exists but is deliberately NOT in the route's fixture map.
    state, tel, assembled = _assembled(hf.fixture_zero_contestation_state)
    assert len(assembled) == 6270
    assert count_tokens(assembled) == 1256
    assert hashlib.sha256(assembled.encode()).hexdigest()[:16] == "c5e59bc3da82b566"
    assert "zero" not in br_routes.HARNESS_FIXTURE_BUILDERS
    assert "zero_contestation" not in br_routes.HARNESS_FIXTURE_BUILDERS


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


def test_route_fixtures_are_the_harness_fixtures():
    for fid, builder in (("fitting", hf.fixture_fitting_state),
                         ("failed", hf.fixture_failed_state),
                         ("stress", hf.fixture_stress_state)):
        assert br_routes.HARNESS_FIXTURE_BUILDERS[fid] is builder


# ---------------------------------------------------------------------------
# Route: B2 fixtures through the candidate gate (mocked generation)
# ---------------------------------------------------------------------------

OWNER = {"id": "owner-id", "email": "owner@local.zenaf"}
OTHER = {"id": "someone-else"}
FAKE_KEY = "FAKE-KEY-VALUE-67890"

FIT_BLOCK = (
    "Narrative synthesis here.\n```json\n"
    + json.dumps({
        "positions": [{"claim_ids": ["C1"], "position": "Cap adopted.",
                       "supporting_reasoning": "Grounded in C1."}],
        "disagreements": [],
        "recommendations": [],
        "limitations": []})
    + "\n```\n")


def _call_post(app, path: str, payload: dict) -> tuple[int, dict]:
    raw = json.dumps(payload).encode()
    scope = {
        "type": "http",
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "headers": [
            (b"content-type", b"application/json"),
            (b"content-length", str(len(raw)).encode()),
        ],
        "client": ("testclient", 50000),
        "server": ("testserver", 80),
    }
    messages: list[dict] = []
    sent_request = False

    async def receive():
        nonlocal sent_request
        if not sent_request:
            sent_request = True
            return {"type": "http.request", "body": raw, "more_body": False}
        return {"type": "http.disconnect"}

    async def send(message: dict) -> None:
        messages.append(message)

    asyncio.run(app(scope, receive, send))
    start = next(m for m in messages if m["type"] == "http.response.start")
    body = b"".join(
        m.get("body", b"") for m in messages if m["type"] == "http.response.body"
    )
    return start["status"], json.loads(body.decode() or "{}")


@pytest.fixture()
def app(tmp_path, monkeypatch):
    import local_ai.vision_execution.storage as ve_store_mod

    monkeypatch.setattr(
        br_routes, "get_build_room_store_dir", lambda: tmp_path / "store"
    )
    monkeypatch.setattr(ve_store_mod, "get_owner_user_id", lambda: OWNER["id"])
    application = FastAPI()
    application.include_router(br_routes.router)
    return application


class _FakeParticipant:
    def __init__(self, text: str):
        self.text = text
        self.calls: list[tuple[str, int]] = []

    def generate(self, prompt: str, *, timeout: int = 120) -> str:
        self.calls.append((prompt, timeout))
        return self.text


def _mock_participant(monkeypatch, fake):
    monkeypatch.setattr(
        br_routes, "resolve_openai_participant",
        lambda principal: (fake, ""),
    )


def _expected_b2_prompt(fixture: str) -> str:
    packet, reg, unresolved, chains = br_routes.HARNESS_FIXTURE_BUILDERS[
        fixture]()
    state = build_synthesis_state(
        packet, reg, unresolved, chains,
        cap_chars=candidate_cap.VERIFICATION_BUILD_CHAR_CAP,
        telemetry=_telemetry())
    assert state["prompt"] is not None
    return state["prompt"] + "\n\n" + _telemetry()


@pytest.mark.parametrize("bad", ["X", "zero", "zero_contestation", "FITTING", ""])
def test_b2_invalid_fixture_refused_and_no_generation(
        app, monkeypatch, bad):
    app.dependency_overrides[get_current_user] = lambda: OWNER
    fake = _FakeParticipant(FIT_BLOCK)
    _mock_participant(monkeypatch, fake)
    status, _ = _call_post(app, "/build-room/harness/synthesis-call",
                           {"fixture": bad})
    assert status == 422
    assert fake.calls == []


def test_b2_non_owner_is_403_and_no_generation(app, monkeypatch):
    app.dependency_overrides[get_current_user] = lambda: OTHER
    fake = _FakeParticipant(FIT_BLOCK)
    _mock_participant(monkeypatch, fake)
    status, _ = _call_post(app, "/build-room/harness/synthesis-call",
                           {"fixture": "stress"})
    assert status == 403
    assert fake.calls == []


@pytest.mark.parametrize("fixture,tokens", [
    ("fitting", 6928), ("failed", 8410), ("stress", 11935)])
def test_b2_fixture_single_generation_through_candidate_gate(
        app, monkeypatch, tmp_path, fixture, tokens):
    app.dependency_overrides[get_current_user] = lambda: OWNER
    fake = _FakeParticipant(FIT_BLOCK)
    _mock_participant(monkeypatch, fake)
    status, body = _call_post(app, "/build-room/harness/synthesis-call",
                              {"fixture": fixture})
    assert status == 200, body
    assert body["fixture_id"] == fixture
    assert body["ok"] is True
    assert body["generated"] is True
    assert body["generations_used"] == 1
    assert len(fake.calls) == 1
    sent_prompt, sent_timeout = fake.calls[0]
    assert sent_timeout == 120
    assert sent_prompt == _expected_b2_prompt(fixture)
    # Candidate gate, not char cap, governed admission.
    assert body["candidate_gate_enabled"] is True
    assert body["candidate_gate"]["admitted"] is True
    assert body["candidate_gate"]["total_tokens"] == tokens
    assert body["candidate_gate"]["enforcement_unit"] == "tokens"
    assert body["assembled_prompt_tokens"] == tokens
    assert body["candidate_cap_tokens"] == 12500
    assert body["production_cap_chars"] == 40000
    assert body["enforcement_unit"] == "tokens"
    assert body["model_tokenizer_agreement"]["agrees"] is True
    assert body["prompt_sha256"] == hashlib.sha256(
        sent_prompt.encode()).hexdigest()
    # Verbatim output + production evaluation, kept separate.
    assert body["raw"] == FIT_BLOCK
    # No prompt text, no credentials, no credential-shaped keys.
    assert "prompt" not in body
    assert _SYNTHESIS_INSTRUCTION not in json.dumps(body)
    assert FAKE_KEY not in json.dumps(body)
    assert not any(k in ("api_key", "password", "token", "secret")
                   for k in body)
    # No persistence.
    assert list((tmp_path / "store").glob("meeting_*.transcript.json")) == []


def test_b2_over_cap_refused_and_no_generation(app, monkeypatch):
    app.dependency_overrides[get_current_user] = lambda: OWNER
    fake = _FakeParticipant(FIT_BLOCK)
    _mock_participant(monkeypatch, fake)
    monkeypatch.setattr(candidate_cap, "CANDIDATE_SYNTHESIS_PROMPT_TOKENS",
                        1000)
    status, body = _call_post(app, "/build-room/harness/synthesis-call",
                              {"fixture": "stress"})
    assert status == 200, body
    assert body["ok"] is False
    assert body["generated"] is False
    assert body["candidate_gate"]["admitted"] is False
    assert body["candidate_gate"]["total_tokens"] == 11935
    assert body["candidate_gate"]["excess_tokens"] == 11935 - 1000
    assert fake.calls == []


def test_b2_agreement_failure_disables_gate_and_no_generation(
        app, monkeypatch):
    app.dependency_overrides[get_current_user] = lambda: OWNER
    fake = _FakeParticipant(FIT_BLOCK)
    _mock_participant(monkeypatch, fake)
    monkeypatch.setattr(
        candidate_cap, "verify_model_tokenizer_agreement",
        lambda **kw: {"agrees": False,
                      "tokenizer_model": "gpt-4o-mini",
                      "synthesizer_model": "gpt-4o",
                      "encoding": "o200k_base",
                      "expected_encoding": "o200k_base",
                      "tiktoken_available": True,
                      "reason": "test disagreement"})
    status, body = _call_post(app, "/build-room/harness/synthesis-call",
                              {"fixture": "fitting"})
    assert status == 200, body
    assert body["ok"] is False
    assert body["generated"] is False
    assert body["candidate_gate_enabled"] is False
    assert body["model_tokenizer_agreement"]["agrees"] is False
    assert fake.calls == []


def test_b2_absent_key_visible_and_no_generation(app, monkeypatch):
    app.dependency_overrides[get_current_user] = lambda: OWNER
    monkeypatch.setattr(
        br_routes, "resolve_openai_participant",
        lambda principal: (None, "absent: no openai api key present for this principal"),
    )
    status, body = _call_post(app, "/build-room/harness/synthesis-call",
                              {"fixture": "fitting"})
    assert status == 200, body
    assert body["ok"] is False
    assert body["generated"] is False
    assert "absent" in body["absence"]
    assert body["candidate_gate"]["admitted"] is True
    assert "generations_used" not in body
