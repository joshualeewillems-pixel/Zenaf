"""Meeting impressions land in review — the Weaver's promise, kept.

Semantics under test:
  - When a keystone-1 meeting completes, exactly one "meeting_impression"
    claim is filed for it: inference = the read-back with weave markers
    stripped, evidence = the user's answer verbatim, detail = both full
    texts plus the strands the read-back named.
  - The claim hangs off a ConnectedAgent anchored to the meeting's
    transcript id ("meeting-conductor-1"), sorted under the read-back's
    strands — which is what places it in the seat's review group.
  - Filing is idempotent per run: re-entering a completed meeting never
    duplicates the claim and never resets a verdict. A replay files a
    NEW claim for the new run; the archived run's claim and verdict stay.
  - A verdict on the claim lands training signals through the same
    claim-feedback machinery as every other claim — one signal per
    read-back strand, zoned to that strand.
"""

from __future__ import annotations

import threading
from pathlib import Path

import pytest

from local_ai.agent_intake.pipeline import log_claim_feedback
from local_ai.agent_intake.store import AgentStore
from local_ai.conversation.meeting import MeetingService, MeetingStore
from local_ai.conversation.store import ConversationStore
from local_ai.presence_ingest.store import PresenceStore
from local_ai.vision_execution import keystone_seeding
from local_ai.vision_execution import service as ve


@pytest.fixture()
def ve_ctx(tmp_path, monkeypatch):
    """Isolate the vision-execution SQLite DB per test."""
    import local_ai.vision_execution.storage as ve_store

    monkeypatch.setattr(ve_store, "_DB_PATH", tmp_path / "ve.db")
    monkeypatch.setattr(ve_store, "_DB_DIR", tmp_path)
    monkeypatch.setattr(ve_store, "_init_done_paths", set())
    monkeypatch.setattr(ve_store, "_thread_local", threading.local())
    return {}


class FakeGen:
    """Same beats as tests/test_meetings.py: read-back weaves the user's
    words and names the Compass and Logic strands."""

    def __init__(self):
        self.prompts: list[str] = []

    def __call__(self, prompt, **kwargs):
        self.prompts.append(prompt)
        if "has just corrected your first impression" in prompt:
            return (
                "A first impression, anchored in [[u]]your words[[/u]] — correct me."
                "\nStrands: Compass, Logic"
            )
        if "READ-BACK" in prompt:
            return (
                "A first impression, anchored in [[u]]your words[[/u]] — correct me."
                "\nStrands: Compass, Logic"
            )
        if "ENCOUNTER" in prompt:
            return "An engaged reply that hears two tensions together."
        return "A plain reply."



#: Tutorial-beat mechanism (2026-10-24, corrected the same day):
#: this fake simulates a character that teaches its beats WITH
#: CONTENT — every generation output carries a teaching sentence
#: with all three beats' anchors plus the three beat trailers
#: (trailers stripped before anything is spoken). Trailers alone
#: no longer count under the content guard. Prompts and
#: generation counts are unchanged; spoken bodies gain the
#: teaching sentence. The gate itself is pinned by
#: tests/test_encounter_tutorial_beats.py; this suite pins the
#: other behaviors.
#: Teaching sentence the fakes speak (correction 2026-10-24):
#: beat trailers alone no longer count — coverage requires
#: content, so a fake that teaches its beats must speak them.
#: One sentence carrying all three conductor beats' anchors
#: (council/tree/hearing-together, competing priorities/sit
#: together, new voice/whole orchestra/in ear). Inserted BEFORE
#: any Strands: bookkeeping line (strands parsing reads from the
#: end) and before the beat trailers, so every trailer parse in
#: the runtime sees the same trailing structure as the original
#: output; thread trailers are position-tolerant.
_TEACHING_SENTENCE = (
    "My ground is the council and the tree, where parts of your "
    "life need hearing together; bring me the competing priorities "
    "that will not sit together; every new voice changes what the "
    "whole orchestra can play, and I keep the whole of it in ear."
)

_BEAT_SUFFIX = (
    "\n[[beat:conductor:terrain]] [[beat:conductor:involvement]] "
    "[[beat:conductor:why_meet]]"
)


def _teaching(gen):
    def wrapper(prompt, **kwargs):
        out = gen(prompt, **kwargs)
        lines = out.split("\n")
        for i, line in enumerate(lines):
            if line.strip().lower().startswith("strands:"):
                lines.insert(i, _TEACHING_SENTENCE)
                break
        else:
            lines.append(_TEACHING_SENTENCE)
        return "\n".join(lines) + _BEAT_SUFFIX
    return wrapper


def _svc(tmp_path, gen=None):
    agents_db = tmp_path / "agents.db"
    return MeetingService(
        ConversationStore(tmp_path / "conv.db"),
        MeetingStore(tmp_path / "meetings.db"),
        generate_fn=_teaching(gen or FakeGen()),
        agent_store_factory=lambda uid: AgentStore(agents_db, user_id=uid),
    )


def _agents(tmp_path, uid) -> AgentStore:
    return AgentStore(tmp_path / "agents.db", user_id=uid)


def _seeded_user(email="impressions@example.com"):
    user = ve.create_user_account(email, "pw", "Meet")
    keystone_seeding.seed_meet_your_council(user["id"])
    return user["id"]


def _run_conductor_to_completion(
    svc, uid,
    answer="I work by deadlines first, then everything else follows.",
    response="That's right.",
):
    """UPDATED for the Weaver pattern: the drive is the pattern's
    shape — a first substantive turn (the shared work begins), a
    second (the read lands), then the response to the impression."""
    svc.start(uid, "conductor")
    svc.turn(uid, "conductor", answer)
    svc.turn(
        uid, "conductor",
        "And in my own work it's the same — what breaks first gets my hands first.",
    )
    state = svc.turn(uid, "conductor", response)
    if state["status"] != "complete":
        # The answer left a thread open (a substantive correction,
        # under the deterministic estimate): one settled turn ends it.
        state = svc.turn(uid, "conductor", "Got it.")
    return state


READBACK_STRIPPED = "A first impression, anchored in your words — correct me."
RESPONSE = "Mostly right — except I protect mornings first."


# ------------------------------------------------------------------ filing


def test_completion_files_one_impression_claim(ve_ctx, tmp_path):
    uid = _seeded_user()
    svc = _svc(tmp_path)
    state = _run_conductor_to_completion(
        svc, uid,
        answer="I triage by what breaks first if I ignore it.",
        response=RESPONSE,
    )
    assert state["status"] == "complete"

    store = _agents(tmp_path, uid)
    agent = store.get("meeting-conductor-1")
    assert agent is not None
    assert agent.name == "First meeting — Weaver"
    assert agent.source_platform == "meeting"
    assert agent.status == "pending_review"
    # A meeting is not an import: there is nothing to mine.
    assert agent.mining_state == "skipped"
    # The read-back's strands (Compass, Logic) are the sort — this is
    # what groups the agent under the seats those strands touch.
    assert agent.sort.strand_weights == {"self": 1.0, "number": 1.0}
    assert agent.sort.primary_strand == "self"
    # Non-empty moments keep the claims route from re-sorting the agent
    # and hiding the stored claim behind a rebuilt set.
    assert agent.sort.moments

    claims = store.get_claims("meeting-conductor-1")
    assert len(claims) == 1
    claim = claims[0]
    assert claim.claim_type == "meeting_impression"
    assert claim.title == "First impression — Weaver"
    assert claim.id.startswith("meeting-conductor-1:impression:self+number:")
    assert claim.status == "pending"
    # The promise: both texts complete, word for word. The inference is
    # the full read-back with the weave markup (not words) stripped.
    assert claim.evidence == RESPONSE
    assert claim.inference == READBACK_STRIPPED + "\n" + _TEACHING_SENTENCE
    assert "[[u]]" not in claim.inference
    assert READBACK_STRIPPED in claim.detail
    assert RESPONSE in claim.detail
    assert "the Compass and Logic strands" in claim.detail


def test_refiling_is_idempotent_and_a_verdict_survives(ve_ctx, tmp_path):
    uid = _seeded_user()
    svc = _svc(tmp_path)
    _run_conductor_to_completion(svc, uid, response=RESPONSE)

    store = _agents(tmp_path, uid)
    claim = store.get_claims("meeting-conductor-1")[0]
    store.update_claim(claim.id, status="accepted")

    # Re-entering the completed meeting hits the backfill path; the
    # claim must not duplicate and the verdict must not reset.
    svc.start(uid, "conductor")
    claims = store.get_claims("meeting-conductor-1")
    assert [c.id for c in claims] == [claim.id]
    assert claims[0].status == "accepted"


def test_replay_files_a_second_distinct_claim(ve_ctx, tmp_path):
    uid = _seeded_user()
    svc = _svc(tmp_path)
    _run_conductor_to_completion(svc, uid, response=RESPONSE)

    store = _agents(tmp_path, uid)
    first = store.get_claims("meeting-conductor-1")[0]
    store.update_claim(first.id, status="accepted")

    svc.restart(uid, "conductor")
    state = _run_conductor_to_completion(
        svc, uid,
        answer="Second time: I start with people, not tasks.",
        response="Yes, that's the shape of it.",
    )
    assert state["status"] == "complete"

    claims = store.get_claims("meeting-conductor-1")
    assert len(claims) == 2
    by_id = {c.id: c for c in claims}
    assert by_id[first.id].status == "accepted"  # archived run untouched
    assert by_id[first.id].evidence == RESPONSE
    second = next(c for c in claims if c.id != first.id)
    assert second.status == "pending"
    assert second.evidence == "Yes, that's the shape of it."
    assert second.inference == READBACK_STRIPPED + "\n" + _TEACHING_SENTENCE


# ----------------------------------------------------------------- verdicts


def _verdict(tmp_path, uid, claim, action):
    """What the claim verdict routes do: persist the status, then log
    the feedback signal through the shared machinery."""
    store = _agents(tmp_path, uid)
    store.update_claim(claim.id, status="accepted" if action == "accepted" else "rejected")
    presence = PresenceStore(tmp_path / "signals.db")
    log_claim_feedback(
        agent_id="meeting-conductor-1",
        claim_id=claim.id,
        claim_type=claim.claim_type,
        claim_title=claim.title,
        action=action,
        user_id=uid,
        evidence=claim.evidence,
        inference=claim.inference,
        presence_store=presence,
    )
    return presence.list_signals_by_kind("claim_feedback")


def test_acceptance_lands_evidence_under_both_readback_strands(ve_ctx, tmp_path):
    uid = _seeded_user()
    svc = _svc(tmp_path)
    _run_conductor_to_completion(svc, uid, response=RESPONSE)

    store = _agents(tmp_path, uid)
    claim = store.get_claims("meeting-conductor-1")[0]
    signals = _verdict(tmp_path, uid, claim, "accepted")

    # One signal per read-back strand (Compass -> self, Logic -> number),
    # each carrying the claim's own texts — the impression becomes
    # strand evidence exactly where the read-back said it was heard.
    assert len(signals) == 2
    assert {s.zone for s in signals} == {"self", "number"}
    for s in signals:
        assert s.valence == "endorsed"  # the claim-feedback map's accept valence
        assert s.payload_redacted == RESPONSE
        assert s.summary == READBACK_STRIPPED + "\n" + _TEACHING_SENTENCE
        assert s.provenance["claim_type"] == "meeting_impression"


def test_rejection_dismisses_under_both_strands(ve_ctx, tmp_path):
    uid = _seeded_user()
    svc = _svc(tmp_path)
    _run_conductor_to_completion(svc, uid, response=RESPONSE)

    store = _agents(tmp_path, uid)
    claim = store.get_claims("meeting-conductor-1")[0]
    signals = _verdict(tmp_path, uid, claim, "rejected")

    assert len(signals) == 2
    assert {s.zone for s in signals} == {"self", "number"}
    assert all(s.valence == "rejected" for s in signals)
    assert store.get_claims("meeting-conductor-1")[0].status == "rejected"
