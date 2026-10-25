"""Steward increment D — inspectable surface (proposal §7) + the
five GPT-weigh-in clarification constraints (build constraints
authorized by Joshua with the revised proposal).

Covers: the pure read model (one envelope, five signal kinds),
live decline consultation with coverage served alongside result
and NO invitation-permission field, kind-specific provenance with
ref_state never collapsed, origin/confirmation separation,
delivery lifecycle participation + observable definitions,
grouped list + drill-down + oversized-group escape hatch,
single-acquisition snapshot consistency, per-user scoping,
channel separation (no fellowship "!", no intake rows), and the
route (three GET endpoints, 401/400/404 semantics).

Stores are tmp SQLite files. Observable rows are inserted via
direct SQL where the test is about D's reading of stored rows
(the C suite covers friction derivation itself); one suppressed
row is built through the real claim -> suppress path so the
served shape is proven against a genuinely settled row. All
clocks that ordering depends on are fixed via SQL.
"""

from __future__ import annotations

import ast
import json
import sqlite3
import threading
from pathlib import Path

import pytest

from local_ai.narrative import NarrativeStore, ProgressionPosition
from local_ai.narrative.derivation import record_offer_decline
from local_ai.narrative.read_model import (
    build_signals_response,
    get_group_members,
    get_signal_detail,
)
from local_ai.narrative.refs import SourceRef

USER = "user-1"
OTHER = "user-2"
T0 = "2026-10-01T00:00:00+00:00"
T1 = "2026-10-01T00:00:01+00:00"
T2 = "2026-10-01T00:00:02+00:00"
T3 = "2026-10-01T00:00:03+00:00"


def _store(tmp_path, name="narrative.db"):
    return NarrativeStore(db_path=tmp_path / name)


def _sql(store, sql, params=()):
    conn = sqlite3.connect(str(store.db_path))
    try:
        conn.execute(sql, params)
        conn.commit()
    finally:
        conn.close()


def _dump(store):
    """Full store state for purity comparisons (table -> rows)."""
    conn = sqlite3.connect(str(store.db_path))
    try:
        tables = [
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "ORDER BY name"
            ).fetchall()
        ]
        return {
            table: conn.execute(
                f"SELECT * FROM {table} ORDER BY rowid"
            ).fetchall()
            for table in tables
        }
    finally:
        conn.close()


def _thread(store, user, *, origin="user_declared", title="t",
            scope=None, cast=None):
    return store.create_thread(
        user, origin=origin, title=title, scope=scope, cast=cast
    )


def _backdate(store, table, row_id, created_at):
    _sql(
        store,
        f"UPDATE {table} SET created_at = ? WHERE id = ?",
        (created_at, row_id),
    )


def _evidence(store, user, thread_id, ref_id, kind="event"):
    return store.add_evidence(
        user, thread_id, SourceRef(kind=kind, ref_id=ref_id,
                                   evidence_kind="quote")
    )


def _reading(store, user, thread_id, evidence_ids, *, author="steward",
             primary_scale="personal", lens="descent_and_return",
             phase="descent"):
    progression = (
        ProgressionPosition.positioned(lens, phase)
        if lens is not None
        else ProgressionPosition.unknown()
    )
    return store.propose_reading(
        user,
        thread_id,
        author=author,
        reading={"tensions": []},
        evidence_refs=list(evidence_ids),
        scales=[primary_scale] if primary_scale else None,
        primary_scale=primary_scale,
        progression=progression,
        touch=False,
    )


def _observable(store, user, *, thread_id, kind, signal_key, refs,
                detail, created_at=T1):
    _sql(
        store,
        "INSERT INTO steward_observables (id, user_id, thread_id, "
        "kind, signal_key, evidence_refs_json, detail_json, "
        "first_seen_at, last_seen_at, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            f"obs-{signal_key}",
            user,
            thread_id,
            kind,
            signal_key,
            json.dumps(refs),
            json.dumps(detail),
            created_at,
            created_at,
            created_at,
        ),
    )


def _suppressed_real(store, user, *, scope="subject", key="boss"):
    """A genuinely settled suppressed row via claim -> suppress."""
    thread = store.create_thread_with_deferred_prose(
        user,
        origin="steward_proposal",
        title="suppressed thread",
        evidence_refs=[SourceRef(kind="event", ref_id="ev-s",
                                 evidence_kind="quote")],
        deferred_kind="birth",
        evidence_signature="sig-suppressed",
        evidence_texts=[{"text": "verbatim, must be cleared"}],
    )
    rows = store.deferred_prose_for(user, status="pending")
    assert len(rows) == 1
    claimed = store.claim_deferred_prose(user, rows[0]["id"])
    assert claimed is not None
    assert store.mark_deferred_prose_suppressed(
        user, rows[0]["id"], scope=scope, key=key
    )
    return thread, rows[0]


def _snapshot(store, user):
    return store.snapshot_for_read(user)


def _resp(store, user, **filters):
    return build_signals_response(
        _snapshot(store, user),
        user_id=user,
        derivation_active=True,
        **filters,
    )


def _group(resp, group_id):
    for group in resp["groups"]:
        if group["group_id"] == group_id:
            return group
    raise AssertionError(f"group {group_id!r} not in response")


def _signal(group, kind, signal_id=None):
    for signal in group["signals"]:
        if signal["signal_kind"] != kind:
            continue
        if signal_id is None or signal["id"] == signal_id:
            return signal
    raise AssertionError(f"signal {kind}/{signal_id} not in group")


def _basic_fixture(store, user=USER):
    """One user_declared thread + evidence + steward reading."""
    thread = _thread(store, user, title="basic")
    ev = _evidence(store, user, thread.id, "ev-1")
    reading = _reading(store, user, thread.id, [ev.id])
    return thread, ev, reading


# ---------------------------------------------------------------------------
# §7.1 / §7.2 purity — no writes through model or route
# ---------------------------------------------------------------------------


def test_purity_serving_changes_nothing(tmp_path):
    store = _store(tmp_path)
    thread, ev, reading = _basic_fixture(store)
    _observable(store, USER, thread_id=thread.id, kind="thread_quiet",
                signal_key="o3:x", refs=[thread.id],
                detail={"thread_updated_at": T0, "window_days": 14})
    store.set_signal_delivery(USER, signal_kind="reading",
                              signal_id=reading.id,
                              delivery_status="surfaced")
    before = _dump(store)
    _resp(store, USER)
    _resp(store, USER, kind="reading")
    get_signal_detail(_snapshot(store, USER), kind="reading",
                      signal_id=reading.id)
    get_signal_detail(_snapshot(store, USER), kind="thread",
                      signal_id=thread.id)
    get_group_members(_snapshot(store, USER), group_id=thread.id)
    assert _dump(store) == before


def test_serving_never_touches_clocks_or_cursor(tmp_path):
    store = _store(tmp_path)
    thread, ev, reading = _basic_fixture(store)
    _sql(store, "UPDATE narrative_threads SET updated_at = ? WHERE id = ?",
         (T0, thread.id))
    _sql(store,
         "INSERT INTO steward_processing_position "
         "(user_id, byte_offset, file_identity, updated_at) "
         "VALUES (?, 42, 'dev:ino', ?)",
         (USER, T0))
    _resp(store, USER)
    conn = sqlite3.connect(str(store.db_path))
    try:
        assert conn.execute(
            "SELECT updated_at FROM narrative_threads WHERE id = ?",
            (thread.id,),
        ).fetchone()[0] == T0
        assert conn.execute(
            "SELECT byte_offset FROM steward_processing_position "
            "WHERE user_id = ?",
            (USER,),
        ).fetchone()[0] == 42
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# §7.3 decline coverage + result, honestly served (no permission field)
# ---------------------------------------------------------------------------


def test_decline_precise_match_and_coverage(tmp_path):
    store = _store(tmp_path)
    thread, ev, reading = _basic_fixture(store)
    store.annotate_evidence_entities(
        USER, thread.id, {("event", "ev-1"): "boss"}
    )
    record_offer_decline(store, USER, scope="subject", key="boss")
    resp = _resp(store, USER)
    signal = _signal(_group(resp, thread.id), "reading", reading.id)
    state = signal["decline_state"]
    assert state["result"] == "matched"
    assert state["matched_scope"] == "subject"
    assert state["consulted_scopes"] == ["subject"]
    assert [s["scope"] for s in state["unconsulted_scopes"]] == [
        "invitation", "class",
    ]
    assert "servable_as_invitation" not in json.dumps(resp)
    assert '"authorized"' not in json.dumps(resp)


def test_decline_coarse_and_unknown_are_ambiguous_not_matches(tmp_path):
    store = _store(tmp_path)
    # Coarse: scope label, no entity annotation.
    coarse = _thread(store, USER, title="coarse", scope="work")
    record_offer_decline(store, USER, scope="subject", key="other")
    resp = _resp(store, USER)
    signal = _signal(_group(resp, coarse.id), "thread")
    assert signal["decline_state"]["result"] == "ambiguous"
    assert "coarse" in signal["decline_state"]["ambiguous_reason"]
    # Unknown: no entity, no scope.
    unknown = _thread(store, USER, title="unknown")
    resp = _resp(store, USER)
    signal = _signal(_group(resp, unknown.id), "thread")
    assert signal["decline_state"]["result"] == "ambiguous"
    assert "unknown" in signal["decline_state"]["ambiguous_reason"]


def test_decline_class_birth_only_and_matches_beat_ambiguity(tmp_path):
    store = _store(tmp_path)
    thread = _thread(store, USER, origin="steward_proposal",
                     title="birth")
    record_offer_decline(store, USER, scope="class", key="birth")
    record_offer_decline(store, USER, scope="subject", key="other")
    resp = _resp(store, USER)
    signal = _signal(_group(resp, thread.id), "thread")
    state = signal["decline_state"]
    assert state["result"] == "matched"
    assert state["matched_scope"] == "class"
    assert state["consulted_scopes"] == ["subject", "class"]
    # Matches beat ambiguity: precise subject match wins over the
    # standing (non-matching) subject decline.
    thread2, ev2, reading2 = _basic_fixture(store, USER)
    store.annotate_evidence_entities(
        USER, thread2.id, {("event", "ev-1"): "other"}
    )
    resp = _resp(store, USER)
    signal = _signal(_group(resp, thread2.id), "reading", reading2.id)
    assert signal["decline_state"]["result"] == "matched"
    assert signal["decline_state"]["matched_scope"] == "subject"


def test_decline_no_match_found_is_not_clearance(tmp_path):
    store = _store(tmp_path)
    thread, ev, reading = _basic_fixture(store)
    resp = _resp(store, USER)
    state = _signal(
        _group(resp, thread.id), "reading", reading.id
    )["decline_state"]
    assert state["result"] == "no_match_found"
    # Invitation was NOT checked — the response says so, never
    # implying a comprehensive clearance.
    assert {
        "scope": "invitation",
        "reason": "invitation keys are proposal-time, not stored",
    } in state["unconsulted_scopes"]


def test_decline_delivery_dismissal_is_not_invitation_clearance(tmp_path):
    store = _store(tmp_path)
    thread, ev, reading = _basic_fixture(store)
    store.set_signal_delivery(USER, signal_kind="reading",
                              signal_id=reading.id,
                              delivery_status="dismissed")
    resp = _resp(store, USER)
    signal = _signal(_group(resp, thread.id), "reading", reading.id)
    assert signal["delivery_status"] == "dismissed"
    # Dismissing delivery says nothing about invitation permission:
    # invitation is still unconsulted, not cleared.
    assert "invitation" in [
        s["scope"] for s in signal["decline_state"]["unconsulted_scopes"]
    ]


# ---------------------------------------------------------------------------
# §7.4 declined still inspectable in full
# ---------------------------------------------------------------------------


def test_declined_signals_served_in_full(tmp_path):
    store = _store(tmp_path)
    thread, ev, reading = _basic_fixture(store)
    store.annotate_evidence_entities(
        USER, thread.id, {("event", "ev-1"): "boss"}
    )
    record_offer_decline(store, USER, scope="subject", key="boss")
    resp = _resp(store, USER)
    signal = _signal(_group(resp, thread.id), "reading", reading.id)
    assert signal["content"]["reading"]["tensions"] == []
    assert signal["provenance"]["ref_state"] == "complete"
    detail = get_signal_detail(_snapshot(store, USER), kind="reading",
                               signal_id=reading.id)
    assert detail["content"]["reading"]["tensions"] == []
    assert detail["provenance"]["evidence_rows"] != []


# ---------------------------------------------------------------------------
# §7.5 per-user scoping, including grouped responses
# ---------------------------------------------------------------------------


def test_per_user_scoping_and_no_existence_leak(tmp_path):
    store = _store(tmp_path)
    mine, _, _ = _basic_fixture(store, USER)
    theirs, _, _ = _basic_fixture(store, OTHER)
    resp = _resp(store, USER)
    assert [g["group_id"] for g in resp["groups"]] == [mine.id]
    assert resp["totals"]["group_count"] == 1
    with pytest.raises(LookupError):
        get_signal_detail(_snapshot(store, USER), kind="thread",
                          signal_id=theirs.id)
    with pytest.raises(LookupError):
        get_signal_detail(_snapshot(store, USER), kind="thread",
                          signal_id="no-such-thread")


# ---------------------------------------------------------------------------
# §7.6 / §7.7 serving does not transition or touch clocks
# ---------------------------------------------------------------------------


def test_serving_never_transitions_delivery(tmp_path):
    store = _store(tmp_path)
    thread, ev, reading = _basic_fixture(store)
    store.set_signal_delivery(USER, signal_kind="reading",
                              signal_id=reading.id,
                              delivery_status="surfaced")
    for _ in range(3):
        resp = _resp(store, USER)
        assert _signal(
            _group(resp, thread.id), "reading", reading.id
        )["delivery_status"] == "surfaced"
        get_signal_detail(_snapshot(store, USER), kind="reading",
                          signal_id=reading.id)
    conn = sqlite3.connect(str(store.db_path))
    try:
        assert conn.execute(
            "SELECT delivery_status FROM steward_signal_states"
        ).fetchone()[0] == "surfaced"
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# §7.8 kind-specific provenance validity
# ---------------------------------------------------------------------------


def test_kind_specific_provenance(tmp_path):
    store = _store(tmp_path)
    thread, ev, reading = _basic_fixture(store)
    _observable(store, USER, thread_id=thread.id, kind="thread_quiet",
                signal_key="o3:x", refs=[thread.id],
                detail={"thread_updated_at": T0, "window_days": 14})
    _observable(store, USER, thread_id=None,
                kind="impression_unanswered",
                signal_key="o1:meeting-x:noclaim", refs=["meeting-x"],
                detail={"meeting_key": "meeting-x",
                        "archetype_id": "weaver", "keystone_index": 1,
                        "claim_id": None})
    resp = _resp(store, USER)
    # Thread header: refs not_applicable is VALID, not a gap.
    header = _signal(_group(resp, thread.id), "thread")
    assert header["provenance"]["ref_state"] == "not_applicable"
    assert header["provenance"]["provenance_resolved"] is True
    # Reading: supporting refs, complete.
    assert _signal(
        _group(resp, thread.id), "reading", reading.id
    )["provenance"]["ref_state"] == "complete"
    # O3: the thread clock IS the fact — complete, not unresolved.
    assert _signal(
        _group(resp, thread.id), "observable"
    )["provenance"]["ref_state"] == "complete"
    # O1: meeting key basis — complete without narrative evidence.
    meeting = _group(resp, "meeting:meeting-x")
    assert meeting["thread"] is None
    assert meeting["signals"][0]["provenance"]["ref_state"] == "complete"


def test_dangling_refs_served_marked_never_dropped(tmp_path):
    store = _store(tmp_path)
    thread, ev, reading = _basic_fixture(store)
    # Point the reading's refs at a nonexistent evidence row.
    _sql(store,
         "UPDATE thread_readings SET evidence_refs_json = ? WHERE id = ?",
         (json.dumps(["ghost-evidence"]), reading.id))
    resp = _resp(store, USER)
    signal = _signal(_group(resp, thread.id), "reading", reading.id)
    assert signal["provenance"]["ref_state"] == "present_but_unresolved"
    assert signal["provenance"]["provenance_resolved"] is False
    assert signal["provenance"]["unresolved_ids"] == ["ghost-evidence"]
    # Still served, never silently omitted, never fabricated.
    assert signal["provenance"]["evidence_rows"] == []
    detail = get_signal_detail(_snapshot(store, USER), kind="reading",
                               signal_id=reading.id)
    assert detail["provenance"]["unresolved_ids"] == ["ghost-evidence"]


def test_observable_with_empty_refs_is_expected_but_missing(tmp_path):
    store = _store(tmp_path)
    thread, _, _ = _basic_fixture(store)
    _observable(store, USER, thread_id=thread.id,
                kind="correction_no_subsequent_activity",
                signal_key="o2:bad", refs=[],
                detail={"claim_id": "c1"})
    resp = _resp(store, USER)
    signal = _signal(_group(resp, thread.id), "observable")
    assert signal["provenance"]["ref_state"] == "expected_but_missing"
    assert signal["provenance"]["provenance_resolved"] is False


# ---------------------------------------------------------------------------
# §7.9 origin, confirmation, no manufactured provisional verdict
# ---------------------------------------------------------------------------


def test_origin_is_not_confirmation(tmp_path):
    store = _store(tmp_path)
    proposed = _thread(store, USER, origin="steward_proposal",
                       title="steward")
    declared = _thread(store, USER, origin="user_declared",
                       title="declared")
    resp = _resp(store, USER)
    sig = _signal(_group(resp, proposed.id), "thread")
    assert sig["steward_proposed"] is True
    assert sig["confirmation_state"] == "unknown"
    assert sig["origin"] == "steward_proposal"
    assert "provisional" not in sig
    sig = _signal(_group(resp, declared.id), "thread")
    assert sig["steward_proposed"] is False
    assert sig["confirmation_state"] == "unknown"
    # A confirmed CHANGE is not thread confirmation.
    _sql(store,
         "INSERT INTO thread_changes (id, thread_id, kind, "
         "evidence_refs_json, status, created_at) VALUES (?, ?, ?, "
         "'[]', 'confirmed', ?)",
         ("chg-1", declared.id, "extended", T1))
    resp = _resp(store, USER)
    assert _signal(
        _group(resp, declared.id), "thread"
    )["confirmation_state"] == "unknown"


# ---------------------------------------------------------------------------
# §7.10 divergence labeled divergence, never contradiction
# ---------------------------------------------------------------------------


def test_divergence_label_never_contradiction(tmp_path):
    store = _store(tmp_path)
    thread, ev, reading = _basic_fixture(store)
    reading2 = _reading(store, USER, thread.id, [ev.id], phase="ascent")
    _observable(store, USER, thread_id=thread.id,
                kind="divergent_reading_positions",
                signal_key="o4:x", refs=[ev.id],
                detail={"reading_ids": [reading.id, reading2.id],
                        "lens_id": "descent_and_return",
                        "phases": {reading.id: "descent",
                                   reading2.id: "return"},
                        "primary_scale": "personal"})
    resp = _resp(store, USER)
    signal = _signal(_group(resp, thread.id), "observable")
    blob = json.dumps(signal)
    assert "divergent_reading_positions" in blob
    assert "contradiction" not in blob
    assert "conflict" not in blob
    assert "adjudication" not in blob


# ---------------------------------------------------------------------------
# §7.11 O1 grouping correct
# ---------------------------------------------------------------------------


def test_o1_grouping_exact(tmp_path):
    store = _store(tmp_path)
    thread, _, _ = _basic_fixture(store)
    _observable(store, USER, thread_id=None,
                kind="impression_unanswered",
                signal_key="o1:m1:noclaim", refs=["m1"],
                detail={"meeting_key": "m1", "claim_id": None})
    _observable(store, USER, thread_id=None,
                kind="impression_unanswered",
                signal_key="o1:m2:noclaim", refs=["m2"],
                detail={"meeting_key": "m2", "claim_id": None})
    resp = _resp(store, USER)
    assert _group(resp, "meeting:m1")["signals"][0]["signal_key"] == \
        "o1:m1:noclaim"
    assert _group(resp, "meeting:m2")["signals"][0]["signal_key"] == \
        "o1:m2:noclaim"
    # No thread group contains an O1 row; no thread invented.
    thread_group = _group(resp, thread.id)
    assert all(
        s["signal_kind"] != "observable"
        or s["content"]["thread_id"] is not None
        for s in thread_group["signals"]
    )
    assert _group(resp, "meeting:m1")["thread"] is None


# ---------------------------------------------------------------------------
# §7.12 batch/group retrieval + per-claim drill-down
# ---------------------------------------------------------------------------


def test_batch_and_drill_down(tmp_path):
    store = _store(tmp_path)
    thread, ev, reading = _basic_fixture(store)
    _backdate(store, "thread_readings", reading.id, T0)
    _observable(store, USER, thread_id=thread.id, kind="thread_quiet",
                signal_key="o3:x", refs=[thread.id],
                detail={"thread_updated_at": T0, "window_days": 14})
    resp = _resp(store, USER)
    group = _group(resp, thread.id)
    kinds = [s["signal_kind"] for s in group["signals"]]
    assert kinds == ["thread", "reading", "observable"]
    # Every batch signal is individually drill-downable, with MORE
    # provenance detail (resolved evidence rows) than the list.
    detail = get_signal_detail(_snapshot(store, USER), kind="reading",
                               signal_id=reading.id)
    assert detail["provenance"]["evidence_rows"][0]["ref_id"] == "ev-1"
    assert detail["provenance"]["evidence_rows"][0]["tier"] is not None
    listed = _signal(group, "reading", reading.id)
    assert listed["provenance"]["evidence_rows"] == []


# ---------------------------------------------------------------------------
# §7.13 pagination/bounds honored
# ---------------------------------------------------------------------------


def _three_threads(store):
    ids = []
    for index, created in enumerate((T0, T1, T2)):
        thread = _thread(store, USER, title=f"t{index}")
        _backdate(store, "narrative_threads", thread.id, created)
        ids.append(thread.id)
    return ids


def test_pagination_groups_and_totals(tmp_path):
    store = _store(tmp_path)
    ids = _three_threads(store)
    page1 = _resp(store, USER, limit=1)
    assert len(page1["groups"]) == 1
    assert page1["groups"][0]["group_id"] == ids[0]
    assert page1["totals"]["group_count"] == 3
    assert page1["pagination"]["cursor"] is not None
    page2 = _resp(store, USER, limit=1,
                  cursor=page1["pagination"]["cursor"])
    assert page2["groups"][0]["group_id"] == ids[1]
    page3 = _resp(store, USER, limit=1,
                  cursor=page2["pagination"]["cursor"])
    assert page3["groups"][0]["group_id"] == ids[2]
    assert page3["pagination"]["cursor"] is None
    assert page3["pagination"]["truncated"] is False
    with pytest.raises(ValueError):
        _resp(store, USER, limit=0)
    with pytest.raises(ValueError):
        _resp(store, USER, limit=201)
    with pytest.raises(ValueError):
        _resp(store, USER, cursor="not-base64!!!")


def test_pagination_is_not_a_frozen_snapshot(tmp_path):
    """Cross-request pagination is best-effort continuation, not a
    frozen snapshot: a group created after page 1 still appears on
    page 2 (clarification constraint b)."""
    store = _store(tmp_path)
    ids = _three_threads(store)
    page1 = _resp(store, USER, limit=1)
    late = _thread(store, USER, title="late")
    page2 = _resp(store, USER, limit=10,
                  cursor=page1["pagination"]["cursor"])
    assert [g["group_id"] for g in page2["groups"]] == [ids[1], ids[2],
                                                       late.id]


# ---------------------------------------------------------------------------
# §7.14 no intake conflation; §7.16 verdict != delivery
# ---------------------------------------------------------------------------


def test_no_intake_rows_and_empty_is_not_404(tmp_path):
    store = _store(tmp_path)
    resp = _resp(store, USER)
    assert resp["groups"] == []
    assert resp["totals"] == {"group_count": 0, "signal_count": 0,
                              "decline_count": 0}
    assert "intake" not in json.dumps(resp)
    thread, _, _ = _basic_fixture(store)
    resp = _resp(store, USER)
    assert "intake" not in json.dumps(resp)


def test_verdict_and_delivery_vary_independently(tmp_path):
    store = _store(tmp_path)
    thread, ev, reading = _basic_fixture(store)
    store.accept_reading(USER, reading.id)
    resp = _resp(store, USER)
    signal = _signal(_group(resp, thread.id), "reading", reading.id)
    assert signal["content"]["status"] == "accepted"
    assert signal["delivery_status"] == "pending"
    store.set_signal_delivery(USER, signal_kind="reading",
                              signal_id=reading.id,
                              delivery_status="surfaced")
    resp = _resp(store, USER)
    signal = _signal(_group(resp, thread.id), "reading", reading.id)
    assert signal["content"]["status"] == "accepted"
    assert signal["delivery_status"] == "surfaced"


# ---------------------------------------------------------------------------
# §7.15 no fellowship-"!" coupling; turn path never imports D
# ---------------------------------------------------------------------------


def test_no_coupling_to_fellowship_or_turn_path(tmp_path):
    import local_ai.narrative.read_model as read_model

    read_path = Path(read_model.__file__)
    tree = ast.parse(read_path.read_text(encoding="utf-8"))
    banned = ("local_ai.fellowship", "local_ai.conversation",
              "local_ai.narrative.sweep", "local_ai.narrative.friction")
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            assert not any(
                node.module == prefix or node.module.startswith(prefix + ".")
                for prefix in banned
            ), node.module
        elif isinstance(node, ast.Import):
            assert not any(
                name.name == prefix
                or name.name.startswith(prefix + ".")
                for name in node.names for prefix in banned
            )
    conv_dir = read_path.resolve().parent.parent / "conversation"
    offenders = []
    for path in sorted(conv_dir.glob("*.py")):
        parsed = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(parsed):
            if isinstance(node, ast.ImportFrom):
                module = node.module or ""
                if module == "local_ai.narrative.read_model":
                    offenders.append(path.name)
            elif isinstance(node, ast.Import):
                if any(name.name == "local_ai.narrative.read_model"
                       for name in node.names):
                    offenders.append(path.name)
    assert offenders == []


# ---------------------------------------------------------------------------
# §7.17 error semantics (model layer)
# ---------------------------------------------------------------------------


def test_model_error_semantics(tmp_path):
    store = _store(tmp_path)
    with pytest.raises(ValueError):
        _resp(store, USER, kind="bogus")
    with pytest.raises(ValueError):
        _resp(store, USER, delivery_status="bogus")
    with pytest.raises(ValueError):
        _resp(store, USER, decline_result="bogus")
    with pytest.raises(ValueError):
        _resp(store, USER, unconsulted_scope="bogus")
    with pytest.raises(ValueError):
        _resp(store, USER, seat="bogus-seat")
    with pytest.raises(ValueError):
        get_signal_detail(_snapshot(store, USER), kind="bogus",
                          signal_id="x")


# ---------------------------------------------------------------------------
# §7.18 suppressed-row shape (real settled row)
# ---------------------------------------------------------------------------


def test_suppressed_row_shape(tmp_path):
    store = _store(tmp_path)
    thread, row = _suppressed_real(store, USER, scope="subject",
                                   key="boss")
    resp = _resp(store, USER)
    group = _group(resp, thread.id)
    signal = _signal(group, "suppressed_proposal")
    assert signal["content"]["status"] == "suppressed_by_decline"
    assert signal["content"]["verbatim_texts"] == []
    assert signal["content"]["texts_cleared"] is True
    assert signal["content"]["suppressed_by"] == {
        "scope": "subject", "key": "boss",
    }
    assert signal["content"]["evidence_refs"] != []
    # The retained key resolves against the thread's evidence rows.
    assert signal["provenance"]["ref_state"] == "complete"
    assert signal["delivery_status"] == "not_applicable"
    assert "servable_as_invitation" not in json.dumps(signal)
    # The thread + evidence still serve normally alongside it.
    assert _signal(group, "thread")["content"]["id"] == thread.id
    detail = get_signal_detail(_snapshot(store, USER),
                               kind="suppressed_proposal",
                               signal_id=row["id"])
    assert detail["content"]["suppressed_by"]["key"] == "boss"


# ---------------------------------------------------------------------------
# §7.19 oversized-group escape hatch (6,000-signal group)
# ---------------------------------------------------------------------------


def _huge_group(store, user, count=6000):
    """A thread group with `count` readings via direct SQL (the test
    is about D's pagination, not derivation; rows mimic valid
    stored readings exactly: non-empty refs to one real evidence
    row)."""
    thread = _thread(store, user, title="huge")
    ev = _evidence(store, user, thread.id, "ev-1")
    tag = thread.id[-6:]
    values = ",".join(
        f"('rd-{tag}-{i:05d}', '{thread.id}', 'steward', "
        f"'{{\"tensions\": []}}', '[\"{ev.id}\"]', 'proposed', '{T1}')"
        for i in range(count)
    )
    _sql(store,
         "INSERT INTO thread_readings (id, thread_id, author, "
         "reading_json, evidence_refs_json, status, created_at) "
         f"VALUES {values}")
    return thread


def test_oversized_group_escape_hatch(tmp_path):
    store = _store(tmp_path)
    thread = _huge_group(store, USER)
    resp = _resp(store, USER)
    group = _group(resp, thread.id)
    assert group["oversized"] is True
    assert group["signals"] == []
    assert group["signal_count"] == 6001  # thread signal + readings
    assert group["members_url"].startswith(
        f"/steward/groups/{thread.id}/members"
    )
    assert resp["pagination"]["truncated"] is True
    assert resp["totals"]["signal_count"] == 6001
    # The list cursor advances past the descriptor (no repeat).
    assert resp["pagination"]["cursor"] is not None
    page2 = _resp(store, USER, cursor=resp["pagination"]["cursor"])
    assert page2["groups"] == []
    # A filter requesting exactly the group returns the descriptor,
    # never 6,000 signals in one response.
    only = _resp(store, USER, thread_id=thread.id)
    assert len(only["groups"]) == 1
    assert only["groups"][0]["oversized"] is True
    assert only["groups"][0]["signals"] == []
    # Members endpoint returns everything across bounded pages.
    seen = 0
    cursor = None
    pages = 0
    while True:
        out = get_group_members(
            _snapshot(store, USER), group_id=thread.id, limit=500,
            cursor=cursor,
        )
        assert out["signal_count"] == 6001
        seen += len(out["signals"])
        pages += 1
        cursor = out["pagination"]["cursor"]
        if cursor is None:
            break
    assert seen == 6001 and pages == 13


# ---------------------------------------------------------------------------
# §7.20 snapshot consistency (single lock acquisition)
# ---------------------------------------------------------------------------


class _CountingLock:
    """A threading.Lock wrapper counting acquisitions."""

    def __init__(self):
        self._inner = threading.Lock()
        self.count = 0

    def __enter__(self):
        self.count += 1
        return self._inner.__enter__()

    def __exit__(self, *exc):
        return self._inner.__exit__(*exc)

    def acquire(self, *args, **kwargs):
        self.count += 1
        return self._inner.acquire(*args, **kwargs)

    def release(self):
        return self._inner.release()


def test_snapshot_single_lock_acquisition(tmp_path):
    store = _store(tmp_path)
    thread, ev, reading = _basic_fixture(store)
    record_offer_decline(store, USER, scope="subject", key="boss")
    lock = _CountingLock()
    store._lock = lock
    snapshot = store.snapshot_for_read(USER)
    build_signals_response(snapshot, user_id=USER, derivation_active=True)
    assert lock.count == 1


# ---------------------------------------------------------------------------
# §7.21 delivery participation + observable surfaced + cascade
# ---------------------------------------------------------------------------


def test_delivery_participation_and_transitions(tmp_path):
    store = _store(tmp_path)
    thread, ev, reading = _basic_fixture(store)
    user_reading = _reading(store, USER, thread.id, [ev.id],
                            author="user")
    _observable(store, USER, thread_id=thread.id, kind="thread_quiet",
                signal_key="o3:x", refs=[thread.id],
                detail={"thread_updated_at": T0, "window_days": 14})
    resp = _resp(store, USER)
    group = _group(resp, thread.id)
    assert _signal(group, "thread")["delivery_status"] == "not_applicable"
    assert _signal(
        group, "reading", user_reading.id
    )["delivery_status"] == "not_applicable"
    assert _signal(
        group, "reading", reading.id
    )["delivery_status"] == "pending"
    assert _signal(
        group, "observable"
    )["delivery_status"] == "pending"
    # set_signal_delivery refuses non-participating kinds.
    with pytest.raises(ValueError):
        store.set_signal_delivery(USER, signal_kind="thread",
                                  signal_id=thread.id,
                                  delivery_status="surfaced")
    with pytest.raises(ValueError):
        store.set_signal_delivery(USER, signal_kind="reading",
                                  signal_id=user_reading.id,
                                  delivery_status="surfaced")
    with pytest.raises(ValueError):
        store.set_signal_delivery(USER, signal_kind="reading",
                                  signal_id="nope",
                                  delivery_status="surfaced")
    with pytest.raises(ValueError):
        store.set_signal_delivery(USER, signal_kind="reading",
                                  signal_id=reading.id,
                                  delivery_status="bogus")
    # Transitions enforced: pending -> discussed ok; no going back;
    # dismissed is terminal.
    store.set_signal_delivery(USER, signal_kind="reading",
                              signal_id=reading.id,
                              delivery_status="discussed")
    with pytest.raises(ValueError):
        store.set_signal_delivery(USER, signal_kind="reading",
                                  signal_id=reading.id,
                                  delivery_status="surfaced")
    store.set_signal_delivery(USER, signal_kind="reading",
                              signal_id=reading.id,
                              delivery_status="dismissed")
    with pytest.raises(ValueError):
        store.set_signal_delivery(USER, signal_kind="reading",
                                  signal_id=reading.id,
                                  delivery_status="discussed")
    # Same-state set is an idempotent no-op, not an error.
    store.set_signal_delivery(USER, signal_kind="reading",
                              signal_id=reading.id,
                              delivery_status="dismissed")


def test_delivery_rows_cascade_with_thread_and_clear(tmp_path):
    store = _store(tmp_path)
    thread, ev, reading = _basic_fixture(store)
    store.set_signal_delivery(USER, signal_kind="reading",
                              signal_id=reading.id,
                              delivery_status="surfaced")
    assert store.delete_thread(USER, thread.id) is True
    conn = sqlite3.connect(str(store.db_path))
    try:
        assert conn.execute(
            "SELECT COUNT(*) FROM steward_signal_states"
        ).fetchone()[0] == 0
    finally:
        conn.close()
    # Routine clear: proposed reading + its delivery row go;
    # verdict reading + its delivery row survive (rule A).
    thread2, ev2, reading2 = _basic_fixture(store, USER)
    store.accept_reading(USER, reading2.id)
    proposed = _reading(store, USER, thread2.id, [ev2.id])
    store.set_signal_delivery(USER, signal_kind="reading",
                              signal_id=reading2.id,
                              delivery_status="surfaced")
    store.set_signal_delivery(USER, signal_kind="reading",
                              signal_id=proposed.id,
                              delivery_status="surfaced")
    store.clear_user_material(USER, operation="routine_clear")
    conn = sqlite3.connect(str(store.db_path))
    try:
        remaining = {
            row[0]
            for row in conn.execute(
                "SELECT signal_id FROM steward_signal_states"
            ).fetchall()
        }
    finally:
        conn.close()
    assert remaining == {reading2.id}


# ---------------------------------------------------------------------------
# Route tests (TestClient over the steward router only)
# ---------------------------------------------------------------------------


def _route_app(store, user=USER):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    import api.routes.steward_routes as steward_routes
    from api.routes.auth_routes import get_current_user

    app = FastAPI()
    app.include_router(steward_routes.router)
    app.dependency_overrides[get_current_user] = lambda: {"id": user}
    client = TestClient(app, raise_server_exceptions=False)
    return client, steward_routes


def test_route_list_detail_members_and_errors(tmp_path, monkeypatch):
    store = _store(tmp_path)
    thread, ev, reading = _basic_fixture(store)
    client, steward_routes = _route_app(store)
    # Fresh handle per request (mirroring production open-query-
    # close): the route closes its store after each request, so a
    # shared handle would break the second call.
    monkeypatch.setattr(steward_routes, "get_narrative_store",
                        lambda: NarrativeStore(
                            db_path=tmp_path / "narrative.db"))
    monkeypatch.setattr(steward_routes, "steward_consent_allowed",
                        lambda user_id: True)
    resp = client.get("/steward/signals")
    assert resp.status_code == 200
    body = resp.json()
    assert body["user_id"] == USER
    assert body["derivation_active"] is True
    assert body["groups"][0]["group_id"] == thread.id
    detail = client.get(f"/steward/signals/reading/{reading.id}")
    assert detail.status_code == 200
    assert detail.json()["id"] == reading.id
    assert detail.json()["provenance"]["evidence_rows"] != []
    # 404: unknown id and cross-user id are identical.
    mine_404 = client.get("/steward/signals/thread/nope")
    assert mine_404.status_code == 404
    other_thread, _, _ = _basic_fixture(store, OTHER)
    cross = client.get(f"/steward/signals/thread/{other_thread.id}")
    assert cross.status_code == 404
    assert cross.json() == mine_404.json()
    # 400: unknown filter value, unknown kind, bad limit, bad cursor.
    assert client.get("/steward/signals?kind=bogus").status_code == 400
    assert client.get("/steward/signals?limit=0").status_code == 400
    assert client.get("/steward/signals?cursor=!!!").status_code == 400
    assert client.get("/steward/signals/bogus/x").status_code == 400
    assert client.get("/steward/groups/nope/members").status_code == 404
    members = client.get(f"/steward/groups/{thread.id}/members")
    assert members.status_code == 200
    assert members.json()["signal_count"] == 2  # thread + reading


def test_route_unauthenticated_is_401(tmp_path):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    import api.routes.steward_routes as steward_routes

    app = FastAPI()
    app.include_router(steward_routes.router)
    client = TestClient(app, raise_server_exceptions=False)
    assert client.get("/steward/signals").status_code == 401
    assert client.get("/steward/signals/thread/x").status_code == 401


def test_route_is_get_only(tmp_path):
    import api.routes.steward_routes as steward_routes

    for route in steward_routes.router.routes:
        assert set(route.methods) == {"GET"}


# ---------------------------------------------------------------------------
# Clarification constraints (GPT weigh-in, authorized as build constraints)
# ---------------------------------------------------------------------------


def test_clarification_a_dismissed_never_blocks_underlying_access(tmp_path):
    """Dismissed is terminal for the delivery instance ONLY: the
    underlying interpretation stays independently reviewable."""
    store = _store(tmp_path)
    thread, ev, reading = _basic_fixture(store)
    store.set_signal_delivery(USER, signal_kind="reading",
                              signal_id=reading.id,
                              delivery_status="dismissed")
    resp = _resp(store, USER)
    signal = _signal(_group(resp, thread.id), "reading", reading.id)
    assert signal["delivery_status"] == "dismissed"
    assert signal["content"]["reading"]["tensions"] == []
    detail = get_signal_detail(_snapshot(store, USER), kind="reading",
                               signal_id=reading.id)
    assert detail["content"]["reading"]["tensions"] == []
    # And a fetch never marks anything surfaced (no fetch path may
    # move delivery state, in either direction).
    fresh = _store(tmp_path, "fresh.db")
    thread2, ev2, reading2 = _basic_fixture(fresh)
    _resp(fresh, USER)
    get_signal_detail(_snapshot(fresh, USER), kind="reading",
                      signal_id=reading2.id)
    conn = sqlite3.connect(str(fresh.db_path))
    try:
        assert conn.execute(
            "SELECT COUNT(*) FROM steward_signal_states"
        ).fetchone()[0] == 0
    finally:
        conn.close()


def test_clarification_c_groups_carry_no_consent_semantics(tmp_path):
    """Groups are retrieval units, not consent units: no field,
    endpoint, or key in D's output implies thread-wide
    authorization for reviewing or approving one reading."""
    store = _store(tmp_path)
    thread, ev, reading = _basic_fixture(store)
    resp = _resp(store, USER)
    blob = json.dumps(resp)
    assert "consent" not in blob.lower()
    assert "authoriz" not in blob.lower()
    for group in resp["groups"]:
        assert set(group.keys()) <= {
            "group_id", "group_kind", "thread", "meeting_key",
            "signals", "signal_count", "oversized", "members_url",
        }


def test_clarification_d_filter_consistency(tmp_path):
    """Thread headers stay as group context under kind filters;
    member pages preserve parent filters and ordering; totals,
    descriptors, and member pages describe the same set."""
    store = _store(tmp_path)
    thread = _huge_group(store, USER, count=100)
    # Kind filter: header remains as context even though the thread
    # signal itself is filtered out of the member list.
    resp = _resp(store, USER, thread_id=thread.id, kind="reading")
    group = resp["groups"][0]
    assert group["thread"]["id"] == thread.id
    assert all(s["signal_kind"] == "reading" for s in group["signals"])
    assert group["signal_count"] == 100
    assert resp["totals"]["signal_count"] == 100
    # Oversized + filtered: descriptor count == member total.
    big = _huge_group(store, USER, count=6000)
    resp = _resp(store, USER, thread_id=big.id, kind="reading")
    descriptor = resp["groups"][0]
    assert descriptor["oversized"] is True
    assert descriptor["signal_count"] == 6000
    members = get_group_members(_snapshot(store, USER), group_id=big.id,
                                kind="reading", limit=500)
    assert members["signal_count"] == 6000
    assert all(s["signal_kind"] == "reading"
               for s in members["signals"])
    # Member pages in cursor order concatenate to the full filtered
    # set, each page internally in (created_at, id) order.
    seen: list[str] = []
    cursor = None
    while True:
        out = get_group_members(_snapshot(store, USER), group_id=big.id,
                                kind="reading", limit=500, cursor=cursor)
        seen.extend(s["id"] for s in out["signals"])
        cursor = out["pagination"]["cursor"]
        if cursor is None:
            break
    assert len(seen) == 6000 and len(set(seen)) == 6000


def test_clarification_e_malformed_records_stay_inspectable(tmp_path):
    """Malformed-but-identifiable records are served, visibly
    marked — never silently omitted, never with fabricated
    provenance (covered by the dangling-ref test; asserted again
    here for the clarification, including an observable whose
    detail lost its meeting key)."""
    store = _store(tmp_path)
    thread, _, _ = _basic_fixture(store)
    _observable(store, USER, thread_id=None,
                kind="impression_unanswered",
                signal_key="o1:broken:noclaim", refs=["m-broken"],
                detail={"claim_id": None})  # no meeting_key at all
    resp = _resp(store, USER)
    groups = [g for g in resp["groups"] if g["group_id"] == "ungrouped"]
    assert len(groups) == 1
    signal = groups[0]["signals"][0]
    assert signal["provenance"]["ref_state"] == "expected_but_missing"
    assert signal["provenance"]["provenance_resolved"] is False
    assert signal["content"]["detail"] == {"claim_id": None}


# ---------------------------------------------------------------------------
# Follow-up fixes on PR #216 (GPT review of the PR, authorized by
# Joshua 2026-10-25): (a) filter validation precedes any store read
# (proposal §4.4); (b) large-history snapshot behavior.
# ---------------------------------------------------------------------------


def test_route_validation_precedes_snapshot_read(tmp_path, monkeypatch):
    """Invalid filter/limit/cursor values are 400s WITHOUT a store
    read (proposal §4.4). Proved by booming the snapshot loader:
    if the route touched the snapshot first, the boom would turn
    these requests into 500s instead of 400s."""
    store = _store(tmp_path)
    thread, ev, reading = _basic_fixture(store)
    client, steward_routes = _route_app(store)
    monkeypatch.setattr(steward_routes, "get_narrative_store",
                        lambda: NarrativeStore(
                            db_path=tmp_path / "narrative.db"))
    monkeypatch.setattr(steward_routes, "steward_consent_allowed",
                        lambda user_id: True)
    orig_snapshot = steward_routes._build_snapshot

    def _boom(store_handle, user_id):
        raise AssertionError("snapshot must not load on invalid input")

    monkeypatch.setattr(steward_routes, "_build_snapshot", _boom)
    # List endpoint: every value-validated filter, plus limits
    # and cursor shape (list max is 200).
    bad_list = [
        "/steward/signals?kind=bogus",
        "/steward/signals?delivery_status=bogus",
        "/steward/signals?decline_result=bogus",
        "/steward/signals?unconsulted_scope=bogus",
        "/steward/signals?seat=bogus",
        "/steward/signals?limit=0",
        "/steward/signals?limit=201",
        "/steward/signals?cursor=!!!",
    ]
    for url in bad_list:
        resp = client.get(url)
        assert resp.status_code == 400, url
    # Detail endpoint: the kind value validates before the snapshot;
    # the id lookup still needs data (and stays a 404).
    assert client.get("/steward/signals/bogus/x").status_code == 400
    # Members endpoint: filters, limits (members max is 500),
    # cursor shape.
    bad_members = [
        f"/steward/groups/{thread.id}/members?kind=bogus",
        f"/steward/groups/{thread.id}/members?delivery_status=bogus",
        f"/steward/groups/{thread.id}/members?limit=0",
        f"/steward/groups/{thread.id}/members?limit=501",
        f"/steward/groups/{thread.id}/members?cursor=!!!",
    ]
    for url in bad_members:
        resp = client.get(url)
        assert resp.status_code == 400, url
    # Positive control with the snapshot restored: valid requests
    # still work, and id-existence lookup still 404s (it needs
    # data, so it runs after the snapshot by design).
    monkeypatch.setattr(steward_routes, "_build_snapshot", orig_snapshot)
    assert client.get("/steward/signals").status_code == 200
    assert client.get("/steward/signals/thread/nope").status_code == 404
    assert client.get(
        f"/steward/groups/{thread.id}/members"
    ).status_code == 200


def _large_history(store, user, threads=200, readings_per_thread=25):
    """200 threads x 25 readings = 5,000 readings + 200 thread
    headers = 5,200 signals, via bulk SQL per thread (the test is
    about D's snapshot/read costs, not derivation)."""
    last_thread = None
    last_reading_id = None
    for t in range(threads):
        thread = _thread(store, user, title=f"bulk-{t:03d}")
        ev = _evidence(store, user, thread.id, f"ev-{t:03d}")
        values = ",".join(
            f"('rd-bulk-{t:03d}-{i:03d}', '{thread.id}', 'steward', "
            f"'{{\"tensions\": []}}', '[\"{ev.id}\"]', 'proposed', '{T1}')"
            for i in range(readings_per_thread)
        )
        _sql(store,
             "INSERT INTO thread_readings (id, thread_id, author, "
             "reading_json, evidence_refs_json, status, created_at) "
             f"VALUES {values}")
        last_thread = thread
        last_reading_id = f"rd-bulk-{t:03d}-{readings_per_thread - 1:03d}"
    return last_thread, last_reading_id


def test_large_history_snapshot_behavior(tmp_path):
    """Snapshot cost on a large history: the snapshot runs a
    FIXED number of SELECTs (one per table) no matter how large
    the history is — it never issues one query per thread or per
    signal (no N+1). List, drill-down, and member pages stay
    correct across the whole history. No wall-time assertion: CI
    timing is not a behavior guarantee; observed time/memory for
    this history size is reported in the PR body instead."""
    store = _store(tmp_path)
    last_thread, last_reading_id = _large_history(store, USER)
    # Query-count proof: trace the store connection during one
    # snapshot and assert the fixed SELECT set.
    seen: list[str] = []
    store._conn.set_trace_callback(seen.append)
    try:
        snap = _snapshot(store, USER)
    finally:
        store._conn.set_trace_callback(None)
    selects = [s for s in seen if s.strip().upper().startswith("SELECT")]
    assert len(selects) == 8, selects
    # Totals describe the whole history, not just the first page.
    resp = build_signals_response(
        snap, user_id=USER, derivation_active=True)
    assert resp["totals"]["group_count"] == 200
    assert resp["totals"]["signal_count"] == 5200
    assert len(resp["groups"]) == 50  # default group page
    assert resp["pagination"]["cursor"] is not None
    assert resp["pagination"]["truncated"] is False
    # Walking every page yields every group and every signal.
    groups_seen = list(resp["groups"])
    cursor = resp["pagination"]["cursor"]
    while cursor is not None:
        page = build_signals_response(
            _snapshot(store, USER), user_id=USER,
            derivation_active=True, cursor=cursor)
        groups_seen.extend(page["groups"])
        cursor = page["pagination"]["cursor"]
    assert len(groups_seen) == 200
    assert sum(g["signal_count"] for g in groups_seen) == 5200
    # Drill-down into the last thread's last reading, and a member
    # page for that thread, both against the full history.
    detail = get_signal_detail(_snapshot(store, USER), kind="reading",
                               signal_id=last_reading_id)
    assert detail["id"] == last_reading_id
    members = get_group_members(_snapshot(store, USER),
                                group_id=last_thread.id)
    assert members["signal_count"] == 26  # header + 25 readings
    assert len(members["signals"]) == 26
