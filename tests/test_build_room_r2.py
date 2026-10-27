"""R2 tests: multi-participant deliberation.

Generation is mocked — no live API calls, no real key values anywhere.
Fake participants branch on prompt markers (the same markers real
models would see): synthesis / follow-up / registry-bearing response /
plain opening. No role labels appear in prompts, code, or tests.
"""

from __future__ import annotations

import asyncio
import json
import time

import pytest
from fastapi import FastAPI

from api.routes import build_room_routes as br_routes
from api.routes.auth_routes import get_current_user
from local_ai.build_room import meeting as meeting_mod
from local_ai.build_room.meeting import (
    Budget,
    EvidencePacket,
    run_multi_model_meeting,
)
from local_ai.build_room.participants import SEAT_SPECS, Seat

FAKE_KEY = "FAKE-KEY-R2-12345"
NAMES = [name for name, _, _ in SEAT_SPECS]


class FakeParticipant:
    """Duck-typed seat participant: generate(prompt, timeout=...)."""

    def __init__(self, name, *, opening="", response="", revision="",
                 synthesis="", delay=0.0, boom=False):
        self.name = name
        self.provider_id = dict((n, p) for n, p, _ in SEAT_SPECS)[name]
        self.model = "fake-model"
        self.key_source = "settings"
        self._texts = {
            "synthesis": synthesis,
            "revision": revision,
            "response": response,
            "opening": opening,
        }
        self.delay = delay
        self.boom = boom
        self.prompts: list[str] = []

    def generate(self, prompt, *, timeout=120):
        self.prompts.append(prompt)
        if self.delay:
            time.sleep(self.delay)
        if self.boom:
            raise RuntimeError("provider exploded")
        if "Write the synthesis" in prompt:
            return self._texts["synthesis"]
        if "state the relationship explicitly" in prompt:
            return self._texts["revision"]
        if "Claim registry" in prompt:
            return self._texts["response"]
        return self._texts["opening"]


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


def _read(path):
    return path.read_text(encoding="utf-8")


def _kinds(result):
    return [e.kind for e in result.transcript.entries]


def _registry(result):
    return result.artifact["claim_registry"]


def test_full_meeting_registers_claims_in_stable_order(tmp_path):
    fakes = {
        "GPT": FakeParticipant(
            "GPT",
            opening="1. Inferred: Authority confusion is a failure mode.\n2. Proposed: Keep authorization with Joshua.",
            response="In response to C3, I agree: the registry point stands.",
            revision="Relationship: defended.\nIn response to C1, I defend my claim:\n"
                     "1. Inferred: Authority confusion remains the top risk.",
        ),
        "Claude": FakeParticipant(
            "Claude",
            opening="1. Inferred: Parallel monologues are a failure mode.",
            response="1. Objection to C1: authorization alone does not "
                     "prevent a synthesis from misrepresenting choices.",
            synthesis=(
                "Synthesis of the deliberation.\n"
                "Positions:\n"
                "- C1, C2: Authority must stay with Joshua.\n"
                "Disagreements:\n"
                "- C1 vs C3: whether the registry alone prevents confusion.\n"
            ),
        ),
        "Gemini": FakeParticipant("Gemini", opening="1. Proposed: Add addressable claims."),
        "Grok": FakeParticipant("Grok", opening="1. Speculative: The room may perform deliberation."),
        "Muse": FakeParticipant("Muse", opening="1. Inferred: Cost grows with participants."),
    }
    result = run_multi_model_meeting(_packet(), store_dir=tmp_path, seats=_seats(fakes))
    assert result.ok is True
    reg = _registry(result)
    # Stable order: GPT's opening claims first, then Claude, Gemini, Grok, Muse.
    assert reg[0]["id"] == "C1" and reg[0]["participant"] == "GPT"
    assert reg[1]["participant"] == "GPT"
    assert reg[2]["participant"] == "Claude"
    assert [c["participant"] for c in reg if c["phase"] == "opening"] == [
        "GPT", "GPT", "Claude", "Gemini", "Grok", "Muse"]
    assert "convene" == _kinds(result)[0]
    assert result.transcript.entries[0].participant == "Reynard (convener)"
    # Response interaction: Claude's numbered, explicitly targeted
    # objection to C1 (C6: other-author citation + targeted move).
    claude_resp = [i for i in result.artifact["interactions"]
                   if i["participant"] == "Claude" and i["phase"] == "response"][0]
    assert claude_resp["cited_claim_ids"] == ["C1"]
    assert "objection" in claude_resp["stated_moves"]
    assert claude_resp["addressable"] is True
    # Revision: GPT defended C1 — links without replacing.
    rev = [c for c in reg if c["phase"] == "revision"][0]
    assert rev["relationship"] == "defended"
    assert rev["supersedes"] is None
    assert "C1" in rev["relates_to"]
    assert reg[0]["text"] == "Inferred: Authority confusion is a failure mode."
    # Synthesis: attributed positions/disagreements, unresolved, verbatim text.
    assert result.artifact["synthesis"]["status"] == "complete"
    assert result.artifact["synthesis"]["attributed_to"] == "Claude"
    assert "Synthesis of the deliberation." in result.artifact["synthesis"]["text"]
    pos = result.artifact["positions"]
    assert pos and pos[0]["attributed_to"] == "Claude"
    assert pos[0]["claim_ids"] == ["C1", "C2"]
    dis = result.artifact["disagreements"]
    assert dis and dis[0]["status"] == "unresolved"
    assert dis[0]["claim_ids"] == ["C1", "C3"]
    assert dis[0]["attributed_to"] == "Claude"
    # Artifact boundaries kept.
    assert result.artifact["status"] == "DRAFT_EXPERIMENTAL"
    assert result.artifact["is_review_item"] is False
    assert "RECOMMENDS ONLY" in result.artifact["authorization"]
    assert "model-authored" in result.artifact["claims_note"]
    assert "English" in result.artifact["language_note"]
    # Usage lines carry phase + citations; no fake key anywhere.
    usage = [_l for _l in (tmp_path / "usage.jsonl").read_text().splitlines()]
    by_phase = {}
    for line in usage:
        row = json.loads(line)
        assert row["operation"] == "build_room_r2_meeting"
        assert row["token_usage"] == "unavailable"
        by_phase.setdefault(row["phase"], []).append(row)
    assert set(by_phase) >= {"opening", "response", "revision", "synthesis"}
    resp_rows = [r for r in by_phase["response"] if r["participant"] == "Claude"]
    assert resp_rows and resp_rows[0]["cited_claim_ids"] == ["C1"]
    for path in (result.transcript_path, result.artifact_path, tmp_path / "usage.jsonl"):
        assert FAKE_KEY not in _read(path)


def test_deterministic_order_under_parallel_completion(tmp_path):
    # GPT finishes last but must still register first.
    fakes = {
        "GPT": FakeParticipant("GPT", opening="1. Inferred: First claim.", delay=0.3),
        "Claude": FakeParticipant("Claude", opening="1. Inferred: Second claim."),
        "Gemini": FakeParticipant("Gemini", opening="1. Inferred: Third claim."),
        "Grok": FakeParticipant("Grok", opening="1. Inferred: Fourth claim."),
        "Muse": FakeParticipant("Muse", opening="1. Inferred: Fifth claim."),
    }
    # Synthesis must exist for ok, but ordering is decided at openings.
    fakes["Claude"]._texts["synthesis"] = "Synthesis.\nPositions:\n- C1: first.\n"
    started = time.time()
    result = run_multi_model_meeting(_packet(), store_dir=tmp_path, seats=_seats(fakes))
    elapsed = time.time() - started
    reg = [c for c in _registry(result) if c["phase"] == "opening"]
    assert [c["participant"] for c in reg] == NAMES
    assert [c["id"] for c in reg] == ["C1", "C2", "C3", "C4", "C5"]
    # Parallel: wall time near the slowest call, not the sum.
    assert elapsed < 2.0


def test_dead_citation_and_zero_claims_noted(tmp_path):
    fakes = {
        "GPT": FakeParticipant("GPT", opening="1. Inferred: Real claim."),
        "Claude": FakeParticipant(
            "Claude", opening="1. Inferred: Another claim.",
            response="In response to C999, I object: this ID does not exist.",
            synthesis="Synthesis."),
        "Gemini": FakeParticipant("Gemini", opening="No numbered claims here."),
        "Grok": FakeParticipant("Grok", opening="1. Inferred: Third."),
        "Muse": FakeParticipant("Muse", opening="1. Inferred: Fourth."),
    }
    result = run_multi_model_meeting(_packet(), store_dir=tmp_path, seats=_seats(fakes))
    notes = [e.text for e in result.transcript.entries if e.kind == "note"]
    assert any("C999" in n and "does not exist" in n for n in notes)
    assert any("zero claims" in n and "Gemini" in n for n in notes)
    claude_resp = [i for i in result.artifact["interactions"]
                   if i["participant"] == "Claude" and i["phase"] == "response"][0]
    assert claude_resp["cited_claim_ids"] == []
    assert claude_resp["dead_citations"] == ["C999"]
    assert claude_resp["addressable"] is False


def test_name_mention_without_citation_not_addressable(tmp_path):
    fakes = {
        "GPT": FakeParticipant("GPT", opening="1. Inferred: Real claim."),
        "Claude": FakeParticipant(
            "Claude", opening="1. Inferred: Another claim.",
            response="As GPT noted, I agree with the general direction.",
            synthesis="Synthesis."),
        "Gemini": FakeParticipant("Gemini", opening="1. Inferred: Third."),
        "Grok": FakeParticipant("Grok", opening="1. Inferred: Fourth."),
        "Muse": FakeParticipant("Muse", opening="1. Inferred: Fifth."),
    }
    result = run_multi_model_meeting(_packet(), store_dir=tmp_path, seats=_seats(fakes))
    claude_resp = [i for i in result.artifact["interactions"]
                   if i["participant"] == "Claude" and i["phase"] == "response"][0]
    assert claude_resp["cited_claim_ids"] == []
    assert claude_resp["addressable"] is False


def test_revision_relationships_revised_defended_withdrawn(tmp_path):
    # Openings (1 claim each, stable order): GPT=C1, Claude=C2,
    # Gemini=C3, Grok=C4, Muse=C5.
    fakes = {
        "GPT": FakeParticipant(
            "GPT", opening="1. Inferred: Alpha.",
            revision="Relationship: defended.\nIn response to C1, I defend:\n"
                     "1. Inferred: Alpha stands."),
        "Claude": FakeParticipant(
            "Claude", opening="1. Inferred: Beta.",
            synthesis="Synthesis.",
            response="In response to C1, I object: alpha is overstated. "
                     "In response to C4, I object: delta is unproven.",
            revision="Relationship: revised.\nIn response to C2, I revise:\n"
                     "1. Inferred: Beta, qualified."),
        "Gemini": FakeParticipant(
            "Gemini", opening="1. Inferred: Gamma.",
            response="In response to C2, I object: beta needs evidence.",
            revision="Relationship: withdrawn.\nIn response to C3, I withdraw it:\n"
                     "1. Withdrawn: Gamma is retracted."),
        "Grok": FakeParticipant(
            "Grok", opening="1. Inferred: Delta.",
            response="In response to C3, I object: gamma is speculative.",
            revision=""),  # invited (C4 objected) but passes: empty follow-up
        "Muse": FakeParticipant("Muse", opening="1. Inferred: Epsilon."),
    }
    result = run_multi_model_meeting(_packet(), store_dir=tmp_path, seats=_seats(fakes))
    reg = _registry(result)
    revs = {c["participant"]: c for c in reg if c["phase"] == "revision"}
    assert revs["GPT"]["relationship"] == "defended"
    assert revs["GPT"]["supersedes"] is None
    assert "C1" in revs["GPT"]["relates_to"]
    assert revs["Claude"]["relationship"] == "revised"
    assert revs["Claude"]["supersedes"] == "C2"
    assert revs["Gemini"]["relationship"] == "withdrawn"
    assert revs["Gemini"]["withdraws"] == "C3"
    # Originals stay in the registry, untouched.
    assert reg[0]["id"] == "C1" and reg[1]["id"] == "C2" and reg[2]["id"] == "C3"
    # C4 drew a prose objection (Claude) with no parseable numbered
    # spans, so under C5 it is an unclassified interaction — recorded
    # with its citations, never promoted into unresolved_objections —
    # even though Grok's follow-up related to nothing. Same for C1.
    unresolved = {u["claim_id"] for u in result.artifact["unresolved_objections"]}
    assert "C4" not in unresolved
    assert "C1" not in unresolved
    claude_resp = [i for i in result.artifact["interactions"]
                   if i["participant"] == "Claude" and i["phase"] == "response"][0]
    assert claude_resp["classification"] == "unclassified"
    assert claude_resp["cited_claim_ids"] == ["C1", "C4"]
    assert "objection" in claude_resp["stated_moves"]


def test_disagreement_preservation_no_collapse(tmp_path):
    fakes = {
        "GPT": FakeParticipant(
            "GPT", opening="1. Inferred: Alpha."),
        "Claude": FakeParticipant(
            "Claude", opening="1. Inferred: Beta.",
            response="In response to C1, I object: alpha conflicts with beta.",
            synthesis=(
                "Synthesis.\n"
                "Positions:\n"
                "- C1: Alpha position.\n"
                "- C2: Beta position.\n"
                "Disagreements:\n"
                "- C1 vs C2: alpha and beta conflict.\n"
            )),
        "Gemini": FakeParticipant("Gemini", opening="1. Inferred: Gamma."),
        "Grok": FakeParticipant("Grok", opening="1. Inferred: Delta."),
        "Muse": FakeParticipant("Muse", opening="1. Inferred: Epsilon."),
    }
    result = run_multi_model_meeting(_packet(), store_dir=tmp_path, seats=_seats(fakes))
    # Both positions survive alongside the synthesis; nothing resolved.
    assert len(result.artifact["positions"]) == 2
    assert len(result.artifact["disagreements"]) == 1
    assert result.artifact["disagreements"][0]["status"] == "unresolved"
    assert result.artifact["synthesis"]["text"].startswith("Synthesis.")
    assert not any(d.get("status") == "resolved"
                   for d in result.artifact["disagreements"])


def test_synthesis_overflow_visible_not_truncated(tmp_path):
    fakes = {
        name: FakeParticipant(name, opening="1. Inferred: Some claim with substance.",
                              synthesis="Synthesis.")
        for name in NAMES
    }
    budget = Budget(max_contributions=16, max_prompt_chars=20000,
                    max_response_prompt_chars=100)
    result = run_multi_model_meeting(_packet(), store_dir=tmp_path,
                                     seats=_seats(fakes), budget=budget)
    assert result.ok is False
    assert result.artifact["synthesis"]["status"] == "INCOMPLETE"
    assert result.artifact["synthesis"]["text"] is None
    assert "budget_exceeded" in result.artifact["synthesis"]["reason"]
    failures = [e.text for e in result.transcript.entries if e.kind == "failure"]
    assert any("budget_exceeded" in f and "synthesis" in f for f in failures)
    # The complete transcript is preserved regardless of prompt limits.
    persisted = json.loads(_read(result.transcript_path))
    assert len(persisted["entries"]) == len(result.transcript.entries)
    assert any(e["kind"] == "contribution" for e in persisted["entries"])


def test_failure_isolation_one_provider_down(tmp_path):
    # The failing seat must not be the synthesizer seat: with Claude
    # synthesizing, a down Claude takes synthesis down with it, so
    # isolation is demonstrated with Gemini down instead.
    fakes = {
        "GPT": FakeParticipant("GPT", opening="1. Inferred: Alpha."),
        "Claude": FakeParticipant("Claude", opening="1. Inferred: Beta.",
                                   synthesis="Synthesis."),
        "Gemini": FakeParticipant("Gemini", opening="", boom=True),
        "Grok": FakeParticipant("Grok", opening="1. Inferred: Delta."),
        "Muse": FakeParticipant("Muse", opening="1. Inferred: Epsilon."),
    }
    result = run_multi_model_meeting(_packet(), store_dir=tmp_path, seats=_seats(fakes))
    assert result.ok is True
    failures = [(e.participant, e.text) for e in result.transcript.entries
                if e.kind == "failure"]
    # Gemini fails in every phase it is called in; no other participant
    # is affected — that is failure isolation.
    assert failures and all(p == "Gemini" for p, _ in failures)
    assert all("RuntimeError" in text for _, text in failures)
    assert any(c["participant"] == "GPT" for c in _registry(result))
    assert not any(c["participant"] == "Gemini" for c in _registry(result))


def test_absence_recorded_meeting_continues(tmp_path):
    # The absent seat must not be the synthesizer seat: with Claude
    # synthesizing, an absent Claude means no synthesis runs.
    fakes = {
        "GPT": FakeParticipant("GPT", opening="1. Inferred: Alpha."),
        "Claude": FakeParticipant("Claude", opening="1. Inferred: Beta.",
                                   synthesis="Synthesis."),
        "Gemini": None,  # absent
        "Grok": FakeParticipant("Grok", opening="1. Inferred: Delta."),
        "Muse": FakeParticipant("Muse", opening="1. Inferred: Epsilon."),
    }
    result = run_multi_model_meeting(_packet(), store_dir=tmp_path, seats=_seats(fakes))
    assert result.ok is True
    assert any(e.kind == "absence" and e.participant == "Gemini"
               for e in result.transcript.entries)
    assert any(e.kind == "note" and "did not respond" in e.text
               and e.participant == "Gemini" for e in result.transcript.entries)
    prov = {p["participant"]: p for p in result.artifact["provenance"]}
    assert prov["Gemini"]["status"] == "absent"
    assert prov["GPT"]["status"] == "present"


def test_all_absent_meeting_fails_cleanly(tmp_path):
    seats = _seats({name: None for name in NAMES})
    result = run_multi_model_meeting(_packet(), store_dir=tmp_path, seats=seats)
    assert result.ok is False
    assert result.artifact["synthesis"] is None
    assert "no opening contributions" in (result.artifact["synthesis_failure"] or "")
    # No contributions beyond absences/failures; the convenor's
    # telemetry note (C8) is metadata, not a contribution.
    assert all(e.kind in ("convene", "absence", "failure", "note")
               for e in result.transcript.entries)


def test_generation_budget_cap_respected(tmp_path):
    fakes = {name: FakeParticipant(name, opening="1. Inferred: Claim.",
                                    synthesis="Synthesis.")
             for name in NAMES}
    budget = Budget(max_contributions=2, max_prompt_chars=20000,
                    max_response_prompt_chars=40000)
    result = run_multi_model_meeting(_packet(), store_dir=tmp_path,
                                     seats=_seats(fakes), budget=budget)
    assert result.ok is False
    contributions = [e for e in result.transcript.entries if e.kind == "contribution"]
    assert len(contributions) == 2  # GPT + Claude openings only
    assert any("budget_exceeded" in e.text for e in result.transcript.entries
               if e.kind == "failure")


def test_no_role_labels_in_prompts(tmp_path):
    fakes = {name: FakeParticipant(name, opening="1. Inferred: Claim.",
                                    response="In response to C1, I agree.",
                                    revision="Relationship: defended. In response to C1, I defend: 1. Inferred: stands.",
                                    synthesis="Synthesis.")
             for name in NAMES}
    result = run_multi_model_meeting(_packet(), store_dir=tmp_path, seats=_seats(fakes))
    banned = ("Weaver", "Firebrand", "Champion", "Guardian", "Ambassador",
              "Conductor", "Skeptic", "Gardener", "Bear", "Raven", "Crane")
    for fake in fakes.values():
        for prompt in fake.prompts:
            for label in banned:
                assert label not in prompt
    assert result.transcript.entries[0].participant == "Reynard (convener)"


def test_synthesis_prompt_requires_english(tmp_path):
    fakes = {name: FakeParticipant(name, opening="1. Inferred: Claim.",
                                    synthesis="Synthesis.")
             for name in NAMES}
    result = run_multi_model_meeting(_packet(), store_dir=tmp_path, seats=_seats(fakes))
    claude = fakes["Claude"]
    synth_prompts = [p for p in claude.prompts if "Write the synthesis" in p]
    assert len(synth_prompts) == 1
    assert "Write the synthesis in English" in synth_prompts[0]


# --- Endpoint: POST /build-room/meetings/r2 ---

OWNER = {"id": "owner-id", "email": "owner@local.zenaf"}
OTHER = {"id": "someone-else"}


def _call_post(app, path: str, payload: dict) -> tuple[int, dict]:
    raw = json.dumps(payload).encode()
    scope = {
        "type": "http", "http_version": "1.1", "method": "POST", "scheme": "http",
        "path": path, "raw_path": path.encode(), "query_string": b"",
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
    body = b"".join(m.get("body", b"") for m in messages if m["type"] == "http.response.body")
    return start["status"], json.loads(body.decode() or "{}")


@pytest.fixture()
def app(tmp_path, monkeypatch):
    import local_ai.vision_execution.storage as ve_store_mod

    monkeypatch.setattr(br_routes, "get_build_room_store_dir", lambda: tmp_path / "store")
    monkeypatch.setattr(ve_store_mod, "get_owner_user_id", lambda: OWNER["id"])
    application = FastAPI()
    application.include_router(br_routes.router)
    return application


def _body() -> dict:
    return {"work_item": "Test work item",
            "question": "What would make the Build-Council Room fail to function as a genuine deliberative council?",
            "excerpts": ["excerpt one"],
            "constraints": ["room deliberates, never decides"],
            "source_refs": ["local_ai/build_room/meeting.py"]}


def test_r2_unauthenticated_is_401(app):
    status, _ = _call_post(app, "/build-room/meetings/r2", _body())
    assert status == 401


def test_r2_non_owner_is_403(app):
    app.dependency_overrides[get_current_user] = lambda: OTHER
    status, _ = _call_post(app, "/build-room/meetings/r2", _body())
    assert status == 403


def test_r2_owner_runs_meeting_persists_files(app, tmp_path, monkeypatch):
    app.dependency_overrides[get_current_user] = lambda: OWNER
    fakes = {name: FakeParticipant(name, opening="1. Inferred: Claim.",
                                    synthesis="Synthesis.")
             for name in NAMES}
    monkeypatch.setattr(meeting_mod, "resolve_seat_participants",
                        lambda principal: _seats(fakes))
    status, body = _call_post(app, "/build-room/meetings/r2", _body())
    assert status == 200, body
    assert body["ok"] is True
    assert body["artifact"]["status"] == "DRAFT_EXPERIMENTAL"
    assert body["artifact"]["is_review_item"] is False
    assert len(body["artifact"]["claim_registry"]) == 5
    assert body["artifact"]["synthesis"]["status"] == "complete"
    assert FAKE_KEY not in json.dumps(body)
    store = tmp_path / "store"
    assert list(store.glob("meeting_*.transcript.json"))
    assert list(store.glob("meeting_*.draft_artifact.json"))


def test_r2_caller_account_principal_is_used(app, tmp_path, monkeypatch):
    app.dependency_overrides[get_current_user] = lambda: OWNER
    seen: dict = {}

    def fake_run(packet, *, store_dir, budget=None, principal=None, seats=None,
                 experimental_candidate_gate=False):
        from local_ai.build_room.meeting import MeetingResult, Transcript
        seen["principal"] = principal
        seen["store_dir"] = str(store_dir)
        seen["experimental_candidate_gate"] = experimental_candidate_gate
        return MeetingResult(meeting_id="m1", transcript=Transcript(),
                             artifact={"status": "DRAFT_EXPERIMENTAL"}, ok=True,
                             transcript_path=tmp_path / "t.json",
                             artifact_path=tmp_path / "a.json")

    monkeypatch.setattr(br_routes, "run_multi_model_meeting", fake_run)
    status, body = _call_post(app, "/build-room/meetings/r2", _body())
    assert status == 200, body
    principal = seen["principal"]
    assert principal.account_user_id == OWNER["id"]
    assert principal.scope == "account"
    assert seen["store_dir"] == str(tmp_path / "store")
    # Default body carries no flag: the route must pass False.
    assert seen["experimental_candidate_gate"] is False
