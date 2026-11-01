"""Narrative Steward Phase 7 — layer completion + rollout (FINAL phase).

Covers the addendum §5 acceptance criteria and the §6
architectural test, all at fixture level (no live demonstration,
no live spend authorized):

- P7-A: registry complete — every §1 branch registered with
  its conditioning contract and a recorded decision;
  build-council recorded as sibling, garden deferred explicitly.
- P7-B: conditioning audit — each branch names its conditioner
  per schedule step, spot-checked against implemented wiring.
- P7-C: architectural test §6 — a Gardener development reaches
  the Weaver's available context ONLY after both gates, and
  the Weaver's response is her own (adopt / translate /
  qualify / decline), with no silent adoption, no manufactured
  verdict, zero generations for availability, and disagreement
  preserved.
- P7-D: oversight functions (I1) live and verdict-routed —
  stall / conflict / drift proposals surface in review, and
  confirming one changes NO thread, reading, or branch state.
- P7-E: state-revision pass (I3) live — a previously accepted
  interpretation gains candidate status through the schedule
  without being mutated.
- P7-F: dual-axis resolution (I4) visible in thread status
  and resolution rendering; lens comes only from the accepted
  fitting (no canon built in Phase 7).
- P7-G: correspondence function (§3) live under its evidence
  rules — adopt + translate + decline across seats on the
  SAME correspondence, abstention as a complete result, never
  evidence, no auto-chaining from discovery.
- P7-H: rollout criteria defined and flag-gated with
  thresholds UNSET — no default flip, ever, on this code.
- P7-I: no default flips, no seat-prompt changes, no
  subsumption: consent defaults off, sibling/deferred
  branches cannot respond, build-council records untouched.

No model calls anywhere: every generation is absent (the
coordination path takes no generate_fn at all).
"""

from __future__ import annotations

import inspect
import json
import sqlite3

import pytest

from local_ai.narrative import (
    branches as branches_mod,
)
from local_ai.narrative import (
    correspondence as corr_mod,
)
from local_ai.narrative import (
    oversight as ovs_mod,
)
from local_ai.narrative import (
    review as review_mod,
)
from local_ai.narrative import (
    rollout as rollout_mod,
)
from local_ai.narrative import (
    schedule as sched_mod,
)
from local_ai.narrative.consent import (
    coordination_allowed,
    steward_consent_allowed,
    steward_coordination_allowed,
)
from local_ai.narrative.context import (
    WEAVER_BRANCH_ID,
    narrative_context_for,
)
from local_ai.narrative.discovery import discover, propose as discover_propose
from local_ai.narrative.refs import SourceRef
from local_ai.narrative.store import NarrativeStore

USER = "user-1"

FLAGS_ON = {"steward_derivation": True, "steward_coordination": True}
FLAGS_OFF = {"steward_derivation": False, "steward_coordination": False}

CLAIM_A = SourceRef(kind="claim", ref_id="claim-a", evidence_kind="quote")
CLAIM_B = SourceRef(kind="claim", ref_id="claim-b", evidence_kind="quote")
EVENT_A = SourceRef(kind="event", ref_id="evt-a", evidence_kind="entity_ref")

NOW = "2026-11-01T00:00:00Z"
OLD = "2026-01-01T00:00:00Z"


@pytest.fixture()
def store(tmp_path):
    return NarrativeStore(db_path=tmp_path / "narrative.db")


def _perm_conn(flags_by_user):
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE user_permissions_settings ("
        "user_id TEXT, permissions_json TEXT, updated_at TEXT)"
    )
    for user_id, flags in flags_by_user.items():
        conn.execute(
            "INSERT INTO user_permissions_settings VALUES (?, ?, ?)",
            (user_id, json.dumps(flags), "2026-10-31T00:00:00Z"),
        )
    conn.commit()
    return conn


def _thread(store, status, title, refs, scope="harbor notes"):
    thread = store.create_thread(
        USER, origin="user_declared", title=title, evidence_refs=refs,
        scope=scope,
    )
    if status != "nascent":
        store.set_thread_status(USER, thread.id, status)
    return store.get_thread(USER, thread.id)


def _annotate(store, thread_id, mapping):
    """mapping: {(ref_kind, ref_id): entity_ref} — the store's
    annotation key is the ref identity, not the row id."""
    store.annotate_evidence_entities(USER, thread_id, mapping)


def _evidence_ids(store, thread_id):
    return [row.id for row in store.evidence_for(USER, thread_id)]


def _backdate(store, tmp_path, thread_id, timestamp):
    conn = sqlite3.connect(str(tmp_path / "narrative.db"))
    conn.execute(
        "UPDATE thread_evidence SET created_at = ? WHERE thread_id = ?",
        (timestamp, thread_id),
    )
    conn.commit()
    conn.close()


def _standing_thread(store, title, ref, author, reading_text):
    """Active thread with one evidence row + an accepted reading."""
    thread = _thread(store, "active", title, [ref])
    reading = store.propose_reading(
        USER, thread.id, author=author,
        reading={"tensions": [reading_text], "open_questions": [],
                 "milestones": []},
        evidence_refs=[ref],
    )
    store.accept_reading(USER, reading.id)
    thread = store.get_thread(USER, thread.id)
    assert thread.standing_reading_id == reading.id
    return thread, reading


# -- P7-A: registry complete -----------------------------------------------


def test_registry_complete_with_decision_per_branch():
    audit = branches_mod.registry_audit()
    assert audit["complete"] is True
    assert audit["incomplete_reasons"] == []
    assert len(audit["branches"]) == 11
    for entry in audit["branches"]:
        assert entry["decision"], entry["branch_id"]
    ids = {entry["branch_id"] for entry in audit["branches"]}
    assert ids == {
        "seat:mentor", "seat:champion", "seat:guardian",
        "seat:maverick", "seat:ambassador", "seat:conductor",
        "seat:skeptic", "vision_execution", "journal",
        "build_council", "garden",
    }


def test_build_council_recorded_as_sibling_not_subsumed():
    contract = branches_mod.get_branch("build_council")
    assert contract is not None
    assert "SIBLING" in contract.decision
    assert "never subsumed" in contract.decision
    assert "coordination" not in contract.capabilities
    # The sibling record is not coordination-capable, structurally.
    assert contract not in branches_mod.coordination_capable_branches()


def test_garden_deferred_explicitly_not_invented():
    contract = branches_mod.get_branch("garden")
    assert contract is not None
    assert "DEFERRED" in contract.decision
    assert contract.capabilities == ()
    assert contract.conditioning_sources == ()


# -- P7-B: conditioning audit ----------------------------------------------


def test_conditioning_audit_spot_checks():
    audit = branches_mod.conditioning_audit()
    # 11 branches + 2 reading surfaces, 4 schedule steps each.
    assert len(audit) == 52
    by_branch_step = {
        (row["branch_id"], row["step"]): row["conditioner"]
        for row in audit
    }
    # Seats: draft conditioned by the jurisdiction registry.
    assert "SeatJurisdiction" in by_branch_step[("seat:mentor", "draft")]
    assert "SeatJurisdiction" in by_branch_step[("seat:conductor", "draft")]
    # Review: the user verdict, for every branch alike.
    for branch_id in (
        "seat:mentor", "seat:conductor", "vision_execution", "journal",
    ):
        assert by_branch_step[(branch_id, "review")] == (
            "user verdict (review layer)"
        )
    # Journal never conditions evidence at any step but review.
    for step in ("draft", "revision", "artifact"):
        assert by_branch_step[("journal", step)].startswith("none")
    # Sibling and deferred condition nothing at any step.
    for step in ("draft", "revision", "review", "artifact"):
        assert by_branch_step[("build_council", step)].startswith(
            "none — sibling"
        )
        assert by_branch_step[("garden", step)].startswith("none — deferred")
    # Reading surfaces hold no state at any step.
    for step in ("draft", "revision", "review", "artifact"):
        assert by_branch_step[("today", step)].startswith("none")
        assert by_branch_step[("review", step)].startswith("none")


# -- P7-C: architectural test §6 --------------------------------------------


def _gardener_thread(store):
    """Gardener development: active thread, mentor reading accepted."""
    thread, reading = _standing_thread(
        store, "Loft ledger", CLAIM_A, "mentor", "patience developing"
    )
    _annotate(store, thread.id, {("claim", "claim-a"): "project:loft"})
    return store.get_thread(USER, thread.id), reading


def test_architectural_gates_consent_and_relevance(store):
    thread, _reading = _gardener_thread(store)
    conn_on = _perm_conn({USER: FLAGS_ON})
    # Both gates pass: consent on + shared entity ref attended.
    ctx = narrative_context_for(
        store, USER, WEAVER_BRANCH_ID,
        attended_entity_refs=["project:loft"], connection=conn_on,
    )
    assert ctx.available is True
    assert ctx.block is not None
    assert "Loft ledger" in ctx.block
    assert ctx.assessment_ids, "availability must carry assessments"
    # Consent off: nothing crosses, not even a title.
    ctx_off = narrative_context_for(
        store, USER, WEAVER_BRANCH_ID,
        attended_entity_refs=["project:loft"],
        connection=_perm_conn({USER: FLAGS_OFF}),
    )
    assert ctx_off.available is False
    assert ctx_off.block is None
    # Irrelevant: consent on, but nothing the Weaver attends to.
    ctx_irr = narrative_context_for(
        store, USER, WEAVER_BRANCH_ID,
        attended_entity_refs=["project:unrelated"], connection=conn_on,
    )
    assert ctx_irr.available is False
    assert ctx_irr.block is None


def test_architectural_weaver_responses_all_four(store):
    thread, mentor_reading = _gardener_thread(store)
    conn_on = _perm_conn({USER: FLAGS_ON})
    ctx = narrative_context_for(
        store, USER, WEAVER_BRANCH_ID,
        attended_entity_refs=["project:loft"], connection=conn_on,
    )
    assert ctx.available is True
    ev_ids = _evidence_ids(store, thread.id)
    verdicts_before = store.verdicts_for(USER)

    # ADOPT: the Weaver records her own reading of the shared
    # evidence. Proposed only — no standing change, no verdict
    # manufactured by availability.
    adopt = store.propose_reading(
        USER, thread.id, author="conductor",
        reading={"tensions": ["patience developing"],
                 "open_questions": [], "milestones": []},
        evidence_refs=[CLAIM_A],
    )
    assert adopt.status == "proposed"
    assert store.get_thread(USER, thread.id).standing_reading_id == (
        mentor_reading.id
    )

    # TRANSLATE: same relationship in her register — time
    # signatures binding freedom to form, not Odysseus.
    translate = store.propose_reading(
        USER, thread.id, author="conductor",
        reading={"tensions": [
            "time signatures binding freedom to a predictable form"
        ], "open_questions": [], "milestones": []},
        evidence_refs=[CLAIM_A],
    )
    assert translate.status == "proposed"
    assert translate.reading["tensions"] != adopt.reading["tensions"]

    # QUALIFY: flag the relevance assessment without changing
    # it, the evidence, or requiring adjudication.
    assessment_id = ctx.assessment_ids[0]
    assessments_before = store.assessments_for(USER)
    flag = store.record_discrepancy_flag(
        USER, assessment_id, WEAVER_BRANCH_ID,
        objection="apparent recurrence may be coincidental",
        evidence_refs=ev_ids,
    )
    assert flag.status == "open"
    assert store.assessments_for(USER) == assessments_before

    # DECLINE: a second preparation, consumed by nothing,
    # writes no reading, no flag, no verdict.
    readings_before = store.readings_for(USER, thread.id)
    flags_before = store.flags_for(USER)
    narrative_context_for(
        store, USER, WEAVER_BRANCH_ID,
        attended_entity_refs=["project:loft"], connection=conn_on,
    )
    assert store.readings_for(USER, thread.id) == readings_before
    assert store.flags_for(USER) == flags_before
    assert store.verdicts_for(USER) == verdicts_before

    # DISAGREEMENT PRESERVED: mentor + Weaver readings coexist,
    # attributed, different — no convergence step ran.
    readings = store.readings_for(USER, thread.id)
    by_author = {r.author: r for r in readings}
    assert by_author["mentor"].status == "accepted"
    assert by_author["conductor"].status == "proposed"
    assert by_author["mentor"].id != by_author["conductor"].id


def test_architectural_zero_generations_and_facts_only(store):
    thread, reading = _gardener_thread(store)
    # The coordination path takes no generate_fn at all.
    params = inspect.signature(narrative_context_for).parameters
    assert not any("generat" in name for name in params)
    ctx = narrative_context_for(
        store, USER, WEAVER_BRANCH_ID,
        attended_entity_refs=["project:loft"],
        connection=_perm_conn({USER: FLAGS_ON}),
    )
    assert ctx.available is True
    # Facts only: title, status, scope, evidence count — never
    # reading text, never evidence text.
    assert "patience developing" not in (ctx.block or "")
    assert "Loft ledger" in (ctx.block or "")


# -- P7-D: oversight live + verdict-routed, never commanding ----------------


def test_oversight_stall_conflict_drift(store, tmp_path):
    # STALL: active thread, only old evidence, now far later.
    stall_thread = _thread(store, "active", "Loft ledger", [CLAIM_A])
    _backdate(store, tmp_path, stall_thread.id, OLD)
    # DRIFT: standing reading; founding refs disjoint from recent.
    drift_thread, _dr = _standing_thread(
        store, "Harbor notes", CLAIM_B, "mentor", "steady course"
    )
    _annotate(store, drift_thread.id, {("claim", "claim-b"): "project:loft"})
    _backdate(store, tmp_path, drift_thread.id, OLD)
    recent = store.add_evidence(USER, drift_thread.id, EVENT_A)
    _annotate(store, drift_thread.id, {("event", "evt-a"): "project:harbor"})
    # CONFLICT: two active threads sharing a ref, different
    # standing readings.
    t1, _r1 = _standing_thread(store, "First claim", CLAIM_A, "mentor", "one")
    t2, _r2 = _standing_thread(store, "Second claim", CLAIM_A, "champion", "two")
    for t in (t1, t2):
        _annotate(store, t.id, {("claim", "claim-a"): "project:shared"})

    ensured = ovs_mod.detect_oversight(store, USER, now=NOW)
    kinds = {(p.thread_id, p.kind) for p in ensured}
    assert (stall_thread.id, "stall") in kinds
    assert (drift_thread.id, "drift") in kinds
    assert (t1.id, "conflict") in kinds
    # Dedupe: a second run on unchanged state adds nothing.
    ensured_again = ovs_mod.detect_oversight(store, USER, now=NOW)
    assert {(p.thread_id, p.kind) for p in ensured_again} == kinds
    assert len(store.oversight_proposals_for(USER)) == len(kinds)


def test_oversight_verdict_never_commands(store, tmp_path):
    thread = _thread(store, "active", "Loft ledger", [CLAIM_A])
    _backdate(store, tmp_path, thread.id, OLD)
    (proposal,) = [
        p for p in ovs_mod.detect_oversight(store, USER, now=NOW)
        if p.kind == "stall"
    ]
    # Surfaces in review.
    items = review_mod.pending_review_items(store, USER)
    assert any(
        item.item_kind == "oversight" and item.item_id.endswith(proposal.id)
        for item in items
    )
    # Confirming changes NO thread, reading, or branch state.
    thread_before = store.get_thread(USER, thread.id).to_dict()
    readings_before = [
        r.to_dict() for r in store.readings_for(USER, thread.id)
    ]
    decided = review_mod.apply_verdict(
        store, USER, f"oversight:{proposal.id}", "accepted"
    )
    assert decided.status == "confirmed"
    assert store.get_thread(USER, thread.id).to_dict() == thread_before
    assert [
        r.to_dict() for r in store.readings_for(USER, thread.id)
    ] == readings_before
    # Rejecting a fresh proposal dismisses the observation only.
    thread2 = _thread(store, "active", "Second ledger", [CLAIM_B])
    _backdate(store, tmp_path, thread2.id, OLD)
    (proposal2,) = [
        p for p in ovs_mod.detect_oversight(store, USER, now=NOW)
        if p.thread_id == thread2.id and p.kind == "stall"
    ]
    decided2 = review_mod.apply_verdict(
        store, USER, f"oversight:{proposal2.id}", "rejected"
    )
    assert decided2.status == "dismissed"


# -- P7-E: state revision (I3) ------------------------------------------------


def test_reconsideration_candidate_without_mutation(store):
    thread, reading = _standing_thread(
        store, "Loft ledger", CLAIM_A, "mentor", "patience developing"
    )
    before = None
    for row in store.readings_for(USER, thread.id):
        if row.id == reading.id:
            before = row.to_dict()
    assert before is not None and before["status"] == "accepted"

    cand = sched_mod.propose_reconsideration(
        store, USER, reading.id, "does this reading still fit?"
    )
    assert cand.status == "proposed"
    # The reading row is byte-identical: still accepted, same
    # content, same evidence refs.
    after = None
    for row in store.readings_for(USER, thread.id):
        if row.id == reading.id:
            after = row.to_dict()
    assert after == before
    # Dedupe: a second proposal while proposed returns the same.
    cand2 = sched_mod.propose_reconsideration(store, USER, reading.id)
    assert cand2.id == cand.id
    # Surfaces in review; verdict affirms the candidacy, and
    # the reading is STILL untouched.
    items = review_mod.pending_review_items(store, USER)
    assert any(
        item.item_kind == "reconsideration"
        and item.item_id.endswith(cand.id)
        for item in items
    )
    decided = review_mod.apply_verdict(
        store, USER, f"reconsideration:{cand.id}", "accepted"
    )
    assert decided.status == "affirmed"
    final = None
    for row in store.readings_for(USER, thread.id):
        if row.id == reading.id:
            final = row.to_dict()
    assert final == before

    # A second reading's candidacy can be dismissed instead.
    thread2, reading2 = _standing_thread(
        store, "Harbor notes", CLAIM_B, "mentor", "steady course"
    )
    cand_b = sched_mod.propose_reconsideration(store, USER, reading2.id)
    decided_b = review_mod.apply_verdict(
        store, USER, f"reconsideration:{cand_b.id}", "rejected"
    )
    assert decided_b.status == "dismissed"
    # Non-accepted readings cannot gain candidacy.
    proposed = store.propose_reading(
        USER, thread2.id, author="mentor",
        reading={"tensions": ["new"], "open_questions": [],
                 "milestones": []},
        evidence_refs=[CLAIM_B],
    )
    with pytest.raises(ValueError):
        sched_mod.propose_reconsideration(store, USER, proposed.id)


# -- P7-F: dual-axis resolution (I4) ------------------------------------------


def _no_resolved_key(obj):
    if isinstance(obj, dict):
        assert "resolved" not in obj
        for value in obj.values():
            _no_resolved_key(value)
    elif isinstance(obj, list):
        for value in obj:
            _no_resolved_key(value)


def test_dual_axis_visible_in_thread_status(store):
    thread, reading = _standing_thread(
        store, "Loft ledger", CLAIM_A, "mentor", "patience developing"
    )
    display = sched_mod.thread_status_display(store, USER, thread.id)
    # Both axes present, no single resolved bit anywhere.
    assert display["developmental"]["status"] == "active"
    assert display["epistemic"]["standing_reading"]["id"] == reading.id
    assert display["epistemic"]["standing_reading"]["status"] == "accepted"
    _no_resolved_key(display)
    # Lens comes only from the accepted fitting: none yet.
    assert display["epistemic"]["lens"] is None
    # Accept a fitting: the lens appears; a draft's claimed lens
    # never counts (resolution uses the accepted fitting only).
    fitting = store.set_fitting(
        USER, thread.id, lens_id="descent_and_return",
        evidence_refs=[CLAIM_A], proposed_by="steward",
    )
    store.set_fitting_status(USER, fitting.id, "accepted")
    display2 = sched_mod.thread_status_display(store, USER, thread.id)
    assert display2["epistemic"]["lens"]["lens_id"] == "descent_and_return"
    # Reconsideration candidacies list separately, never as a
    # revision of the reading itself.
    cand = sched_mod.propose_reconsideration(store, USER, reading.id)
    display3 = sched_mod.thread_status_display(store, USER, thread.id)
    assert [r["id"] for r in display3["reconsiderations"]] == [cand.id]
    assert display3["epistemic"]["standing_reading"]["status"] == "accepted"


# -- P7-G: correspondence (§3) -------------------------------------------------


def _two_threads_with_evidence(store):
    t1, _r1 = _standing_thread(store, "Loft ledger", CLAIM_A, "mentor", "one")
    t2, _r2 = _standing_thread(
        store, "Harbor notes", CLAIM_B, "champion", "two"
    )
    return t1, t2


def test_correspondence_adopt_translate_decline_same_item(store):
    t1, t2 = _two_threads_with_evidence(store)
    ev1 = _evidence_ids(store, t1.id)[0]
    ev2 = _evidence_ids(store, t2.id)[0]
    outcome = corr_mod.propose_correspondence(
        store, USER,
        evidence_refs=[ev1, ev2],
        structural_tension="patience vs avoidance",
        proposed_relationship="restraint that is simultaneously "
        "protective and limiting",
        candidate_metaphor="Odysseus bound to the mast",
        mapping={"patience": "the ropes", "avoidance": "the mast"},
        limitations="the myth does not say whether the restraint "
        "is wisdom or fear",
    )
    assert outcome.abstained is False
    corr = outcome.correspondence
    assert corr is not None and corr.status == "proposed"
    assert corr.id.startswith("corr-")
    assert sorted(corr.thread_ids) == sorted([t1.id, t2.id])

    # Three seats, three responses, same correspondence — and
    # the steward status does NOT move for any of them.
    corr_mod.respond_to_correspondence(
        store, USER, corr.id, "seat:conductor", "adopt"
    )
    with pytest.raises(ValueError):
        # Translate without the seat's own imagery is refused.
        corr_mod.respond_to_correspondence(
            store, USER, corr.id, "seat:ambassador", "translate"
        )
    corr_mod.respond_to_correspondence(
        store, USER, corr.id, "seat:ambassador", "translate",
        expression="time signatures binding freedom to form",
    )
    corr_mod.respond_to_correspondence(
        store, USER, corr.id, "seat:skeptic", "decline",
        expression="not a useful parallel here",
    )
    responses = store.responses_for(USER, corr.id)
    assert {r.branch_id: r.response for r in responses} == {
        "seat:conductor": "adopt",
        "seat:ambassador": "translate",
        "seat:skeptic": "decline",
    }
    assert store.get_correspondence(USER, corr.id).status == "proposed"

    # Only the user verdict moves the status — and the seat
    # responses survive it unchanged.
    decided = review_mod.apply_verdict(
        store, USER, f"correspondence:{corr.id}", "accepted"
    )
    assert decided.status == "user_accepted"
    assert store.get_correspondence(USER, corr.id).status == "user_accepted"
    assert {r.branch_id: r.response for r in store.responses_for(USER, corr.id)} == {
        "seat:conductor": "adopt",
        "seat:ambassador": "translate",
        "seat:skeptic": "decline",
    }


def test_correspondence_abstention_is_complete(store):
    t1, _r1 = _standing_thread(store, "Loft ledger", CLAIM_A, "mentor", "one")
    ev1 = _evidence_ids(store, t1.id)[0]
    # Fewer than two refs: abstain, write nothing.
    out = corr_mod.propose_correspondence(
        store, USER, evidence_refs=[ev1],
        structural_tension="x", proposed_relationship="y",
        limitations="z",
    )
    assert out.abstained is True and out.correspondence is None
    # Single-thread refs: abstain, write nothing.
    ev1b = store.add_evidence(USER, t1.id, EVENT_A).id
    out2 = corr_mod.propose_correspondence(
        store, USER, evidence_refs=[ev1, ev1b],
        structural_tension="x", proposed_relationship="y",
        limitations="z",
    )
    assert out2.abstained is True and out2.correspondence is None
    # No limitations: abstain — an analogy without a breakdown
    # risks imposing meaning.
    t2, _r2 = _standing_thread(store, "Harbor notes", CLAIM_B, "champion", "two")
    ev2 = _evidence_ids(store, t2.id)[0]
    out3 = corr_mod.propose_correspondence(
        store, USER, evidence_refs=[ev1, ev2],
        structural_tension="x", proposed_relationship="y",
        limitations="",
    )
    assert out3.abstained is True and out3.correspondence is None
    assert store.correspondences_for(USER) == []
    # Unresolvable refs are a caller error, not an abstention.
    with pytest.raises(ValueError):
        corr_mod.propose_correspondence(
            store, USER, evidence_refs=[ev1, "no-such-evidence"],
            structural_tension="x", proposed_relationship="y",
            limitations="z",
        )


def test_correspondence_never_evidence_and_no_auto_chain(store):
    t1, t2 = _two_threads_with_evidence(store)
    ev1 = _evidence_ids(store, t1.id)[0]
    ev2 = _evidence_ids(store, t2.id)[0]
    outcome = corr_mod.propose_correspondence(
        store, USER, evidence_refs=[ev1, ev2],
        structural_tension="patience vs avoidance",
        proposed_relationship="restraint protective and limiting",
        limitations="does not say whether wisdom or fear",
    )
    corr = outcome.correspondence
    assert corr is not None
    # A reading cannot cite a correspondence id: the attach
    # path only resolves thread_evidence row ids.
    with pytest.raises(ValueError):
        store.propose_reading(
            USER, t1.id, author="steward",
            reading={"tensions": ["x"], "open_questions": [],
                     "milestones": []},
            evidence_refs=[corr.id],
        )
    # No evidence row is, or cites, a correspondence.
    for tid in (t1.id, t2.id):
        for row in store.evidence_for(USER, tid):
            assert not row.id.startswith("corr-")
    # Discovery runs and proposes — and creates zero
    # correspondences: no auto-chaining, ever.
    result = discover(store, USER)
    discover_propose(store, USER, result.candidates)
    assert store.correspondences_for(USER) == [corr]


# -- P7-H: rollout criteria, flag-gated, thresholds unset ---------------------


def test_rollout_thresholds_unset_and_gate_closed(store):
    assert rollout_mod.ROLLOUT_THRESHOLDS is None
    # Even perfect inputs cannot open the gate while unset.
    assert rollout_mod.default_change_permitted(
        precision=1.0, coverage=1.0
    ) is False
    status = rollout_mod.rollout_status(store, USER)
    assert status["thresholds"] is None
    assert status["default_change_allowed"] is False
    assert "thresholds_unset" in status["reason"]
    # Precision still reports, and now covers the new kinds.
    assert status["precision"]["precision"] is None  # no verdicts yet
    assert status["verdict_coverage"]["coverage"] is None


def test_rollout_precision_covers_new_kinds(store):
    t1, t2 = _two_threads_with_evidence(store)
    ev1 = _evidence_ids(store, t1.id)[0]
    ev2 = _evidence_ids(store, t2.id)[0]
    outcome = corr_mod.propose_correspondence(
        store, USER, evidence_refs=[ev1, ev2],
        structural_tension="patience vs avoidance",
        proposed_relationship="restraint protective and limiting",
        limitations="does not say whether wisdom or fear",
    )
    corr = outcome.correspondence
    assert corr is not None
    review_mod.apply_verdict(
        store, USER, f"correspondence:{corr.id}", "accepted"
    )
    precision = store.proposal_precision(USER)
    assert precision["per_kind"]["correspondence"]["accepted"] == 1
    assert precision["per_kind"]["correspondence"]["decided"] == 1
    assert precision["overall"]["accepted"] == 1


# -- P7-I: no flips, no subsumption, no prompt changes ------------------------


def test_no_default_flips_and_sibling_cannot_respond(store):
    empty_conn = _perm_conn({})
    assert steward_consent_allowed(USER, connection=empty_conn) is False
    assert steward_coordination_allowed(USER, connection=empty_conn) is False
    assert coordination_allowed(USER, connection=empty_conn) is False
    # The sibling record and the deferred branch are not
    # confirmed branches and cannot respond to correspondence.
    t1, t2 = _two_threads_with_evidence(store)
    ev1 = _evidence_ids(store, t1.id)[0]
    ev2 = _evidence_ids(store, t2.id)[0]
    outcome = corr_mod.propose_correspondence(
        store, USER, evidence_refs=[ev1, ev2],
        structural_tension="patience vs avoidance",
        proposed_relationship="restraint protective and limiting",
        limitations="does not say whether wisdom or fear",
    )
    corr = outcome.correspondence
    assert corr is not None
    with pytest.raises(ValueError):
        corr_mod.respond_to_correspondence(
            store, USER, corr.id, "build_council", "adopt"
        )
    with pytest.raises(ValueError):
        corr_mod.respond_to_correspondence(
            store, USER, corr.id, "garden", "adopt"
        )
    with pytest.raises(ValueError):
        corr_mod.respond_to_correspondence(
            store, USER, corr.id, "today", "adopt"
        )
