"""Conductor two-run supersede sequence (Joshua, 2026-10-28).

Decision: prior-run claims on restart use SUPERSEDE. When a new
meeting run produces a new impression, it replaces the prior run's
claim: the old claim remains visible in the record history, but only
the new claim counts as current. Nothing is erased. DISTINCT from the
pending-impression discard rule (never-delivered impressions on
voluntary end); supersede covers prior ACCEPTED/filed claims replaced
by a new filed claim.

Precise semantics pinned here:
1. Restart ALONE does not supersede: restart archives the prior run
   verbatim and the prior claim stays current.
2. At new filing, prior meeting_impression claim(s) for
   meeting-conductor-1 become superseded: row retained, prior verdict
   preserved visibly in the retained row (recorded in detail), never
   deleted, never silently overwritten, retrievable via get_claims.
3. After the new filing, exactly ONE standing/current
   meeting_impression claim exists for the seat + visitor.

IMPLEMENTATION STATUS — READ FIRST: the filing path
(_file_impression in local_ai/conversation/meeting.py) is SHARED
runtime code, and a separate shared-foundation supersede follow-up PR
(stacked on PR #255) owns the authoritative shared mechanism,
including the claim-status encoding (CLAIM_STATUSES has no
"superseded" value today). This per-seat PR deliberately does NOT
implement a second mechanism in shared code. Therefore:

- test_restart_alone_does_not_supersede PASSES on this PR alone
  (restart already never touches claims).
- test_second_filing_supersedes_prior_claim ran xfail
  (integration-pending against the shared PR) until the shared
  mechanism (#260) landed with the encoding asserted here;
  marker removed. test_meeting_impressions.py's
  test_replay_files_a_second_distinct_claim already carries the
  supersede expectation on main.

Harness mirrors tests/test_meeting_impressions.py (same FakeGen
beats, same drive to completion, same AgentStore read path). No
model calls: generation is canned.
"""

from __future__ import annotations

import threading

import pytest

from local_ai.agent_intake.store import AgentStore
from local_ai.conversation.meeting import MeetingService, MeetingStore
from local_ai.conversation.store import ConversationStore
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


class _FakeGen:
    """Same beats as test_meeting_impressions.py: the read-back
    weaves the user's words and names the Compass and Logic strands."""

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


def _svc(tmp_path):
    agents_db = tmp_path / "agents.db"
    return MeetingService(
        ConversationStore(tmp_path / "conv.db"),
        MeetingStore(tmp_path / "meetings.db"),
        generate_fn=_teaching(_FakeGen()),
        agent_store_factory=lambda uid: AgentStore(agents_db, user_id=uid),
    )


def _agents(tmp_path, uid) -> AgentStore:
    return AgentStore(tmp_path / "agents.db", user_id=uid)


def _seeded_user(email="supersede@example.com"):
    user = ve.create_user_account(email, "pw", "Meet")
    keystone_seeding.seed_meet_your_council(user["id"])
    return user["id"]


def _run_conductor_to_completion(svc, uid, answer, response):
    """First substantive turn (shared work begins), second (the read
    lands), then the response to the impression; a settled turn ends
    it if the answer left a thread open. UPDATED for decoupled
    recognition (no-scripting build, 2026-10-29): recognition no
    longer closes — the visitor's own Complete action finishes it."""
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
        state = svc.complete(uid, "conductor")
    assert state["status"] == "complete"
    return state


def _standing(claims):
    """Claims counting as current: everything not marked superseded."""
    return [c for c in claims if c.status != "superseded"]


def test_restart_alone_does_not_supersede(ve_ctx, tmp_path):
    # Run 1 files; the visitor accepts; restart alone must leave the
    # claim standing — supersede happens at new filing, never at
    # restart.
    uid = _seeded_user()
    svc = _svc(tmp_path)
    _run_conductor_to_completion(
        svc, uid,
        answer="I triage by what breaks first if I ignore it.",
        response="Mostly right — except I protect mornings first.",
    )
    store = _agents(tmp_path, uid)
    first = store.get_claims("meeting-conductor-1")[0]
    assert first.claim_type == "meeting_impression"
    store.update_claim(first.id, status="accepted")

    svc.restart(uid, "conductor")

    claims = store.get_claims("meeting-conductor-1")
    assert len(claims) == 1
    assert claims[0].id == first.id
    assert claims[0].status == "accepted"
    assert len(_standing(claims)) == 1


def test_second_filing_supersedes_prior_claim(ve_ctx, tmp_path):
    # Run 1 files and is accepted; restart; run 2 files. Old row
    # retained with its prior verdict visible; exactly one standing
    # claim remains.
    uid = _seeded_user()
    svc = _svc(tmp_path)
    _run_conductor_to_completion(
        svc, uid,
        answer="I triage by what breaks first if I ignore it.",
        response="Mostly right — except I protect mornings first.",
    )
    store = _agents(tmp_path, uid)
    first = store.get_claims("meeting-conductor-1")[0]
    store.update_claim(first.id, status="accepted")
    assert len(_standing(store.get_claims("meeting-conductor-1"))) == 1

    svc.restart(uid, "conductor")
    _run_conductor_to_completion(
        svc, uid,
        answer="Second time: I start with people, not tasks.",
        response="Yes, that's the shape of it.",
    )

    claims = store.get_claims("meeting-conductor-1")
    # Nothing erased: both rows retrievable via the existing read.
    assert len(claims) == 2
    by_id = {c.id: c for c in claims}
    old = by_id[first.id]
    assert old.evidence == "Mostly right — except I protect mornings first."
    # Prior verdict preserved visibly in the retained row, not
    # silently overwritten: superseded, with "accepted" recorded.
    assert old.status == "superseded"
    assert "accepted" in (old.detail or "")
    # Exactly one standing/current claim: the new filing.
    standing = _standing(claims)
    assert len(standing) == 1
    assert standing[0].id != first.id
    assert standing[0].status == "pending"
    assert standing[0].evidence == "Yes, that's the shape of it."
