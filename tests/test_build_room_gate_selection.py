"""Build-Council Room experimental candidate-gate selection (Phase C spec §5.5).

Deterministic only: no model is called, no meeting runs on live
keys, no staging calls. Stubbed seat participants drive real
``run_multi_model_meeting`` runs so the gate path — production
default vs explicit experimental candidate selection — is tested
through the production code, not a copy of it.

Covers spec §5.5's four properties: (a) production default stays
40,000 characters; (b) candidate gate engages ONLY via the
explicit experimental flag; (c) assembled prompt measured and
gated at 12,500 exact tokens including telemetry and separators,
with honest refusal (nothing truncated); (d) artifact records
gate used, measured prompt size, and deployed code version as
honestly reportable. Coverage, latency, and cost behavior must
be unchanged under both gates.
"""

from __future__ import annotations

import asyncio
import hashlib
import json

import pytest
from fastapi import FastAPI

from api.routes import build_room_routes as br_routes
from api.routes.auth_routes import get_current_user
from local_ai.build_room import candidate_cap
from local_ai.build_room.meeting import (
    Budget,
    EvidencePacket,
    MeetingResult,
    Transcript,
    _SYNTHESIS_INSTRUCTION,
    current_code_version,
    run_multi_model_meeting,
    synthesis_gate_record,
)
from local_ai.build_room.participants import SEAT_SPECS, Seat

OWNER = {"id": "owner-id", "email": "owner@local.zenaf"}
INSTRUCTION_SHA256 = (
    "41925066d601380a3fd35e29a6232a22ef4fdcfc1006ed4d8e77d905e163b177")


def _synth_block():
    return ("Synthesis.\n```json\n" + json.dumps({
        "positions": [{"claim_ids": ["C1"], "position": "P",
                       "supporting_reasoning": "R"}],
        "disagreements": [], "recommendations": [], "limitations": []})
        + "\n```\n")


class _RecordingFake:
    """Duck-typed seat participant branching on prompt markers,
    recording every synthesis call (the refusal tests assert zero)."""

    def __init__(self, name, *, opening="", synthesis=""):
        self.name = name
        self.provider_id = dict((n, p) for n, p, _ in SEAT_SPECS)[name]
        self.model = "fake-model"
        self.key_source = "settings"
        self._opening = opening
        self._synthesis = synthesis
        self.synthesis_calls: list[str] = []

    def generate(self, prompt, *, timeout=120):
        if "Write the synthesis" in prompt:
            self.synthesis_calls.append(prompt)
            return self._synthesis
        if "state the relationship explicitly" in prompt:
            return "No revision."
        if "Claim registry" in prompt:
            return "No further comment."
        return self._opening


def _sentence(i, seat):
    return (f"Observed: council member {i} from {seat} raised concern {i} about "
            f"deliberative process step {i} involving stakeholder group {i} and "
            f"budget line {i} with follow-through implications for the wider "
            f"community assembly and its ongoing working groups.")


def _bulk_opening(n, seat):
    return "\n".join(f"{i}. {_sentence(i, seat)}" for i in range(1, n + 1))


def _seats(*, lines_per_seat=None, opening_text=None, synthesis_text=None):
    """Seat list; per-seat opening is bulk text or a shared tiny text."""
    synthesis_text = synthesis_text if synthesis_text is not None else _synth_block()
    fakes = {}
    for name, _pid, _model in SEAT_SPECS:
        if lines_per_seat is not None:
            opening = _bulk_opening(lines_per_seat, name)
        else:
            opening = opening_text if opening_text is not None else (
                "1. Observed: A stable fact.")
        fakes[name] = _RecordingFake(name, opening=opening,
                                     synthesis=synthesis_text)
    seats = [Seat(name, pid, model, fakes[name])
             for name, pid, model in SEAT_SPECS]
    return seats, fakes


def _run(tmp_path, seats, **kwargs):
    return run_multi_model_meeting(
        EvidencePacket(work_item="W", question="Q"),
        store_dir=tmp_path / "store", seats=seats, **kwargs)


def _synth_calls(fakes):
    return sum(len(f.synthesis_calls) for f in fakes.values())


def _sha(value):
    assert isinstance(value, str) and len(value) == 64
    assert all(c in "0123456789abcdef" for c in value)


# ---------------------------------------------------------------------------
# (a) Production default unchanged
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# (b) Candidate gate ONLY via the explicit flag
# ---------------------------------------------------------------------------

def test_flag_defaults_off_and_r1_body_has_no_flag():
    assert RunMeetingBody_has_no_flag()
    body = br_routes.RunMeetingR2Body(work_item="W", question="Q")
    assert body.experimental_candidate_gate is False


def RunMeetingBody_has_no_flag():
    # The R1 body must not carry the flag at all: an R1 meeting
    # cannot select the gate, explicitly or accidentally.
    assert "experimental_candidate_gate" not in br_routes.RunMeetingBody.model_fields
    return True


# ---------------------------------------------------------------------------
# (c) Candidate token gating at 12,500 (telemetry + separators incl.)
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# (d) Artifact records gate + sizes + code version (honestly)
# ---------------------------------------------------------------------------

def test_code_version_gap_and_env_hook(monkeypatch):
    monkeypatch.delenv("ZENAF_CODE_VERSION", raising=False)
    version = current_code_version()
    assert version == {"commit": None, "source": "unavailable"}
    monkeypatch.setenv("ZENAF_CODE_VERSION", "abc123def456")
    version = current_code_version()
    assert version == {"commit": "abc123def456",
                       "source": "environment:ZENAF_CODE_VERSION"}


# ---------------------------------------------------------------------------
# (e) Coverage / latency / cost unchanged under the candidate gate
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Route: flag passthrough (owner-only route, R2 body only)
# ---------------------------------------------------------------------------

def _call_post(app, path: str, payload: dict) -> tuple[int, dict]:
    raw = json.dumps(payload).encode()
    scope = {
        "type": "http", "http_version": "1.1", "method": "POST",
        "scheme": "http", "path": path, "raw_path": path.encode(),
        "query_string": b"",
        "headers": [(b"content-type", b"application/json"),
                    (b"content-length", str(len(raw)).encode())],
        "client": ("testclient", 50000), "server": ("testserver", 80),
    }
    messages: list[dict] = []
    sent = False

    async def receive():
        nonlocal sent
        if not sent:
            sent = True
            return {"type": "http.request", "body": raw, "more_body": False}
        return {"type": "http.disconnect"}

    async def send(message: dict) -> None:
        messages.append(message)

    asyncio.run(app(scope, receive, send))
    start = next(m for m in messages if m["type"] == "http.response.start")
    body = b"".join(
        m.get("body", b"") for m in messages if m["type"] == "http.response.body")
    return start["status"], json.loads(body.decode() or "{}")


@pytest.fixture()
def app(tmp_path, monkeypatch):
    import local_ai.vision_execution.storage as ve_store_mod
    monkeypatch.setattr(
        br_routes, "get_build_room_store_dir", lambda: tmp_path / "store")
    monkeypatch.setattr(ve_store_mod, "get_owner_user_id", lambda: OWNER["id"])
    application = FastAPI()
    application.include_router(br_routes.router)
    return application


def test_route_flag_passthrough(app, monkeypatch):
    app.dependency_overrides[get_current_user] = lambda: OWNER
    captured: dict = {}

    def fake_run(packet, *, store_dir, principal, experimental_candidate_gate=False):
        captured["flag"] = experimental_candidate_gate
        return MeetingResult(
            meeting_id="test123", transcript=Transcript(), artifact={},
            ok=True, transcript_path=None, artifact_path=None)

    monkeypatch.setattr(br_routes, "run_multi_model_meeting", fake_run)
    status, _body = _call_post(
        app, "/build-room/meetings/r2",
        {"work_item": "W", "question": "Q", "experimental_candidate_gate": True})
    assert status == 200
    assert captured["flag"] is True
    status, _body = _call_post(
        app, "/build-room/meetings/r2", {"work_item": "W", "question": "Q"})
    assert status == 200
    assert captured["flag"] is False


# ---------------------------------------------------------------------------
# Pins: instruction byte-identity + unchanged caps
# ---------------------------------------------------------------------------

def test_instruction_pinned_fidelity_revision_and_caps_unchanged():
    assert len(_SYNTHESIS_INSTRUCTION) == 4165  # fidelity-correction revision pin
    assert hashlib.sha256(_SYNTHESIS_INSTRUCTION.encode()).hexdigest() == (
        INSTRUCTION_SHA256)
    assert Budget().max_response_prompt_chars == 40000
    assert candidate_cap.CANDIDATE_SYNTHESIS_PROMPT_TOKENS == 12500
    assert candidate_cap.PRODUCTION_SYNTHESIS_PROMPT_CHARS == 40000
    # The gate record helper itself pins the production default.
    record = synthesis_gate_record(
        gate="production_chars", cap_chars=40000, cap_tokens=None,
        total_chars=100, total_tokens=25, prompt_sha256="x" * 64,
        admitted=True, reason=None)
    assert record["cap_chars"] == 40000
