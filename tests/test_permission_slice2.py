"""Permission Slice 2 tests: Settings surface + pause + revocation choice.

Covers, per inventory §3 Slice 2 and the corrections test alignment:
- C3-T1: one R1 record, shown twice (strand group + general noting
  group); the two displays cannot disagree.
- C4-T1–T6: pause lifecycle (new starts blocked; cancelable pending
  canceled and visible; committed complete safely and visibly;
  stances byte-identical across a pause cycle; canceled never
  silently restarted; in-flight ask honored for its instance only),
  plus the clarification I.1 cases (stance write during pause;
  C4-T1 rule-3: a newly written Just-do-it stance starts nothing
  until un-pause).
- T7/S3/S4 as amended — the Slice 2 parts only: revocation effective
  immediately, retained counts unchanged by revocation, choosing
  nothing changes nothing. The parts that need the noting record and
  the Review queue (pending notes in Review; DELETE erasing notes;
  REVIEW surfacing notes) wait for Slice 3 and are named, not faked,
  in the test docstrings.
- S1/S2 for the wired flags (R2/R3 stances honored at the framework
  check without re-asking / without re-asking to overcome refusal).
  Steward-gate wiring itself is Slice 6; these tests pin the
  framework-check outcomes the wiring will consume.
- Retained counts (Rev2 §4.2): R1/R3 zero by design; R2 threads, R4
  invitations, R5 proposals, R6 nudges counted from existing stores.
- Framework API routes: shape, validation (400s), stance/pause
  round-trips, stance write during pause.

Bounds honored: no noting record, no Review queue, no circle, no
Part 2 notices, no C1 contracts, no R4/R5/R6 wiring, no subsystem
behavior redesigns, no model calls, no scope-ledger changes.

C4-T2 note: the design's setup (a queued reminder and an unsent
derivation proposal pending when pause begins) has no substrate in
code — there is no scheduler and no derivation-proposal surfacing
path. The pause therefore cancels nothing, and the test pins the
honest empty cancel report plus stances/history untouched. The full
C4-T2 case waits for the substrates that create cancelable pending
operations (Slice 3/6).
"""

from __future__ import annotations

import json
import sqlite3
import threading

import pytest
from fastapi import HTTPException

from local_ai.permissions import framework as F
from local_ai.permissions import registry as R
from local_ai.permissions import retained as RT
from local_ai.permissions import store as S
import api.routes.settings_routes as settings_mod


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _perm_conn():
    """In-memory permissions DB in the minimal steward-test shape."""
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE user_permissions_settings ("
        "user_id TEXT, permissions_json TEXT, updated_at TEXT)"
    )
    conn.commit()
    return conn


@pytest.fixture()
def ve_ctx(tmp_path, monkeypatch):
    """Isolate the vision-execution SQLite DB per test (real path)."""
    import local_ai.vision_execution.storage as ve_store

    monkeypatch.setattr(ve_store, "_DB_PATH", tmp_path / "ve.db")
    monkeypatch.setattr(ve_store, "_DB_DIR", tmp_path)
    monkeypatch.setattr(ve_store, "_init_done_paths", set())
    monkeypatch.setattr(ve_store, "_thread_local", threading.local())
    return ve_store


@pytest.fixture()
def perm_conn():
    return _perm_conn()


def _set(conn, user, capability, row, stance, surface="settings"):
    return S.set_stance(
        user, capability, row, stance, surface=surface, connection=conn
    )


def _set_all_just_do_it(conn, user):
    """Every capability to Just do it (R6 needs an explicit row key)."""
    _set(conn, user, "R1", "strand:heart", "just_do_it")
    _set(conn, user, "R1", "source:general_conversation", "just_do_it")
    _set(conn, user, "R2", "all", "just_do_it")
    _set(conn, user, "R3", "all", "just_do_it")
    _set(conn, user, "R4", "champion", "just_do_it")
    _set(conn, user, "R5", "all", "just_do_it")
    _set(conn, user, "R6", "commitment-1", "just_do_it")


def _evidence():
    return {
        "user_message": "Staging trial test.",
        "responding_seat": "champion",
        "assistant_reply": "That's no hill.",
        "context": [],
    }


def _seed_proposal(ve_store, user_id, proposal_id="prop-1"):
    """One pending proposal row, inserted directly (record_task_proposal
    requires provenance verification against a source message; the
    count query only needs the row)."""
    conn = ve_store.get_connection()
    conn.execute(
        "INSERT INTO task_proposals (id, user_id, conversation_id, "
        "source_message_id, block_index, proposal_index, seat, title, "
        "state, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, "
        "'pending', '2026-11-06T00:00:00+00:00', '2026-11-06T00:00:00+00:00')",
        (proposal_id, user_id, "talk-1", f"msg-{proposal_id}", 0, 0, "champion", "Seed task"),
    )
    conn.commit()
    return conn


# ---------------------------------------------------------------------------
# C3-T1 — one record, shown twice
# ---------------------------------------------------------------------------


def test_c3_t1_strand_and_general_displays_agree(perm_conn):
    """Set via the strand presentation; the general noting group shows
    the same record. Set via the general group; the strand
    presentation shows it. At no point can the two disagree, because
    there is only one record (corrections C3.2)."""
    u = "u1"
    _set(perm_conn, u, "R1", "strand:heart", "just_do_it")
    # The "general group" read is the same store read.
    assert S.get_stance(u, "R1", "strand:heart", connection=perm_conn)["stance"] == "just_do_it"
    assert S.get_stances(u, connection=perm_conn)["R1"]["strand:heart"]["stance"] == "just_do_it"
    # Exactly one record exists for the row — no second authority.
    assert len([k for k in S.get_stances(u, connection=perm_conn)["R1"] if k == "strand:heart"]) == 1
    # Now set via the general group; the strand presentation follows.
    _set(perm_conn, u, "R1", "strand:heart", "ask_me")
    assert S.get_stance(u, "R1", "strand:heart", connection=perm_conn)["stance"] == "ask_me"
    # A source row is independent of the strand rows (same capability,
    # different row) — setting it does not move the strand rows.
    _set(perm_conn, u, "R1", "source:general_conversation", "dont_do_it")
    assert S.get_stance(u, "R1", "strand:heart", connection=perm_conn)["stance"] == "ask_me"
    # R7 stays retired: no R7 record can be written or read.
    with pytest.raises(ValueError):
        S.set_stance(u, "R7", "all", "just_do_it", surface="settings", connection=perm_conn)


def test_c3_t1_framework_state_shows_each_row_once(perm_conn, monkeypatch):
    """The framework GET carries each R1 row once, so two displays
    built from the same payload cannot disagree."""
    from local_ai.permissions import retained as _rt

    monkeypatch.setattr(
        S, "_default_connection", lambda: perm_conn
    )
    monkeypatch.setattr(_rt, "retained_counts", lambda user_id, **kw: {c: 0 for c in ("R1", "R2", "R3", "R4", "R5", "R6")})
    _set(perm_conn, "u1", "R1", "strand:heart", "just_do_it")
    state = settings_mod.get_framework_permissions({"id": "u1"})
    r1 = [c for c in state["capabilities"] if c["id"] == "R1"][0]
    keys = [row["key"] for row in r1["rows"]]
    assert len(keys) == len(set(keys))  # no row listed twice
    heart = [row for row in r1["rows"] if row["key"] == "strand:heart"][0]
    assert heart["stance"] == "just_do_it"
    assert heart["stance_source"] == "user"


# ---------------------------------------------------------------------------
# C4-T1 — new operations blocked immediately on pause
# ---------------------------------------------------------------------------


def test_c4_t1_pause_blocks_new_starts_for_every_capability(perm_conn):
    u = "u1"
    _set_all_just_do_it(perm_conn, u)
    checks = [
        ("R1", ["strand:heart"]),
        ("R2", None),
        ("R3", None),
        ("R4", ["champion"]),
        ("R5", None),
        ("R6", ["commitment-1"]),
    ]
    for capability, rows in checks:
        assert F.framework_check(u, capability, scope_rows=rows, connection=perm_conn).outcome == "proceed"
    S.set_pause(u, True, surface="settings", connection=perm_conn)
    for capability, rows in checks:
        decision = F.framework_check(u, capability, scope_rows=rows, connection=perm_conn)
        assert decision.outcome == "deny"
        assert decision.reason == "paused"
    # Ordinary conversation is never paused: a stance write (I.1
    # rule 2) still succeeds while paused.
    S.set_stance(u, "R1", "strand:hands", "ask_me", surface="settings", connection=perm_conn)
    assert S.get_stance(u, "R1", "strand:hands", connection=perm_conn)["stance"] == "ask_me"


# ---------------------------------------------------------------------------
# C4-T2 — cancelable pending operations canceled (and visible)
# ---------------------------------------------------------------------------


def test_c4_t2_pause_cancels_nothing_and_reports_it(perm_conn, monkeypatch):
    """Slice 2 honest rendering: no cancelable pending operation
    exists in the wired surface (no scheduler, no derivation-proposal
    path), so the pause cancels nothing — and says so, instead of
    silently pretending pending work was handled. Stances and history
    are untouched by the pause itself (C4.2(d))."""
    from local_ai.permissions import retained as _rt

    monkeypatch.setattr(S, "_default_connection", lambda: perm_conn)
    monkeypatch.setattr(_rt, "retained_counts", lambda user_id, **kw: {c: 0 for c in ("R1", "R2", "R3", "R4", "R5", "R6")})
    u = "u1"
    _set_all_just_do_it(perm_conn, u)
    before_stances = json.dumps(S.get_stances(u, connection=perm_conn), sort_keys=True)
    before_history = S.stance_history(u, connection=perm_conn)
    # Call the route function directly (no TestClient, no real DB —
    # the S4/S5 pattern). The body is a Pydantic model in production;
    # construct it here.
    from local_ai.vision_execution.models import FrameworkPauseUpdate

    resp = settings_mod.put_framework_pause(
        FrameworkPauseUpdate(paused=True), {"id": u}
    )
    assert resp["canceled_operations"] == []
    assert resp["pause"]["paused"] is True
    after_stances = json.dumps(S.get_stances(u, connection=perm_conn), sort_keys=True)
    assert after_stances == before_stances
    assert S.stance_history(u, connection=perm_conn) == before_history


# ---------------------------------------------------------------------------
# C4-T3 — committed operations complete safely, visibly
# ---------------------------------------------------------------------------


def test_c4_t3_committed_work_survives_pause_and_stays_visible(perm_conn):
    """A stance write committed before pause remains complete and
    visible after pause; pausing rolls back and hides nothing."""
    u = "u1"
    record = _set(perm_conn, u, "R1", "strand:heart", "just_do_it")
    history_before = S.stance_history(u, connection=perm_conn)
    assert len(history_before) == 1
    S.set_pause(u, True, surface="settings", connection=perm_conn)
    assert S.get_stance(u, "R1", "strand:heart", connection=perm_conn) == record
    assert S.stance_history(u, connection=perm_conn) == history_before
    # The pause itself wrote no history.
    assert len(S.stance_history(u, connection=perm_conn)) == 1
    S.set_pause(u, False, surface="settings", connection=perm_conn)
    assert S.get_stance(u, "R1", "strand:heart", connection=perm_conn) == record


# ---------------------------------------------------------------------------
# C4-T4 — stances byte-identical across a pause cycle
# ---------------------------------------------------------------------------


def test_c4_t4_stances_byte_identical_across_pause_cycle(perm_conn):
    u = "u1"
    _set_all_just_do_it(perm_conn, u)
    conn = perm_conn
    stances_before = conn.execute(
        "SELECT stances_json FROM user_permissions_settings WHERE user_id = ?",
        (u,),
    ).fetchone()[0]
    history_before = S.stance_history(u, connection=conn)
    S.set_pause(u, True, surface="settings", connection=conn)
    S.set_pause(u, False, surface="settings", connection=conn)
    stances_after = conn.execute(
        "SELECT stances_json FROM user_permissions_settings WHERE user_id = ?",
        (u,),
    ).fetchone()[0]
    assert stances_after == stances_before
    assert S.stance_history(u, connection=conn) == history_before
    # The pause record itself is cleared, not left set.
    assert S.get_pause(u, connection=conn)["paused"] is False


# ---------------------------------------------------------------------------
# C4-T5 — canceled operations never silently restarted
# ---------------------------------------------------------------------------


def test_c4_t5_unpause_restores_stances_not_operations(perm_conn):
    u = "u1"
    _set_all_just_do_it(perm_conn, u)
    history_before = S.stance_history(u, connection=perm_conn)
    S.set_pause(u, True, surface="settings", connection=perm_conn)
    S.set_pause(u, False, surface="settings", connection=perm_conn)
    # Un-pausing wrote no history and started nothing: the check
    # returns stance-based outcomes again, nothing resumed.
    assert S.stance_history(u, connection=perm_conn) == history_before
    assert F.framework_check(u, "R2", connection=perm_conn).outcome == "proceed"
    assert F.framework_check(u, "R5", connection=perm_conn).outcome == "proceed"
    # A stance written DURING pause takes effect after un-pause
    # (I.1 rule 2) — that is the stance resuming, not an operation.
    S.set_pause(u, True, surface="settings", connection=perm_conn)
    _set(perm_conn, u, "R2", "all", "ask_me")
    S.set_pause(u, False, surface="settings", connection=perm_conn)
    assert F.framework_check(u, "R2", connection=perm_conn).outcome == "ask"


# ---------------------------------------------------------------------------
# C4-T6 — in-flight ask honored for its instance only
# ---------------------------------------------------------------------------


def test_c4_t6_in_flight_ask_honored_for_its_instance_only(perm_conn):
    u = "u1"
    _set(perm_conn, u, "R1", "strand:heart", "ask_me")
    history_before = S.stance_history(u, connection=perm_conn)
    S.set_pause(u, True, surface="settings", connection=perm_conn)
    decision = F.framework_check(
        u, "R1", scope_rows=["strand:heart"], connection=perm_conn,
        is_existing_instance=True,
    )
    assert decision.outcome == "proceed"
    assert decision.instance_only is True
    # The answer writes NO stance change (C2: an instance yes is an
    # instance yes) — history is exactly what the setup wrote.
    assert S.get_stance(u, "R1", "strand:heart", connection=perm_conn)["stance"] == "ask_me"
    assert S.stance_history(u, connection=perm_conn) == history_before
    # And no NEW instance starts while paused.
    assert F.framework_check(
        u, "R1", scope_rows=["strand:heart"], connection=perm_conn,
        is_existing_instance=False,
    ).outcome == "deny"


# ---------------------------------------------------------------------------
# I.1 — stance write during pause; rule-3 case
# ---------------------------------------------------------------------------


def test_i1_rule2_stance_write_during_pause_succeeds_but_starts_nothing(perm_conn):
    u = "u1"
    S.set_pause(u, True, surface="settings", connection=perm_conn)
    record = _set(perm_conn, u, "R1", "strand:heart", "just_do_it")
    assert record["stance"] == "just_do_it"
    # Visible immediately.
    assert S.get_stance(u, "R1", "strand:heart", connection=perm_conn)["stance"] == "just_do_it"
    # But takes no effect for new operations until un-pause.
    assert F.framework_check(u, "R1", scope_rows=["strand:heart"], connection=perm_conn).outcome == "deny"
    S.set_pause(u, False, surface="settings", connection=perm_conn)
    assert F.framework_check(u, "R1", scope_rows=["strand:heart"], connection=perm_conn).outcome == "proceed"


def test_i1_rule3_new_just_do_it_during_pause_starts_nothing(perm_conn):
    """C4-T1 gains the rule-3 case: a newly written Just-do-it stance
    during pause still starts nothing until un-pause."""
    u = "u1"
    S.set_pause(u, True, surface="settings", connection=perm_conn)
    _set(perm_conn, u, "R2", "all", "just_do_it")
    assert F.framework_check(u, "R2", connection=perm_conn).outcome == "deny"
    assert F.framework_check(u, "R2", connection=perm_conn).reason == "paused"
    S.set_pause(u, False, surface="settings", connection=perm_conn)
    assert F.framework_check(u, "R2", connection=perm_conn).outcome == "proceed"


# ---------------------------------------------------------------------------
# T7 / S3 / S4 as amended — Slice 2 parts
# ---------------------------------------------------------------------------


def test_t7_revocation_immediate_and_counts_unchanged(perm_conn, ve_ctx, tmp_path):
    """T7 (a)+(b): Ask-me stops silent capture at once; Don't-do-it
    takes effect immediately; retained counts do not move. T7 (c) —
    Review showing the pending notes — needs the noting record and
    the Review queue (Slice 3), named here, not tested."""
    from local_ai.conversation.store import ConversationStore
    from local_ai.followthrough.store import FollowthroughStore
    from local_ai.narrative.store import NarrativeStore

    u = "u1"
    _set(perm_conn, u, "R1", "strand:heart", "just_do_it")
    n_store = NarrativeStore(tmp_path / "narrative.db")
    n_store.create_thread(u, title="A thread")
    c_store = ConversationStore(tmp_path / "conv.db")
    c_store.create_or_refresh_invitation(u, "talk-1", "guardian", "hand to offer", evidence=_evidence())
    f_store = FollowthroughStore(tmp_path / "ft.db")
    f_store.create_nudge(u, "deadline", "task", "t1", "low", "due soon")
    ve_conn = _seed_proposal(ve_ctx, u)
    before = RT.retained_counts(
        u,
        narrative_store=n_store,
        conversation_store=c_store,
        followthrough_store=f_store,
        ve_connection=ve_conn,
    )
    assert before == {"R1": 0, "R2": 1, "R3": 0, "R4": 1, "R5": 1, "R6": 1}
    # (a) Ask me stops silent capture: the check asks, never proceeds.
    _set(perm_conn, u, "R1", "strand:heart", "ask_me")
    assert F.framework_check(u, "R1", scope_rows=["strand:heart"], connection=perm_conn).outcome == "ask"
    # (b) Don't do it is effective immediately, and changes nothing retained.
    _set(perm_conn, u, "R1", "strand:heart", "dont_do_it")
    assert S.get_stance(u, "R1", "strand:heart", connection=perm_conn)["stance"] == "dont_do_it"
    after = RT.retained_counts(
        u,
        narrative_store=n_store,
        conversation_store=c_store,
        followthrough_store=f_store,
        ve_connection=ve_conn,
    )
    assert after == before
    n_store.close()
    c_store.close()
    f_store.close()


def test_s3_revocation_stops_future_only(perm_conn, ve_ctx, tmp_path):
    """S3 as amended, Slice 2 parts: no new capture/derivation from
    the moment of the change; retained items keep their dispositions.
    The pending-notes-in-Review half waits for Slice 3."""
    from local_ai.conversation.store import ConversationStore
    from local_ai.followthrough.store import FollowthroughStore

    u = "u1"
    _set(perm_conn, u, "R1", "strand:heart", "just_do_it")
    _set(perm_conn, u, "R2", "all", "just_do_it")
    c_store = ConversationStore(tmp_path / "conv.db")
    c_store.create_or_refresh_invitation(u, "talk-1", "guardian", "hand to offer", evidence=_evidence())
    f_store = FollowthroughStore(tmp_path / "ft.db")
    f_store.create_nudge(u, "deadline", "task", "t1", "low", "due soon")
    ve_conn = _seed_proposal(ve_ctx, u)
    _set(perm_conn, u, "R1", "strand:heart", "dont_do_it")
    _set(perm_conn, u, "R2", "all", "dont_do_it")
    assert F.framework_check(u, "R1", scope_rows=["strand:heart"], connection=perm_conn).outcome == "deny"
    assert F.framework_check(u, "R2", connection=perm_conn).outcome == "deny"
    # Retained items keep their dispositions: invitation still
    # pending, proposal still pending, nudge still live.
    assert len(c_store.list_pending_invitations(u)) == 1
    assert ve_ctx.count_pending_task_proposals(u, connection=ve_conn) == 1
    assert len(f_store.list_feed_nudges(u)) == 1
    c_store.close()
    f_store.close()


def test_s4_choosing_nothing_changes_nothing_retained(perm_conn, ve_ctx, tmp_path):
    """S4 (a), Slice 2 part: revoke, choose nothing — the retained
    items remain, unchanged, and the choice remains available (the
    counts are still reported). S4 (b) DELETE and (c) REVIEW wait for
    the Slice 3 Review queue, which owns erasure and per-item review."""
    from local_ai.conversation.store import ConversationStore
    from local_ai.followthrough.store import FollowthroughStore
    from local_ai.narrative.store import NarrativeStore

    u = "u1"
    n_store = NarrativeStore(tmp_path / "narrative.db")
    n_store.create_thread(u, title="A thread")
    c_store = ConversationStore(tmp_path / "conv.db")
    c_store.create_or_refresh_invitation(u, "talk-1", "guardian", "hand to offer", evidence=_evidence())
    f_store = FollowthroughStore(tmp_path / "ft.db")
    f_store.create_nudge(u, "deadline", "task", "t1", "low", "due soon")
    ve_conn = _seed_proposal(ve_ctx, u)
    kwargs = dict(
        narrative_store=n_store,
        conversation_store=c_store,
        followthrough_store=f_store,
        ve_connection=ve_conn,
    )
    before = RT.retained_counts(u, **kwargs)
    _set(perm_conn, u, "R2", "all", "dont_do_it")
    # Choosing nothing: no delete, no freeze — counts identical, items
    # still listed, choice still available from the counts.
    after = RT.retained_counts(u, **kwargs)
    assert after == before
    assert after["R2"] == 1
    assert len(n_store.threads_for(u, limit=None)) == 1
    n_store.close()
    c_store.close()
    f_store.close()


# ---------------------------------------------------------------------------
# S1 / S2 for the wired flags (R2/R3, framework-check level)
# ---------------------------------------------------------------------------


def test_s1_r2_r3_just_do_it_honored_without_re_asking(perm_conn):
    """S1: a standing Just-do-it authorization proceeds without a
    per-instance ask. (The instance-yes second run needs the noting
    pattern — Slice 3.)"""
    u = "u1"
    _set(perm_conn, u, "R2", "all", "just_do_it")
    _set(perm_conn, u, "R3", "all", "just_do_it")
    assert F.framework_check(u, "R2", connection=perm_conn).outcome == "proceed"
    assert F.framework_check(u, "R3", connection=perm_conn).outcome == "proceed"


def test_s2_r2_r3_dont_do_it_honored_without_re_asking(perm_conn):
    """S2: a standing refusal denies without producing an ask — no
    re-asking, rephrasing, or escalation to overcome it. (The
    instance-no second run needs the noting pattern — Slice 3.)"""
    u = "u1"
    _set(perm_conn, u, "R2", "all", "dont_do_it")
    _set(perm_conn, u, "R3", "all", "dont_do_it")
    for capability in ("R2", "R3"):
        decision = F.framework_check(u, capability, connection=perm_conn)
        assert decision.outcome == "deny"
        assert decision.outcome != "ask"


# ---------------------------------------------------------------------------
# Retained counts
# ---------------------------------------------------------------------------


def test_retained_counts_all_zero_for_new_user(perm_conn, ve_ctx):
    ve_conn = ve_ctx.get_connection()
    counts = RT.retained_counts("nobody", ve_connection=ve_conn)
    assert counts == {"R1": 0, "R2": 0, "R3": 0, "R4": 0, "R5": 0, "R6": 0}


def test_retained_counts_r2_threads(tmp_path, ve_ctx):
    from local_ai.narrative.store import NarrativeStore

    ve_conn = ve_ctx.get_connection()
    store = NarrativeStore(tmp_path / "narrative.db")
    store.create_thread("u1", title="One")
    store.create_thread("u1", title="Two")
    store.create_thread("u2", title="Not mine")
    counts = RT.retained_counts("u1", narrative_store=store, ve_connection=ve_conn)
    assert counts["R2"] == 2
    assert counts["R1"] == 0 and counts["R3"] == 0
    store.close()


def test_retained_counts_r4_invitations(tmp_path, ve_ctx):
    from local_ai.conversation.store import ConversationStore

    ve_conn = ve_ctx.get_connection()
    store = ConversationStore(tmp_path / "conv.db")
    store.create_or_refresh_invitation("u1", "talk-1", "guardian", "hand to offer", evidence=_evidence())
    store.create_or_refresh_invitation("u1", "talk-2", "maverick", "another angle", evidence=_evidence())
    counts = RT.retained_counts("u1", conversation_store=store, ve_connection=ve_conn)
    assert counts["R4"] == 2
    # An expired invitation is not retained: past-expiry rows are
    # not pending even before a sweep materializes the status.
    store._conn.execute(
        "UPDATE invitations SET expires_at = '2020-01-01T00:00:00+00:00' "
        "WHERE conversation_id = 'talk-2'"
    )
    store._conn.commit()
    counts = RT.retained_counts("u1", conversation_store=store, ve_connection=ve_conn)
    assert counts["R4"] == 1
    store.close()


def test_retained_counts_r5_proposals(ve_ctx):
    ve_conn = _seed_proposal(ve_ctx, "u1", "prop-1")
    _seed_proposal(ve_ctx, "u1", "prop-2")
    _seed_proposal(ve_ctx, "u2", "prop-3")
    assert ve_ctx.count_pending_task_proposals("u1", connection=ve_conn) == 2
    counts = RT.retained_counts("u1", ve_connection=ve_conn)
    assert counts["R5"] == 2
    # A decided proposal is not retained.
    ve_conn.execute("UPDATE task_proposals SET state = 'declined' WHERE id = 'prop-2'")
    ve_conn.commit()
    counts = RT.retained_counts("u1", ve_connection=ve_conn)
    assert counts["R5"] == 1


def test_retained_counts_r6_nudges(tmp_path, ve_ctx):
    from local_ai.followthrough.store import FollowthroughStore

    ve_conn = ve_ctx.get_connection()
    store = FollowthroughStore(tmp_path / "ft.db")
    store.create_nudge("u1", "deadline", "task", "t1", "low", "due soon")
    store.create_nudge("u1", "deadline", "task", "t2", "low", "due soon")
    counts = RT.retained_counts("u1", followthrough_store=store, ve_connection=ve_conn)
    assert counts["R6"] == 2
    # A resolved nudge is not retained.
    nudge = store.list_feed_nudges("u1")[0]
    store.resolve_nudge(nudge["id"], "u1")
    counts = RT.retained_counts("u1", followthrough_store=store, ve_connection=ve_conn)
    assert counts["R6"] == 1
    store.close()


def test_retained_counts_r1_r3_zero_by_design(ve_ctx):
    """R1: no noting record until Slice 3. R3: coordination writes no
    persisted distribution record. Both are 0 by design, not by an
    unread store."""
    ve_conn = ve_ctx.get_connection()
    counts = RT.retained_counts("u1", ve_connection=ve_conn)
    assert counts["R1"] == 0
    assert counts["R3"] == 0


# ---------------------------------------------------------------------------
# Framework API routes (direct function calls, monkeypatched store)
# ---------------------------------------------------------------------------


def _route_ctx(perm_conn, monkeypatch):
    monkeypatch.setattr(S, "_default_connection", lambda: perm_conn)
    monkeypatch.setattr(
        RT,
        "retained_counts",
        lambda user_id, **kw: {c: 0 for c in ("R1", "R2", "R3", "R4", "R5", "R6")},
    )


def test_framework_get_shape(perm_conn, monkeypatch):
    _route_ctx(perm_conn, monkeypatch)
    _set(perm_conn, "u1", "R4", "champion", "dont_do_it")
    state = settings_mod.get_framework_permissions({"id": "u1"})
    assert state["paused"] is False
    assert {c["id"] for c in state["capabilities"]} == {"R1", "R2", "R3", "R4", "R5", "R6"}
    r1 = [c for c in state["capabilities"] if c["id"] == "R1"][0]
    assert len(r1["rows"]) == 9  # 7 strands + 2 sources
    assert r1["default_stance"] == "ask_me"
    assert r1["rows"][0]["stance_source"] == "default"
    r4 = [c for c in state["capabilities"] if c["id"] == "R4"][0]
    assert r4["supported_stances"] == ["just_do_it", "dont_do_it"]
    champion = [row for row in r4["rows"] if row["key"] == "champion"][0]
    assert champion["stance"] == "dont_do_it"
    assert champion["stance_source"] == "user"
    r6 = [c for c in state["capabilities"] if c["id"] == "R6"][0]
    assert r6["rows"] == []  # no per-commitment rows until Slice 6 wiring
    for cap in state["capabilities"]:
        assert cap["quieted"] is False  # no quieting machinery until Slice 3
        assert cap["retained_count"] == 0


def test_framework_stance_put_validates(perm_conn, monkeypatch):
    from local_ai.vision_execution.models import FrameworkStanceUpdate

    _route_ctx(perm_conn, monkeypatch)
    with pytest.raises(HTTPException) as exc:
        settings_mod.put_framework_stance(
            FrameworkStanceUpdate(capability="R7", row_key="all", stance="just_do_it"),
            {"id": "u1"},
        )
    assert exc.value.status_code == 400
    with pytest.raises(HTTPException) as exc:
        settings_mod.put_framework_stance(
            FrameworkStanceUpdate(capability="R4", row_key="champion", stance="ask_me"),
            {"id": "u1"},
        )
    assert exc.value.status_code == 400  # R4 does not support Ask me
    with pytest.raises(HTTPException) as exc:
        settings_mod.put_framework_stance(
            FrameworkStanceUpdate(capability="R1", row_key="strand:nope", stance="just_do_it"),
            {"id": "u1"},
        )
    assert exc.value.status_code == 400


def test_framework_stance_put_writes_and_returns_state(perm_conn, monkeypatch):
    from local_ai.vision_execution.models import FrameworkStanceUpdate

    _route_ctx(perm_conn, monkeypatch)
    resp = settings_mod.put_framework_stance(
        FrameworkStanceUpdate(capability="R1", row_key="strand:heart", stance="just_do_it"),
        {"id": "u1"},
    )
    assert resp["record"]["stance"] == "just_do_it"
    assert resp["retained_choice_offered"] is False  # not a revocation
    r1 = [c for c in resp["state"]["capabilities"] if c["id"] == "R1"][0]
    heart = [row for row in r1["rows"] if row["key"] == "strand:heart"][0]
    assert heart["stance"] == "just_do_it"
    # Revocation with retained items offers the choice (nonblocking).
    monkeypatch.setattr(
        RT,
        "retained_counts",
        lambda user_id, **kw: {"R1": 3, "R2": 0, "R3": 0, "R4": 0, "R5": 0, "R6": 0},
    )
    resp = settings_mod.put_framework_stance(
        FrameworkStanceUpdate(capability="R1", row_key="strand:heart", stance="dont_do_it"),
        {"id": "u1"},
    )
    assert resp["retained_choice_offered"] is True
    assert resp["retained_count"] == 3


def test_framework_pause_put_roundtrip(perm_conn, monkeypatch):
    from local_ai.vision_execution.models import FrameworkPauseUpdate

    _route_ctx(perm_conn, monkeypatch)
    _set(perm_conn, "u1", "R2", "all", "just_do_it")
    resp = settings_mod.put_framework_pause(FrameworkPauseUpdate(paused=True), {"id": "u1"})
    assert resp["pause"]["paused"] is True
    assert resp["canceled_operations"] == []
    assert resp["state"]["paused"] is True
    resp = settings_mod.put_framework_pause(FrameworkPauseUpdate(paused=False), {"id": "u1"})
    assert resp["pause"]["paused"] is False
    assert resp["state"]["paused"] is False
    # Stances survived the cycle untouched.
    assert S.get_stance("u1", "R2", "all", connection=perm_conn)["stance"] == "just_do_it"


def test_framework_stance_put_during_pause(perm_conn, monkeypatch):
    from local_ai.vision_execution.models import FrameworkPauseUpdate, FrameworkStanceUpdate

    _route_ctx(perm_conn, monkeypatch)
    settings_mod.put_framework_pause(FrameworkPauseUpdate(paused=True), {"id": "u1"})
    resp = settings_mod.put_framework_stance(
        FrameworkStanceUpdate(capability="R1", row_key="strand:heart", stance="just_do_it"),
        {"id": "u1"},
    )
    assert resp["record"]["stance"] == "just_do_it"
    assert resp["state"]["paused"] is True  # pause override untouched
    assert F.framework_check(
        "u1", "R1", scope_rows=["strand:heart"], connection=perm_conn
    ).outcome == "deny"


# ---------------------------------------------------------------------------
# Founder-verdict corrections, 2026-11-06 (draft PR #338, checks 1–3)
# ---------------------------------------------------------------------------


class _FailingStore:
    """A store whose every read raises: simulates a corrupt/unreadable
    store file. The count must come back unavailable, never zero."""

    def threads_for(self, *args, **kwargs):
        raise sqlite3.Error("simulated unreadable store")

    def list_pending_invitations(self, *args, **kwargs):
        raise sqlite3.Error("simulated unreadable store")

    def list_feed_nudges(self, *args, **kwargs):
        raise sqlite3.Error("simulated unreadable store")


def test_checks_r2_failed_read_is_unavailable_not_zero(tmp_path, ve_ctx, monkeypatch):
    """Check 2: a failed retained read must not appear as zero.
    R2/R4/R6 read failures -> None; R5 counter failure -> None;
    R1/R3 stay verified 0 by design (no store to read)."""
    import local_ai.vision_execution.storage as ve_storage

    ve_conn = ve_ctx.get_connection()
    failing = _FailingStore()
    monkeypatch.setattr(
        ve_storage,
        "count_pending_task_proposals",
        lambda user_id, connection=None: (_ for _ in ()).throw(
            sqlite3.OperationalError("simulated unreadable store")
        ),
    )
    counts = RT.retained_counts(
        "u1",
        narrative_store=failing,
        conversation_store=failing,
        followthrough_store=failing,
        ve_connection=ve_conn,
    )
    assert counts["R2"] is None
    assert counts["R4"] is None
    assert counts["R5"] is None
    assert counts["R6"] is None
    assert counts["R1"] == 0
    assert counts["R3"] == 0


def test_checks_r2_missing_db_file_is_verified_zero(tmp_path, monkeypatch, ve_ctx):
    """Check 2, other side: a store whose database file does not exist
    yet is a VERIFIED zero (nothing can be retained), not unavailable.
    A GET must not create the file to find that out."""
    import local_ai.conversation.store as conv_mod
    import local_ai.followthrough.store as ft_mod
    import local_ai.narrative.store as narrative_mod

    monkeypatch.setattr(narrative_mod, "DEFAULT_DB_PATH", tmp_path / "no-narrative.db")
    monkeypatch.setattr(conv_mod, "DEFAULT_DB_PATH", tmp_path / "no-conv.db")
    monkeypatch.setattr(ft_mod, "DEFAULT_DB_PATH", tmp_path / "no-ft.db")
    ve_conn = ve_ctx.get_connection()
    counts = RT.retained_counts("u1", ve_connection=ve_conn)
    assert counts == {"R1": 0, "R2": 0, "R3": 0, "R4": 0, "R5": 0, "R6": 0}
    assert not (tmp_path / "no-narrative.db").exists()
    assert not (tmp_path / "no-conv.db").exists()
    assert not (tmp_path / "no-ft.db").exists()


def test_checks_r2_framework_get_carries_count_status(perm_conn, monkeypatch):
    """Check 2 at the API: GET /permissions/framework carries
    retained_count (int or null) AND retained_count_status
    ('available' / 'unavailable') per capability."""
    _route_ctx(perm_conn, monkeypatch)
    monkeypatch.setattr(
        RT,
        "retained_counts",
        lambda user_id, **kw: {"R1": 0, "R2": None, "R3": 0, "R4": 0, "R5": 0, "R6": 0},
    )
    state = settings_mod.get_framework_permissions({"id": "u1"})
    r2 = [c for c in state["capabilities"] if c["id"] == "R2"][0]
    assert r2["retained_count"] is None
    assert r2["retained_count_status"] == "unavailable"
    r1 = [c for c in state["capabilities"] if c["id"] == "R1"][0]
    assert r1["retained_count"] == 0
    assert r1["retained_count_status"] == "available"


def test_checks_r2_stance_put_unavailable_count_offers_no_choice(perm_conn, monkeypatch):
    """Check 2: a revocation with an unavailable count offers no
    retained-information choice — the surface cannot choose about
    items it could not count."""
    from local_ai.vision_execution.models import FrameworkStanceUpdate

    _route_ctx(perm_conn, monkeypatch)
    monkeypatch.setattr(
        RT,
        "retained_counts",
        lambda user_id, **kw: {"R1": None, "R2": 0, "R3": 0, "R4": 0, "R5": 0, "R6": 0},
    )
    resp = settings_mod.put_framework_stance(
        FrameworkStanceUpdate(capability="R1", row_key="strand:heart", stance="dont_do_it"),
        {"id": "u1"},
    )
    assert resp["retained_count"] is None
    assert resp["retained_count_status"] == "unavailable"
    assert resp["retained_choice_offered"] is False


def test_checks_r3_framework_read_is_owner_scoped(perm_conn, monkeypatch):
    """Check 3a: a second user's framework state is not readable by
    the first — stances and pause both come back as that user's own
    (defaults + unpaused for a stranger)."""
    from local_ai.vision_execution.models import FrameworkPauseUpdate

    _route_ctx(perm_conn, monkeypatch)
    _set(perm_conn, "u1", "R1", "strand:heart", "just_do_it")
    settings_mod.put_framework_pause(FrameworkPauseUpdate(paused=True), {"id": "u1"})
    mine = settings_mod.get_framework_permissions({"id": "u1"})
    assert mine["paused"] is True
    r1 = [c for c in mine["capabilities"] if c["id"] == "R1"][0]
    heart = [row for row in r1["rows"] if row["key"] == "strand:heart"][0]
    assert heart["stance"] == "just_do_it"
    assert heart["stance_source"] == "user"
    theirs = settings_mod.get_framework_permissions({"id": "u2"})
    assert theirs["paused"] is False
    r1t = [c for c in theirs["capabilities"] if c["id"] == "R1"][0]
    heart_t = [row for row in r1t["rows"] if row["key"] == "strand:heart"][0]
    assert heart_t["stance"] == "ask_me"  # registry default, not u1's record
    assert heart_t["stance_source"] == "default"


def test_checks_r3_stance_write_is_owner_scoped(perm_conn, monkeypatch):
    """Check 3b: a stance write lands under the authenticated user
    only; the other user's record is untouched."""
    from local_ai.vision_execution.models import FrameworkStanceUpdate

    _route_ctx(perm_conn, monkeypatch)
    _set(perm_conn, "u1", "R1", "strand:heart", "just_do_it")
    settings_mod.put_framework_stance(
        FrameworkStanceUpdate(capability="R1", row_key="strand:heart", stance="dont_do_it"),
        {"id": "u2"},
    )
    assert S.get_stance("u1", "R1", "strand:heart", connection=perm_conn)["stance"] == "just_do_it"
    assert S.get_stance("u2", "R1", "strand:heart", connection=perm_conn)["stance"] == "dont_do_it"


def test_checks_r3_pause_write_is_owner_scoped(perm_conn, monkeypatch):
    """Check 3c: a pause write lands under the authenticated user
    only; the other user's pause is untouched."""
    from local_ai.vision_execution.models import FrameworkPauseUpdate

    _route_ctx(perm_conn, monkeypatch)
    settings_mod.put_framework_pause(FrameworkPauseUpdate(paused=True), {"id": "u2"})
    assert S.get_pause("u1", connection=perm_conn)["paused"] is False
    assert S.get_pause("u2", connection=perm_conn)["paused"] is True


def test_checks_r3_retained_counts_are_owner_scoped(tmp_path, ve_ctx):
    """Check 3d: retained-count aggregation counts only the caller's
    items — another user's threads, invitations, proposals, and
    nudges never leak into the count."""
    from local_ai.conversation.store import ConversationStore
    from local_ai.followthrough.store import FollowthroughStore
    from local_ai.narrative.store import NarrativeStore

    ve_conn = ve_ctx.get_connection()
    _seed_proposal(ve_ctx, "u2", "prop-u2")
    nstore = NarrativeStore(tmp_path / "narrative.db")
    nstore.create_thread("u2", title="Theirs")
    cstore = ConversationStore(tmp_path / "conv.db")
    cstore.create_or_refresh_invitation(
        "u2", "talk-9", "guardian", "hand to offer", evidence=_evidence()
    )
    fstore = FollowthroughStore(tmp_path / "ft.db")
    fstore.create_nudge("u2", "deadline", "task", "t9", "low", "due soon")
    kwargs = dict(
        narrative_store=nstore,
        conversation_store=cstore,
        followthrough_store=fstore,
        ve_connection=ve_conn,
    )
    mine = RT.retained_counts("u1", **kwargs)
    assert mine == {"R1": 0, "R2": 0, "R3": 0, "R4": 0, "R5": 0, "R6": 0}
    theirs = RT.retained_counts("u2", **kwargs)
    assert theirs["R2"] == 1
    assert theirs["R4"] == 1
    assert theirs["R5"] == 1
    assert theirs["R6"] == 1
    nstore.close()
    cstore.close()
    fstore.close()


def test_checks_r3_body_cannot_choose_user(perm_conn, monkeypatch):
    """Check 3: the owner comes from the authenticated principal,
    never from the request body. The stance/pause bodies carry no
    user field — an extra user_id in the payload is dropped, and the
    write still lands under the authenticated user only."""
    from local_ai.vision_execution.models import (
        FrameworkPauseUpdate,
        FrameworkStanceUpdate,
    )

    _route_ctx(perm_conn, monkeypatch)
    assert "user_id" not in FrameworkStanceUpdate.model_fields
    assert "user_id" not in FrameworkPauseUpdate.model_fields
    stance_body = FrameworkStanceUpdate.model_validate(
        {
            "capability": "R1",
            "row_key": "strand:heart",
            "stance": "just_do_it",
            "user_id": "u2",
        }
    )
    settings_mod.put_framework_stance(stance_body, {"id": "u1"})
    assert S.get_stance("u1", "R1", "strand:heart", connection=perm_conn)["stance"] == "just_do_it"
    assert S.get_stance("u2", "R1", "strand:heart", connection=perm_conn) is None
    settings_mod.put_framework_pause(
        FrameworkPauseUpdate.model_validate({"paused": True, "user_id": "u2"}),
        {"id": "u1"},
    )
    assert S.get_pause("u1", connection=perm_conn)["paused"] is True
    assert S.get_pause("u2", connection=perm_conn)["paused"] is False


def test_checks_r3_empty_owner_rejected_fail_closed(perm_conn, monkeypatch):
    """Check 3: an empty or missing owner fails closed at the route
    boundary — 404, not 403 (PR #329's rule) — on all three framework
    routes, and no write lands for the empty owner."""
    from local_ai.vision_execution.models import (
        FrameworkPauseUpdate,
        FrameworkStanceUpdate,
    )

    _route_ctx(perm_conn, monkeypatch)
    for bad in ({"id": ""}, {"id": "   "}, {}):
        with pytest.raises(HTTPException) as exc:
            settings_mod.get_framework_permissions(bad)
        assert exc.value.status_code == 404
        with pytest.raises(HTTPException) as exc:
            settings_mod.put_framework_stance(
                FrameworkStanceUpdate(
                    capability="R1", row_key="strand:heart", stance="just_do_it"
                ),
                bad,
            )
        assert exc.value.status_code == 404
        with pytest.raises(HTTPException) as exc:
            settings_mod.put_framework_pause(FrameworkPauseUpdate(paused=True), bad)
        assert exc.value.status_code == 404
    assert S.get_stances("", connection=perm_conn) == {}
    assert S.get_pause("", connection=perm_conn)["paused"] is False


def test_checks_r3_unauthenticated_rejected(monkeypatch):
    """Check 3: no session cookie, or a cookie whose session resolves
    to no user, is rejected at the auth boundary (401) before any
    framework route runs."""
    from starlette.requests import Request

    from api.routes import auth_routes as auth_mod

    with pytest.raises(HTTPException) as exc:
        auth_mod.get_current_user(Request({"type": "http", "headers": []}))
    assert exc.value.status_code == 401
    import local_ai.vision_execution.service as ve_service

    monkeypatch.setattr(ve_service, "get_session_user", lambda token: None)
    stale = Request(
        {"type": "http", "headers": [(b"cookie", b"zenaf_session=stale-token")]}
    )
    with pytest.raises(HTTPException) as exc:
        auth_mod.get_current_user(stale)
    assert exc.value.status_code == 401
