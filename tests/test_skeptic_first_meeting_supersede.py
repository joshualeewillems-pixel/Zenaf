"""Skeptic first meeting — prior-run claims on restart: SUPERSEDE.

Decision (Joshua, 2026-10-28, verbatim rule): prior-run claims on
restart use SUPERSEDE. When a new meeting run produces a new
impression, it replaces the prior run's claim: the old claim
remains visible in the record history, but only the new claim
counts as current. Nothing is erased. This is DISTINCT from the
pending-impression discard rule (impressions never delivered on
voluntary end); supersede covers prior ACCEPTED/filed claims
replaced by a new filed claim.

Precise semantics under test:
1. Restart ALONE does not supersede. Restart archives the prior
   run verbatim; the prior claim stays current until a new run
   completes and files a new impression.
2. At new filing, prior meeting_impression claim(s) for the same
   agent_id ("meeting-skeptic-1") become superseded: row
   retained, prior verdict preserved visibly in the retained row
   (never delete the row, never silently overwrite a user's
   verdict — record the prior status in the retained row, e.g.
   note/detail, and keep it retrievable via the existing claim
   reads).
3. After the new filing, exactly ONE standing/current
   meeting_impression claim exists for that seat + visitor.
4. Grounding in origin/main: `_file_impression` files one claim
   per run with a run_key from the run's created_at, and its
   comment says the archived run's claim is never touched
   ("A replay is a new run with a new claim; the archived run's
   claim and verdict stay untouched" — see also
   tests/test_meeting_impressions.py::test_replay_files_a_second_distinct_claim,
   which pins that current behavior for the Weaver). Supersede
   changes that behavior, but only at new filing, not at restart.

IMPLEMENTATION STATUS — READ FIRST. This PR ships NO filing-path
change, deliberately. The authoritative supersede mechanism is
owned by a separate shared-foundation supersede follow-up PR
(stacked on PR #255); this per-seat PR must not ship a second,
parallel mechanism in the shared `_file_impression` path (which
would also change Weaver behavior and collide with that
follow-up at merge — the shared version wins at merge, keep only
one mechanism). Consequences for this file:

- `test_restart_alone_does_not_supersede` PASSES today: it pins
  semantics (1), which already holds (restart archives; filing
  is untouched by restart).
- `test_two_run_supersede_sequence` ran skipped
  (integration-pending) until the shared mechanism (#260)
  landed; its superseded-marking predicate already accepts
  #260's exact marker (`status == "superseded"`), so no
  conforming was needed — skip removed, test runs green
  against it.

Harness note: the Skeptic meeting is deliberately unregistered
in `SCRIPTS` (this PR gates availability by non-registration),
so these tests monkeypatch-register it for the duration of the
test — the same control the gate test uses — to drive real
runs through `MeetingService`. The registration is reverted
after each test; nothing here makes the meeting
visitor-accessible.
"""

from __future__ import annotations

import threading

import pytest

from local_ai.agent_intake.store import AgentStore
from local_ai.conversation.meeting import MeetingService, MeetingStore
from local_ai.conversation.store import ConversationStore
from local_ai.council import meetings as MT
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
    """Same beats as tests/test_meetings.py: the read-back weaves
    the user's words and names the Compass and Logic strands."""

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


def _svc(tmp_path, gen=None):
    agents_db = tmp_path / "agents.db"
    return MeetingService(
        ConversationStore(tmp_path / "conv.db"),
        MeetingStore(tmp_path / "meetings.db"),
        generate_fn=gen or FakeGen(),
        agent_store_factory=lambda uid: AgentStore(agents_db, user_id=uid),
    )


def _agents(tmp_path, uid) -> AgentStore:
    return AgentStore(tmp_path / "agents.db", user_id=uid)


def _seeded_user(email="skeptic-supersede@example.com"):
    user = ve.create_user_account(email, "pw", "Meet")
    keystone_seeding.seed_meet_your_council(user["id"])
    return user["id"]


def _register_skeptic(monkeypatch):
    """Availability gate, lifted for this test only: the script is
    unregistered in SCRIPTS by design (see the gate test), so the
    service can only drive a Skeptic run while it is patched in."""
    monkeypatch.setitem(MT.SCRIPTS, ("skeptic", 1), MT.SKEPTIC_FIRST_MEETING)


def _mark_weaver_done(uid):
    """Entry gate: the Weaver opens the council, so a Skeptic run
    needs the conductor's keystone 1 Done (same step as the gate
    test). Seeding alone is not enough."""
    from local_ai.conversation.meeting import _seat_keystone_tasks
    from local_ai.vision_execution import models as ve_models

    tasks = _seat_keystone_tasks(uid, "conductor")
    assert tasks and tasks[0]["status"] != "Done"
    ve.update_task(
        tasks[0]["id"],
        ve_models.TaskUpdate(status="Done"),
        uid,
    )
    assert _seat_keystone_tasks(uid, "conductor")[0]["status"] == "Done"


def _run_skeptic_to_completion(svc, uid, answer, response):
    """Mirror of the Weaver run-to-completion drive: a first
    substantive turn (examination begins), a second (the read
    lands), then the response to the impression; one settled turn
    if the answer left a thread open."""
    svc.start(uid, "skeptic")
    svc.turn(uid, "skeptic", answer)
    svc.turn(
        uid, "skeptic",
        "And in my own work it's the same — I keep coming back to what I haven't checked.",
    )
    state = svc.turn(uid, "skeptic", response)
    if state["status"] != "complete":
        state = svc.turn(uid, "skeptic", "Got it.")
    assert state["status"] == "complete"
    return state


def _meeting_claims(tmp_path, uid):
    return _agents(tmp_path, uid).get_claims("meeting-skeptic-1")


def _impression_claims(tmp_path, uid):
    return [
        c for c in _meeting_claims(tmp_path, uid)
        if c.claim_type == "meeting_impression"
    ]


# ---------------------------------------------------------------------------
# Semantics (1): restart alone does not supersede — passes today.
# ---------------------------------------------------------------------------


def test_restart_alone_does_not_supersede(ve_ctx, tmp_path, monkeypatch):
    _register_skeptic(monkeypatch)
    uid = _seeded_user()
    _mark_weaver_done(uid)
    svc = _svc(tmp_path)
    _run_skeptic_to_completion(
        svc, uid,
        answer="I work by deadlines first, then everything else follows.",
        response="That's right.",
    )

    store = _agents(tmp_path, uid)
    first = _impression_claims(tmp_path, uid)
    assert len(first) == 1
    first = first[0]
    assert first.status == "pending"
    # The visitor rules on run 1's claim: the verdict is now the
    # thing supersede must never silently overwrite.
    assert store.update_claim(first.id, status="accepted")

    # Restart alone: archives the run verbatim, resets the meeting
    # — and touches no claim.
    state = svc.restart(uid, "skeptic")
    assert state["status"] == "not_started"
    assert len(svc.meetings.list_archives(uid, "skeptic", 1)) == 1

    claims = _impression_claims(tmp_path, uid)
    assert len(claims) == 1
    assert claims[0].id == first.id
    assert claims[0].status == "accepted"
    assert claims[0].inference == first.inference
    assert claims[0].evidence == first.evidence


# ---------------------------------------------------------------------------
# Semantics (2)–(3): two-run supersede — integration-pending.
# ---------------------------------------------------------------------------


def test_two_run_supersede_sequence(ve_ctx, tmp_path, monkeypatch):
    _register_skeptic(monkeypatch)
    uid = _seeded_user()
    _mark_weaver_done(uid)
    svc = _svc(tmp_path)
    _run_skeptic_to_completion(
        svc, uid,
        answer="I work by deadlines first, then everything else follows.",
        response="That's right.",
    )

    store = _agents(tmp_path, uid)
    first = _impression_claims(tmp_path, uid)
    assert len(first) == 1
    first = first[0]
    assert store.update_claim(first.id, status="accepted")

    svc.restart(uid, "skeptic")
    _run_skeptic_to_completion(
        svc, uid,
        answer="Second time: I start with people, not tasks.",
        response="Yes, that's the shape of it.",
    )

    claims = _impression_claims(tmp_path, uid)
    by_id = {c.id: c for c in claims}
    # Nothing is erased: both rows are retrievable via the
    # existing claim reads, and the new run files a distinct claim
    # (new run_key) under the same agent id.
    assert len(claims) == 2
    assert first.id in by_id
    old = by_id[first.id]
    new = next(c for c in claims if c.id != first.id)
    assert new.status == "pending"
    assert new.evidence == "Yes, that's the shape of it."
    # The old row is retained verbatim where it matters: same
    # inference, same evidence.
    assert old.inference == first.inference
    assert old.evidence == first.evidence
    # Prior verdict preserved visibly on the retained row: either
    # the status still shows it, or the row records it in
    # note/detail (the decision's "e.g. note/detail" shape).
    assert old.status == "accepted" or "accepted" in (
        old.detail + old.user_note
    )
    # Superseded marking (shared mechanism defines the exact
    # marker; both shapes accepted — see the module docstring).
    assert old.status == "superseded" or "superseded" in (
        old.detail + old.user_note
    ).lower()
    # Exactly ONE standing/current claim: the new one.
    standing = [
        c for c in claims
        if c.status != "superseded"
        and "superseded" not in c.detail.lower()
        and "superseded" not in c.user_note.lower()
    ]
    assert len(standing) == 1
    assert standing[0].id == new.id
