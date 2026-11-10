"""Slice 2 tests: the encounter store and lifecycle (non-destructive Meet Again).

Proposal §3 (LATEST vs ACTIVE, the corrected _do_reveal order, the
completion-recovery gate) and §2 (fence/finalize).

- T-S2-1  start() creates run 1: run-specific conversation id, the
  recorded opening (script id/version/paragraphs/expected), status
  in_progress, the meetings row points at it
- T-S2-2  a second start() resumes without re-speaking the opening
- T-S2-3  complete() + _do_reveal: the corrected order — reveal keys,
  task Done, fence closed, atomic finalize, meetings mirror; a second
  complete() / _do_reveal is a no-op (no duplicate reveal)
- T-S2-4  turn() to a completed encounter is refused 409
  encounter_finalized and the transcript is unchanged
- T-S2-5  state(): run_id + read_only, demeanor from ANY completed
  encounter
- T-S2-6  met_seats reads encounters only (a meetings-row-only
  completion does not count until materialized)
- T-S2-7  lazy materialization from a meetings row (active + complete)
- T-S2-8  finalize_encounter atomicity + idempotency + the mirror rule
- T-S2-9  list_active UNION (encounter rows + meetings-row-only rows)
- T-S2-10 recovery CR-B5 (fence closed + finalized_at NULL -> finalize)
- T-S2-11 recovery CR-B1/B2 (partial reveal -> re-run completes it
  without duplicating the reveal)
- T-S2-12 recovery 'creating' (resumed with a recorded opening; fails
  closed without one)
- T-S2-13 concurrent starts for one key create exactly one run
- T-S2-14 the run_key / claim identity (new run: run_id; legacy run:
  created_at-derived)
- T-S2-15 _do_reveal re-run idempotency (spoken once, task Done once)

AC11, AC12 (creation idempotency), AC13 (keystone separation),
AC14 (finalization guard), AC24 (CR-B1/B2/B5 here; the deterministic
termination tests land in Slice 6).
"""

from __future__ import annotations

import json
import re
import threading

import pytest

from local_ai.conversation.meeting import (
    MeetingError,
    MeetingService,
    MeetingStore,
    _opening_digest,
    _run_key_for_encounter,
    _seat_keystone_tasks,
)
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


def _svc(tmp_path):
    return MeetingService(
        ConversationStore(tmp_path / "conv.db"),
        MeetingStore(tmp_path / "meetings.db"),
        generate_fn=lambda prompt, **kwargs: "A plain reply.",
    )


def _seeded_user(email="s2@example.com"):
    user = ve.create_user_account(email, "pw", "S2")
    keystone_seeding.seed_meet_your_council(user["id"])
    return user["id"]


def _reveal_keys(svc, uid, cid):
    return [
        m
        for m in svc.conversations.history(uid, cid, limit=200)
        if (m.get("context") or {}).get("meeting")
    ]


def test_t_s2_1_start_creates_run_1(ve_ctx, tmp_path):
    """T-S2-1 (AC2/AC12/AC20): start() creates run 1 with a
    run-specific conversation id, the recorded opening identity, status
    in_progress, and the meetings row pointing at it."""
    uid = _seeded_user()
    svc = _svc(tmp_path)
    state = svc.start(uid, "conductor")
    assert state["status"] == "active"
    assert state["run_id"]
    run_id = state["run_id"]
    assert state["conversation_id"] == f"meeting-conductor-1-{run_id}"
    assert state["read_only"] is False

    enc = svc.meetings.get_latest_encounter(uid, "conductor", 1)
    assert enc["run_id"] == run_id
    assert enc["run_number"] == 1
    assert enc["predecessor_run_id"] is None
    assert enc["conversation_id"] == f"meeting-conductor-1-{run_id}"
    assert enc["status"] == "in_progress"
    assert enc["transcript_source"] == "live"
    assert enc["run_id_provenance"] == "generated"
    assert enc["task_id"] == _seat_keystone_tasks(uid, "conductor")[0]["id"]
    # The recorded opening (proposal §3.3).
    script = MT.get_script("conductor", 1)
    from local_ai.conversation import encounter as ENC

    paragraphs = list(ENC.get_definition(script).opening)
    assert enc["opening_script_id"] == "conductor:1"
    assert enc["opening_script_version"] == _opening_digest(paragraphs)
    assert enc["opening_paragraphs"] == paragraphs
    assert enc["opening_expected"] == len(paragraphs) == 4
    # The meetings row points at the encounter.
    mrow = svc.meetings.get(uid, "conductor", 1)
    assert mrow["run_id"] == run_id
    assert mrow["conversation_id"] == f"meeting-conductor-1-{run_id}"
    # The fence is open.
    assert svc.conversations.get_fence_state(uid, f"meeting-conductor-1-{run_id}") == "open"
    # The opening was spoken once, with its identities.
    msgs = svc.conversations.history(uid, f"meeting-conductor-1-{run_id}", limit=200)
    assert [m["body"] for m in msgs] == paragraphs


def test_t_s2_2_resume_never_repeats_opening(ve_ctx, tmp_path):
    """T-S2-2 (AC12): a second start() resumes without re-speaking
    the opening — the transcript is byte-identical."""
    uid = _seeded_user()
    svc = _svc(tmp_path)
    first = svc.start(uid, "conductor")
    second = svc.start(uid, "conductor")
    assert second["run_id"] == first["run_id"]
    assert len(second["messages"]) == len(first["messages"]) == 4
    assert svc.meetings.get_latest_encounter(uid, "conductor", 1)["run_number"] == 1


def test_t_s2_3_complete_and_reveal_order(ve_ctx, tmp_path):
    """T-S2-3 (AC1/AC14): the corrected _do_reveal order — the reveal
    carries its durable identities, the keystone task is Done, the
    fence is closed, the encounter finalizes atomically (incl. the
    meetings-row mirror), and a second close is a no-op (no duplicate
    reveal, no second task write)."""
    uid = _seeded_user()
    svc = _svc(tmp_path)
    state = svc.start(uid, "conductor")
    run_id = state["run_id"]
    cid = state["conversation_id"]
    script = MT.get_script("conductor", 1)

    # The spoken close (the recognition tests' path): wrap + reveal.
    svc._do_reveal(uid, "conductor", 1, script, wrap_line="wrap line",
                   silent_close=False)
    msgs = svc.conversations.history(uid, cid, limit=200)
    bodies = [m["body"] for m in msgs]
    assert bodies[4] == "wrap line"
    assert bodies[5:] == list(script.reveal)
    # The reveal identities: wrap is index 0, paragraphs 1..n.
    keys = svc.conversations.messages_by_key_prefix(uid, cid, f"reveal:{run_id}:")
    assert [m["message_key"] for m in keys] == [
        f"reveal:{run_id}:{i}" for i in range(len(script.reveal) + 1)
    ]
    # Task Done, fence closed, encounter complete, mirror complete.
    assert _seat_keystone_tasks(uid, "conductor")[0]["status"] == "Done"
    assert svc.conversations.get_fence_state(uid, cid) == "closed"
    enc = svc.meetings.get_latest_encounter(uid, "conductor", 1)
    assert enc["status"] == "complete"
    assert enc["finalized_at"]
    assert enc["completed_at"]
    assert enc["message_count"] == len(msgs)
    mrow = svc.meetings.get(uid, "conductor", 1)
    assert mrow["status"] == "complete"
    assert mrow["stage"] == "complete"
    assert mrow["run_id"] == run_id

    # A second close is a no-op: nothing re-spoken, nothing re-filed.
    before = svc.conversations.history(uid, cid, limit=200)
    svc._do_reveal(uid, "conductor", 1, script, wrap_line="wrap line",
                   silent_close=False)
    after = svc.conversations.history(uid, cid, limit=200)
    assert [m["id"] for m in after] == [m["id"] for m in before]
    assert svc.complete(uid, "conductor")["status"] == "complete"


def test_t_s2_4_turn_to_completed_encounter_refused(ve_ctx, tmp_path):
    """T-S2-4 (AC7): a turn to a completed encounter is refused with
    ``encounter_finalized`` and the transcript is unchanged — the
    encounter's last stored message is its last word, no retry."""
    uid = _seeded_user()
    svc = _svc(tmp_path)
    state = svc.start(uid, "conductor")
    svc.complete(uid, "conductor")
    before = svc.conversations.history(uid, state["conversation_id"], limit=200)
    with pytest.raises(MeetingError) as excinfo:
        svc.turn(uid, "conductor", "hello again")
    assert excinfo.value.code == "encounter_finalized"
    assert excinfo.value.run_id == state["run_id"]
    after = svc.conversations.history(uid, state["conversation_id"], limit=200)
    assert [m["id"] for m in after] == [m["id"] for m in before]


def test_t_s2_5_state_demeanor_from_any_completed_encounter(ve_ctx, tmp_path):
    """T-S2-5 (AC11): state() carries run_id + read_only, and the
    demeanor unlocks when ANY completed encounter exists for the key
    (a later run never re-locks the face)."""
    uid = _seeded_user()
    svc = _svc(tmp_path)
    state = svc.start(uid, "conductor")
    assert state["demeanor"] is None
    assert state["read_only"] is False
    svc.complete(uid, "conductor")
    done = svc.state(uid, "conductor")
    assert done["status"] == "complete"
    assert done["read_only"] is True
    assert done["run_id"] == state["run_id"]
    assert done["demeanor"] == MT.get_script("conductor", 1).demeanor


def test_t_s2_6_met_seats_encounters_only(ve_ctx, tmp_path):
    """T-S2-6 (AC11): met_seats reads the encounters, never the
    meetings rows — a meetings row marked complete without an
    encounter row does not count; materializing it (via state())
    makes it count."""
    uid = _seeded_user()
    svc = _svc(tmp_path)
    svc.meetings.create(uid, "champion", 1)
    svc.meetings.update(uid, "champion", 1, status="complete")
    assert svc.meetings.met_seats(uid) == []
    svc.state(uid, "champion", 1)
    assert svc.meetings.met_seats(uid) == ["champion"]


def test_t_s2_7_lazy_materialization(ve_ctx, tmp_path):
    """T-S2-7: a meetings row that predates encounters materializes
    on read — run 1, provenance 'generated-migration', the fence
    created (open for an active meeting, closed for a completed one),
    and the meetings row pointed at the new run."""
    uid = _seeded_user()
    svc = _svc(tmp_path)
    # Active meetings row + a live message under the legacy shared id.
    svc.meetings.create(uid, "mentor", 1)
    svc.conversations.ensure_conversation(uid, "meeting-mentor-1", kind="meeting")
    svc.conversations.append_message(uid, "meeting-mentor-1", "mentor", "user",
                                     "hello", via_meeting=True)
    enc, mrow = svc._resolve_encounter(uid, "mentor", 1)
    assert enc["run_number"] == 1
    assert enc["run_id_provenance"] == "generated-migration"
    assert enc["transcript_source"] == "live"
    assert enc["conversation_id"] == "meeting-mentor-1"
    assert enc["status"] == "in_progress"
    assert enc["opening_expected"] == 0
    assert enc["opening_paragraphs"] is None
    assert svc.conversations.get_fence_state(uid, "meeting-mentor-1") == "open"
    assert svc.meetings.get(uid, "mentor", 1)["run_id"] == enc["run_id"]
    # A second resolve returns the same row (no duplicate run).
    enc2, _ = svc._resolve_encounter(uid, "mentor", 1)
    assert enc2["run_id"] == enc["run_id"]

    # A completed meetings row materializes complete, fence closed.
    svc.meetings.create(uid, "champion", 1)
    svc.meetings.update(uid, "champion", 1, status="complete", stage="complete")
    enc3, _ = svc._resolve_encounter(uid, "champion", 1)
    assert enc3["status"] == "complete"
    assert enc3["finalized_at"]
    assert svc.conversations.get_fence_state(uid, "meeting-champion-1") == "closed"


def test_t_s2_8_finalize_is_atomic_and_idempotent(ve_ctx, tmp_path):
    """T-S2-8 (AC14/AC18): finalize_encounter flips the encounter and
    mirrors the meetings row in one transaction, and is idempotent —
    a second call returns the same row unchanged. The mirror is
    skipped once the meetings row points at a different run."""
    uid = _seeded_user()
    svc = _svc(tmp_path)
    state = svc.start(uid, "conductor")
    run_id = state["run_id"]
    enc = svc.meetings.finalize_encounter(uid, run_id, message_count=4)
    assert enc["status"] == "complete"
    assert enc["finalized_at"]
    assert enc["message_count"] == 4
    assert svc.meetings.get(uid, "conductor", 1)["status"] == "complete"
    again = svc.meetings.finalize_encounter(uid, run_id, message_count=99)
    assert again["finalized_at"] == enc["finalized_at"]
    assert again["message_count"] == 4  # unchanged by the second call

    # The mirror rule: once the meetings row points at a successor,
    # finalizing the predecessor must not overwrite the pointer. A
    # successor is created directly (the store does not enforce the
    # entry rule) and the meetings row is pointed at it while run 1
    # is still un-finalized.
    uid2 = _seeded_user(email="s2-mirror@example.com")
    svc2 = _svc(tmp_path)
    state2 = svc2.start(uid2, "conductor")
    run1 = state2["run_id"]
    svc2.meetings.create_encounter(
        run_id="run-successor", user_id=uid2, archetype_id="conductor",
        keystone_index=1, run_number=2, predecessor_run_id=run1,
        conversation_id="meeting-conductor-1-run-successor",
        status="in_progress",
    )
    svc2.meetings.update(
        uid2, "conductor", 1, run_id="run-successor",
        conversation_id="meeting-conductor-1-run-successor",
        status="active", stage="encounter",
    )
    finalized = svc2.meetings.finalize_encounter(uid2, run1, message_count=4)
    assert finalized["status"] == "complete"
    mrow2 = svc2.meetings.get(uid2, "conductor", 1)
    assert mrow2["run_id"] == "run-successor"
    assert mrow2["status"] == "active"


def test_t_s2_9_list_active_union(ve_ctx, tmp_path):
    """T-S2-9: list_active returns in-progress ENCOUNTER rows (with
    run_id + conversation_id) UNION meetings rows with status active
    that have no encounter row yet."""
    uid = _seeded_user()
    svc = _svc(tmp_path)
    state = svc.start(uid, "conductor")
    svc.meetings.create(uid, "mentor", 1)  # meetings-row only, active
    rows = svc.meetings.list_active(uid)
    by_arch = {r["archetype_id"]: r for r in rows}
    assert set(by_arch) == {"conductor", "mentor"}
    assert by_arch["conductor"]["run_id"] == state["run_id"]
    assert by_arch["conductor"]["conversation_id"] == state["conversation_id"]
    assert by_arch["mentor"].get("run_id") is None
    assert by_arch["mentor"]["conversation_id"] == "meeting-mentor-1"
    # Completing the conductor drops it from the active set.
    svc.complete(uid, "conductor")
    assert [r["archetype_id"] for r in svc.meetings.list_active(uid)] == ["mentor"]


def test_t_s2_10_recovery_cr_b5(ve_ctx, tmp_path):
    """T-S2-10 (AC24, CR-B5): fence closed + finalized_at NULL heals
    by completing the finalize from the already-recorded artifacts —
    never re-running _do_reveal, never re-speaking."""
    uid = _seeded_user()
    svc = _svc(tmp_path)
    state = svc.start(uid, "conductor")
    run_id = state["run_id"]
    cid = state["conversation_id"]
    # Simulate the crash between the fence close (step 5) and the
    # finalize (step 6): close the fence, leave finalized_at NULL.
    assert svc.conversations.close_fence(uid, cid, run_id) == "closed"
    enc = svc.meetings.get_latest_encounter(uid, "conductor", 1)
    assert enc["status"] == "in_progress"
    assert enc["finalized_at"] is None
    records = svc.recover_incomplete_encounters(uid)
    assert [r for r in records if r["action"] == "finalized_cr_b5"]
    enc = svc.meetings.get_latest_encounter(uid, "conductor", 1)
    assert enc["status"] == "complete"
    assert enc["finalized_at"]
    assert svc.meetings.get(uid, "conductor", 1)["status"] == "complete"
    # The transcript was never re-spoken (still just the opening).
    assert len(svc.conversations.history(uid, cid, limit=200)) == 4


def test_t_s2_11_recovery_partial_reveal(ve_ctx, tmp_path):
    """T-S2-11 (AC24, CR-B1/B2): a reveal interrupted mid-speech
    (wrap + first paragraph in the transcript, fence open, not
    finalized) heals by re-running _do_reveal — the spoken paragraphs
    return existing (insert-if-absent) and only the missing ones are
    added, so the reveal appears exactly once."""
    uid = _seeded_user()
    svc = _svc(tmp_path)
    state = svc.start(uid, "conductor")
    run_id = state["run_id"]
    cid = state["conversation_id"]
    script = MT.get_script("conductor", 1)
    # The crash state: wrap + reveal[0] spoken, the rest not.
    svc.conversations.append_message(
        uid, cid, "conductor", "voice", "wrap line", mode="base",
        context={"meeting": True}, message_key=f"reveal:{run_id}:0",
        via_meeting=True,
    )
    svc.conversations.append_message(
        uid, cid, "conductor", "voice", script.reveal[0], mode="base",
        context={"meeting": True}, message_key=f"reveal:{run_id}:1",
        via_meeting=True,
    )
    records = svc.recover_incomplete_encounters(uid)
    assert [r for r in records if r["action"] == "reveal_replayed"]
    msgs = svc.conversations.history(uid, cid, limit=200)
    bodies = [m["body"] for m in msgs]
    assert bodies[4] == "wrap line"
    assert bodies[5:] == list(script.reveal)
    assert len(bodies) == 4 + 1 + len(script.reveal)
    enc = svc.meetings.get_latest_encounter(uid, "conductor", 1)
    assert enc["status"] == "complete"
    assert svc.conversations.get_fence_state(uid, cid) == "closed"


def test_t_s2_12_recovery_creating(ve_ctx, tmp_path):
    """T-S2-12 (AC12/AC24): an encounter stuck in 'creating' with a
    recorded opening resumes (the opening re-attempts insert-if-absent,
    then the flip); one with NO recorded opening fails closed — the
    encounter stays creating, with the reason recorded."""
    uid = _seeded_user()
    svc = _svc(tmp_path)
    # With a recorded opening: the creation resumes.
    state = svc.start(uid, "conductor")
    run_id = state["run_id"]
    svc.meetings.update_encounter(uid, run_id, status="creating")
    records = svc.recover_incomplete_encounters(uid)
    assert [r for r in records if r["action"] == "creation_resumed"]
    enc = svc.meetings.get_latest_encounter(uid, "conductor", 1)
    assert enc["status"] == "in_progress"
    assert len(svc.conversations.history(uid, state["conversation_id"], limit=200)) == 4

    # Without a recorded opening: fail closed.
    uid2 = _seeded_user(email="s2-creating@example.com")
    svc2 = _svc(tmp_path)
    enc2 = svc2.meetings.create_encounter(
        run_id="run-orphan", user_id=uid2, archetype_id="conductor",
        keystone_index=1, run_number=1,
        conversation_id="meeting-conductor-1-run-orphan",
        status="creating",
    )
    records = svc2.recover_incomplete_encounters(uid2)
    failed = [r for r in records if r["action"] == "failed"]
    assert failed and "never recorded" in failed[0]["detail"]
    assert svc2.meetings.get_encounter(uid2, "run-orphan")["status"] == "creating"


def test_t_s2_13_concurrent_starts_create_one_run(ve_ctx, tmp_path):
    """T-S2-13 (AC12/AC19-adjacent): two concurrent starts for one key
    create exactly one run-1 encounter (the per-key lock + the unique
    run_number)."""
    uid = _seeded_user()
    svc = _svc(tmp_path)
    results: list = []
    errors: list = []

    def _start():
        try:
            results.append(svc.start(uid, "conductor"))
        except Exception as exc:  # noqa: BLE001 — collected below
            errors.append(exc)

    threads = [threading.Thread(target=_start) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors, errors
    assert len(results) == 2
    assert results[0]["run_id"] == results[1]["run_id"]
    assert len(svc.meetings.list_encounters(uid, "conductor", 1)) == 1


def test_t_s2_14_run_key_claim_identity(ve_ctx, tmp_path):
    """T-S2-14 (AC13): the impression claim id carries the run's key —
    the run_id for a new run, the created_at-derived key for a run
    that predates encounters — so a re-filing of the same run finds
    its existing claim instead of filing a second one."""
    uid = _seeded_user()
    svc = _svc(tmp_path)
    state = svc.start(uid, "conductor")
    run_id = state["run_id"]
    script = MT.get_script("conductor", 1)
    # A read-back, as the host would have recorded it.
    svc.meetings.update(
        uid, "conductor", 1,
        readback_claim="You conduct.",
        readback_response="That's right.",
        readback_strands=json.dumps(["Compass"]),
    )
    svc._file_impression(uid, "conductor", 1, script)
    from local_ai.agent_intake.store import AgentStore

    store = AgentStore(user_id=uid)
    claims = store.get_claims("meeting-conductor-1")
    assert len(claims) == 1
    # The claim id carries the run_id (not the created_at key).
    assert run_id in claims[0].id
    # Re-filing the same run is a no-op (no second claim).
    svc._file_impression(uid, "conductor", 1, script)
    assert len(store.get_claims("meeting-conductor-1")) == 1
    store.close()

    # A legacy (materialized) run keeps its created_at-derived key:
    # the claim id matches the old computation, so the pre-existing
    # claim is found, not duplicated.
    uid2 = _seeded_user(email="s2-legacy@example.com")
    svc2 = _svc(tmp_path)
    svc2.meetings.create(uid2, "mentor", 1)
    svc2.meetings.update(
        uid2, "mentor", 1,
        readback_claim="You garden.",
        readback_response="Yes.",
        readback_strands=json.dumps(["Compass"]),
        status="complete", stage="complete",
    )
    mrow = svc2.meetings.get(uid2, "mentor", 1)
    legacy_key = re.sub(r"[^0-9A-Za-z]", "", mrow["created_at"] or "") or "run"
    enc, _ = svc2._resolve_encounter(uid2, "mentor", 1)
    assert _run_key_for_encounter(enc, mrow) == legacy_key
    assert legacy_key not in enc["run_id"]
    script2 = MT.get_script("mentor", 1)
    svc2._file_impression(uid2, "mentor", 1, script2)
    store2 = AgentStore(user_id=uid2)
    claims2 = store2.get_claims("meeting-mentor-1")
    assert len(claims2) == 1
    assert legacy_key in claims2[0].id
    svc2._file_impression(uid2, "mentor", 1, script2)
    assert len(store2.get_claims("meeting-mentor-1")) == 1
    store2.close()


def test_t_s2_15_do_reveal_rerun_is_idempotent(ve_ctx, tmp_path):
    """T-S2-15 (AC14/AC24): re-running _do_reveal speaks the reveal
    once — the second run returns the existing messages, marks the
    already-Done task a no-op, and finalizes once."""
    uid = _seeded_user()
    svc = _svc(tmp_path)
    state = svc.start(uid, "conductor")
    cid = state["conversation_id"]
    script = MT.get_script("conductor", 1)
    svc._do_reveal(uid, "conductor", 1, script, wrap_line="wrap line",
                   silent_close=False)
    first = svc.conversations.history(uid, cid, limit=200)
    svc._do_reveal(uid, "conductor", 1, script, wrap_line="wrap line",
                   silent_close=False)
    second = svc.conversations.history(uid, cid, limit=200)
    assert [m["id"] for m in second] == [m["id"] for m in first]
    assert _seat_keystone_tasks(uid, "conductor")[0]["status"] == "Done"
    assert svc.meetings.get_latest_encounter(uid, "conductor", 1)["status"] == "complete"
