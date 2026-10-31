"""Narrative Steward Phase 1 — review wiring + branch contract.

Covers the addendum §4 acceptance criteria, fixture-tested (no seat
wiring, no foreground generation anywhere on the coordination path):

- D1: steward proposals appear as review items (births/fittings/
  readings as queue cards, changes as thread notes) and transition
  store state on verdict; non-proposals never appear; decided items
  never reappear; unresolved is recorded without transitioning.
- D2: the branch registry lists every §1 branch with status, and
  coordination capability is contracted — never assumed.
- D3: coordination consent requires BOTH default-off flags, each
  fail-closed.
- D4: relevance is a deterministic, inspectable step — never a stub
  forwarding every event.
- D5: context availability requires consent + relevance re-validated
  at preparation time; unavailable preparations leak no content;
  availability is not delivery (no generation on the path).
- D6: discrepancy flags preserve the assessment and change nothing;
  declining context writes nothing.
- D7: proposal precision counts review verdicts only, so it cannot
  reward convergence.
- D8: boundary fixtures — read-plus-emit-only and indiscriminate
  fan-out both fail availability.
- Routes: the /steward/review verdict surface (list + accept /
  reject / unresolve), with steward_routes' auth discipline.
"""

from __future__ import annotations

import inspect
import json
import sqlite3

import pytest

from local_ai.narrative import NarrativeStore
from local_ai.narrative.branches import (
    BRANCHES,
    READING_SURFACES,
    branch_registry,
    coordination_capable_branches,
    get_branch,
)
from local_ai.narrative.consent import (
    coordination_allowed,
    steward_consent_allowed,
    steward_coordination_allowed,
)
from local_ai.narrative.coordination import (
    prepare_context,
    record_discrepancy_flag,
)
from local_ai.narrative.refs import SourceRef
from local_ai.narrative.relevance import assess_relevance
from local_ai.narrative.review import (
    apply_verdict,
    pending_review_items,
)

USER = "user-1"
OTHER = "user-2"

CLAIM_REF = SourceRef(kind="claim", ref_id="claim-9", evidence_kind="quote")
EVENT_REF = SourceRef(kind="event", ref_id="evt-8", evidence_kind="entity_ref")


@pytest.fixture()
def store(tmp_path):
    return NarrativeStore(db_path=tmp_path / "narrative.db")


def _perm_conn(tmp_path, flags_by_user):
    # Fresh in-memory DB per call: several tests build multiple
    # permission states within one tmp_path.
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


def _set_flags(conn, user_id, flags):
    conn.execute(
        "UPDATE user_permissions_settings SET permissions_json = ? "
        "WHERE user_id = ?",
        (json.dumps(flags), user_id),
    )
    conn.commit()


def _proposal_fixture(store, user=USER):
    """One of each proposal kind, plus the non-proposals that must
    never appear as review items."""
    thread = store.create_thread(
        user,
        origin="steward_proposal",
        title="A thread the steward proposed",
        evidence_refs=(CLAIM_REF,),
    )
    user_thread = store.create_thread(
        user, origin="user_declared", title="A thread the user declared"
    )
    reading = store.propose_reading(
        user,
        thread.id,
        author="steward",
        reading={"tensions": ["patience versus avoidance"]},
        evidence_refs=(CLAIM_REF,),
    )
    store.propose_reading(
        user,
        thread.id,
        author="mentor",
        reading={"tensions": ["growth"]},
        evidence_refs=(CLAIM_REF,),
    )
    change = store.record_change(
        user, thread.id, kind="milestone", evidence_refs=(EVENT_REF,)
    )
    fitting = store.set_fitting(
        user,
        thread.id,
        lens_id="departure_initiation_return",
        evidence_refs=(CLAIM_REF,),
        proposed_by="steward",
    )
    store.set_fitting(
        user,
        thread.id,
        lens_id="descent_and_return",
        evidence_refs=(CLAIM_REF,),
        proposed_by="user",
    )
    return {
        "thread": thread,
        "user_thread": user_thread,
        "reading": reading,
        "change": change,
        "fitting": fitting,
    }


# -- D1: review items + verdicts --------------------------------------------


def test_pending_items_cover_all_four_kinds_with_surfaces(store):
    fx = _proposal_fixture(store)
    items = pending_review_items(store, USER)
    by_kind = {item.item_kind: item for item in items}
    assert set(by_kind) == {"birth", "reading", "change", "fitting"}
    assert by_kind["birth"].item_id == f"birth:{fx['thread'].id}"
    assert by_kind["birth"].surface == "queue_card"
    assert by_kind["reading"].surface == "queue_card"
    assert by_kind["fitting"].surface == "queue_card"
    assert by_kind["change"].surface == "thread_note"
    # Non-proposals never appear.
    ids = {item.item_id for item in items}
    assert f"birth:{fx['user_thread'].id}" not in ids
    assert len([i for i in items if i.item_kind == "reading"]) == 1
    assert len([i for i in items if i.item_kind == "fitting"]) == 1


def test_verdicts_transition_state_and_leave_pending(store):
    fx = _proposal_fixture(store)
    out = apply_verdict(store, USER, f"birth:{fx['thread'].id}", "accepted")
    assert out.status == "active"
    assert store.get_thread(USER, fx["thread"].id).status == "active"
    out = apply_verdict(store, USER, f"reading:{fx['reading'].id}", "accepted")
    assert out.status == "accepted"
    out = apply_verdict(store, USER, f"change:{fx['change'].id}", "accepted")
    assert out.status == "confirmed"
    out = apply_verdict(store, USER, f"fitting:{fx['fitting'].id}", "rejected")
    assert out.status == "rejected"
    assert pending_review_items(store, USER) == []
    # Verdicts are logged.
    assert len(store.verdicts_for(USER)) == 4


def test_reject_birth_archives_and_is_terminal(store):
    fx = _proposal_fixture(store)
    out = apply_verdict(store, USER, f"birth:{fx['thread'].id}", "rejected")
    assert out.status == "archived"
    assert store.get_thread(USER, fx["thread"].id).status == "archived"
    with pytest.raises(ValueError, match="no pending review item"):
        apply_verdict(store, USER, f"birth:{fx['thread'].id}", "accepted")


def test_unresolved_records_without_transitioning(store):
    fx = _proposal_fixture(store)
    out = apply_verdict(store, USER, f"change:{fx['change'].id}", "unresolved")
    assert out.status == "proposed"  # unchanged, still pending
    assert store.changes_for(USER, fx["thread"].id)[0].status == "proposed"
    verdicts = store.verdicts_for(USER)
    assert len(verdicts) == 1 and verdicts[0].verdict == "unresolved"
    # Still pending afterwards: not deciding is not deciding.
    assert any(
        item.item_id == f"change:{fx['change'].id}"
        for item in pending_review_items(store, USER)
    )


def test_verdict_errors(store):
    fx = _proposal_fixture(store)
    with pytest.raises(ValueError, match="unknown review verdict"):
        apply_verdict(store, USER, f"birth:{fx['thread'].id}", "maybe")
    with pytest.raises(ValueError, match="unknown review item"):
        apply_verdict(store, USER, "bogus:xyz", "accepted")
    with pytest.raises(ValueError, match="no pending review item"):
        apply_verdict(store, USER, "birth:nope", "accepted")
    # Cross-user items are invisible, not merely forbidden.
    with pytest.raises(ValueError, match="no pending review item"):
        apply_verdict(store, OTHER, f"birth:{fx['thread'].id}", "accepted")


# -- D2: branch registry ------------------------------------------------------


def test_registry_lists_every_section1_branch_with_status():
    registry = branch_registry()
    assert len(registry) == len(BRANCHES) == 11
    seats = [c for c in BRANCHES if c.kind == "seat"]
    assert len(seats) == 7
    assert all(c.status == "confirmed" for c in seats)
    assert all("coordination" in c.capabilities for c in seats)
    assert registry["seat:conductor"].display_name == "Weaver"
    assert registry["seat:mentor"].display_name == "Gardener"
    vision = registry["vision_execution"]
    assert vision.status == "confirmed" and vision.kind == "progression"
    journal = registry["journal"]
    assert journal.tier_constraint == "Tier-D only"
    council = registry["build_council"]
    assert council.status == "candidate"
    assert "coordination" not in council.capabilities
    garden = registry["garden"]
    assert garden.status == "candidate" and garden.capabilities == ()
    # Reading surfaces are not branches.
    assert "today" not in registry and "review" not in registry
    assert len(READING_SURFACES) == 2
    assert get_branch("nope") is None
    assert all(
        c.branch_id in {b.branch_id for b in coordination_capable_branches()}
        for c in seats
    )
    assert "build_council" not in {
        b.branch_id for b in coordination_capable_branches()
    }


# -- D3: coordination consent -------------------------------------------------


def test_coordination_flag_mirrors_derivation_fail_closed(tmp_path):
    conn = _perm_conn(
        tmp_path,
        {
            "u-on": {"steward_coordination": True},
            "u-off": {"steward_coordination": False},
            "u-bad": {"steward_coordination": "yes"},
        },
    )
    assert steward_coordination_allowed("u-on", connection=conn) is True
    assert steward_coordination_allowed("u-off", connection=conn) is False
    assert steward_coordination_allowed("ghost", connection=conn) is False
    assert steward_coordination_allowed("u-bad", connection=conn) is False
    _set_flags(conn, "u-on", {"steward_coordination": True})
    conn.execute(
        "UPDATE user_permissions_settings SET permissions_json = 'not-json' "
        "WHERE user_id = 'u-on'"
    )
    conn.commit()
    assert steward_coordination_allowed("u-on", connection=conn) is False


def test_coordination_requires_both_flags(tmp_path):
    both = _perm_conn(
        tmp_path,
        {"u": {"steward_derivation": True, "steward_coordination": True}},
    )
    assert coordination_allowed("u", connection=both) is True
    deriv_only = _perm_conn(
        tmp_path,
        {"u": {"steward_derivation": True, "steward_coordination": False}},
    )
    assert coordination_allowed("u", connection=deriv_only) is False
    coord_only = _perm_conn(
        tmp_path,
        {"u": {"steward_derivation": False, "steward_coordination": True}},
    )
    assert coordination_allowed("u", connection=coord_only) is False
    # Existing derivation semantics untouched.
    assert steward_consent_allowed("u", connection=both) is True
    assert steward_consent_allowed("u", connection=coord_only) is False


# -- D4: relevance ------------------------------------------------------------


def test_relevance_shared_entity_ref():
    result = assess_relevance(
        "seat:conductor",
        candidate_entity_refs=("task-7",),
        attended_entity_refs=("task-7", "task-9"),
    )
    assert result.relevant is True
    assert result.reasons == ("shared_entity_ref",)
    assert result.inputs["shared_entity_refs"] == ["task-7"]


def test_relevance_attended_thread():
    result = assess_relevance(
        "seat:conductor",
        candidate_thread_id="thr-1",
        attended_thread_ids=("thr-1",),
    )
    assert result.relevant is True
    assert "shared_entity_ref" in result.reasons


def test_relevance_focus_term_overlap():
    result = assess_relevance(
        "seat:mentor",
        candidate_text="cultivation and maturation take another season",
    )
    assert result.relevant is True
    assert "focus_term_overlap" in result.reasons
    assert result.inputs["focus_overlap_count"] >= 2


def test_relevance_strand_alignment():
    from local_ai.narrative.relevance import seat_strand_weights

    weights = seat_strand_weights("mentor")
    assert weights, "mentor must carry a strand vector for this fixture"
    result = assess_relevance(
        "seat:mentor", candidate_strand_weights=dict(weights)
    )
    assert result.relevant is True
    assert "strand_alignment" in result.reasons
    assert result.inputs["strand_similarity"] == pytest.approx(1.0)


def test_relevance_unestablished_is_complete_not_failure():
    result = assess_relevance(
        "seat:conductor",
        candidate_text="unrelated weather notes",
        candidate_entity_refs=("evt-zzz",),
        attended_entity_refs=("task-1",),
    )
    assert result.relevant is False
    assert result.reasons == ()
    with pytest.raises(ValueError, match="unknown branch"):
        assess_relevance("seat:nope", candidate_text="anything")


# -- D5: context availability --------------------------------------------------


def _both_on_conn(tmp_path):
    return _perm_conn(
        tmp_path,
        {USER: {"steward_derivation": True, "steward_coordination": True}},
    )


def test_availability_consent_closed_writes_no_assessment(store, tmp_path):
    fx = _proposal_fixture(store)
    conn = _perm_conn(
        tmp_path,
        {USER: {"steward_derivation": True, "steward_coordination": False}},
    )
    out = prepare_context(
        store,
        USER,
        "seat:conductor",
        thread_id=fx["thread"].id,
        attended_thread_ids=(fx["thread"].id,),
        connection=conn,
    )
    assert out.available is False
    assert out.reason == "consent_closed"
    assert out.context is None
    assert out.assessment is None
    assert store.assessments_for(USER) == []


def test_availability_relevance_unestablished_leaks_nothing(store, tmp_path):
    fx = _proposal_fixture(store)
    out = prepare_context(
        store,
        USER,
        "seat:conductor",
        thread_id=fx["thread"].id,
        candidate_text="unrelated weather notes",
        connection=_both_on_conn(tmp_path),
    )
    assert out.available is False
    assert out.reason == "relevance_not_established"
    assert out.context is None
    assert out.assessment is not None and out.assessment.relevant is False


def test_availability_success_returns_bounded_summary(store, tmp_path):
    fx = _proposal_fixture(store)
    out = prepare_context(
        store,
        USER,
        "seat:conductor",
        thread_id=fx["thread"].id,
        attended_thread_ids=(fx["thread"].id,),
        connection=_both_on_conn(tmp_path),
    )
    assert out.available is True
    assert out.reason == "available"
    assert out.context["thread_id"] == fx["thread"].id
    assert out.context["title"] == "A thread the steward proposed"
    # Bounded summary only: no reading content in a Phase 1 payload.
    assert "reading" not in out.context
    assert out.assessment is not None and out.assessment.relevant is True


def test_availability_revalidates_after_revocation(store, tmp_path):
    fx = _proposal_fixture(store)
    conn = _both_on_conn(tmp_path)
    first = prepare_context(
        store,
        USER,
        "seat:conductor",
        thread_id=fx["thread"].id,
        attended_thread_ids=(fx["thread"].id,),
        connection=conn,
    )
    assert first.available is True
    _set_flags(
        conn, USER, {"steward_derivation": True, "steward_coordination": False}
    )
    second = prepare_context(
        store,
        USER,
        "seat:conductor",
        thread_id=fx["thread"].id,
        attended_thread_ids=(fx["thread"].id,),
        connection=conn,
    )
    assert second.available is False
    assert second.reason == "consent_closed"
    # The prior available assessment still exists — and is ignored.
    assert len(store.assessments_for(USER)) == 1


def test_availability_rejects_uncontracted_branch_and_missing_thread(
    store, tmp_path
):
    fx = _proposal_fixture(store)
    conn = _both_on_conn(tmp_path)
    out = prepare_context(
        store, USER, "build_council", connection=conn
    )
    assert out.available is False
    assert out.reason == "branch_not_coordination_contracted"
    out = prepare_context(
        store,
        USER,
        "seat:conductor",
        thread_id="thr-missing",
        attended_thread_ids=("thr-missing",),
        connection=conn,
    )
    assert out.available is False
    assert out.reason == "thread_not_found"
    assert out.context is None
    with pytest.raises(ValueError, match="unknown branch"):
        prepare_context(store, USER, "seat:nope", connection=conn)


def test_availability_path_takes_no_generation():
    params = inspect.signature(prepare_context).parameters
    assert not any("generat" in name for name in params)


# -- D6: discrepancy flags + decline -------------------------------------------


def test_flag_preserves_assessment_and_changes_nothing(store, tmp_path):
    fx = _proposal_fixture(store)
    out = prepare_context(
        store,
        USER,
        "seat:conductor",
        thread_id=fx["thread"].id,
        attended_thread_ids=(fx["thread"].id,),
        connection=_both_on_conn(tmp_path),
    )
    assert out.assessment is not None
    evidence_before = len(store.evidence_for(USER, fx["thread"].id))
    flag = record_discrepancy_flag(
        store,
        USER,
        out.assessment.id,
        "seat:skeptic",
        objection="recurrence looks coincidental",
        evidence_refs=("evt-8",),
    )
    assert flag.status == "open"
    assert flag.assessment_id == out.assessment.id
    assert flag.objection == "recurrence looks coincidental"
    # Original assessment untouched; evidence untouched.
    stored = store.assessments_for(USER, branch_id="seat:conductor")[0]
    assert stored.id == out.assessment.id
    assert stored.relevant is True and stored.reasons == out.assessment.reasons
    assert len(store.evidence_for(USER, fx["thread"].id)) == evidence_before
    assert store.flags_for(USER, assessment_id=out.assessment.id) == [flag]


def test_flag_requires_existing_own_assessment(store, tmp_path):
    with pytest.raises(ValueError, match="unknown relevance assessment"):
        record_discrepancy_flag(store, USER, "asm-nope", "seat:skeptic")
    fx = _proposal_fixture(store)
    out = prepare_context(
        store,
        USER,
        "seat:conductor",
        thread_id=fx["thread"].id,
        attended_thread_ids=(fx["thread"].id,),
        connection=_both_on_conn(tmp_path),
    )
    with pytest.raises(ValueError, match="unknown relevance assessment"):
        record_discrepancy_flag(store, OTHER, out.assessment.id, "seat:skeptic")


def test_decline_writes_no_flag_no_verdict_no_record(store, tmp_path):
    fx = _proposal_fixture(store)
    out = prepare_context(
        store,
        USER,
        "seat:conductor",
        thread_id=fx["thread"].id,
        attended_thread_ids=(fx["thread"].id,),
        connection=_both_on_conn(tmp_path),
    )
    assert out.available is True
    # Decline = not retrieving / not using. Nothing is called here,
    # and nothing may appear: no flag, no verdict, no extra row.
    assert store.flags_for(USER) == []
    assert store.verdicts_for(USER) == []
    assert len(store.assessments_for(USER)) == 1  # only the preparation


# -- D7: proposal precision -----------------------------------------------------


def test_precision_counts_verdicts_only(store):
    assert store.proposal_precision(USER)["overall"]["precision"] is None
    fx = _proposal_fixture(store)
    apply_verdict(store, USER, f"birth:{fx['thread'].id}", "accepted")
    apply_verdict(store, USER, f"reading:{fx['reading'].id}", "rejected")
    apply_verdict(store, USER, f"change:{fx['change'].id}", "unresolved")
    precision = store.proposal_precision(USER)
    assert precision["per_kind"]["birth"] == {
        "accepted": 1,
        "rejected": 0,
        "decided": 1,
        "precision": 1.0,
    }
    assert precision["per_kind"]["reading"]["precision"] == 0.0
    # Unresolved is recorded but excluded from numerator and denominator.
    assert precision["per_kind"]["change"]["decided"] == 0
    assert precision["per_kind"]["change"]["precision"] is None
    assert precision["overall"] == {
        "accepted": 1,
        "rejected": 1,
        "decided": 2,
        "precision": 0.5,
    }


def test_precision_ignores_flags_and_direct_transitions(store, tmp_path):
    fx = _proposal_fixture(store)
    apply_verdict(store, USER, f"birth:{fx['thread'].id}", "accepted")
    before = store.proposal_precision(USER)
    # A flag is not a verdict and cannot move precision.
    out = prepare_context(
        store,
        USER,
        "seat:conductor",
        thread_id=fx["thread"].id,
        attended_thread_ids=(fx["thread"].id,),
        connection=_both_on_conn(tmp_path),
    )
    record_discrepancy_flag(
        store, USER, out.assessment.id, "seat:skeptic", objection="coincidence?"
    )
    assert store.proposal_precision(USER) == before
    # A direct store transition bypassing review is not a verdict either.
    store.set_thread_status(USER, fx["thread"].id, "dormant")
    assert store.proposal_precision(USER) == before


# -- D8: boundary fixtures -------------------------------------------------------


def test_read_plus_emit_only_contract_cannot_coordinate(store, tmp_path):
    # A branch contracted for observation + interpretation but NOT
    # coordination must never receive availability — that contract
    # shape fails Phase 1 acceptance by construction.
    out = prepare_context(
        store, USER, "build_council", connection=_both_on_conn(tmp_path)
    )
    assert out.available is False
    assert out.reason == "branch_not_coordination_contracted"


def test_indiscriminate_fanout_fails_without_relevance(store, tmp_path):
    # Both flags on, zero relationship to anything attended: an
    # event-driven fan-out would deliver; the contract refuses.
    fx = _proposal_fixture(store)
    out = prepare_context(
        store,
        USER,
        "seat:conductor",
        thread_id=fx["thread"].id,
        candidate_text="unrelated weather notes",
        candidate_entity_refs=("evt-zzz",),
        attended_entity_refs=(),
        attended_thread_ids=(),
        connection=_both_on_conn(tmp_path),
    )
    assert out.available is False
    assert out.reason == "relevance_not_established"


# -- Routes ----------------------------------------------------------------------


def _route_client(store, tmp_path, user=USER):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    import api.routes.steward_review_routes as review_routes
    from api.routes.auth_routes import get_current_user

    app = FastAPI()
    app.include_router(review_routes.router)
    app.dependency_overrides[get_current_user] = lambda: {"id": user}
    client = TestClient(app, raise_server_exceptions=False)
    return client, review_routes, tmp_path


def test_review_routes_list_verdict_precision(tmp_path, monkeypatch):
    store = NarrativeStore(db_path=tmp_path / "narrative.db")
    fx = _proposal_fixture(store)
    client, review_routes, _ = _route_client(store, tmp_path)
    monkeypatch.setattr(
        review_routes,
        "get_narrative_store",
        lambda: NarrativeStore(db_path=tmp_path / "narrative.db"),
    )
    resp = client.get("/steward/review")
    assert resp.status_code == 200
    body = resp.json()
    kinds = {item["item_kind"] for item in body["items"]}
    assert kinds == {"birth", "reading", "change", "fitting"}
    assert body["precision"]["overall"]["precision"] is None
    resp = client.post(f"/steward/review/birth/{fx['thread'].id}/accept")
    assert resp.status_code == 200
    assert resp.json()["status"] == "active"
    resp = client.get("/steward/review")
    kinds = {item["item_kind"] for item in resp.json()["items"]}
    assert "birth" not in kinds
    assert resp.json()["precision"]["overall"]["precision"] == 1.0
    # 404: unknown id and cross-user id are identical.
    mine_404 = client.post("/steward/review/birth/nope/reject")
    assert mine_404.status_code == 404
    other = _proposal_fixture(store, OTHER)
    cross = client.post(f"/steward/review/birth/{other['thread'].id}/reject")
    assert cross.status_code == 404
    assert cross.json() == mine_404.json()
    # 400: unknown kind.
    assert client.post("/steward/review/bogus/x/accept").status_code == 400
    # Unresolve keeps the item pending.
    resp = client.post(f"/steward/review/change/{fx['change'].id}/unresolve")
    assert resp.status_code == 200
    assert resp.json()["status"] == "proposed"
    assert any(
        item["item_kind"] == "change"
        for item in client.get("/steward/review").json()["items"]
    )


# -- Non-foreclosure: point-in-time preservation + deletion (Phase 1) ------
# No snapshot capture and no abstention storage are implemented here.
# What is tested is that the contracts do not foreclose them, and
# that deletion is enforceable across Phase 1's own derived records:
# verdict rows follow their items, assessments and flags follow
# their threads, and consent is re-validated per call (no stored
# record grants future access — covered by the D3/D5 tests).


def _verdicted_thread(store, user=USER):
    """A steward-proposal thread with a verdict on every item kind."""
    fx = _proposal_fixture(store, user)
    apply_verdict(store, user, f"birth:{fx['thread'].id}", "accepted")
    apply_verdict(store, user, f"reading:{fx['reading'].id}", "accepted")
    apply_verdict(store, user, f"change:{fx['change'].id}", "accepted")
    apply_verdict(store, user, f"fitting:{fx['fitting'].id}", "accepted")
    return fx


def test_delete_thread_cascades_phase1_rows_but_not_other_threads(store):
    fx = _verdicted_thread(store)
    assessment = store.record_relevance_assessment(
        USER, "weaver", thread_id=fx["thread"].id, relevant=True
    )
    store.record_discrepancy_flag(
        USER, assessment.id, "weaver", objection="test objection"
    )
    null_assessment = store.record_relevance_assessment(
        USER, "weaver", relevant=True
    )
    other = _verdicted_thread(store, OTHER)
    assert store.delete_thread(USER, fx["thread"].id) is True
    # Thread-scoped Phase 1 rows are gone with the thread.
    assert store.assessments_for(USER, thread_id=fx["thread"].id) == []
    assert store.flags_for(USER, assessment_id=assessment.id) == []
    assert store.verdicts_for(USER) == []
    # A NULL-thread assessment is not thread-owned: it survives.
    remaining = store.assessments_for(USER)
    assert {a.id for a in remaining} == {null_assessment.id}
    # Another user's thread and its verdicts are untouched.
    assert store.verdicts_for(OTHER) != []
    assert other["thread"].id in {
        t.id for t in store.threads_for(OTHER)
    }


def _preserved_verdict_setup(store):
    """Two user-declared threads: one proposed reading with an
    unresolved verdict, one accepted reading with an accepted
    verdict, plus an assessment + flag on the first thread."""
    proposed_thread = store.create_thread(
        USER, origin="user_declared", title="preserved proposed"
    )
    proposed_reading = store.propose_reading(
        USER,
        proposed_thread.id,
        author="steward",
        reading={"tensions": ["waiting"]},
        evidence_refs=(CLAIM_REF,),
    )
    # Evidence must be attached to the thread for the reading's refs
    # to resolve; propose_reading attaches them (fixture pattern).
    apply_verdict(
        store, USER, f"reading:{proposed_reading.id}", "unresolved"
    )
    verdict_thread = store.create_thread(
        USER, origin="user_declared", title="preserved verdict"
    )
    verdict_reading = store.propose_reading(
        USER,
        verdict_thread.id,
        author="steward",
        reading={"tensions": ["acting"]},
        evidence_refs=(CLAIM_REF,),
    )
    apply_verdict(store, USER, f"reading:{verdict_reading.id}", "accepted")
    assessment = store.record_relevance_assessment(
        USER, "weaver", thread_id=proposed_thread.id, relevant=True
    )
    flag = store.record_discrepancy_flag(
        USER, assessment.id, "weaver", objection="preserved objection"
    )
    return {
        "proposed_thread": proposed_thread,
        "proposed_reading": proposed_reading,
        "verdict_thread": verdict_thread,
        "verdict_reading": verdict_reading,
        "assessment": assessment,
        "flag": flag,
    }


def test_routine_clear_follows_verdict_rows_with_items(store):
    fx = _preserved_verdict_setup(store)
    report = store.clear_user_material(USER, operation="routine_clear")
    assert report["deleted_proposed_reading_count"] == 1
    assert report["deleted_verdict_reading_count"] == 0
    # The proposed reading and its unresolved verdict row are gone.
    assert store.readings_for(USER, fx["proposed_thread"].id) == []
    verdicts = store.verdicts_for(USER)
    assert {v.item_id for v in verdicts} == {fx["verdict_reading"].id}
    # Rule A: the verdict-state reading AND its verdict row survive.
    assert len(store.readings_for(USER, fx["verdict_thread"].id)) == 1
    # Assessments and flags are decision records, not proposal
    # content: they survive routine clear of preserved threads.
    assert store.assessments_for(
        USER, thread_id=fx["proposed_thread"].id
    ) != []
    assert store.flags_for(USER, assessment_id=fx["assessment"].id) != []


def test_full_delete_removes_verdict_rows_for_deleted_readings(store):
    fx = _preserved_verdict_setup(store)
    report = store.clear_user_material(USER, operation="full_delete")
    assert report["deleted_proposed_reading_count"] == 1
    assert report["deleted_verdict_reading_count"] == 1
    assert store.readings_for(USER, fx["proposed_thread"].id) == []
    assert store.readings_for(USER, fx["verdict_thread"].id) == []
    assert store.verdicts_for(USER) == []
