"""Narrative Steward Phase 3 — change recognition + emergent discovery.

Covers the base plan Phase 3 acceptance (T5) and the accepted
Phase 3 roadmap note's discovery discipline, with no model calls
anywhere (all generation is faked and asserted uncalled on
detector paths):

- P3-A: contradicting claim verdict → exactly one ``contradicted``
  proposal citing the new evidence + prior reading; accepting
  verdict → ``extended``; verdict on foreign claim → nothing;
  re-analysis with no new evidence → zero further proposals.
- P3-B: milestone events (task_completed, decision_recorded) on
  matching entity refs → one ``milestone``; no match → nothing.
- P3-C: dormant-thread motif recurrence → one ``reopened``;
  retired/archived threads never reopen quietly; dormant +
  milestone-kind event → reopened (precedence).
- P3-D: outgrown retirement proposals carry a verified absence
  basis; store validation for retirement reasons/successors.
- P3-E: reinterpreted retirement links the successor and preserves
  both readings; accepting it retires the thread; retired threads
  leave fast-path context blocks.
- P3-F: discovery is gated (pair + distinctive overlap),
  abstention writes nothing, proposals are reviewable births,
  and no duplicate re-proposal; discovery never makes a metaphor.
- P3-G: containment-link traversal terminates on cycles.
- P3-H: live + sweep paths accept all event kinds (incl. the new
  record_edited kind); consent gate still closes both.
- P3-I: thread history is the temporal state (ordered, windowed).
"""

from __future__ import annotations

import json
import sqlite3

import pytest

from local_ai.fellowship.events import EVENT_KINDS, FellowshipEvent
from local_ai.narrative import NarrativeStore
from local_ai.narrative.changes import (
    DEFAULT_OUTGROWN_WINDOW_DAYS,
    detect_changes_for_event,
    detect_outgrown,
    propose_reinterpretation,
    thread_history,
)
from local_ai.narrative.context import narrative_context_for
from local_ai.narrative.derivation import StewardPipeline
from local_ai.narrative.discovery import discover, propose
from local_ai.narrative.links import walk_links
from local_ai.narrative.refs import SourceRef
from local_ai.narrative.review import apply_verdict, pending_review_items
from local_ai.narrative.sweep import STEWARD_SWEEP_KINDS

USER = "user-1"


@pytest.fixture()
def store(tmp_path):
    return NarrativeStore(db_path=tmp_path / "narrative.db")


def _perm_conn():
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE user_permissions_settings ("
        "user_id TEXT, permissions_json TEXT, updated_at TEXT)"
    )
    conn.execute(
        "INSERT INTO user_permissions_settings VALUES (?, ?, ?)",
        (
            USER,
            json.dumps(
                {
                    "steward_derivation": True,
                    "steward_coordination": True,
                }
            ),
            "2026-10-31T00:00:00Z",
        ),
    )
    return conn


def _thread(store, status, title, refs):
    thread = store.create_thread(
        USER, origin="user_declared", title=title, evidence_refs=refs
    )
    if status != "nascent":
        store.set_thread_status(USER, thread.id, status)
    return store.get_thread(USER, thread.id)


def _annotate(store, thread_id, mapping):
    store.annotate_evidence_entities(USER, thread_id, mapping)


def _event(kind, entity_type="", entity_id="", action=None, evid="", event_id=None):
    payload = {} if action is None else {"action": action}
    return FellowshipEvent(
        id=event_id or f"evt-{kind}-{entity_type}-{entity_id}-{action or 'x'}",
        kind=kind,
        user_id=USER,
        entity_type=entity_type,
        entity_id=entity_id,
        evidence_text=evid,
        summary=f"{kind} {entity_type}:{entity_id}",
        payload=payload,
    )


def _claim_thread_with_standing(store, title="Claim thread"):
    """Active thread with claim evidence + an accepted standing reading."""
    claim_ref = SourceRef(kind="claim", ref_id="claim-1", evidence_kind="quote")
    thread = _thread(store, "active", title, [claim_ref])
    reading = store.propose_reading(
        USER,
        thread.id,
        author="steward",
        reading={
            "tensions": ["patience vs avoidance"],
            "open_questions": [],
            "milestones": [],
        },
        evidence_refs=[claim_ref],
    )
    store.accept_reading(USER, reading.id)
    thread = store.get_thread(USER, thread.id)
    assert thread.standing_reading_id == reading.id
    return thread, reading


def _backdate_evidence(store, tmp_path, thread_id, timestamp):
    conn = sqlite3.connect(str(tmp_path / "narrative.db"))
    conn.execute(
        "UPDATE thread_evidence SET created_at = ? WHERE thread_id = ?",
        (timestamp, thread_id),
    )
    conn.commit()
    conn.close()


# ---------------------------------------------------------------- P3-A: verdict

def test_contradicting_verdict_yields_exactly_one_contradicted(store):
    thread, standing = _claim_thread_with_standing(store)
    event = _event("claim_decided", "claim", "claim-1", action="rejected")
    proposals = detect_changes_for_event(store, USER, event)
    assert len(proposals) == 1
    change = proposals[0]
    assert change.kind == "contradicted"
    assert change.status == "proposed"
    assert change.prior_reading_id == standing.id
    items = pending_review_items(store, USER)
    change_items = [i for i in items if i.item_kind == "change"]
    assert len(change_items) == 1
    assert change_items[0].payload["kind"] == "contradicted"


def test_accepting_verdict_yields_extended_not_contradicted(store):
    thread, _ = _claim_thread_with_standing(store)
    event = _event("claim_decided", "claim", "claim-1", action="accepted")
    proposals = detect_changes_for_event(store, USER, event)
    assert len(proposals) == 1
    assert proposals[0].kind == "extended"


def test_verdict_on_foreign_claim_yields_nothing(store):
    _claim_thread_with_standing(store)
    event = _event("claim_decided", "claim", "claim-other", action="rejected")
    assert detect_changes_for_event(store, USER, event) == []


def test_reanalysis_with_no_new_evidence_yields_zero(store):
    _claim_thread_with_standing(store)
    event = _event("claim_decided", "claim", "claim-1", action="rejected")
    assert len(detect_changes_for_event(store, USER, event)) == 1
    assert detect_changes_for_event(store, USER, event) == []


def test_second_verdict_event_while_proposed_is_deduped(store):
    _claim_thread_with_standing(store)
    first = _event(
        "claim_decided", "claim", "claim-1",
        action="rejected", event_id="evt-first",
    )
    second = _event(
        "claim_decided", "claim", "claim-1",
        action="rejected", event_id="evt-second",
    )
    assert len(detect_changes_for_event(store, USER, first)) == 1
    assert detect_changes_for_event(store, USER, second) == []


# ---------------------------------------------------------------- P3-B: milestone

def test_task_completed_matching_entity_yields_milestone(store):
    ref = SourceRef(kind="event", ref_id="evt-task", evidence_kind="entity_ref")
    thread = _thread(store, "active", "Task thread", [ref])
    _annotate(store, thread.id, {("event", "evt-task"): "task:task-1"})
    event = _event("task_completed", "task", "task-1")
    proposals = detect_changes_for_event(store, USER, event)
    assert len(proposals) == 1
    assert proposals[0].kind == "milestone"


def test_decision_recorded_matching_entity_yields_milestone(store):
    ref = SourceRef(kind="event", ref_id="evt-dec", evidence_kind="entity_ref")
    thread = _thread(store, "active", "Decision thread", [ref])
    _annotate(store, thread.id, {("event", "evt-dec"): "decision:dec-1"})
    event = _event("decision_recorded", "decision", "dec-1")
    proposals = detect_changes_for_event(store, USER, event)
    assert len(proposals) == 1
    assert proposals[0].kind == "milestone"


def test_milestone_event_without_match_yields_nothing(store):
    ref = SourceRef(kind="event", ref_id="evt-task", evidence_kind="entity_ref")
    thread = _thread(store, "active", "Task thread", [ref])
    _annotate(store, thread.id, {("event", "evt-task"): "task:task-1"})
    event = _event("task_completed", "task", "task-other")
    assert detect_changes_for_event(store, USER, event) == []


# ---------------------------------------------------------------- P3-C: recurrence

def test_dormant_motif_recurrence_yields_reopened(store):
    ref = SourceRef(kind="event", ref_id="evt-proj", evidence_kind="entity_ref")
    thread = _thread(store, "dormant", "Dormant thread", [ref])
    _annotate(store, thread.id, {("event", "evt-proj"): "project:alpha"})
    event = _event("conversation_turn", "project", "alpha")
    proposals = detect_changes_for_event(store, USER, event)
    assert len(proposals) == 1
    assert proposals[0].kind == "reopened"


def test_dormant_milestone_kind_event_prefers_reopened(store):
    ref = SourceRef(kind="event", ref_id="evt-task", evidence_kind="entity_ref")
    thread = _thread(store, "dormant", "Dormant thread", [ref])
    _annotate(store, thread.id, {("event", "evt-task"): "task:task-1"})
    event = _event("task_completed", "task", "task-1")
    proposals = detect_changes_for_event(store, USER, event)
    assert len(proposals) == 1
    assert proposals[0].kind == "reopened"


def test_retired_and_archived_threads_never_reopen(store):
    ref = SourceRef(kind="event", ref_id="evt-proj", evidence_kind="entity_ref")
    retired = _thread(store, "active", "Retired thread", [ref])
    _annotate(store, retired.id, {("event", "evt-proj"): "project:alpha"})
    store.set_thread_status(
        USER, retired.id, "retired", retirement_reason="completed"
    )
    archived = _thread(store, "active", "Archived thread", [ref])
    _annotate(store, archived.id, {("event", "evt-proj"): "project:alpha"})
    store.set_thread_status(USER, archived.id, "archived")
    event = _event("conversation_turn", "project", "alpha")
    assert detect_changes_for_event(store, USER, event) == []


# ---------------------------------------------------------------- P3-D: outgrown

def test_outgrown_proposal_carries_verified_absence_basis(store, tmp_path):
    ref = SourceRef(kind="event", ref_id="evt-old", evidence_kind="entity_ref")
    thread = _thread(store, "active", "Stale thread", [ref])
    _backdate_evidence(store, tmp_path, thread.id, "2020-01-01T00:00:00+00:00")
    proposals = detect_outgrown(store, USER, window_days=30)
    assert len(proposals) == 1
    change = proposals[0]
    assert change.kind == "retired"
    assert change.reason == "outgrown"
    assert change.absence_window_days == 30
    assert change.absence_last_evidence_at == "2020-01-01T00:00:00+00:00"
    items = pending_review_items(store, USER)
    change_items = [i for i in items if i.item_kind == "change"]
    assert len(change_items) == 1
    assert change_items[0].payload["reason"] == "outgrown"


def test_recent_evidence_blocks_outgrown(store):
    ref = SourceRef(kind="event", ref_id="evt-new", evidence_kind="entity_ref")
    _thread(store, "active", "Fresh thread", [ref])
    assert detect_outgrown(store, USER, window_days=30) == []


def test_outgrown_requires_verified_absence(store, tmp_path):
    ref = SourceRef(kind="event", ref_id="evt-old", evidence_kind="entity_ref")
    thread = _thread(store, "active", "Stale thread", [ref])
    _backdate_evidence(store, tmp_path, thread.id, "2020-01-01T00:00:00+00:00")
    # Wrong last-evidence timestamp: the store re-derives it.
    with pytest.raises(ValueError):
        store.record_change(
            USER,
            thread.id,
            kind="retired",
            evidence_refs=[],
            reason="outgrown",
            absence_basis={
                "window_days": 30,
                "last_evidence_at": "2021-06-01T00:00:00+00:00",
            },
        )
    # No absence basis at all.
    with pytest.raises(ValueError):
        store.record_change(
            USER, thread.id, kind="retired", reason="outgrown"
        )


def test_retirement_validation(store):
    thread = _thread(store, "active", "Thread", [])
    with pytest.raises(ValueError):
        store.record_change(USER, thread.id, kind="retired")
    with pytest.raises(ValueError):
        store.record_change(
            USER, thread.id, kind="retired", reason="reinterpreted"
        )
    with pytest.raises(ValueError):
        store.record_change(
            USER, thread.id, kind="extended", reason="completed"
        )
    with pytest.raises(ValueError):
        store.record_change(
            USER, thread.id, kind="retired", reason="not-a-reason"
        )


# ---------------------------------------------------------------- P3-E: reinterpretation

def test_reinterpretation_links_successor_and_preserves_readings(store):
    old_ref = SourceRef(kind="event", ref_id="evt-old", evidence_kind="entity_ref")
    old = _thread(store, "active", "Old story", [old_ref])
    reading = store.propose_reading(
        USER,
        old.id,
        author="steward",
        reading={"tensions": ["old tension"], "open_questions": [], "milestones": []},
        evidence_refs=[old_ref],
    )
    successor = _thread(store, "active", "New story", [])
    change = propose_reinterpretation(store, USER, old.id, successor.id)
    assert change.kind == "retired"
    assert change.reason == "reinterpreted"
    assert change.successor_thread_id == successor.id
    # Proposal only: statuses and readings untouched.
    assert store.get_thread(USER, old.id).status == "active"
    assert len(store.readings_for(USER, old.id)) == 1
    assert store.readings_for(USER, old.id)[0].id == reading.id
    assert store.readings_for(USER, successor.id) == []


def test_accepting_retirement_retires_the_thread(store):
    old = _thread(store, "active", "Old story", [])
    successor = _thread(store, "active", "New story", [])
    propose_reinterpretation(store, USER, old.id, successor.id)
    items = pending_review_items(store, USER)
    change_items = [i for i in items if i.item_kind == "change"]
    assert len(change_items) == 1
    result = apply_verdict(store, USER, change_items[0].item_id, "accepted")
    assert result.status == "confirmed"
    retired = store.get_thread(USER, old.id)
    assert retired.status == "retired"
    assert retired.retirement_reason == "reinterpreted"
    assert retired.successor_thread_id == successor.id


def test_retired_thread_leaves_context_blocks(store):
    conn = _perm_conn()
    live_ref = SourceRef(kind="event", ref_id="evt-live", evidence_kind="entity_ref")
    live = _thread(store, "active", "Live story", [live_ref])
    _annotate(store, live.id, {("event", "evt-live"): "project:alpha"})
    gone_ref = SourceRef(kind="event", ref_id="evt-gone", evidence_kind="entity_ref")
    gone = _thread(store, "active", "Gone story", [gone_ref])
    _annotate(store, gone.id, {("event", "evt-gone"): "project:alpha"})
    store.set_thread_status(
        USER, gone.id, "retired", retirement_reason="completed"
    )
    prepared = narrative_context_for(
        store,
        USER,
        "seat:conductor",
        attended_entity_refs=["project:alpha"],
        connection=conn,
    )
    assert prepared.available
    assert "Live story" in (prepared.block or "")
    assert "Gone story" not in (prepared.block or "")


# ---------------------------------------------------------------- P3-F: discovery

def _pair_with_shared_ref(store, ref_id="project:alpha"):
    a_ref = SourceRef(kind="event", ref_id="evt-a", evidence_kind="entity_ref")
    b_ref = SourceRef(kind="event", ref_id="evt-b", evidence_kind="entity_ref")
    thread_a = _thread(store, "active", "Story A", [a_ref])
    thread_b = _thread(store, "active", "Story B", [b_ref])
    _annotate(store, thread_a.id, {("event", "evt-a"): ref_id})
    _annotate(store, thread_b.id, {("event", "evt-b"): ref_id})
    return thread_a, thread_b


def test_discovery_pair_proposes_reviewable_birth(store):
    thread_a, thread_b = _pair_with_shared_ref(store)
    result = discover(store, USER)
    assert len(result.candidates) == 1
    candidate = result.candidates[0]
    assert {candidate.thread_a_id, candidate.thread_b_id} == {
        thread_a.id,
        thread_b.id,
    }
    assert candidate.shared_entity_refs == ("project:alpha",)
    assert candidate.score == 1.0
    assert "coincidence" in " ".join(candidate.alternatives)
    assert not hasattr(candidate, "metaphor")
    proposed = propose(store, USER, result.candidates)
    assert len(proposed) == 1
    assert proposed[0].status == "nascent"
    assert proposed[0].origin == "steward_proposal"
    items = pending_review_items(store, USER)
    assert any(i.item_kind == "birth" for i in items)


def test_discovery_single_thread_abstains_without_writing(store):
    _thread(store, "active", "Lonely story", [])
    before = len(store.threads_for(USER, limit=None))
    result = discover(store, USER)
    assert result.candidates == []
    assert result.pairs_examined == 0
    assert result.abstained is False
    assert len(store.threads_for(USER, limit=None)) == before


def test_discovery_generic_ref_below_gate_abstains(store):
    # Five threads share the ref: score 2/5 = 0.4 < 1.0.
    for i in range(5):
        ref = SourceRef(
            kind="event", ref_id=f"evt-{i}", evidence_kind="entity_ref"
        )
        thread = _thread(store, "active", f"Story {i}", [ref])
        _annotate(store, thread.id, {(f"event", f"evt-{i}"): "project:alpha"})
    before = len(store.threads_for(USER, limit=None))
    result = discover(store, USER)
    assert result.candidates == []
    assert result.abstained is True
    assert len(store.threads_for(USER, limit=None)) == before


def test_discovery_no_duplicate_after_proposal(store):
    _pair_with_shared_ref(store)
    first = discover(store, USER)
    assert len(first.candidates) == 1
    propose(store, USER, first.candidates)
    second = discover(store, USER)
    assert second.candidates == []


def test_discovery_ignores_nascent_threads(store):
    thread_a, _ = _pair_with_shared_ref(store)
    # A nascent thread sharing the ref must not pair.
    nascent_ref = SourceRef(
        kind="event", ref_id="evt-n", evidence_kind="entity_ref"
    )
    nascent = store.create_thread(
        USER,
        origin="steward_proposal",
        title="Nascent",
        evidence_refs=[nascent_ref],
    )
    _annotate(store, nascent.id, {("event", "evt-n"): "project:alpha"})
    result = discover(store, USER)
    assert len(result.candidates) == 1
    assert thread_a.id in (
        result.candidates[0].thread_a_id,
        result.candidates[0].thread_b_id,
    )


# ---------------------------------------------------------------- P3-G: links

def test_link_traversal_terminates_on_cycles(store):
    a = _thread(store, "active", "A", [])
    b = _thread(store, "active", "B", [])
    c = _thread(store, "active", "C", [])
    store.link_threads(USER, a.id, b.id)
    store.link_threads(USER, b.id, c.id)
    store.link_threads(USER, c.id, a.id)
    assert walk_links(store, USER, a.id) == [b.id, c.id]
    assert walk_links(store, USER, c.id, direction="ancestors") == [b.id, a.id]
    with pytest.raises(ValueError):
        walk_links(store, USER, a.id, direction="sideways")
    with pytest.raises(ValueError):
        walk_links(store, USER, "no-such-thread")


# ---------------------------------------------------------------- P3-H: live/sweep generalization

def test_sweep_accepts_all_event_kinds(store):
    assert tuple(STEWARD_SWEEP_KINDS) == tuple(EVENT_KINDS)
    assert "record_edited" in EVENT_KINDS


def test_live_path_routes_non_meeting_kinds_without_generation(store):
    calls: list[str] = []

    def fake_gen(prompt: str) -> str:
        calls.append(prompt)
        return ""

    pipeline = StewardPipeline(
        store=store,
        generate_fn=fake_gen,
        scheduler=lambda fn: fn(),
        consent_reader=lambda user_id: True,
    )
    ref = SourceRef(kind="event", ref_id="evt-task", evidence_kind="entity_ref")
    thread = _thread(store, "active", "Task thread", [ref])
    _annotate(store, thread.id, {("event", "evt-task"): "task:task-1"})
    event = _event("task_completed", "task", "task-1")
    pipeline._run_event(event)
    changes = store.changes_for(USER, thread.id)
    assert len(changes) == 1
    assert changes[0].kind == "milestone"
    # Detector attached the event first, so derivation's extension
    # path found nothing new and spent no generation.
    assert calls == []


def test_live_path_gate_closed_runs_nothing(store):
    pipeline = StewardPipeline(
        store=store,
        generate_fn=lambda prompt: "",
        scheduler=lambda fn: fn(),
        consent_reader=lambda user_id: False,
    )
    ref = SourceRef(kind="event", ref_id="evt-task", evidence_kind="entity_ref")
    thread = _thread(store, "active", "Task thread", [ref])
    _annotate(store, thread.id, {("event", "evt-task"): "task:task-1"})
    pipeline._run_event(_event("task_completed", "task", "task-1"))
    assert store.changes_for(USER, thread.id) == []


def test_record_edited_event_is_routed_not_skipped(store):
    calls: list[str] = []

    def fake_gen(prompt: str) -> str:
        calls.append(prompt)
        return ""

    pipeline = StewardPipeline(
        store=store,
        generate_fn=fake_gen,
        scheduler=lambda fn: fn(),
        consent_reader=lambda user_id: True,
    )
    event = _event("record_edited", "task", "task-9")
    pipeline._run_event(event)
    assert calls == []
    assert store.threads_for(USER, limit=None) == []


# ---------------------------------------------------------------- P3-I: temporal state

def test_thread_history_is_ordered_and_windowable(store):
    thread, _ = _claim_thread_with_standing(store)
    first = _event(
        "claim_decided", "claim", "claim-1",
        action="accepted", event_id="evt-hist-1",
    )
    detect_changes_for_event(store, USER, first)
    changes = store.changes_for(USER, thread.id)
    assert len(changes) == 1
    history = thread_history(store, USER, thread.id)
    assert [c.id for c in history] == [c.id for c in changes]
    # Window excluding the only change yields nothing.
    assert thread_history(store, USER, thread.id, since="2999-01-01") == []
    assert (
        len(
            thread_history(
                store, USER, thread.id, until="2999-01-01"
            )
        )
        == 1
    )
