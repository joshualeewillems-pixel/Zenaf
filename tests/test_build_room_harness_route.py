"""Harness-route endpoint tests: owner gate + fixture-only calls.

No httpx here, so like the runner tests these drive a minimal
FastAPI app through its ASGI interface directly. Generation is
mocked — no live API calls, no real key values anywhere. A fake
key value is used to prove it never leaks into responses.

The route under test (POST /build-room/harness/synthesis-call)
accepts ONLY a fixture selector ("D" or "E"), resolves GPT via the
production participant path, makes exactly ONE generation, and
evaluates the verbatim output with the production validator. No
persistence, no prompt text, no credentials in any response.
"""

from __future__ import annotations

import asyncio
import hashlib
import json

import pytest
from fastapi import FastAPI

from api.routes import build_room_routes as br_routes
from api.routes.auth_routes import get_current_user
from local_ai.build_room import harness_fixtures as hf
from local_ai.build_room.meeting import (
    _SYNTHESIS_INSTRUCTION,
    _telemetry_block,
    build_synthesis_state,
)

FAKE_KEY = "FAKE-KEY-VALUE-67890"
OWNER = {"id": "owner-id", "email": "owner@local.zenaf"}
OTHER = {"id": "someone-else"}

D_BLOCK = (
    "Narrative synthesis here.\n```json\n"
    + json.dumps({
        "positions": [{"claim_ids": ["C1"], "position": "Roles need revisability.",
                       "supporting_reasoning": "Grounded in C1 and C4."}],
        "disagreements": [{"opposing_positions": [
            "Assigned roles improve accountability.",
            "Open roles permit more substantive deliberation."],
            "supporting_claims": ["C1", "C2"],
            "unresolved_status": "unresolved"}],
        "recommendations": [],
        "limitations": []})
    + "\n```\n")

E_BLOCK = (
    "Narrative synthesis here.\n```json\n"
    + json.dumps({
        "positions": [{"claim_ids": ["C1"], "position": "Council recommends only.",
                       "supporting_reasoning": "Grounded in C1."}],
        "disagreements": [],
        "recommendations": [],
        "limitations": []})
    + "\n```\n")


def _call_post(app, path: str, payload: dict) -> tuple[int, dict]:
    """Drive a POST with a JSON body through the ASGI interface."""
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
    """Minimal app with only the build-room router.

    Store dir redirected to tmp_path; owner id stubbed so no real
    database is touched. Auth is overridden per test.
    """
    import local_ai.vision_execution.storage as ve_store_mod

    monkeypatch.setattr(
        br_routes, "get_build_room_store_dir", lambda: tmp_path / "store"
    )
    monkeypatch.setattr(ve_store_mod, "get_owner_user_id", lambda: OWNER["id"])
    application = FastAPI()
    application.include_router(br_routes.router)
    return application


class _FakeParticipant:
    """Records generate() calls; returns canned text, never a key."""

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


def _expected_prompt(fixture: str) -> str:
    packet, reg, unresolved, chains = hf.__dict__[
        "fixture_d_state" if fixture == "D" else "fixture_e_state"]()
    state = build_synthesis_state(packet, reg, unresolved, chains,
                                  cap_chars=40000)
    assert state["prompt"] is not None
    return state["prompt"] + "\n\n" + _telemetry_block(**hf.TELEMETRY)


def test_unauthenticated_is_401(app):
    status, _ = _call_post(app, "/build-room/harness/synthesis-call",
                           {"fixture": "D"})
    assert status == 401


def test_non_owner_is_403_and_no_generation(app, monkeypatch):
    app.dependency_overrides[get_current_user] = lambda: OTHER
    fake = _FakeParticipant(D_BLOCK)
    _mock_participant(monkeypatch, fake)
    status, _ = _call_post(app, "/build-room/harness/synthesis-call",
                           {"fixture": "D"})
    assert status == 403
    assert fake.calls == []


@pytest.mark.parametrize("bad", ["X", "d", "", "D ", "DD", "E1"])
def test_invalid_fixture_refused_and_no_generation(app, monkeypatch, bad):
    app.dependency_overrides[get_current_user] = lambda: OWNER
    fake = _FakeParticipant(D_BLOCK)
    _mock_participant(monkeypatch, fake)
    status, _ = _call_post(app, "/build-room/harness/synthesis-call",
                           {"fixture": bad})
    assert status == 422
    assert fake.calls == []


def test_missing_fixture_refused(app, monkeypatch):
    app.dependency_overrides[get_current_user] = lambda: OWNER
    fake = _FakeParticipant(D_BLOCK)
    _mock_participant(monkeypatch, fake)
    status, _ = _call_post(app, "/build-room/harness/synthesis-call", {})
    assert status == 422
    assert fake.calls == []


def test_owner_fixture_d_single_generation(app, monkeypatch, tmp_path):
    app.dependency_overrides[get_current_user] = lambda: OWNER
    fake = _FakeParticipant(D_BLOCK)
    _mock_participant(monkeypatch, fake)
    status, body = _call_post(app, "/build-room/harness/synthesis-call",
                              {"fixture": "D"})
    assert status == 200, body
    assert body["fixture_id"] == "D"
    assert body["ok"] is True
    assert body["generated"] is True
    assert body["generations_used"] == 1
    # Exactly one generation, with the production-assembled prompt.
    assert len(fake.calls) == 1
    sent_prompt, sent_timeout = fake.calls[0]
    assert sent_timeout == 120
    assert sent_prompt == _expected_prompt("D")
    # Verbatim output + production evaluation, kept separate.
    assert body["raw"] == D_BLOCK
    assert body["evaluations"]["disagreements"] == "synthesized_complete"
    assert body["evaluations"]["recommendations"] == "synthesized_empty"
    assert body["block_found"] is True
    assert body["disclosure_notes"]["disagreements_note"] is False
    # Hash + sizes, measured from production objects.
    assert body["prompt_sha256"] == hashlib.sha256(
        sent_prompt.encode()).hexdigest()
    assert body["assembled_prompt_chars"] == len(sent_prompt)
    assert body["state_prompt_chars"] <= 40000
    assert body["telemetry_chars"] == len(sent_prompt) - body["state_prompt_chars"]
    assert body["cap"] == 40000
    assert 0 < body["disclosure_chars"] < body["state_prompt_chars"]
    assert body["mandatory_chars"] < body["state_prompt_chars"]
    # No prompt text, no credentials, no credential-shaped keys.
    assert "prompt" not in body
    assert _SYNTHESIS_INSTRUCTION not in json.dumps(body)
    assert FAKE_KEY not in json.dumps(body)
    assert not any(k in ("api_key", "password", "token", "secret")
                   for k in body)
    # No persistence: the route writes no meeting artifacts.
    assert list((tmp_path / "store").glob("meeting_*.transcript.json")) == []


def test_owner_fixture_e_legitimate_empties(app, monkeypatch):
    app.dependency_overrides[get_current_user] = lambda: OWNER
    fake = _FakeParticipant(E_BLOCK)
    _mock_participant(monkeypatch, fake)
    status, body = _call_post(app, "/build-room/harness/synthesis-call",
                              {"fixture": "E"})
    assert status == 200, body
    assert body["fixture_id"] == "E"
    assert body["ok"] is True
    assert len(fake.calls) == 1
    assert fake.calls[0][0] == _expected_prompt("E")
    assert body["raw"] == E_BLOCK
    assert body["evaluations"]["recommendations"] == "synthesized_empty"
    assert body["evaluations"]["limitations"] == "synthesized_empty"
    assert body["disclosure_notes"]["limitations_note"] is False
    assert FAKE_KEY not in json.dumps(body)


def test_absent_key_visible_and_no_generation(app, monkeypatch):
    app.dependency_overrides[get_current_user] = lambda: OWNER
    monkeypatch.setattr(
        br_routes, "resolve_openai_participant",
        lambda principal: (None, "absent: no openai api key present for this principal"),
    )
    status, body = _call_post(app, "/build-room/harness/synthesis-call",
                              {"fixture": "D"})
    assert status == 200, body
    assert body["ok"] is False
    assert body["generated"] is False
    assert "absent" in body["absence"]
    assert "generations_used" not in body
    # Prompt hash + sizes still reported; nothing generated.
    assert body["prompt_sha256"] == hashlib.sha256(
        _expected_prompt("D").encode()).hexdigest()
    assert body["state_prompt_chars"] <= 40000
    assert FAKE_KEY not in json.dumps(body)


def test_generation_failure_visible_not_a_crash(app, monkeypatch):
    app.dependency_overrides[get_current_user] = lambda: OWNER

    class _Failing:
        def generate(self, prompt: str, *, timeout: int = 120) -> str:
            raise RuntimeError("provider unavailable")

    monkeypatch.setattr(
        br_routes, "resolve_openai_participant",
        lambda principal: (_Failing(), ""),
    )
    status, body = _call_post(app, "/build-room/harness/synthesis-call",
                              {"fixture": "E"})
    assert status == 200, body
    assert body["ok"] is False
    assert body["generated"] is False
    assert "provider unavailable" in body["generation_error"]
    assert FAKE_KEY not in json.dumps(body)


def test_route_fixtures_are_the_harness_fixtures():
    """The route MUST construct the PR #227 states, not a copy."""
    assert br_routes.HARNESS_FIXTURE_BUILDERS["D"] is hf.fixture_d_state
    assert br_routes.HARNESS_FIXTURE_BUILDERS["E"] is hf.fixture_e_state
    for fid, builder in (("D", hf.fixture_d_state),
                         ("E", hf.fixture_e_state)):
        packet, reg, unresolved, chains = builder()
        packet2, reg2, unresolved2, chains2 = (
            br_routes.HARNESS_FIXTURE_BUILDERS[fid]())
        assert packet.work_item == packet2.work_item
        assert packet.question == packet2.question
        assert tuple(packet.constraints) == tuple(packet2.constraints)
        assert [(c.id, c.participant, c.status, c.text)
                for c in reg.claims] == [
            (c.id, c.participant, c.status, c.text)
            for c in reg2.claims]
        assert unresolved == unresolved2
        assert chains == chains2


def test_disclosure_notes_parity_with_harness_helper():
    """Route disclosure conditions match the harness helper exactly."""
    import tests.test_build_room_synthesis_harness as harness

    shapes = [
        ({"disagreements": "synthesized_empty",
          "limitations": "synthesized_empty"},
         [{"state": "unresolved"}], {"superseded_texts": 0,
                                        "responded_to_details": 0}),
        ({"disagreements": "synthesized_complete",
          "limitations": "synthesized_empty"},
         [], {"superseded_texts": 2, "responded_to_details": 1}),
        ({"disagreements": "synthesized_empty",
          "limitations": "synthesized_empty"},
         [], None),
    ]
    for evaluations, unresolved, omitted in shapes:
        assert br_routes._harness_disclosure_notes(
            evaluations, unresolved, omitted) == harness.disclosure_notes(
            evaluations, unresolved, omitted, False)
