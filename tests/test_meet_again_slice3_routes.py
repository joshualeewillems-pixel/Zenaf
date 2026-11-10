"""Slice 3 tests: Meet Again endpoint + encounters routes + retirement.

Proposal §5 (routes), §2 (safeguards), Appendix A (meet_again_requests).

- T-S3-1  meet_again creates run 2: the predecessor is byte-identical
  (AC1), distinct conversation ids (AC2), run_number 2, predecessor
  bound, lineage walks 2 -> 1 (AC4)
- T-S3-2  a retry with the same request_id returns the existing
  successor (resumed, successor_exists) — no duplicate run (AC15/AC19)
- T-S3-3  the same request_id for a different predecessor -> 409
  request_identity_conflict (AC15)
- T-S3-4  a missing predecessor_run_id -> 422 predecessor_required
- T-S3-5  an unknown predecessor -> 422 predecessor_unknown
- T-S3-6  no encounter ever existed -> 404
- T-S3-7  a predecessor still in progress -> 409 encounter_in_progress
- T-S3-8  three runs: the chain walks 3 -> 2 -> 1 (AC4)
- T-S3-9  encounters list + detail routes: owner-scoped, read_only for
  a completed encounter, another user's run_id -> 404 (AC8)
- T-S3-10 GET /meeting?run_id= hydrates a specific encounter (read_only
  for a historical one); a foreign run_id -> 404
- T-S3-11 retirement: no restart route, no MeetingService.restart, no
  MeetingStore.delete (AC3)
- T-S3-12 concurrent meet_again calls yield exactly one successor (AC19)
- T-S3-13 the meet-again route: a missing Idempotency-Key -> 422; a
  valid key -> 200 with encounter/state/resumed
- T-S3-14 a retry after a crash during creation resumes the 'creating'
  successor (the recorded opening is replayed, never re-recorded)
"""

from __future__ import annotations

import threading

import pytest
from fastapi import HTTPException

import api.routes.conversation_routes as routes
from local_ai.conversation.meeting import (
    MeetingError,
    MeetingNotFoundError,
    MeetingService,
    MeetingStore,
    MeetingValidationError,
)
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


def _svc(tmp_path):
    return MeetingService(
        ConversationStore(tmp_path / "conv.db"),
        MeetingStore(tmp_path / "meetings.db"),
        generate_fn=lambda prompt, **kwargs: "A plain reply.",
    )


def _seeded_user(email="s3@example.com"):
    user = ve.create_user_account(email, "pw", "S3")
    keystone_seeding.seed_meet_your_council(user["id"])
    return user["id"]


def _complete_conductor(svc, uid):
    """Drive the Weaver's meeting to its close (start + turns + the
    visitor's own Complete when the runtime hasn't closed it)."""
    svc.start(uid, "conductor")
    svc.turn(uid, "conductor", "I work by deadlines first, then everything else follows.")
    svc.turn(
        uid, "conductor",
        "And in my own work it's the same — what breaks first gets my hands first.",
    )
    state = svc.turn(uid, "conductor", "That's right.")
    if state["status"] != "complete":
        state = svc.turn(uid, "conductor", "Got it.")
    if state["status"] != "complete":
        state = svc.complete(uid, "conductor")
    assert state["status"] == "complete"
    return state


def _messages(svc, uid, cid):
    return svc.conversations.history(uid, cid, limit=200)


def test_t_s3_1_meet_again_creates_run_2(ve_ctx, tmp_path):
    """T-S3-1 (AC1/AC2/AC4): meet_again creates run 2; the predecessor
    is byte-identical, the conversations are distinct, run_number 2,
    the predecessor is bound, the lineage walks 2 -> 1."""
    uid = _seeded_user()
    svc = _svc(tmp_path)
    _complete_conductor(svc, uid)
    run1 = svc.meetings.get_latest_encounter(uid, "conductor", 1)
    assert run1["run_number"] == 1
    pred_row_before = dict(run1)
    pred_msgs_before = _messages(svc, uid, run1["conversation_id"])

    out = svc.meet_again(
        uid, "conductor", 1,
        predecessor_run_id=run1["run_id"], request_id="req-1",
    )
    assert out["resumed"] is False
    assert out["successor_exists"] is False
    run2 = out["encounter"]
    assert run2["run_number"] == 2
    assert run2["predecessor_run_id"] == run1["run_id"]
    assert run2["predecessor_link_kind"] == "witnessed"
    assert run2["conversation_id"] == f"meeting-conductor-1-{run2['run_id']}"
    assert run2["conversation_id"] != run1["conversation_id"]
    assert run2["status"] == "in_progress"
    # AC1: the predecessor is byte-identical.
    assert dict(svc.meetings.get_encounter(uid, run1["run_id"])) == pred_row_before
    assert _messages(svc, uid, run1["conversation_id"]) == pred_msgs_before
    # The successor's messages are disjoint from the predecessor's —
    # by message id (the two runs share the script's opening text by
    # design, so bodies overlap; the rows are distinct).
    run2_ids = {m["id"] for m in _messages(svc, uid, run2["conversation_id"])}
    pred_ids = {m["id"] for m in pred_msgs_before}
    assert not (run2_ids & pred_ids)
    # The meetings row now points at the successor.
    assert svc.meetings.get(uid, "conductor", 1)["run_id"] == run2["run_id"]
    # The lineage walks 2 -> 1.
    chain = svc.list_encounters(uid, "conductor", 1)
    assert [e["run_number"] for e in chain] == [1, 2]
    assert chain[1]["predecessor_run_id"] == chain[0]["run_id"]


def test_t_s3_2_retry_returns_existing_successor(ve_ctx, tmp_path):
    """T-S3-2 (AC15/AC19): a retry with the same request_id returns the
    existing successor (resumed, successor_exists) — no second run."""
    uid = _seeded_user()
    svc = _svc(tmp_path)
    _complete_conductor(svc, uid)
    run1 = svc.meetings.get_latest_encounter(uid, "conductor", 1)
    first = svc.meet_again(
        uid, "conductor", 1,
        predecessor_run_id=run1["run_id"], request_id="req-retry",
    )
    second = svc.meet_again(
        uid, "conductor", 1,
        predecessor_run_id=run1["run_id"], request_id="req-retry",
    )
    assert second["resumed"] is True
    assert second["successor_exists"] is True
    assert second["encounter"]["run_id"] == first["encounter"]["run_id"]
    assert len(svc.list_encounters(uid, "conductor", 1)) == 2


def test_t_s3_3_same_request_id_different_predecessor_conflicts(ve_ctx, tmp_path):
    """T-S3-3 (AC15): the same request_id for a different predecessor
    is a 409 request_identity_conflict."""
    uid = _seeded_user()
    svc = _svc(tmp_path)
    _complete_conductor(svc, uid)
    run1 = svc.meetings.get_latest_encounter(uid, "conductor", 1)
    svc.meet_again(
        uid, "conductor", 1,
        predecessor_run_id=run1["run_id"], request_id="req-conflict",
    )
    with pytest.raises(MeetingError) as exc_info:
        svc.meet_again(
            uid, "conductor", 1,
            predecessor_run_id="some-other-run", request_id="req-conflict",
        )
    assert exc_info.value.code == "request_identity_conflict"


def test_t_s3_4_missing_predecessor_is_422(ve_ctx, tmp_path):
    """T-S3-4: a missing predecessor_run_id -> 422 predecessor_required."""
    uid = _seeded_user()
    svc = _svc(tmp_path)
    _complete_conductor(svc, uid)
    with pytest.raises(MeetingValidationError) as exc_info:
        svc.meet_again(uid, "conductor", 1, predecessor_run_id="", request_id="req-x")
    assert exc_info.value.code == "predecessor_required"
    with pytest.raises(MeetingValidationError) as exc_info:
        svc.meet_again(uid, "conductor", 1, predecessor_run_id=None, request_id="req-x")
    assert exc_info.value.code == "predecessor_required"


def test_t_s3_5_unknown_predecessor_is_422(ve_ctx, tmp_path):
    """T-S3-5: an unknown predecessor run id -> 422 predecessor_unknown."""
    uid = _seeded_user()
    svc = _svc(tmp_path)
    _complete_conductor(svc, uid)
    with pytest.raises(MeetingValidationError) as exc_info:
        svc.meet_again(
            uid, "conductor", 1,
            predecessor_run_id="no-such-run", request_id="req-unknown",
        )
    assert exc_info.value.code == "predecessor_unknown"


def test_t_s3_6_no_encounter_ever_is_404(ve_ctx, tmp_path):
    """T-S3-6: no encounter ever existed for the key -> 404."""
    uid = _seeded_user()
    svc = _svc(tmp_path)
    with pytest.raises(MeetingNotFoundError) as exc_info:
        svc.meet_again(
            uid, "conductor", 1,
            predecessor_run_id="no-such-run", request_id="req-none",
        )
    assert exc_info.value.code == "encounter_not_found"


def test_t_s3_7_in_progress_predecessor_is_409(ve_ctx, tmp_path):
    """T-S3-7: a predecessor still in progress -> 409 encounter_in_progress."""
    uid = _seeded_user()
    svc = _svc(tmp_path)
    svc.start(uid, "conductor")
    run1 = svc.meetings.get_latest_encounter(uid, "conductor", 1)
    with pytest.raises(MeetingError) as exc_info:
        svc.meet_again(
            uid, "conductor", 1,
            predecessor_run_id=run1["run_id"], request_id="req-live",
        )
    assert exc_info.value.code == "encounter_in_progress"
    assert exc_info.value.run_id == run1["run_id"]


def test_t_s3_8_three_runs_chain_walks(ve_ctx, tmp_path):
    """T-S3-8 (AC4): three runs; the chain walks 3 -> 2 -> 1."""
    uid = _seeded_user()
    svc = _svc(tmp_path)
    _complete_conductor(svc, uid)
    run1 = svc.meetings.get_latest_encounter(uid, "conductor", 1)
    svc.meet_again(
        uid, "conductor", 1,
        predecessor_run_id=run1["run_id"], request_id="req-2",
    )
    _complete_conductor(svc, uid)
    run2 = svc.meetings.get_latest_encounter(uid, "conductor", 1)
    assert run2["run_number"] == 2
    svc.meet_again(
        uid, "conductor", 1,
        predecessor_run_id=run2["run_id"], request_id="req-3",
    )
    run3 = svc.meetings.get_latest_encounter(uid, "conductor", 1)
    assert run3["run_number"] == 3
    assert run3["predecessor_run_id"] == run2["run_id"]
    assert run2["predecessor_run_id"] == run1["run_id"]
    chain = svc.list_encounters(uid, "conductor", 1)
    assert [e["run_number"] for e in chain] == [1, 2, 3]
    # Walking the predecessor links from run 3 reaches run 1.
    by_id = {e["run_id"]: e for e in chain}
    walk = [run3["run_id"]]
    while by_id[walk[-1]]["predecessor_run_id"]:
        walk.append(by_id[walk[-1]]["predecessor_run_id"])
    assert walk == [run3["run_id"], run2["run_id"], run1["run_id"]]


def test_t_s3_9_encounters_routes_owner_scoped(ve_ctx, tmp_path, monkeypatch):
    """T-S3-9 (AC8): the encounters list + detail routes are
    owner-scoped; a completed encounter is read_only; another user's
    run_id is a 404."""
    uid = _seeded_user("s3-a@example.com")
    uid2 = _seeded_user("s3-b@example.com")
    svc = _svc(tmp_path)
    monkeypatch.setattr(routes, "_meeting_service", lambda: svc)
    _complete_conductor(svc, uid)
    run1 = svc.meetings.get_latest_encounter(uid, "conductor", 1)

    listed = routes.meeting_encounters("conductor", 1, {"id": uid})
    assert len(listed["encounters"]) == 1
    assert listed["encounters"][0]["run_id"] == run1["run_id"]
    assert listed["encounters"][0]["read_only"] is True
    assert listed["encounters"][0]["identity_kind"] == "generated"
    assert listed["encounters"][0]["lineage_label"] is None

    detail = routes.meeting_encounter_detail(run1["run_id"], 100, 0, {"id": uid})
    assert detail["read_only"] is True
    assert detail["encounter"]["run_id"] == run1["run_id"]
    assert detail["total"] == len(_messages(svc, uid, run1["conversation_id"]))
    assert detail["messages"]

    # Another user sees nothing: the list is empty, the detail 404s.
    assert routes.meeting_encounters("conductor", 1, {"id": uid2})["encounters"] == []
    with pytest.raises(HTTPException) as exc_info:
        routes.meeting_encounter_detail(run1["run_id"], 100, 0, {"id": uid2})
    assert exc_info.value.status_code == 404


def test_t_s3_10_meeting_state_run_id(ve_ctx, tmp_path, monkeypatch):
    """T-S3-10: GET /meeting?run_id= hydrates a specific encounter
    (read_only for a historical one); a foreign run_id is a 404."""
    uid = _seeded_user()
    svc = _svc(tmp_path)
    monkeypatch.setattr(routes, "_meeting_service", lambda: svc)
    _complete_conductor(svc, uid)
    run1 = svc.meetings.get_latest_encounter(uid, "conductor", 1)
    svc.meet_again(
        uid, "conductor", 1,
        predecessor_run_id=run1["run_id"], request_id="req-state",
    )
    run2 = svc.meetings.get_latest_encounter(uid, "conductor", 1)

    # The latest (run 2) by default.
    latest = routes.meeting_state("conductor", 1, {"id": uid})
    assert latest["run_id"] == run2["run_id"]
    assert latest["read_only"] is False
    # The historical run 1, read-only.
    historical = routes.meeting_state(
        "conductor", 1, {"id": uid}, run_id=run1["run_id"]
    )
    assert historical["run_id"] == run1["run_id"]
    assert historical["read_only"] is True
    assert historical["status"] == "complete"
    # A foreign run_id is a 404.
    uid2 = _seeded_user("s3-foreign@example.com")
    with pytest.raises(HTTPException) as exc_info:
        routes.meeting_state("conductor", 1, {"id": uid2}, run_id=run1["run_id"])
    assert exc_info.value.status_code == 404


def test_t_s3_11_restart_is_retired():
    """T-S3-11 (AC3): the delete path is absent — no restart route,
    no MeetingService.restart, no MeetingStore.delete."""
    assert not hasattr(MeetingService, "restart")
    assert not hasattr(MeetingStore, "delete")
    assert not hasattr(routes, "meeting_restart")
    assert not hasattr(routes, "MeetingRestartBody")


def test_t_s3_12_concurrent_meet_again_yields_one_successor(ve_ctx, tmp_path):
    """T-S3-12 (AC19): concurrent meet_again calls (distinct request
    ids, same predecessor) yield exactly one successor."""
    uid = _seeded_user()
    svc = _svc(tmp_path)
    _complete_conductor(svc, uid)
    run1 = svc.meetings.get_latest_encounter(uid, "conductor", 1)

    results: list = []
    errors: list = []

    def _call(i: int) -> None:
        try:
            results.append(svc.meet_again(
                uid, "conductor", 1,
                predecessor_run_id=run1["run_id"], request_id=f"req-conc-{i}",
            ))
        except Exception as exc:  # noqa: BLE001 — collected, asserted below
            errors.append(exc)

    threads = [threading.Thread(target=_call, args=(i,)) for i in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
    assert len(results) == 4
    successor_ids = {r["encounter"]["run_id"] for r in results}
    assert len(successor_ids) == 1
    assert len(svc.list_encounters(uid, "conductor", 1)) == 2
    # Exactly one request recorded the successor (the creation that
    # made it); the adopters hold no record of their own (the schema
    # allows one request record per successor).
    recs = [
        svc.meetings.get_meet_again_request(uid, f"req-conc-{i}")
        for i in range(4)
    ]
    assert sum(1 for r in recs if r is not None) == 1
    assert [r for r in recs if r is not None][0]["successor_run_id"] == next(
        iter(successor_ids)
    )
    for i in range(4):
        again = svc.meet_again(
            uid, "conductor", 1,
            predecessor_run_id=run1["run_id"], request_id=f"req-conc-{i}",
        )
        assert again["encounter"]["run_id"] == next(iter(successor_ids))
        assert again["successor_exists"] is True


def test_t_s3_13_meet_again_route_requires_idempotency_key(
    ve_ctx, tmp_path, monkeypatch
):
    """T-S3-13: the meet-again route requires the Idempotency-Key
    header (422 without it) and returns 200 with encounter/state/
    resumed with one."""
    uid = _seeded_user()
    svc = _svc(tmp_path)
    monkeypatch.setattr(routes, "_meeting_service", lambda: svc)
    _complete_conductor(svc, uid)
    run1 = svc.meetings.get_latest_encounter(uid, "conductor", 1)
    body = routes.MeetingMeetAgainBody(
        archetype_id="conductor", keystone_index=1, predecessor_run_id=run1["run_id"]
    )
    with pytest.raises(HTTPException) as exc_info:
        routes.meeting_meet_again(body, {"id": uid})
    assert exc_info.value.status_code == 422
    assert exc_info.value.detail["code"] == "idempotency_key_required"

    out = routes.meeting_meet_again(body, {"id": uid}, idempotency_key="req-route-1")
    assert out["encounter"]["run_number"] == 2
    assert out["resumed"] is False
    assert out["state"]["run_id"] == out["encounter"]["run_id"]

    # A retry through the route returns the existing successor.
    again = routes.meeting_meet_again(body, {"id": uid}, idempotency_key="req-route-1")
    assert again["resumed"] is True
    assert again["successor_exists"] is True
    assert again["encounter"]["run_id"] == out["encounter"]["run_id"]


def test_t_s3_14_retry_resumes_creating_successor(ve_ctx, tmp_path):
    """T-S3-14 (AC12): a retry after a crash during creation resumes
    the 'creating' successor — the recorded opening is replayed,
    never re-recorded."""
    uid = _seeded_user()
    svc = _svc(tmp_path)
    _complete_conductor(svc, uid)
    run1 = svc.meetings.get_latest_encounter(uid, "conductor", 1)
    # Simulate the crash: the successor row + request record exist,
    # the opening is recorded, but nothing was spoken and the
    # encounter is still 'creating'.
    from local_ai.conversation import encounter as ENC
    from local_ai.conversation.meeting import _opening_digest
    from local_ai.council import meetings as MT

    script = MT.get_script("conductor", 1)
    paragraphs = list(ENC.get_definition(script).opening)
    run2_id = "run-creating-successor"
    svc.meetings.create_encounter_with_request(
        {
            "run_id": run2_id,
            "user_id": uid,
            "archetype_id": "conductor",
            "keystone_index": 1,
            "run_number": 2,
            "predecessor_run_id": run1["run_id"],
            "predecessor_link_kind": "witnessed",
            "conversation_id": f"meeting-conductor-1-{run2_id}",
            "status": "creating",
            "opening_script_id": "conductor:1",
            "opening_script_version": _opening_digest(paragraphs),
            "opening_paragraphs": paragraphs,
            "opening_expected": len(paragraphs),
        },
        {
            "user_id": uid,
            "request_id": "req-crash",
            "predecessor_run_id": run1["run_id"],
            "successor_run_id": run2_id,
        },
    )
    svc.meetings.update(
        uid, "conductor", 1,
        run_id=run2_id, conversation_id=f"meeting-conductor-1-{run2_id}",
    )
    svc.conversations.ensure_conversation(
        uid, f"meeting-conductor-1-{run2_id}", kind="meeting"
    )

    out = svc.meet_again(
        uid, "conductor", 1,
        predecessor_run_id=run1["run_id"], request_id="req-crash",
    )
    assert out["resumed"] is True
    assert out["successor_exists"] is True
    assert out["encounter"]["run_id"] == run2_id
    assert out["encounter"]["status"] == "in_progress"
    # The opening was spoken exactly once (insert-if-absent).
    bodies = [m["body"] for m in _messages(svc, uid, f"meeting-conductor-1-{run2_id}")]
    assert bodies == paragraphs
