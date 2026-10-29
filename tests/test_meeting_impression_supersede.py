"""Meeting-impression supersede (2026-10-28 decision) — shared mechanism.

Semantics under test (seat-agnostic, keyed by agent_id, implemented once
in MeetingService._file_impression):
  - A new run's filing SUPERSEDES every prior meeting_impression claim
    for the same agent: the old row is retained in history with its
    prior verdict recorded in its detail, but only the new claim stands
    — exactly one standing meeting_impression claim per seat+visitor.
  - Restart ALONE does not supersede: the prior claim stays standing
    until a new run completes and files.
  - Same-run re-filing supersedes nothing, including itself.
  - The pending-impression discard rule is untouched: a pending
    (never-delivered) impression on voluntary end is discarded, never
    filed, and never supersedes anything — including a prior run's
    standing claim.
  - A superseded claim takes no new verdict: the API verdict guard
    refuses it, so it cannot mint fresh training input.
  - Readers treat only the standing claim as current: the review
    queue's pending counts ignore superseded rows, and friction's
    latest-impression reader prefers the non-superseded claim.

Coverage shape: full encounter paths run the Weaver (conductor) — the
only seat with a keystone-1 script in this base; the other six seats'
scripts live on their per-seat branches. The seven-seat filing test
drives the real _file_impression chokepoint for every seat agent_id,
which is the mechanism the per-seat branches inherit at merge: the
supersede logic keys on agent_id and never on seat-specific script
content (it reads only script.character for the agent's display name).
"""

from __future__ import annotations

import json
import threading
from types import SimpleNamespace

import pytest

from local_ai.agent_intake import review_claims
from local_ai.agent_intake.review_claims import ReviewClaim
from local_ai.agent_intake.store import AgentStore
from local_ai.conversation import encounter as ENC
from local_ai.conversation.meeting import MeetingService, MeetingStore
from local_ai.conversation.store import ConversationStore
from local_ai.council.archetypes import stock_archetype_ids
from local_ai.narrative.friction import _latest_impression_claim
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


_TEACHING_SENTENCE = (
    "My ground is the council and the tree, where parts of your "
    "life need hearing together; bring me the competing priorities "
    "that will not sit together; every new voice changes what the "
    "whole orchestra can play, and I keep the whole of it in ear."
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
        return "\n".join(lines)

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


def _seeded_user(email="supersede@example.com"):
    user = ve.create_user_account(email, "pw", "Supersede")
    keystone_seeding.seed_meet_your_council(user["id"])
    return user["id"]


def _run_conductor_to_completion(
    svc, uid,
    answer="I work by deadlines first, then everything else follows.",
    response="That's right.",
):
    svc.start(uid, "conductor")
    svc.turn(uid, "conductor", answer)
    svc.turn(
        uid, "conductor",
        "And in my own work it's the same — what breaks first gets my hands first.",
    )
    state = svc.turn(uid, "conductor", response)
    if state["status"] != "complete":
        state = svc.turn(uid, "conductor", "Got it.")
    if state["status"] != "complete":
        # UPDATED for decoupled recognition (no-scripting build,
        # 2026-10-29): recognition no longer closes — the visitor's
        # own Complete action finishes it.
        state = svc.complete(uid, "conductor")
    return state


READBACK_STRIPPED = "A first impression, anchored in your words — correct me."
RESPONSE = "Mostly right — except I protect mornings first."


def _standing(store, agent_id):
    return review_claims.standing_impression_claim(
        store.get_claims(agent_id), agent_id
    )


# ------------------------------------------------------------------ full path


def test_two_run_sequence_supersedes_old_claim(ve_ctx, tmp_path):
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
    # Retained, never deleted; prior verdict visible in history.
    assert by_id[first.id].status == "superseded"
    assert "Prior verdict: accepted." in by_id[first.id].detail
    assert by_id[first.id].evidence == RESPONSE
    # Exactly one standing claim: the new run's.
    standing = _standing(store, "meeting-conductor-1")
    assert standing is not None
    assert standing.id != first.id
    assert standing.status == "pending"
    assert standing.evidence == "Yes, that's the shape of it."
    # Still retrievable through the normal claim reads.
    assert {c["claim_id"] for c in store.claims_for_user(uid)} >= {
        first.id, standing.id,
    }


def test_restart_alone_does_not_supersede(ve_ctx, tmp_path):
    uid = _seeded_user()
    svc = _svc(tmp_path)
    _run_conductor_to_completion(svc, uid, response=RESPONSE)

    store = _agents(tmp_path, uid)
    first = store.get_claims("meeting-conductor-1")[0]
    store.update_claim(first.id, status="accepted")

    svc.restart(uid, "conductor")

    claims = store.get_claims("meeting-conductor-1")
    assert len(claims) == 1
    assert claims[0].status == "accepted"  # still standing, untouched
    assert _standing(store, "meeting-conductor-1").id == first.id


def test_prior_corrected_verdict_and_note_preserved(ve_ctx, tmp_path):
    uid = _seeded_user()
    svc = _svc(tmp_path)
    _run_conductor_to_completion(svc, uid, response=RESPONSE)

    store = _agents(tmp_path, uid)
    first = store.get_claims("meeting-conductor-1")[0]
    store.update_claim(first.id, status="corrected", user_note="Mornings, not deadlines.")

    svc.restart(uid, "conductor")
    _run_conductor_to_completion(
        svc, uid,
        answer="Second time: I start with people, not tasks.",
        response="Yes, that's the shape of it.",
    )

    old = next(
        c for c in store.get_claims("meeting-conductor-1") if c.id == first.id
    )
    assert old.status == "superseded"
    # The user's own words are never overwritten by the system note.
    assert old.user_note == "Mornings, not deadlines."
    assert "Prior verdict: corrected." in old.detail
    assert old.inference == READBACK_STRIPPED + "\n" + _TEACHING_SENTENCE


def test_pending_prior_claim_is_superseded_not_left_open(ve_ctx, tmp_path):
    uid = _seeded_user()
    svc = _svc(tmp_path)
    _run_conductor_to_completion(svc, uid, response=RESPONSE)

    store = _agents(tmp_path, uid)
    first = store.get_claims("meeting-conductor-1")[0]
    assert first.status == "pending"

    svc.restart(uid, "conductor")
    _run_conductor_to_completion(
        svc, uid,
        answer="Second time: I start with people, not tasks.",
        response="Yes, that's the shape of it.",
    )

    claims = store.get_claims("meeting-conductor-1")
    by_id = {c.id: c for c in claims}
    assert by_id[first.id].status == "superseded"
    assert "Prior verdict: pending." in by_id[first.id].detail
    # The review queue must not count the superseded row as open:
    # only the new run's claim is pending.
    assert [c.id for c in claims if c.status == "pending"] == [
        _standing(store, "meeting-conductor-1").id
    ]


def test_same_run_refiling_does_not_supersede_itself(ve_ctx, tmp_path):
    uid = _seeded_user()
    svc = _svc(tmp_path)
    _run_conductor_to_completion(svc, uid, response=RESPONSE)

    store = _agents(tmp_path, uid)
    claim = store.get_claims("meeting-conductor-1")[0]
    store.update_claim(claim.id, status="accepted")

    # Re-entering the completed meeting hits the backfill path.
    svc.start(uid, "conductor")
    claims = store.get_claims("meeting-conductor-1")
    assert [c.id for c in claims] == [claim.id]
    assert claims[0].status == "accepted"  # not superseded by itself
    assert _standing(store, "meeting-conductor-1").id == claim.id


def test_supersede_is_idempotent_across_repeated_filings(ve_ctx, tmp_path):
    uid = _seeded_user()
    svc = _svc(tmp_path)
    _run_conductor_to_completion(svc, uid, response=RESPONSE)
    store = _agents(tmp_path, uid)
    first = store.get_claims("meeting-conductor-1")[0]

    svc.restart(uid, "conductor")
    _run_conductor_to_completion(
        svc, uid,
        answer="Second time: I start with people, not tasks.",
        response="Yes, that's the shape of it.",
    )
    # Backfill re-filing of run 2 must not re-supersede or stack notes.
    svc.start(uid, "conductor")
    claims = store.get_claims("meeting-conductor-1")
    assert len(claims) == 2
    old = next(c for c in claims if c.id == first.id)
    assert old.status == "superseded"
    assert old.detail.count("Superseded by a later first meeting") == 1


# --------------------------------------------------------------------- discard


def _set_pending(svc, uid, text="A held read."):
    row = svc.meetings.get(uid, "conductor", 1)
    state = ENC.EncounterState.from_json(row["state_json"])
    state.impression_pending_text = text
    state.impression_pending_strands = ["Logic"]
    svc.meetings.update(uid, "conductor", 1, state_json=state.to_json())


def test_voluntary_end_with_pending_impression_still_discards(ve_ctx, tmp_path):
    uid = _seeded_user()
    svc = _svc(tmp_path)
    svc.start(uid, "conductor")
    _set_pending(svc, uid)
    state = svc.complete(uid, "conductor")
    assert state["status"] == "complete"
    assert state["pending_impression_discarded"] != ""
    store = _agents(tmp_path, uid)
    assert store.get_claims("meeting-conductor-1") == []


def test_discarded_second_run_leaves_prior_claim_standing(ve_ctx, tmp_path):
    uid = _seeded_user()
    svc = _svc(tmp_path)
    _run_conductor_to_completion(svc, uid, response=RESPONSE)
    store = _agents(tmp_path, uid)
    first = store.get_claims("meeting-conductor-1")[0]
    store.update_claim(first.id, status="accepted")

    # Run 2 begins, holds an impression, and ends voluntarily: the held
    # read is discarded — never filed — so it must not supersede the
    # prior run's standing claim. Discard and supersede stay distinct.
    svc.restart(uid, "conductor")
    svc.start(uid, "conductor")
    _set_pending(svc, uid)
    state = svc.complete(uid, "conductor")
    assert state["status"] == "complete"
    claims = store.get_claims("meeting-conductor-1")
    assert [c.id for c in claims] == [first.id]
    assert claims[0].status == "accepted"
    assert _standing(store, "meeting-conductor-1").id == first.id


# ------------------------------------------------------- filing: all seats


SEVEN_SEAT_AGENT_IDS = [
    "meeting-mentor-1",
    "meeting-champion-1",
    "meeting-guardian-1",
    "meeting-maverick-1",
    "meeting-ambassador-1",
    "meeting-conductor-1",
    "meeting-skeptic-1",
]


def test_seven_seat_agent_ids_match_stock_archetypes():
    assert SEVEN_SEAT_AGENT_IDS == [
        f"meeting-{a}-1" for a in stock_archetype_ids()
    ]


def _file_run(svc, uid, arch, created_at, claim_text, response):
    """One filing-chokepoint run for a seat without a script: create
    the meeting row, pin its creation time (the run_key source), give
    it a read-back, and file through the real _file_impression."""
    svc.meetings.delete(uid, arch, 1)
    svc.meetings.create(uid, arch, 1)
    svc.meetings._conn.execute(
        "UPDATE meetings SET created_at = ? WHERE user_id = ? "
        "AND archetype_id = ? AND keystone_index = 1",
        (created_at, uid, arch),
    )
    svc.meetings._conn.commit()
    svc.meetings.update(
        uid, arch, 1,
        readback_claim=claim_text,
        readback_response=response,
        readback_strands=json.dumps(["Compass", "Logic"]),
    )
    # _file_impression reads only script.character (the agent's display
    # name); the supersede logic itself keys on agent_id alone.
    svc._file_impression(uid, arch, 1, SimpleNamespace(character=arch))


@pytest.mark.parametrize("agent_id", SEVEN_SEAT_AGENT_IDS)
def test_filing_supersedes_for_every_seat_agent_id(ve_ctx, tmp_path, agent_id):
    arch = agent_id[len("meeting-"):-len("-1")]
    uid = _seeded_user()
    svc = _svc(tmp_path)
    store = _agents(tmp_path, uid)

    _file_run(
        svc, uid, arch, "2026-10-28T10:00:00+00:00",
        "First run's impression.", "First run's answer.",
    )
    first = store.get_claims(agent_id)
    assert len(first) == 1
    assert first[0].status == "pending"
    store.update_claim(first[0].id, status="accepted")
    # An unrelated claim type must survive the supersede untouched.
    store.save_claims(agent_id, [
        ReviewClaim(
            id=f"{agent_id}:strand:self:m1",
            claim_type="strand",
            title="Self strand",
            evidence="evidence",
            inference="inference",
        )
    ])

    _file_run(
        svc, uid, arch, "2026-10-28T11:00:00+00:00",
        "Second run's impression.", "Second run's answer.",
    )

    claims = store.get_claims(agent_id)
    by_id = {c.id: c for c in claims}
    assert by_id[first[0].id].status == "superseded"
    assert "Prior verdict: accepted." in by_id[first[0].id].detail
    assert by_id[f"{agent_id}:strand:self:m1"].status == "pending"
    standing = _standing(store, agent_id)
    assert standing is not None
    assert standing.id != first[0].id
    assert standing.status == "pending"
    assert standing.evidence == "Second run's answer."
    assert standing.inference == "Second run's impression."
    # Exactly one standing meeting_impression claim for this seat.
    assert [
        c for c in claims
        if c.claim_type == "meeting_impression" and c.status != "superseded"
    ] == [standing]


@pytest.mark.parametrize("agent_id", SEVEN_SEAT_AGENT_IDS)
def test_filing_same_run_refile_supersedes_nothing_for_every_seat(
    ve_ctx, tmp_path, agent_id
):
    arch = agent_id[len("meeting-"):-len("-1")]
    uid = _seeded_user()
    svc = _svc(tmp_path)
    store = _agents(tmp_path, uid)

    _file_run(
        svc, uid, arch, "2026-10-28T10:00:00+00:00",
        "One run's impression.", "One run's answer.",
    )
    claim = store.get_claims(agent_id)[0]
    store.update_claim(claim.id, status="accepted")

    # Re-filing the identical row (same created_at -> same run_key).
    svc._file_impression(uid, arch, 1, SimpleNamespace(character=arch))
    claims = store.get_claims(agent_id)
    assert [c.id for c in claims] == [claim.id]
    assert claims[0].status == "accepted"


# ------------------------------------------------------------- standing reads


def test_standing_helper_heals_legacy_rows_on_next_filing(ve_ctx, tmp_path):
    # Two runs filed before the supersede rule landed: both stand.
    agent_id = "meeting-conductor-1"
    uid = _seeded_user()
    svc = _svc(tmp_path)
    store = _agents(tmp_path, uid)
    _file_run(
        svc, uid, "conductor", "2026-10-28T10:00:00+00:00",
        "Legacy run one.", "Answer one.",
    )
    _file_run(
        svc, uid, "conductor", "2026-10-28T11:00:00+00:00",
        "Legacy run two.", "Answer two.",
    )
    # Simulate the pre-supersede world: the second filing above already
    # superseded the first under the new rule, so rebuild the legacy
    # shape directly — two standing rows — and check the helper picks
    # the latest, then heals fully on the next real filing.
    claims = store.get_claims(agent_id)
    assert len(claims) == 2
    first, second = claims[0], claims[1]
    assert second.status == "pending"
    # Restore the legacy shape (both standing) via a direct re-save.
    store.save_claims(agent_id, [
        ReviewClaim(
            id=first.id, claim_type="meeting_impression",
            title=first.title, evidence=first.evidence,
            inference=first.inference, detail=first.detail,
            status="pending",
        )
    ])
    legacy = store.get_claims(agent_id)
    assert all(c.status == "pending" for c in legacy)
    assert _standing(store, agent_id).id == second.id
    _file_run(
        svc, uid, "conductor", "2026-10-28T12:00:00+00:00",
        "New run.", "New answer.",
    )
    healed = store.get_claims(agent_id)
    assert [
        c for c in healed
        if c.claim_type == "meeting_impression" and c.status != "superseded"
    ] == [_standing(store, agent_id)]
    assert _standing(store, agent_id).evidence == "New answer."


def test_latest_impression_reader_prefers_standing_claim():
    base = {
        "agent_id": "meeting-conductor-1",
        "claim_type": "meeting_impression",
    }
    old = {**base, "id": "old", "status": "superseded",
           "created_at": "2026-10-28T12:00:00+00:00"}
    new = {**base, "id": "new", "status": "pending",
           "created_at": "2026-10-28T11:00:00+00:00"}
    # Even with a LATER created_at on the superseded row (clock skew),
    # the reader must return the standing claim, not history.
    assert _latest_impression_claim([old, new], "meeting-conductor-1")["id"] == "new"
    # With no standing row at all, it falls back to latest-created.
    assert _latest_impression_claim([old], "meeting-conductor-1")["id"] == "old"
    assert _latest_impression_claim([], "meeting-conductor-1") is None


def test_supersede_helper_never_overwrites_user_note_or_stacks():
    claim = ReviewClaim(
        id="meeting-conductor-1:impression:self:run1",
        claim_type="meeting_impression",
        title="First impression — Weaver",
        evidence="answer",
        inference="impression",
        detail="Heard under the Compass strand.",
        status="corrected",
        user_note="Mornings, not deadlines.",
    )
    out = review_claims.supersede_claim(claim, "meeting-conductor-1:impression:self:run2")
    assert out.status == "superseded"
    assert out.user_note == "Mornings, not deadlines."
    assert out.evidence == "answer" and out.inference == "impression"
    assert "Prior verdict: corrected." in out.detail
    assert "meeting-conductor-1:impression:self:run2" in out.detail
    # Already superseded: unchanged, no stacked note.
    assert review_claims.supersede_claim(out, "other") is out
    assert out.detail.count("Superseded by a later first meeting") == 1


# ------------------------------------------------------------ verdict guard


def test_verdict_guard_refuses_superseded_claims():
    from fastapi import HTTPException

    from api.routes.agent_routes import _reject_superseded_verdict

    superseded = ReviewClaim(
        id="meeting-conductor-1:impression:self:run1",
        claim_type="meeting_impression",
        title="First impression — Weaver",
        evidence="answer",
        inference="impression",
        status="superseded",
    )
    with pytest.raises(HTTPException) as exc:
        _reject_superseded_verdict(superseded)
    assert exc.value.status_code == 409
    standing = ReviewClaim(
        id="meeting-conductor-1:impression:self:run2",
        claim_type="meeting_impression",
        title="First impression — Weaver",
        evidence="answer",
        inference="impression",
        status="pending",
    )
    _reject_superseded_verdict(standing)  # no raise
