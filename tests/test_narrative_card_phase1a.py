"""Story-First Discovery, Phase 1A — the deterministic core.

Pins the Phase 1 acceptance criteria that Phase 1A owns (plan:
zenaf-story-first-discovery-implementation-plan-2026-11-21.md):

1. An organically revised thread renders predecessor in history,
   successor in the current field — stored status untouched.
2. Pencil context carries the successor's material, never the
   organically superseded predecessor's.
3. Aria's expression substrate excludes organically superseded
   readings from provisional material.
4. A card endorsement is an annotation only: every reading status
   and standing pointer byte-identical, the verdict path
   unreachable from the annotation path.
5. Support classification fixtures for all four classes, with
   uncertainty preserved (absence of cohesion is NOT additional).
6. Currency derivation and the card view are generation-free by
   construction (no generate_fn anywhere in their signatures).
8. Coexistence: verdict standing (legacy readings) and organic
   currency (card readings) operate independently in one store.

Everything here runs with zero model generations: the derivation,
the card view, and the classifier are pure functions over records,
and the store paths exercised are the existing deterministic ones.
"""

from __future__ import annotations

import inspect
import json
import sqlite3

import pytest

from local_ai.narrative import review as steward_review
from local_ai.narrative.card_view import card_for
from local_ai.narrative.currency import (
    classify_support,
    derive_currency,
    support_block,
)
from local_ai.narrative.models import (
    NarrativeThread,
    ThreadChange,
    ThreadEvidence,
    ThreadReading,
)
from local_ai.narrative.refs import SourceRef
from local_ai.narrative.store import NarrativeStore

USER = "user-1"
OTHER = "user-2"

EVENT_REF = SourceRef(kind="event", ref_id="evt-8", evidence_kind="entity_ref")
EVENT_REF_2 = SourceRef(kind="event", ref_id="evt-9", evidence_kind="entity_ref")
EVENT_REF_3 = SourceRef(kind="event", ref_id="evt-10", evidence_kind="entity_ref")
CLAIM_REF = SourceRef(kind="claim", ref_id="claim-9", evidence_kind="quote")
CLAIM_REF_2 = SourceRef(kind="claim", ref_id="claim-10", evidence_kind="quote")
CLAIM_REF_3 = SourceRef(kind="claim", ref_id="claim-11", evidence_kind="quote")


@pytest.fixture()
def store(tmp_path):
    s = NarrativeStore(db_path=tmp_path / "narrative.db")
    yield s
    s.close()


def _organic_revision(store, user=USER):
    """A thread whose v1 is organically superseded by v2.

    Revision runs on the two writes the Rev 6 contract allows —
    propose_reading + a change record naming prior and successor.
    No verdict is involved; both readings keep stored status
    "proposed".
    """
    thread = store.create_thread(
        user, origin="user_declared", title="The long climb",
        evidence_refs=(EVENT_REF,),
    )
    store.set_thread_status(user, thread.id, "active")
    v1 = store.propose_reading(
        user, thread.id, author="steward",
        reading={
            "tensions": ["the old tension"],
            "open_questions": ["the old question"],
            "structure": {"conflicts": ["old conflict"]},
            "distinctions": ["not the old story"],
            "tags": ["old"],
        },
        evidence_refs=(CLAIM_REF,),
    )
    v2 = store.propose_reading(
        user, thread.id, author="steward",
        reading={
            "tensions": ["the new tension"],
            "open_questions": ["the new question"],
            "structure": {"conflicts": ["new conflict"]},
            "distinctions": ["not the new story"],
            "tags": ["new"],
            "support": {
                "duplicate": [],
                "probable_retelling": [],
                "additional": ["ev-extra"],
                "undetermined": [],
            },
        },
        evidence_refs=(CLAIM_REF_2,),
    )
    change = store.record_change(
        user, thread.id, kind="extended",
        evidence_refs=(EVENT_REF_2,),
        prior_reading_id=v1.id, new_reading_id=v2.id,
    )
    return store.get_thread(user, thread.id), v1, v2, change


# -- criterion 1: the card renders organic revision -------------------------


def test_criterion_1_card_places_predecessor_in_history(store):
    thread, v1, v2, _change = _organic_revision(store)
    card = card_for(store, USER, thread.id)

    assert card["thread"] == {
        "id": thread.id, "title": "The long climb", "status": "active",
    }
    assert card["evidence_count"] == 4
    assert [e["id"] for e in card["current_field"]] == [v2.id]
    assert [e["id"] for e in card["history"]] == [v1.id]
    assert card["has_competing"] is False

    # Supersession is derived, never written: stored status is
    # still the verdict-history value, "proposed", for both.
    stored = {r.id: r.status for r in store.readings_for(USER, thread.id)}
    assert stored == {v1.id: "proposed", v2.id: "proposed"}
    assert store.get_thread(USER, thread.id).standing_reading_id is None

    history_entry = card["history"][0]
    assert history_entry["currency"]["placement"] == "history"
    assert "superseded" in history_entry["currency"]["labels"]

    current_entry = card["current_field"][0]
    assert current_entry["currency"]["placement"] == "current"
    assert current_entry["author"] == "steward"
    assert current_entry["status"] == "proposed"
    assert current_entry["structure"] == {"conflicts": ["new conflict"]}
    assert current_entry["distinctions"] == ["not the new story"]
    assert current_entry["tags"] == ["new"]
    assert current_entry["endorsements"] == []


def test_card_for_unknown_thread_raises(store):
    with pytest.raises(ValueError):
        card_for(store, USER, "thr-does-not-exist")
    with pytest.raises(ValueError):
        card_for(store, OTHER, _organic_revision(store)[0].id)


# -- currency derivation units ------------------------------------------------


def _reading(rid, status="proposed", created="2026-11-20T10:00:00+00:00",
             refs=(), payload=None):
    return ThreadReading(
        id=rid, thread_id="thr-x", author="steward",
        reading=payload or {}, evidence_refs=list(refs),
        status=status, created_at=created,
    )


def _change(cid, kind, prior=None, new=None, refs=()):
    return ThreadChange(
        id=cid, thread_id="thr-x", kind=kind, evidence_refs=list(refs),
        prior_reading_id=prior, new_reading_id=new, status="proposed",
        created_at="2026-11-20T11:00:00+00:00",
    )


def _thread(status="active"):
    return NarrativeThread(id="thr-x", user_id=USER, title="T", status=status)


def test_currency_emerging_single_live_reading():
    r = _reading("r1")
    result = derive_currency(_thread(), [r], [])
    assert result["r1"].placement == "current"
    assert result["r1"].labels == ("emerging",)


def test_currency_weakened_by_unresolved_contradiction():
    r = _reading("r1")
    c = _change("c1", "contradicted", prior="r1", new=None, refs=["e2"])
    result = derive_currency(_thread(), [r], [c])
    assert result["r1"].placement == "current"
    assert result["r1"].labels == ("weakened",)


def test_currency_competing_live_readings():
    older = _reading("r1", created="2026-11-20T10:00:00+00:00")
    newer = _reading("r2", created="2026-11-20T12:00:00+00:00")
    result = derive_currency(_thread(), [older, newer], [])
    assert result["r1"].placement == "current"
    assert result["r1"].labels == ("competing",)
    assert result["r2"].placement == "current"
    assert result["r2"].labels == ("competing", "emerging")


def test_currency_stored_terminal_statuses_are_history():
    sup = _reading("r1", status="superseded")
    rej = _reading("r2", status="rejected")
    result = derive_currency(_thread(), [sup, rej], [])
    assert result["r1"].placement == "history"
    assert result["r1"].labels == ("superseded",)
    assert result["r2"].placement == "history"
    assert result["r2"].labels == ("rejected",)


def test_currency_dormant_thread_labels_everything():
    v1 = _reading("r1", refs=["e1"])
    v2 = _reading("r2", created="2026-11-20T12:00:00+00:00")
    c = _change("c1", "extended", prior="r1", new="r2", refs=["e1"])
    result = derive_currency(_thread(status="dormant"), [v1, v2], [c])
    assert result["r1"].placement == "history"
    assert "dormant" in result["r1"].labels
    assert result["r2"].placement == "current"
    assert "dormant" in result["r2"].labels


def test_currency_recurring_from_successor_support_accounting():
    v1 = _reading("r1", refs=["e1"])
    v2 = _reading(
        "r2", created="2026-11-20T12:00:00+00:00",
        payload={"support": {"additional": ["e9"]}},
    )
    c = _change("c1", "extended", prior="r1", new="r2", refs=["e1"])
    result = derive_currency(_thread(), [v1, v2], [c])
    assert result["r1"].placement == "history"
    assert "recurring" in result["r1"].labels
    assert "superseded" in result["r1"].labels


def test_currency_recurring_accounting_is_authoritative_when_present():
    # Accounting present but empty of "additional": NOT recurring,
    # even though the change cites a ref the prior never cited.
    v1 = _reading("r1", refs=["e1"])
    v2 = _reading(
        "r2", created="2026-11-20T12:00:00+00:00",
        payload={"support": {"additional": []}},
    )
    c = _change("c1", "extended", prior="r1", new="r2", refs=["e2"])
    result = derive_currency(_thread(), [v1, v2], [c])
    assert "recurring" not in result["r1"].labels


def test_currency_recurring_fallback_without_accounting():
    v1 = _reading("r1", refs=["e1"])
    v2 = _reading("r2", created="2026-11-20T12:00:00+00:00")
    fresh = _change("c1", "extended", prior="r1", new="r2", refs=["e2"])
    result = derive_currency(_thread(), [v1, v2], [fresh])
    assert "recurring" in result["r1"].labels
    stale = _change("c1", "extended", prior="r1", new="r2", refs=["e1"])
    result = derive_currency(_thread(), [v1, v2], [stale])
    assert "recurring" not in result["r1"].labels


# -- criterion 5: support classification --------------------------------------


def _ev(eid, kind, ref_id, entity=None,
        created="2026-11-20T10:00:00+00:00", note=""):
    return ThreadEvidence(
        id=eid, thread_id="thr-x", ref_kind=kind, ref_id=ref_id,
        evidence_kind="entity_ref", note=note, created_at=created,
        entity_ref=entity,
    )


def test_classifier_duplicate_citation():
    new = _ev("n1", "claim", "c1")
    out = classify_support({("claim", "c1")}, [], [new])
    assert out == {
        "duplicate": ["n1"], "probable_retelling": [],
        "additional": [], "undetermined": [],
    }


def test_classifier_probable_retelling():
    prior = _ev("p1", "event", "e1", entity="person:x")
    new = _ev("n1", "event", "e2", entity="person:x")
    out = classify_support(
        {("event", "e1")}, [prior], [new],
        cohesion_pairs={frozenset(("p1", "n1"))},
    )
    assert out["probable_retelling"] == ["n1"]
    assert out["additional"] == []
    # Tuple pairs normalize the same way.
    out2 = classify_support(
        {("event", "e1")}, [prior], [new], cohesion_pairs={("p1", "n1")},
    )
    assert out2["probable_retelling"] == ["n1"]


def test_classifier_additional_by_date():
    prior = _ev("p1", "event", "e1", entity="person:x",
                created="2026-11-20T10:00:00+00:00")
    new = _ev("n1", "event", "e2", entity="person:x",
              created="2026-11-21T09:00:00+00:00")
    out = classify_support({("event", "e1")}, [prior], [new])
    assert out["additional"] == ["n1"]


def test_classifier_additional_by_entity():
    prior = _ev("p1", "event", "e1", entity="person:x")
    new = _ev("n1", "event", "e2", entity="person:y")
    out = classify_support({("event", "e1")}, [prior], [new])
    assert out["additional"] == ["n1"]


def test_classifier_additional_by_ref_kind():
    prior = _ev("p1", "event", "e1", entity="person:x")
    new = _ev("n1", "claim", "c1", entity=None)
    out = classify_support({("event", "e1")}, [prior], [new])
    assert out["additional"] == ["n1"]


def test_classifier_undetermined_uncertainty_fixture():
    # Novel evidence, no cohesion data, and NO occasion marker:
    # same date, same entity, same kind. Absence of cohesion is
    # not proof of an independent event — undetermined, and
    # explicitly NOT additional.
    prior = _ev("p1", "event", "e1", entity="person:x")
    new = _ev("n1", "event", "e2", entity="person:x")
    out = classify_support({("event", "e1")}, [prior], [new])
    assert out["undetermined"] == ["n1"]
    assert out["additional"] == []
    assert out["probable_retelling"] == []


def test_classifier_no_priors_is_undetermined():
    # Nothing to compare against: occasion markers cannot fire on
    # vacuous truth.
    new = _ev("n1", "event", "e1", entity="person:x")
    out = classify_support(set(), [], [new])
    assert out["undetermined"] == ["n1"]
    assert out["additional"] == []


def test_support_block_matches_classifier_shape():
    prior = _ev("p1", "event", "e1", entity="person:x")
    new = _ev("n1", "event", "e2", entity="person:x",
              created="2026-11-22T08:00:00+00:00")
    block = support_block({("event", "e1")}, [prior], [new])
    assert block == classify_support({("event", "e1")}, [prior], [new])
    assert list(block) == [
        "duplicate", "probable_retelling", "additional", "undetermined",
    ]
    assert block["additional"] == ["n1"]


# -- criterion 6: generation-free by construction -----------------------------


def test_criterion_6_currency_and_card_take_no_generation():
    assert list(inspect.signature(derive_currency).parameters) == [
        "thread", "readings", "changes",
    ]
    assert list(inspect.signature(card_for).parameters) == [
        "store", "user_id", "thread_id",
    ]
    assert list(inspect.signature(classify_support).parameters) == [
        "lineage_cited", "prior_evidence_rows", "new_evidence_rows",
        "cohesion_pairs",
    ]
    import local_ai.narrative.currency as currency_module

    assert not hasattr(currency_module, "generate_fn")
    assert not hasattr(currency_module, "generate")


# -- criterion 4: endorsement is an annotation only ---------------------------


def _snapshot(store, user):
    snap = {}
    for thread in store.threads_for(user, limit=None):
        snap[thread.id] = {
            "status": thread.status,
            "standing_reading_id": thread.standing_reading_id,
            "readings": {
                r.id: r.status for r in store.readings_for(user, thread.id)
            },
        }
    return snap


def test_criterion_4_endorsement_is_annotation_only(store, monkeypatch):
    thread, v1, v2, _change = _organic_revision(store)
    before = _snapshot(store, USER)

    def _boom(*args, **kwargs):
        raise AssertionError("the verdict path must be unreachable")

    monkeypatch.setattr(NarrativeStore, "accept_reading", _boom)
    monkeypatch.setattr(NarrativeStore, "reject_reading", _boom)
    monkeypatch.setattr(steward_review, "apply_verdict", _boom)

    annotation = store.record_card_endorsement(
        USER, v1.id, "endorsed", note="this telling is mine"
    )
    assert annotation["reading_id"] == v1.id
    assert annotation["stance"] == "endorsed"
    assert annotation["note"] == "this telling is mine"
    assert annotation["created_at"]

    # Every reading status and standing pointer byte-identical.
    assert _snapshot(store, USER) == before

    # Retrievable, unambiguously typed, attached to the version.
    rows = store.card_endorsements_for(USER, v1.id)
    assert len(rows) == 1
    assert rows[0]["stance"] == "endorsed"
    assert rows[0]["note"] == "this telling is mine"
    raw = store.verdicts_for(USER, item_kind="card_endorsement")
    assert len(raw) == 1
    assert raw[0].item_id == v1.id
    # …and invisible to the verdict vocabulary's own readers.
    assert store.verdicts_for(USER, item_kind="reading") == []

    # A later organic revision does not move the annotation.
    v3 = store.propose_reading(
        USER, thread.id, author="steward",
        reading={"tensions": ["the newest tension"]},
        evidence_refs=(CLAIM_REF_3,),
    )
    store.record_change(
        USER, thread.id, kind="extended",
        evidence_refs=(EVENT_REF_3,),
        prior_reading_id=v2.id, new_reading_id=v3.id,
    )
    assert store.card_endorsements_for(USER, v1.id)[0]["stance"] == "endorsed"
    card = card_for(store, USER, thread.id)
    history = {e["id"]: e for e in card["history"]}
    assert history[v1.id]["endorsements"][0]["note"] == "this telling is mine"
    assert [e["id"] for e in card["current_field"]] == [v3.id]


def test_endorsement_validation(store):
    _thread, v1, _v2, _change = _organic_revision(store)
    with pytest.raises(ValueError):
        store.record_card_endorsement(USER, v1.id, "accepted")
    with pytest.raises(ValueError):
        store.record_card_endorsement(USER, "rdg-missing", "endorsed")
    with pytest.raises(ValueError):
        store.record_card_endorsement(OTHER, v1.id, "endorsed")
    # Multiple stances accumulate as separate annotations.
    store.record_card_endorsement(USER, v1.id, "unresolved")
    store.record_card_endorsement(USER, v1.id, "endorsed")
    stances = [r["stance"] for r in store.card_endorsements_for(USER, v1.id)]
    assert stances == ["unresolved", "endorsed"]


def test_endorsement_route_dispatches_only_to_annotation(
    tmp_path, monkeypatch
):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from api.routes import steward_review_routes as routes
    from api.routes.auth_routes import get_current_user

    nstore = NarrativeStore(db_path=tmp_path / "narrative.db")
    thread, v1, v2, _change = _organic_revision(nstore)
    nstore.close()

    def _boom(*args, **kwargs):
        raise AssertionError("the verdict path must be unreachable")

    monkeypatch.setattr(steward_review, "apply_verdict", _boom)
    monkeypatch.setattr(NarrativeStore, "accept_reading", _boom)
    monkeypatch.setattr(NarrativeStore, "reject_reading", _boom)
    monkeypatch.setattr(
        routes, "get_narrative_store",
        lambda: NarrativeStore(db_path=tmp_path / "narrative.db"),
    )
    app = FastAPI()
    app.include_router(routes.router)
    app.dependency_overrides[get_current_user] = lambda: {"id": USER}
    client = TestClient(app, raise_server_exceptions=False)

    resp = client.post(
        f"/steward/review/reading/{v1.id}/endorse",
        json={"stance": "endorsed", "note": "yes"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["item_kind"] == "card_endorsement"
    assert body["annotation"]["stance"] == "endorsed"
    assert body["annotation"]["note"] == "yes"

    resp404 = client.post(
        "/steward/review/reading/rdg-missing/endorse",
        json={"stance": "endorsed"},
    )
    assert resp404.status_code == 404
    resp400 = client.post(
        f"/steward/review/reading/{v1.id}/endorse",
        json={"stance": "accepted"},
    )
    assert resp400.status_code == 400

    check = NarrativeStore(db_path=tmp_path / "narrative.db")
    try:
        statuses = {
            r.id: r.status for r in check.readings_for(USER, thread.id)
        }
        assert statuses == {v1.id: "proposed", v2.id: "proposed"}
        assert check.get_thread(USER, thread.id).standing_reading_id is None
        assert len(check.card_endorsements_for(USER, v1.id)) == 1
    finally:
        check.close()


# -- criterion 8: both contracts coexist ---------------------------------------


def test_criterion_8_verdict_and_organic_contracts_coexist(store):
    # Legacy thread under verdict standing.
    legacy = store.create_thread(
        USER, origin="user_declared", title="Legacy",
        evidence_refs=(EVENT_REF,),
    )
    l1 = store.propose_reading(
        USER, legacy.id, author="steward",
        reading={"tensions": ["legacy one"]}, evidence_refs=(CLAIM_REF,),
    )
    l2 = store.propose_reading(
        USER, legacy.id, author="steward",
        reading={"tensions": ["legacy two"]}, evidence_refs=(CLAIM_REF_2,),
    )
    steward_review.apply_verdict(store, USER, f"reading:{l1.id}", "accepted")
    assert store.get_thread(USER, legacy.id).standing_reading_id == l1.id

    # Card thread under organic currency, in the same store.
    card_thread, v1, v2, _change = _organic_revision(store)

    # The legacy lifecycle continues exactly as today: accepting
    # l2 supersedes l1 and re-points standing.
    steward_review.apply_verdict(store, USER, f"reading:{l2.id}", "accepted")
    legacy_after = store.get_thread(USER, legacy.id)
    assert legacy_after.standing_reading_id == l2.id
    legacy_statuses = {
        r.id: r.status for r in store.readings_for(USER, legacy.id)
    }
    assert legacy_statuses == {l1.id: "superseded", l2.id: "accepted"}

    # The card thread's currency is unaffected by the verdicts…
    card = card_for(store, USER, card_thread.id)
    assert [e["id"] for e in card["current_field"]] == [v2.id]
    assert [e["id"] for e in card["history"]] == [v1.id]
    # …and verdict machinery never touched the card thread.
    assert store.get_thread(USER, card_thread.id).standing_reading_id is None
    card_statuses = {
        r.id: r.status for r in store.readings_for(USER, card_thread.id)
    }
    assert card_statuses == {v1.id: "proposed", v2.id: "proposed"}


# -- review queue: readings carry derived currency -----------------------------


def test_review_queue_reading_items_carry_currency(store):
    thread, v1, v2, _change = _organic_revision(store)
    items = steward_review.pending_review_items(store, USER)
    by_id = {item.item_id: item for item in items}
    retired = by_id[f"reading:{v1.id}"]
    assert retired.payload["currency"]["placement"] == "history"
    assert "superseded" in retired.payload["currency"]["labels"]
    live = by_id[f"reading:{v2.id}"]
    assert live.payload["currency"]["placement"] == "current"
    # Verdict behavior unchanged: the item is still actionable.
    assert live.status == "proposed"
    assert thread.id == live.thread_id


# -- criterion 2: pencil carries the successor, never the predecessor --------
#
# Setup mirrors tests/test_steward_pencil_context.py: the master
# switch on, both consent flags open through an in-memory
# permissions connection, an active thread whose evidence is
# annotated with the attended entity.


def _perm_conn(flags_by_user):
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE user_permissions_settings ("
        "user_id TEXT, permissions_json TEXT, updated_at TEXT)"
    )
    for user_id, flags in flags_by_user.items():
        conn.execute(
            "INSERT INTO user_permissions_settings VALUES (?, ?, ?)",
            (user_id, json.dumps(flags), "2026-11-21T00:00:00Z"),
        )
    conn.commit()
    return conn


_FLAGS_ON = {"steward_derivation": True, "steward_coordination": True}


@pytest.fixture()
def pencil_on(monkeypatch):
    monkeypatch.setenv("ZENAF_STEWARD_PENCIL", "1")


def _pencil_thread(store):
    thread = store.create_thread(
        USER, origin="user_declared", title="The long climb",
        evidence_refs=(EVENT_REF,),
    )
    store.annotate_evidence_entities(
        USER, thread.id, {("event", "evt-8"): "person:quinlin"}
    )
    store.set_thread_status(USER, thread.id, "active")
    return store.get_thread(USER, thread.id)


def test_criterion_2_pencil_renders_successor_not_predecessor(
    store, pencil_on
):
    from local_ai.narrative.context import (
        PENCIL_BRANCH_ID,
        pencil_context_for,
    )

    thread = _pencil_thread(store)
    # The successor is proposed FIRST and the predecessor second,
    # so the predecessor is the LAST proposed reading — the one
    # the pre-1A selection ([-1]) would have served. Currency, not
    # position, must decide.
    successor = store.propose_reading(
        USER, thread.id, author="steward",
        reading={
            "tensions": ["the new tension"],
            "open_questions": ["the new question"],
        },
        evidence_refs=(CLAIM_REF_2,),
    )
    predecessor = store.propose_reading(
        USER, thread.id, author="steward",
        reading={
            "tensions": ["the old tension"],
            "open_questions": ["the old question"],
        },
        evidence_refs=(CLAIM_REF,),
    )
    store.record_change(
        USER, thread.id, kind="extended",
        evidence_refs=(EVENT_REF_2,),
        prior_reading_id=predecessor.id, new_reading_id=successor.id,
    )
    conn = _perm_conn({USER: _FLAGS_ON})
    prepared = pencil_context_for(
        store, USER, PENCIL_BRANCH_ID,
        attended_entity_refs=("person:quinlin",), connection=conn,
    )
    assert prepared.available is True
    assert "the new tension" in prepared.block
    assert "the old tension" not in prepared.block
    assert "the old question" not in prepared.block


def test_pencil_no_material_when_only_proposed_reading_is_superseded(
    store, pencil_on
):
    from local_ai.narrative.context import (
        PENCIL_BRANCH_ID,
        pencil_context_for,
    )

    thread = _pencil_thread(store)
    v1 = store.propose_reading(
        USER, thread.id, author="steward",
        reading={
            "tensions": ["the old tension"],
            "open_questions": ["the old question"],
        },
        evidence_refs=(CLAIM_REF,),
    )
    v2 = store.propose_reading(
        USER, thread.id, author="steward",
        reading={
            "tensions": ["the accepted tension"],
            "open_questions": ["the accepted question"],
        },
        evidence_refs=(CLAIM_REF_2,),
    )
    # v2 leaves the proposed set through the verdict path; the
    # change record then retires v1 organically. No proposed
    # reading remains current, so the thread offers no material.
    store.accept_reading(USER, v2.id)
    store.record_change(
        USER, thread.id, kind="extended",
        evidence_refs=(EVENT_REF_2,),
        prior_reading_id=v1.id, new_reading_id=v2.id,
    )
    conn = _perm_conn({USER: _FLAGS_ON})
    prepared = pencil_context_for(
        store, USER, PENCIL_BRANCH_ID,
        attended_entity_refs=("person:quinlin",), connection=conn,
    )
    assert prepared.available is False
    assert prepared.reason == "no_pencil_material"
    assert prepared.block is None


# -- criterion 3: Aria's substrate excludes organically superseded readings --
#
# Fixtures mirror tests/test_aria_expression.py (the ve_conn
# monkeypatch pattern, the thread helper, the derive call).


ARIA_USER = "user-aria"
ENTITY_TYPE = "project"
ENTITY_ID = "proj-garden"
TARGET_REF = f"{ENTITY_TYPE}:{ENTITY_ID}"


@pytest.fixture()
def ve_conn(monkeypatch):
    import local_ai.vision_execution.storage as ve_storage

    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    ve_storage.init_db(conn)
    monkeypatch.setattr(ve_storage, "get_connection", lambda: conn)
    yield conn
    conn.close()


@pytest.fixture()
def conv(tmp_path):
    from local_ai.conversation.store import ConversationStore

    s = ConversationStore(db_path=str(tmp_path / "conv.db"))
    yield s
    s.close()


@pytest.fixture()
def narr(tmp_path):
    s = NarrativeStore(db_path=str(tmp_path / "narr.db"))
    yield s
    s.close()


@pytest.fixture()
def agent(tmp_path):
    from local_ai.agent_intake.store import AgentStore

    s = AgentStore(db_path=str(tmp_path / "agent.db"), user_id=ARIA_USER)
    yield s
    s.close()


def _aria_thread(narr, user, ref_id, entity_ref=None, title="A thread"):
    thread = narr.create_thread(
        user,
        title=title,
        origin="user_declared",
        evidence_refs=[
            SourceRef(kind="event", ref_id=ref_id, evidence_kind="entity_ref")
        ],
    )
    if entity_ref is not None:
        narr.annotate_evidence_entities(
            user, thread.id, {("event", ref_id): entity_ref}
        )
    return thread


def test_criterion_3_aria_excludes_organically_superseded(
    ve_conn, conv, narr, agent
):
    from local_ai.atelier import derive_aria_expression

    thread = _aria_thread(narr, ARIA_USER, "ev-1", TARGET_REF)
    successor = narr.propose_reading(
        ARIA_USER, thread.id, author="steward",
        reading={"tensions": ["the new tension"]},
        evidence_refs=[
            SourceRef(kind="event", ref_id="ev-1", evidence_kind="entity_ref")
        ],
    )
    predecessor = narr.propose_reading(
        ARIA_USER, thread.id, author="steward",
        reading={"tensions": ["the old tension"]},
        evidence_refs=[
            SourceRef(kind="event", ref_id="ev-1", evidence_kind="entity_ref")
        ],
    )
    narr.record_change(
        ARIA_USER, thread.id, kind="extended",
        evidence_refs=[
            SourceRef(kind="event", ref_id="ev-2", evidence_kind="entity_ref")
        ],
        prior_reading_id=predecessor.id, new_reading_id=successor.id,
    )
    spec = derive_aria_expression(
        ARIA_USER, ENTITY_TYPE, ENTITY_ID,
        conversation_store=conv, narrative_store=narr, agent_store=agent,
    )
    readings = [e for e in spec.provisional if e["kind"] == "reading"]
    assert [e["source_id"] for e in readings] == [successor.id]
    assert spec.coverage["recognition_absent"] is False
