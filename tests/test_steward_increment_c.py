"""Steward increment C — friction-signal derivation (proposal §10).

Covers the proposal's acceptance tests for narrowed increment C
only: four observables (unanswered impression, correction with no
subsequent recorded activity, thread quiet, divergent reading
positions), observable shape (no status/author/delivery fields),
recompute convergence + removal, no link traversal, no judgments,
no generation, no change rows, gate-per-thread semantics, sweep
phase order, prune interaction, and the deletion distinction +
warn-first preview content under rule A (routine clear removes
only proposed readings on preserved threads; verdict-state
readings survive until full deletion). Storage + derivation only:
no surfacing, no dialogue change, no UI. Stores are tmp SQLite
files; meetings and claims arrive as plain dicts (the sweep wires
the real stores in production). All clocks are fixed (NOW) with
backdated rows via direct SQL, so ordering assertions are exact.
"""

from __future__ import annotations

import inspect
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from local_ai.narrative import NarrativeStore, ProgressionPosition
from local_ai.narrative.derivation import (
    record_offer_decline,
    subject_key_for_thread,
)
from local_ai.narrative.friction import (
    FRICTION_QUIET_WINDOW_DAYS,
    run_friction_pass,
)
from local_ai.narrative.refs import SourceRef

USER = "user-1"
OTHER = "user-2"
NOW = datetime(2026, 10, 25, 12, 0, 0, tzinfo=timezone.utc)
OLD_CLAIM = "2026-06-01T00:00:00+00:00"
OLD_ROW = "2026-06-01T00:00:00+00:00"
OLD_THREAD = "2026-06-02T00:00:00+00:00"
VERY_OLD = "2026-05-01T00:00:00+00:00"


def _store(tmp_path):
    return NarrativeStore(db_path=tmp_path / "narrative.db")


def _sql(store, sql, params=()):
    conn = sqlite3.connect(str(store.db_path))
    try:
        conn.execute(sql, params)
        conn.commit()
    finally:
        conn.close()


def _backdate_thread(store, thread_id, updated_at, row_time=None):
    """Set a thread's clock (and, when given, all its rows' clocks)
    so quiet/ordering assertions are exact, not timing-dependent."""
    _sql(
        store,
        "UPDATE narrative_threads SET updated_at = ? WHERE id = ?",
        (updated_at, thread_id),
    )
    if row_time is not None:
        _sql(
            store,
            "UPDATE thread_evidence SET created_at = ? WHERE thread_id = ?",
            (row_time, thread_id),
        )
        _sql(
            store,
            "UPDATE thread_readings SET created_at = ? WHERE thread_id = ?",
            (row_time, thread_id),
        )
        _sql(
            store,
            "UPDATE thread_changes SET created_at = ? WHERE thread_id = ?",
            (row_time, thread_id),
        )


def _thread(store, user, *, origin="user_declared", title="t", scope=None):
    return store.create_thread(
        user, origin=origin, title=title, scope=scope
    )


def _evidence(store, user, thread_id, ref_id, kind="event"):
    return store.add_evidence(
        user,
        thread_id,
        SourceRef(kind=kind, ref_id=ref_id, evidence_kind="quote"),
    )


def _reading(
    store,
    user,
    thread_id,
    evidence_ids,
    *,
    author="steward",
    primary_scale="personal",
    lens="descent_and_return",
    phase="descent",
    reading=None,
):
    progression = (
        ProgressionPosition.positioned(lens, phase)
        if lens is not None
        else ProgressionPosition.unknown()
    )
    return store.propose_reading(
        user,
        thread_id,
        author=author,
        reading=reading or {"tensions": []},
        evidence_refs=list(evidence_ids),
        scales=["personal"] if primary_scale else [],
        primary_scale=primary_scale,
        progression=progression,
    )


def _meeting(*, stage="complete", status="complete", claim="you are X",
             response=""):
    return {
        "archetype_id": "weaver",
        "keystone_index": 1,
        "stage": stage,
        "status": status,
        "readback_claim": claim,
        "readback_response": response,
    }


def _claim(*, claim_id="c1", status="corrected", updated_at=OLD_CLAIM,
           agent_id="agent-1", claim_type="strand"):
    return {
        "id": claim_id,
        "agent_id": agent_id,
        "claim_type": claim_type,
        "status": status,
        "user_note": "",
        "created_at": OLD_CLAIM,
        "updated_at": updated_at,
    }


def _pass(store, user, *, meetings=None, claims=None, gate=None, now=NOW):
    return run_friction_pass(
        store,
        user,
        meetings=meetings if meetings is not None else [],
        claims=claims if claims is not None else [],
        gate_open=gate,
        now=now,
    )


def _kinds(store, user):
    return sorted(o.kind for o in store.observables_for(user))


# ---------------------------------------------------------------------------
# O1 — impression with no recorded response
# ---------------------------------------------------------------------------


def test_o1_fires_exactly(tmp_path):
    """§10 O1: complete + non-empty claim + empty response fires;
    incomplete, empty claim, non-empty response do not; a pending
    claim verdict is normal, not a missing response."""
    store = _store(tmp_path)
    meeting = _meeting()
    filed = _claim(
        claim_id="meeting-weaver-1:impression:none:run1",
        status="pending",
        agent_id="meeting-weaver-1",
        claim_type="meeting_impression",
    )
    result = _pass(store, USER, meetings=[meeting], claims=[filed])
    assert result.written == 1
    rows = store.observables_for(USER)
    assert len(rows) == 1
    row = rows[0]
    assert row.kind == "impression_unanswered"
    assert row.thread_id is None
    assert row.detail["meeting_key"] == "meeting-weaver-1"
    assert row.detail["claim_id"] == filed["id"]
    assert filed["id"] in row.evidence_refs
    assert "meeting-weaver-1" in row.evidence_refs


def test_o1_does_not_fire_variants(tmp_path):
    """§10 O1 negatives: incomplete meeting, empty claim, answered
    impression each yield no row; a filed claim alone never fires."""
    store = _store(tmp_path)
    variants = [
        _meeting(stage="encounter"),
        _meeting(status="active"),
        _meeting(claim=""),
        _meeting(claim="   "),
        _meeting(response="yes, that is right"),
    ]
    result = _pass(store, USER, meetings=variants, claims=[])
    assert result.written == 0
    assert store.observables_for(USER) == []


def test_o1_recompute_removal(tmp_path):
    """§10 recompute removal: recording a response later removes
    the O1 row on the next pass (resolution by recompute, not by
    verdict)."""
    store = _store(tmp_path)
    _pass(store, USER, meetings=[_meeting()], claims=[])
    assert len(store.observables_for(USER)) == 1
    result = _pass(
        store, USER, meetings=[_meeting(response="got it")], claims=[]
    )
    assert result.removed == 1
    assert store.observables_for(USER) == []


# ---------------------------------------------------------------------------
# O2 — correction with no subsequent recorded activity
# ---------------------------------------------------------------------------


def test_o2_fires_exactly(tmp_path):
    """§10 O2: corrected claim + attached to a live thread + no
    later reading/change fires; the row asserts the absence and
    nothing more (detail carries only the claim id + verdict time)."""
    store = _store(tmp_path)
    thread = _thread(store, USER)
    ev = _evidence(store, USER, thread.id, "claim-1", kind="claim")
    claim = _claim(claim_id="claim-1")
    result = _pass(store, USER, claims=[claim])
    assert result.written == 1
    rows = store.observables_for(USER)
    assert len(rows) == 1
    row = rows[0]
    assert row.kind == "correction_no_subsequent_activity"
    assert row.thread_id == thread.id
    assert row.evidence_refs == [ev.id]
    assert row.detail == {
        "claim_id": "claim-1",
        "claim_updated_at": OLD_CLAIM,
    }


def test_o2_does_not_fire_other_verdicts_or_unattached(tmp_path):
    """§10 O2 negatives: every non-corrected verdict, and a
    corrected claim attached to no thread, yield no row."""
    store = _store(tmp_path)
    thread = _thread(store, USER)
    _evidence(store, USER, thread.id, "claim-1", kind="claim")
    for status in ("accepted", "explained", "rejected", "unresolved",
                   "pending"):
        result = _pass(
            store, USER, claims=[_claim(claim_id="claim-1", status=status)]
        )
        assert result.written == 0, status
        assert store.observables_for(USER) == [], status
    # Corrected but unattached: no thread carries the claim.
    result = _pass(store, USER, claims=[_claim(claim_id="claim-9")])
    assert result.written == 0
    assert store.observables_for(USER) == []


def test_o2_defeated_by_later_reading_or_change(tmp_path):
    """§10 O2: a later reading OR a later change each defeats the
    row; an earlier reading does not (the time comparison is
    load-bearing, and it runs against the claim's verdict time)."""
    store = _store(tmp_path)
    # Later reading defeats.
    t1 = _thread(store, USER, title="later-reading")
    _evidence(store, USER, t1.id, "claim-1", kind="claim")
    ev1 = _evidence(store, USER, t1.id, "evt-1")
    _reading(store, USER, t1.id, [ev1.id])
    result = _pass(store, USER, claims=[_claim(claim_id="claim-1")])
    assert result.written == 0
    # Later change defeats (change needs NEW evidence by invariant,
    # so the change cites a fresh ref, not an attached row id).
    t2 = _thread(store, USER, title="later-change")
    _evidence(store, USER, t2.id, "claim-2", kind="claim")
    store.record_change(
        USER, t2.id, kind="extended",
        evidence_refs=[
            SourceRef(kind="event", ref_id="evt-2-new",
                      evidence_kind="quote")
        ],
    )
    result = _pass(store, USER, claims=[_claim(claim_id="claim-2")])
    assert result.written == 0
    # Earlier reading does NOT defeat: backdate the reading before
    # the claim's verdict time, and the row fires.
    t3 = _thread(store, USER, title="earlier-reading")
    _evidence(store, USER, t3.id, "claim-3", kind="claim")
    ev3 = _evidence(store, USER, t3.id, "evt-3")
    reading = _reading(store, USER, t3.id, [ev3.id])
    _sql(
        store,
        "UPDATE thread_readings SET created_at = ? WHERE id = ?",
        (VERY_OLD, reading.id),
    )
    result = _pass(store, USER, claims=[_claim(claim_id="claim-3")])
    assert result.written == 1
    rows = [
        o for o in store.observables_for(USER)
        if o.thread_id == t3.id
    ]
    assert len(rows) == 1


def test_o2_skips_terminal_threads(tmp_path):
    """§10 O2: a corrected claim on an archived thread is a settled
    story, not friction — no row."""
    store = _store(tmp_path)
    thread = _thread(store, USER)
    _evidence(store, USER, thread.id, "claim-1", kind="claim")
    store.set_thread_status(USER, thread.id, "archived")
    result = _pass(store, USER, claims=[_claim(claim_id="claim-1")])
    assert result.written == 0
    assert store.observables_for(USER) == []


# ---------------------------------------------------------------------------
# O3 — thread with no recent recorded activity
# ---------------------------------------------------------------------------


def test_o3_fires_exactly(tmp_path):
    """§10 O3: nascent/active + clock older than the 14-day window
    fires; dormant, terminal, and recently-touched threads do not."""
    store = _store(tmp_path)
    assert FRICTION_QUIET_WINDOW_DAYS == 14
    quiet_nascent = _thread(store, USER, title="quiet-nascent")
    _backdate_thread(store, quiet_nascent.id, OLD_THREAD)
    quiet_active = _thread(store, USER, title="quiet-active")
    store.set_thread_status(USER, quiet_active.id, "active")
    _backdate_thread(store, quiet_active.id, OLD_THREAD)
    dormant = _thread(store, USER, title="dormant")
    store.set_thread_status(USER, dormant.id, "dormant")
    _backdate_thread(store, dormant.id, OLD_THREAD)
    resolved = _thread(store, USER, title="resolved")
    store.set_thread_status(USER, resolved.id, "resolved")
    _backdate_thread(store, resolved.id, OLD_THREAD)
    fresh = _thread(store, USER, title="fresh")
    result = _pass(store, USER)
    assert result.written == 2
    rows = store.observables_for(USER)
    assert sorted(o.thread_id for o in rows) == sorted(
        [quiet_nascent.id, quiet_active.id]
    )
    assert all(o.kind == "thread_quiet" for o in rows)
    assert all(o.detail["window_days"] == 14 for o in rows)


def test_o3_recent_evidence_blocks_quiet(tmp_path):
    """§10 O3: a thread whose clock is old but which gained evidence
    recently is active, not quiet — the row-recency check, not the
    clock alone, decides (evidence attach does not move the clock
    in add_evidence, so this case is real)."""
    store = _store(tmp_path)
    thread = _thread(store, USER)
    _backdate_thread(store, thread.id, OLD_THREAD)
    _evidence(store, USER, thread.id, "evt-recent")
    result = _pass(store, USER)
    assert result.written == 0
    assert store.observables_for(USER) == []


def test_o3_c_writes_do_not_break_quiet(tmp_path):
    """§10 O3: C's own observable writes leave updated_at untouched,
    so observing quiet never counts as activity breaking quiet —
    the row survives its own pass, twice."""
    store = _store(tmp_path)
    thread = _thread(store, USER)
    _backdate_thread(store, thread.id, OLD_THREAD)
    _pass(store, USER)
    before = store.get_thread(USER, thread.id).updated_at
    result = _pass(store, USER)
    after = store.get_thread(USER, thread.id).updated_at
    assert before == after == OLD_THREAD
    assert result.refreshed == 1
    assert len(store.observables_for(USER)) == 1


# ---------------------------------------------------------------------------
# O4 — divergent reading positions (fields differing, nothing more)
# ---------------------------------------------------------------------------


def _divergence_pair(store, user, *, title="t", scope=None):
    """A thread with two complementary steward readings: same
    scale + lens, both positioned, different phases, shared
    evidence. Complementary readings DO fire — the row claims the
    fields differ, not that the readings conflict."""
    thread = _thread(store, user, title=title, scope=scope)
    ev = _evidence(store, user, thread.id, "evt-shared")
    r1 = _reading(
        store, user, thread.id, [ev.id], phase="descent",
        reading={"tensions": ["roots"]},
    )
    r2 = _reading(
        store, user, thread.id, [ev.id], phase="ascent",
        reading={"tensions": ["road"]},
    )
    return thread, ev, r1, r2


def test_o4_fires_on_complementary_readings(tmp_path):
    """§10 O4: complementary readings with differing fields fire,
    labeled divergence — the detail names lens, phases, and scale,
    and claims nothing beyond the differing fields."""
    store = _store(tmp_path)
    thread, ev, r1, r2 = _divergence_pair(store, USER)
    result = _pass(store, USER)
    assert result.written == 1
    rows = store.observables_for(USER)
    assert len(rows) == 1
    row = rows[0]
    assert row.kind == "divergent_reading_positions"
    assert row.thread_id == thread.id
    assert row.evidence_refs == [ev.id]
    assert row.detail["lens_id"] == "descent_and_return"
    assert row.detail["primary_scale"] == "personal"
    assert row.detail["reading_ids"] == sorted([r1.id, r2.id])
    assert row.detail["phases"] == {
        r1.id: "descent",
        r2.id: "ascent",
    }


def test_o4_guards_each_independently(tmp_path):
    """§10 O4: every guard failing alone yields no row — ruled
    reading, different scale, unknown/inapplicable position, same
    phase, disjoint evidence, recorded contradiction, non-steward
    author, different lens."""
    store = _store(tmp_path)
    cases = []

    # Ruled reading: accept one of the pair.
    t, ev, r1, r2 = _divergence_pair(store, USER, title="ruled")
    store.accept_reading(USER, r1.id)
    cases.append(t)
    # Different scale.
    t, ev, r1, r2 = _divergence_pair(store, USER, title="scale")
    _sql(
        store,
        "UPDATE thread_readings SET primary_scale = ? WHERE id = ?",
        ("collective", r2.id),
    )
    cases.append(t)
    # Unknown position.
    t = _thread(store, USER, title="unknown-pos")
    ev = _evidence(store, USER, t.id, "evt-u")
    _reading(store, USER, t.id, [ev.id], lens=None, phase=None)
    _reading(store, USER, t.id, [ev.id], phase="ascent")
    cases.append(t)
    # Same phase.
    t = _thread(store, USER, title="same-phase")
    ev = _evidence(store, USER, t.id, "evt-s")
    _reading(store, USER, t.id, [ev.id], phase="descent")
    _reading(store, USER, t.id, [ev.id], phase="descent")
    cases.append(t)
    # Disjoint evidence.
    t = _thread(store, USER, title="disjoint")
    ev1 = _evidence(store, USER, t.id, "evt-d1")
    ev2 = _evidence(store, USER, t.id, "evt-d2")
    _reading(store, USER, t.id, [ev1.id], phase="descent")
    _reading(store, USER, t.id, [ev2.id], phase="ascent")
    cases.append(t)
    # Recorded contradiction covers the pair (the change cites a
    # fresh ref — invariant 2 forbids asserting movement on only
    # old evidence).
    t, ev, r1, r2 = _divergence_pair(store, USER, title="contra")
    store.record_change(
        USER, t.id, kind="contradicted",
        evidence_refs=[
            SourceRef(kind="event", ref_id="evt-contra-new",
                      evidence_kind="quote")
        ],
        prior_reading_id=r1.id, new_reading_id=r2.id,
    )
    cases.append(t)
    # Non-steward author (visitor reading in the pair).
    t = _thread(store, USER, title="visitor-author")
    ev = _evidence(store, USER, t.id, "evt-v")
    _reading(store, USER, t.id, [ev.id], phase="descent")
    _reading(
        store, USER, t.id, [ev.id], author="user", phase="ascent"
    )
    cases.append(t)
    # Different lens.
    t = _thread(store, USER, title="lens")
    ev = _evidence(store, USER, t.id, "evt-l")
    _reading(store, USER, t.id, [ev.id], phase="descent")
    _reading(
        store, USER, t.id, [ev.id],
        lens="sowing_growth_harvest_fallow", phase="sowing",
    )
    cases.append(t)

    result = _pass(store, USER)
    assert result.written == 0
    assert store.observables_for(USER) == []


# ---------------------------------------------------------------------------
# Shape, recompute, traversal, language
# ---------------------------------------------------------------------------


def test_observable_shape_no_status_author_delivery(tmp_path):
    """§10 shape: rows carry exactly the observable fields — no
    status, no author, no delivery fields — evidence non-empty,
    first_seen preserved across recomputes, last_seen refreshed."""
    store = _store(tmp_path)
    thread, ev, r1, r2 = _divergence_pair(store, USER)
    _pass(store, USER)
    row = store.observables_for(USER)[0]
    assert set(row.to_dict().keys()) == {
        "id", "user_id", "thread_id", "kind", "signal_key",
        "evidence_refs", "detail", "first_seen_at", "last_seen_at",
        "created_at",
    }
    assert row.evidence_refs
    _sql(
        store,
        "UPDATE steward_observables SET first_seen_at = ?, "
        "last_seen_at = ? WHERE id = ?",
        (VERY_OLD, VERY_OLD, row.id),
    )
    _pass(store, USER)
    row2 = store.observables_for(USER)[0]
    assert row2.id == row.id
    assert row2.first_seen_at == VERY_OLD
    assert row2.last_seen_at > VERY_OLD


def test_recompute_convergence_and_removal(tmp_path):
    """§10 recompute: same state twice → same rows, no duplicates
    (second pass writes nothing); ruling a reading removes the
    divergence row on the next pass."""
    store = _store(tmp_path)
    thread, ev, r1, r2 = _divergence_pair(store, USER)
    first = _pass(store, USER)
    assert first.written == 1
    second = _pass(store, USER)
    assert second.written == 0
    assert second.refreshed == 1
    assert second.removed == 0
    assert len(store.observables_for(USER)) == 1
    store.accept_reading(USER, r1.id)
    third = _pass(store, USER)
    assert third.removed == 1
    assert store.observables_for(USER) == []


def test_no_link_traversal(tmp_path):
    """§10: threads connected ONLY by links, with suggestive
    content, yield no signal of any kind — C never reads links."""
    store = _store(tmp_path)
    a = _thread(store, USER, title="linked-a")
    b = _thread(store, USER, title="linked-b")
    store.link_threads(USER, a.id, b.id, note="same story, revisited")
    result = _pass(store, USER)
    assert result.written == 0
    assert store.observables_for(USER) == []


def test_stale_language_sweep():
    """Stale-language sweep: the terms below appear in C's module
    or this test file only as deferred-work statements — every
    matching line carries a defer marker on the same line."""
    banned = ["inconsistent", "unapplied", "circling", "adjudication_needed"]  # deferred-work terms only
    root = Path(__file__).resolve().parents[1]
    for path in (
        root / "local_ai" / "narrative" / "friction.py",
        Path(__file__).resolve(),
    ):
        for line in path.read_text().splitlines():
            for term in banned:
                if term in line:
                    assert "defer" in line.lower(), (
                        f"{path}:{line!r} uses {term!r} as a live claim"
                    )


# ---------------------------------------------------------------------------
# Zero judgments, zero generation, zero changes; gate; sweep order
# ---------------------------------------------------------------------------


def test_c_proposes_nothing_and_spends_no_generation(tmp_path):
    """§10 narrowed C: a pass creates no readings, no changes, no
    deferred rows, and moves no last_change_at — and the pass
    takes no generation function at all."""
    assert "generate_fn" not in inspect.signature(
        run_friction_pass
    ).parameters
    store = _store(tmp_path)
    thread, ev, r1, r2 = _divergence_pair(store, USER)
    before_readings = len(store.readings_for(USER, thread.id))
    before_changes = len(store.changes_for(USER, thread.id))
    before_deferred = len(store.deferred_prose_for(USER))
    before_change_at = store.get_thread(USER, thread.id).last_change_at
    result = _pass(store, USER)
    assert result.written == 1  # the divergence observable only
    assert len(store.readings_for(USER, thread.id)) == before_readings
    assert len(store.changes_for(USER, thread.id)) == before_changes
    assert len(store.deferred_prose_for(USER)) == before_deferred
    assert (
        store.get_thread(USER, thread.id).last_change_at
        == before_change_at
    )
    assert not any(
        isinstance(r.reading, dict) and "judgment_kind" in r.reading
        for r in store.readings_for(USER, thread.id)
    )


def test_gate_per_thread_and_flag_off(tmp_path):
    """§10 gate: withdrawal mid-pass leaves committed thread
    transactions standing and skips the rest (thread granularity);
    a flag-off pass derives nothing AND removes nothing stale."""
    store = _store(tmp_path)
    threads = []
    for title in ("t1", "t2", "t3"):
        thread = _thread(store, USER, title=title)
        _backdate_thread(store, thread.id, OLD_THREAD)
        threads.append(thread)
    calls = {"n": 0}

    def gate():
        calls["n"] += 1
        return calls["n"] <= 2  # open for t1, t2; closed for t3 + O1

    result = _pass(store, USER, gate=gate)
    assert result.threads_scanned == 2
    assert result.gate_skipped_threads == 1
    assert result.gate_skipped_meetings is True
    rows = store.observables_for(USER)
    assert sorted(o.thread_id for o in rows) == sorted(
        [threads[0].id, threads[1].id]
    )
    # Make t1's row stale (touch it current) but keep the gate
    # closed: the stale row must SURVIVE (recompute paused).
    _sql(
        store,
        "UPDATE narrative_threads SET updated_at = ? WHERE id = ?",
        (NOW.isoformat(), threads[0].id),
    )
    result = _pass(store, USER, gate=lambda: False)
    assert result.written == 0
    assert result.removed == 0
    assert result.threads_scanned == 0
    assert result.gate_skipped_threads == 3
    assert len(store.observables_for(USER)) == 2


def test_sweep_phase_order_and_friction_result(tmp_path, monkeypatch):
    """§10 wiring: the friction pass runs after the deferred worker
    and before prune, and its counts land on the sweep result."""
    import local_ai.narrative.sweep as sweep_module
    from local_ai.narrative.sweep import run_sweep_for_user

    store = _store(tmp_path)
    log_path = tmp_path / "activity.log"
    log_path.write_bytes(b"")
    order: list[str] = []

    class _Counts:
        def to_dict(self):
            return {"written": 0}

    def fake_friction(*args, **kwargs):
        order.append("friction")
        return _Counts()

    def fake_prune(*args, **kwargs):
        order.append("prune")
        return []

    monkeypatch.setattr(
        sweep_module, "run_friction_pass", fake_friction
    )
    monkeypatch.setattr(
        sweep_module, "prune_ignored_threads", fake_prune
    )
    result = run_sweep_for_user(
        store,
        USER,
        log_path=log_path,
        consent_reader=lambda uid: True,
    )
    assert order == ["friction", "prune"]
    assert result.friction == {"written": 0}
    assert result.to_dict()["friction"] == {"written": 0}


def test_prune_cascades_observables(tmp_path):
    """§10 prune: a prune-eligible thread with only proposed
    readings still prunes, and its C rows go with it (no orphan
    observables); a thread with a visitor verdict does not prune."""
    from local_ai.narrative.sweep import prune_ignored_threads

    store = _store(tmp_path)
    prunable = _thread(store, USER, origin="steward_proposal",
                       title="prunable")
    ev = _evidence(store, USER, prunable.id, "evt-p")
    _reading(store, USER, prunable.id, [ev.id])
    # Backdate thread + rows together so the thread is genuinely
    # quiet (no row newer than the thread clock).
    _backdate_thread(
        store, prunable.id, "2026-05-01T00:00:00+00:00",
        row_time="2026-05-01T00:00:00+00:00",
    )
    _pass(store, USER)
    assert len(store.observables_for(USER)) == 1
    deleted = prune_ignored_threads(store, USER)
    assert deleted == [prunable.id]
    assert store.observables_for(USER) == []
    assert store.get_thread(USER, prunable.id) is None

    kept = _thread(store, USER, origin="steward_proposal", title="kept")
    _backdate_thread(store, kept.id, "2026-05-01T00:00:00+00:00")
    ev2 = _evidence(store, USER, kept.id, "evt-k")
    reading = _reading(store, USER, kept.id, [ev2.id])
    store.accept_reading(USER, reading.id)
    _sql(
        store,
        "UPDATE narrative_threads SET updated_at = ? WHERE id = ?",
        ("2026-05-01T00:00:00+00:00", kept.id),
    )
    deleted = prune_ignored_threads(store, USER)
    assert deleted == []
    assert store.get_thread(USER, kept.id) is not None


def test_touch_flag_specified(tmp_path):
    """§7.4: propose_reading's touch flag — False leaves the thread
    clock alone (the future judgment-writing increment's guard);
    the default preserves existing behavior."""
    store = _store(tmp_path)
    thread = _thread(store, USER)
    ev = _evidence(store, USER, thread.id, "evt-1")
    _backdate_thread(store, thread.id, OLD_THREAD)
    store.propose_reading(
        USER, thread.id, author="steward", reading={},
        evidence_refs=[ev.id], touch=False,
    )
    assert store.get_thread(USER, thread.id).updated_at == OLD_THREAD
    store.propose_reading(
        USER, thread.id, author="steward", reading={},
        evidence_refs=[ev.id],
    )
    assert store.get_thread(USER, thread.id).updated_at != OLD_THREAD


def test_unbounded_scan(tmp_path):
    """§7.3: the friction scan is explicitly unbounded — 105 live
    threads all scan (the default 100 cap is for other callers,
    and it still holds there)."""
    store = _store(tmp_path)
    for i in range(105):
        _thread(store, USER, title=f"t{i}")
    result = _pass(store, USER)
    assert result.threads_scanned == 105
    assert len(store.threads_for(USER)) == 100
    assert len(store.threads_for(USER, limit=None)) == 105


def test_observables_do_not_consult_declines(tmp_path):
    """§8.1: a divergence observable fires on a declined subject's
    thread exactly as elsewhere — facts are recorded, declines
    govern what is served (D), never internal record-keeping."""
    store = _store(tmp_path)
    thread, ev, r1, r2 = _divergence_pair(store, USER, scope="work")
    key, precision = subject_key_for_thread(store, USER, thread)
    assert (key, precision) == ("work", "coarse")
    record_offer_decline(store, USER, scope="subject", key=key)
    result = _pass(store, USER)
    assert result.written == 1
    rows = store.observables_for(USER)
    assert len(rows) == 1
    assert rows[0].kind == "divergent_reading_positions"


def test_no_scores_paraphrase_yields_nothing(tmp_path):
    """§10 no-scores: paraphrased material with different entity
    refs yields no signal of any kind — and no similarity
    machinery exists in the friction module to misfire."""
    from pathlib import Path as _Path

    root = _Path(__file__).resolve().parents[1]
    source = (root / "local_ai" / "narrative" / "friction.py").read_text()
    assert "cosine" not in source
    assert "similarity" not in source
    store = _store(tmp_path)
    for title, entity in (("a", "person:boss"), ("b", "person:other")):
        thread = _thread(store, USER, title=title)
        ev = _evidence(store, USER, thread.id, f"evt-{title}")
        store.annotate_evidence_entities(
            USER, thread.id, {("event", f"evt-{title}"): entity}
        )
    result = _pass(store, USER)
    assert result.written == 0
    assert store.observables_for(USER) == []


# ---------------------------------------------------------------------------
# Deletion preview + clear, rule A
# ---------------------------------------------------------------------------


def test_deletion_preview_and_clear_rule_a(tmp_path):
    """§10 deletion: preview counts match clear exactly (observables
    split thread/meeting, readings split proposed/verdict, verdict
    readings lost via wholesale threads counted separately); routine
    clear removes steward threads + all observables + proposed
    readings on preserved threads and PRESERVES verdict-state
    readings, user threads, and declines (rule A); full deletion
    removes verdict readings + declines too; cleared observables
    re-derive on the next pass (clear is not suppression); meetings
    and claims live in separate stores and are never touched."""
    from local_ai.agent_intake.store import AgentStore
    from local_ai.conversation.meeting import MeetingStore

    store = _store(tmp_path)
    # Separate-store rows: a meeting row + a claim row. Clear runs
    # SQL only against narrative tables, so these must survive.
    meetings = MeetingStore(db_path=tmp_path / "meetings.db")
    meeting_row = meetings.create(USER, "weaver", 1)
    agents = AgentStore(db_path=tmp_path / "agents.db", user_id=USER)
    conn = sqlite3.connect(str(tmp_path / "agents.db"))
    conn.execute(
        "INSERT INTO review_claims (claim_id, agent_id, claim_type, "
        "title, evidence, inference, detail, status, user_note, "
        "question, scope, turn_ref, created_at, updated_at, user_id) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("c-keep", "agent-1", "strand", "t", "", "", "", "pending",
         "", "", "moment", "", OLD_CLAIM, OLD_CLAIM, USER),
    )
    conn.commit()
    conn.close()

    # Steward-proposal thread S, wholesale-deleted, carrying one
    # verdict-state reading (counted separately, never hidden).
    s_thread = _thread(store, USER, origin="steward_proposal", title="s")
    s_ev = _evidence(store, USER, s_thread.id, "evt-s")
    s_reading = _reading(store, USER, s_thread.id, [s_ev.id])
    store.accept_reading(USER, s_reading.id)
    # Preserved user thread U1: one proposed + one verdict reading,
    # backdated together so O3 fires on it.
    u1 = _thread(store, USER, title="u1")
    u1_ev = _evidence(store, USER, u1.id, "evt-u1")
    proposed = _reading(store, USER, u1.id, [u1_ev.id])
    verdict = _reading(store, USER, u1.id, [u1_ev.id])
    store.accept_reading(USER, verdict.id)
    _backdate_thread(
        store, u1.id, OLD_THREAD, row_time=OLD_ROW
    )
    # Preserved user thread U2: one rejected (verdict-state) reading.
    u2 = _thread(store, USER, title="u2")
    u2_ev = _evidence(store, USER, u2.id, "evt-u2")
    rejected = _reading(store, USER, u2.id, [u2_ev.id])
    store.reject_reading(USER, rejected.id)
    # One decline row (B's rule: routine preserves, full removes).
    record_offer_decline(store, USER, scope="subject", key="person:boss")
    # One O1 row (meeting-scoped) + O3 on U1.
    meeting = _meeting()
    _pass(store, USER, meetings=[meeting], claims=[])

    preview = store.deletion_preview(USER, operation="routine_clear")
    assert preview["observable_count"] == 2
    assert preview["observable_thread_scoped_count"] == 1
    assert preview["observable_meeting_scoped_count"] == 1
    assert preview["proposed_readings_on_preserved_count"] == 1
    assert preview["verdict_readings_on_preserved_count"] == 2
    assert preview["judgment_readings_proposed"] == 0
    assert preview["judgment_readings_verdict_state"] == 0
    assert preview["accepted_readings_on_deleted_threads"] == 1
    assert preview["declines"]["preserved"] is True
    assert preview["declines"]["total"] == 1

    report = store.clear_user_material(
        USER, operation="routine_clear", preview=preview
    )
    assert report["deleted_thread_ids"] == [s_thread.id]
    assert report["deleted_observable_count"] == 2
    assert report["deleted_proposed_reading_count"] == 1
    assert report["deleted_verdict_reading_count"] == 0
    assert report["deleted_decline_count"] == 0
    # Rule A preserved set.
    assert store.get_thread(USER, u1.id) is not None
    assert store.get_thread(USER, u2.id) is not None
    assert store.get_thread(USER, s_thread.id) is None
    remaining = {
        r.id: r.status
        for t in (u1, u2)
        for r in store.readings_for(USER, t.id)
    }
    assert remaining == {verdict.id: "accepted", rejected.id: "rejected"}
    assert store.observables_for(USER) == []
    assert len(store.dismissals_for(USER)) == 1
    # Separate stores untouched.
    assert meetings.get(USER, "weaver", 1) is not None
    assert len(agents.claims_for_user(USER)) == 1

    # Clear is not suppression: the facts still hold, so the next
    # pass re-derives both observables.
    result = _pass(store, USER, meetings=[meeting], claims=[])
    assert result.written == 2
    assert sorted(o.kind for o in store.observables_for(USER)) == [
        "impression_unanswered",
        "thread_quiet",
    ]

    # Full deletion: verdict readings + declines go too; user
    # threads themselves are never deleted by either operation.
    preview_full = store.deletion_preview(USER, operation="full_delete")
    assert preview_full["verdict_readings_on_preserved_count"] == 2
    report_full = store.clear_user_material(
        USER, operation="full_delete", preview=preview_full
    )
    assert report_full["deleted_verdict_reading_count"] == 2
    assert report_full["deleted_decline_count"] == 1
    assert report_full["deleted_observable_count"] == 2
    assert store.get_thread(USER, u1.id) is not None
    assert store.get_thread(USER, u2.id) is not None
    assert store.readings_for(USER, u1.id) == []
    assert store.readings_for(USER, u2.id) == []
    assert store.dismissals_for(USER) == []
    assert store.observables_for(USER) == []
    assert meetings.get(USER, "weaver", 1) is not None
    assert len(agents.claims_for_user(USER)) == 1
    meetings.close()
    agents.close()
