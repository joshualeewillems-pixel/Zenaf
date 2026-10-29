"""Maverick restart supersede — Joshua's decision, 2026-10-28.

Rule: prior-run claims on restart use SUPERSEDE. When a new meeting
run produces a new impression, it replaces the prior run's claim: the
old claim remains visible in the record history, but only the new claim
counts as current. Nothing is erased. DISTINCT from the
pending-impression discard rule (never-delivered impressions on
voluntary end); supersede covers prior ACCEPTED/filed claims replaced
by a new filed claim.

Precise semantics under test:
1. Restart ALONE does not supersede: restart archives the prior run
   verbatim; the prior claim stays current until a new run completes
   and files.
2. At new filing, prior meeting_impression claim(s) for the same
   agent id (meeting-maverick-1) become superseded: row retained,
   prior verdict preserved visibly in the retained row, retrievable
   via the existing claim reads.
3. After the new filing, exactly ONE standing/current
   meeting_impression claim exists for that seat + visitor.

STATUS — READ FIRST. This file is per-seat VERIFICATION, not a
mechanism. The authoritative shared supersede mechanism lives in a
separate shared-foundation follow-up PR (stacked on PR #255) and wins
at merge; this PR ships NO claim-system change and invents NO second
standing/claim system. Accordingly:

- test_restart_alone_does_not_supersede PASSES on this branch today
  (restart touches no claims) and guards the restart-alone rule
  against the shared implementation too.
- test_second_filing_supersedes_prior_claim is marked xfail
  (integration-pending): on this branch the archived run's claim
  stays untouched by design (see _file_impression's docstring), so
  the standing count is 2, not 1. When the shared mechanism lands,
  this test must XPASS — and the xfail marker must then be removed
  rather than left as decoration.

The tests drive the completion chokepoint (complete() -> _do_reveal
-> _file_impression) with fabricated read-back rows, because the
Maverick's begin is gated in this PR and a full start -> turn ->
complete -> restart -> start drive is only possible after release.
The filing contract verified is the same one the live sequence
exercises. "Standing" is defined mechanism-neutrally: a claim counts
as standing unless it visibly records supersession (in its status,
detail, or user note) — so the test accepts whatever visible marker
the shared mechanism chooses, and fails on exactly the current
behavior (no marker, two live claims).
"""

from __future__ import annotations

import json
import threading

import pytest

from local_ai.agent_intake.store import AgentStore
from local_ai.conversation.meeting import (
    MeetingService,
    MeetingStore,
    _seat_keystone_tasks,
)
from local_ai.conversation.store import ConversationStore
from local_ai.vision_execution import keystone_seeding
from local_ai.vision_execution import service as ve

AGENT_ID = "meeting-maverick-1"


@pytest.fixture()
def ve_ctx(tmp_path, monkeypatch):
    import local_ai.vision_execution.storage as ve_store

    monkeypatch.setattr(ve_store, "_DB_PATH", tmp_path / "ve.db")
    monkeypatch.setattr(ve_store, "_DB_DIR", tmp_path)
    monkeypatch.setattr(ve_store, "_init_done_paths", set())
    monkeypatch.setattr(ve_store, "_thread_local", threading.local())
    return {}


def _svc(tmp_path):
    agents_db = tmp_path / "agents.db"
    return MeetingService(
        ConversationStore(tmp_path / "conv.db"),
        MeetingStore(tmp_path / "meetings.db"),
        generate_fn=lambda prompt, **kwargs: "A plain reply.",
        agent_store_factory=lambda uid: AgentStore(agents_db, user_id=uid),
    )


def _seeded_user(email="maverick-supersede@example.com"):
    user = ve.create_user_account(email, "pw", "Mav")
    keystone_seeding.seed_meet_your_council(user["id"])
    return user["id"]


def _claims(tmp_path, uid):
    return AgentStore(tmp_path / "agents.db", user_id=uid).get_claims(AGENT_ID)


def _meeting_claims(tmp_path, uid):
    return [c for c in _claims(tmp_path, uid) if c.claim_type == "meeting_impression"]


def _complete_run(svc, uid, run_created_at, readback, response):
    """Fabricate an in-progress Maverick run with a read-back, then
    close it through the real completion chokepoint so the filing
    path (not a private helper) is what files the claim."""
    svc.meetings.create(uid, "maverick", 1)
    svc.meetings.update(
        uid, "maverick", 1,
        status="active",
        readback_claim=readback,
        readback_response=response,
        readback_strands=json.dumps(["Compass"]),
    )
    # MeetingStore.update whitelists its fields (created_at is not one),
    # but the run key comes from created_at — pin it directly so the
    # two runs' claim ids differ deterministically, not by wall-clock luck.
    with svc.meetings._lock:
        svc.meetings._conn.execute(
            "UPDATE meetings SET created_at = ? WHERE user_id = ? "
            "AND archetype_id = ? AND keystone_index = ?",
            (run_created_at, uid, "maverick", 1),
        )
        svc.meetings._conn.commit()
    state = svc.complete(uid, "maverick")
    assert state["status"] == "complete"
    assert _seat_keystone_tasks(uid, "maverick")[0]["status"] == "Done"


def _is_superseded(claim) -> bool:
    hay = " ".join((claim.status, claim.detail, claim.user_note)).lower()
    return "superseded" in hay


def _standing(claims):
    return [c for c in claims if not _is_superseded(c)]


def test_restart_alone_does_not_supersede(ve_ctx, tmp_path):
    """Semantics 1: restart archives verbatim and touches no claim.
    Passes on this branch today; guards the shared implementation
    against superseding at restart instead of at new filing."""
    uid = _seeded_user()
    svc = _svc(tmp_path)
    _complete_run(
        svc, uid, "2026-10-28T10:00:00+00:00",
        "Run one: you orient by the door nobody chose.",
        "That's right.",
    )
    claims = _meeting_claims(tmp_path, uid)
    assert len(claims) == 1
    run1 = claims[0]
    # The visitor rules on run 1: verdict recorded.
    AgentStore(tmp_path / "agents.db", user_id=uid).update_claim(
        run1.id, "accepted", "Yes — that is how I orient.")
    svc.restart(uid, "maverick")
    # The archive kept the run; the claim is untouched and current.
    assert svc.meetings.get(uid, "maverick", 1) is None
    assert svc.meetings.list_archives(uid, "maverick", 1), "run archived verbatim"
    after = _meeting_claims(tmp_path, uid)
    assert len(after) == 1
    assert after[0].id == run1.id
    assert after[0].status == "accepted"
    assert not _is_superseded(after[0])
    assert len(_standing(after)) == 1


@pytest.mark.xfail(
    reason=(
        "integration-pending: the shared supersede follow-up PR "
        "(stacked on PR #255) owns the mechanism; this branch ships "
        "none. Remove this marker when that PR lands — the test must "
        "then XPASS and the marker must go, not linger."
    ),
    strict=False,
)
def test_second_filing_supersedes_prior_claim(ve_ctx, tmp_path):
    """Semantics 2+3: run 1 files and is accepted; restart (no change);
    run 2 files; the run-1 row is retained with its prior verdict
    visible and marked superseded; exactly one claim stands."""
    uid = _seeded_user()
    svc = _svc(tmp_path)
    _complete_run(
        svc, uid, "2026-10-28T10:00:00+00:00",
        "Run one: you orient by the door nobody chose.",
        "That's right.",
    )
    run1 = _meeting_claims(tmp_path, uid)[0]
    AgentStore(tmp_path / "agents.db", user_id=uid).update_claim(
        run1.id, "accepted", "Yes — that is how I orient.")
    svc.restart(uid, "maverick")
    assert len(_standing(_meeting_claims(tmp_path, uid))) == 1  # restart alone: no change
    _complete_run(
        svc, uid, "2026-10-28T11:00:00+00:00",
        "Run two: you orient by the exit you hold open, not the room.",
        "Closer — that second one.",
    )
    claims = _meeting_claims(tmp_path, uid)
    # Nothing erased: both rows retrievable.
    assert len(claims) == 2
    by_id = {c.id: c for c in claims}
    assert run1.id in by_id
    old, new = by_id[run1.id], [c for c in claims if c.id != run1.id][0]
    # The old row visibly records supersession AND its prior verdict.
    assert _is_superseded(old)
    assert "accepted" in " ".join((old.detail, old.user_note)).lower()
    # Exactly one standing claim, and it is the new filing.
    standing = _standing(claims)
    assert len(standing) == 1
    assert standing[0].id == new.id
    assert new.inference.startswith("Run two:")
