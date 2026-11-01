"""Narrative Steward Phase 6 — diffusion schedule, literal (global
revision + visible resolutions).

Acceptance, from the reconciled architecture §2 + §5 Phase 6 and
the phase brief:

- The §2 schedule as a reusable pass (draft → revision → review
  → artifact) with approval gates between steps; no step advances
  past a gate without its approval.
- Global revision pass: whole-draft rewrite, versioned (every
  rewrite preserves the prior version retrievably); involvement
  recorded per rewrite (user vs synthesized split asserted);
  Tier-E immutable; accepted readings never rewritten without a
  new proposal.
- Resolution rendering: approval state + involvement + fitted
  lens; blend shown only as labeled provenance, never as a score.
- First adopter: the narrative artifact path (steward readings →
  artifact drafts) runs through the schedule.
- Deliberately not: build-council schedule untouched; verbatim
  evidence never rewritten (byte-compare test); no auto-applied
  revision; no diffusion language model; no Tier-E record changed;
  rejected options not recorded (§6.7 default).
"""

from __future__ import annotations

import json

import pytest

from local_ai.narrative import NarrativeStore
from local_ai.narrative import review, schedule
from local_ai.narrative.refs import SourceRef

USER = "phase6-user"
OTHER = "phase6-other"


@pytest.fixture
def store(tmp_path):
    return NarrativeStore(db_path=tmp_path / "narrative.db")


def _ref(n):
    return SourceRef(kind="claim", ref_id=f"claim-{n}", evidence_kind="quote")


def _thread(store, user=USER, title="The long walk", refs=(1,)):
    thread = store.create_thread(
        user,
        origin="user_declared",
        title=title,
        evidence_refs=[_ref(n) for n in refs],
    )
    store.set_thread_status(user, thread.id, "active")
    return store.get_thread(user, thread.id)


def _evidence_ids(store, thread_id, user=USER):
    return [e.id for e in store.evidence_for(user, thread_id)]


def _draft(store, thread, user=USER, **kw):
    kw.setdefault("content", {"telling": "first telling"})
    kw.setdefault("involvement", {"synthesized_units": 100.0})
    return schedule.start_draft(
        store,
        user,
        thread.id,
        title=thread.title,
        evidence_refs=_evidence_ids(store, thread.id, user),
        **kw,
    )


def _accepted_reading(store, thread_id, n=2, user=USER):
    reading = store.propose_reading(
        user,
        thread_id,
        author="steward",
        reading={"tensions": ["patience vs avoidance"]},
        evidence_refs=[_ref(n)],
    )
    store.accept_reading(user, reading.id)
    return store.readings_for(user, thread_id, status="accepted")[0]


# -- Schedule steps + gates ---------------------------------------------------


def test_draft_creates_proposed_v1_and_step_is_draft(store):
    thread = _thread(store)
    artifact, v1 = _draft(store, thread)
    assert v1.version_no == 1
    assert v1.status == "proposed"
    assert v1.content == {"telling": "first telling"}
    assert store.artifact_status(USER, artifact.id) == "drafting"
    assert schedule.step_of_artifact(store, USER, artifact.id) == "draft"


def test_draft_requires_evidence_citation(store):
    thread = _thread(store)
    with pytest.raises(ValueError, match="at least one evidence"):
        schedule.start_draft(
            store, USER, thread.id, content={"telling": "uncited"}
        )


def test_draft_rejects_unknown_or_other_thread_evidence(store):
    thread = _thread(store)
    other = _thread(store, user=OTHER, title="Other", refs=(9,))
    other_ev = _evidence_ids(store, other.id, OTHER)[0]
    with pytest.raises(ValueError, match="unknown evidence"):
        schedule.start_draft(
            store,
            USER,
            thread.id,
            content={"telling": "x"},
            evidence_refs=["nope"],
        )
    with pytest.raises(ValueError, match="unknown evidence"):
        schedule.start_draft(
            store,
            USER,
            thread.id,
            content={"telling": "x"},
            evidence_refs=[other_ev],
        )


def test_revision_is_whole_draft_not_patch(store):
    thread = _thread(store)
    artifact, v1 = _draft(store, thread)
    v2 = schedule.propose_revision(
        store,
        USER,
        artifact.id,
        content={"telling": "second telling"},
    )
    assert v2.version_no == 2
    assert v2.status == "proposed"
    # Nothing merges: a key present in v1 and absent in v2 stays absent.
    assert v2.content == {"telling": "second telling"}
    assert "telling" not in v1.content or v1.content == {
        "telling": "first telling"
    }
    assert store.get_artifact_version(USER, v1.id).content == {
        "telling": "first telling"
    }


def test_revision_defaults_to_full_current_state(store):
    thread = _thread(store)
    _accepted_reading(store, thread.id)
    artifact, _v1 = _draft(store, thread)
    v2 = schedule.propose_revision(
        store, USER, artifact.id, content={"telling": "global"}
    )
    # Global means the whole constellation: current evidence +
    # current accepted readings, not a slice the caller picked.
    assert v2.evidence_refs == _evidence_ids(store, thread.id)
    assert v2.reading_ids == [
        r.id
        for r in store.readings_for(USER, thread.id, status="accepted")
    ]


def test_gates_block_advancement_without_approval(store):
    thread = _thread(store)
    artifact, v1 = _draft(store, thread)
    # A merely proposed version is NOT a pending review item:
    # the review step has not been entered.
    assert review.pending_review_items(store, USER) == []
    with pytest.raises(ValueError, match="no pending review item"):
        review.apply_verdict(store, USER, f"revision:{v1.id}", "accepted")
    assert store.get_artifact_version(USER, v1.id).status == "proposed"
    # Direct acceptance without the in_review gate refuses too.
    with pytest.raises(ValueError, match="cannot move"):
        store.accept_artifact_version(USER, v1.id)
    # Render before acceptance is nothing, not a draft leak.
    assert schedule.render(store, USER, artifact.id) is None
    # Submit twice refuses the second time; state unchanged.
    schedule.submit_for_review(store, USER, v1.id)
    assert store.get_artifact_version(USER, v1.id).status == "in_review"
    with pytest.raises(ValueError, match="cannot move"):
        store.submit_artifact_version_for_review(USER, v1.id)


def test_review_flow_accept_reject_unresolved(store):
    thread = _thread(store)
    artifact, v1 = _draft(store, thread)
    schedule.submit_for_review(store, USER, v1.id)
    # Unresolved is explicit not-deciding: verdict logged, still in review.
    item = review.apply_verdict(
        store, USER, f"revision:{v1.id}", "unresolved"
    )
    assert item.status == "in_review"
    assert store.get_artifact_version(USER, v1.id).status == "in_review"
    assert any(
        i.item_id == f"revision:{v1.id}"
        for i in review.pending_review_items(store, USER)
    )
    # Rejected is terminal and stays a row, never silently reactivated.
    item = review.apply_verdict(store, USER, f"revision:{v1.id}", "rejected")
    assert item.status == "rejected"
    assert store.get_artifact_version(USER, v1.id).status == "rejected"
    assert schedule.render(store, USER, artifact.id) is None
    with pytest.raises(ValueError, match="cannot move"):
        store.submit_artifact_version_for_review(USER, v1.id)
    # A fresh revision can still be accepted afterwards.
    v2 = schedule.propose_revision(
        store, USER, artifact.id, content={"telling": "third"}
    )
    schedule.submit_for_review(store, USER, v2.id)
    item = review.apply_verdict(store, USER, f"revision:{v2.id}", "accepted")
    assert item.status == "accepted"
    rendered = schedule.render(store, USER, artifact.id)
    assert rendered is not None and rendered["content"] == {"telling": "third"}


def test_second_acceptance_supersedes_first_retrievably(store):
    thread = _thread(store)
    artifact, v1 = _draft(store, thread)
    schedule.submit_for_review(store, USER, v1.id)
    review.apply_verdict(store, USER, f"revision:{v1.id}", "accepted")
    v2 = schedule.propose_revision(
        store, USER, artifact.id, content={"telling": "v2"}
    )
    schedule.submit_for_review(store, USER, v2.id)
    review.apply_verdict(store, USER, f"revision:{v2.id}", "accepted")
    assert store.get_artifact_version(USER, v1.id).status == "superseded"
    assert store.get_artifact_version(USER, v1.id).content == {
        "telling": "first telling"
    }
    rendered = schedule.render(store, USER, artifact.id)
    assert rendered["version_no"] == 2
    assert rendered["content"] == {"telling": "v2"}
    assert schedule.step_of_artifact(store, USER, artifact.id) == "artifact"


def test_unaccepted_revision_never_becomes_standing_state(store):
    thread = _thread(store)
    _accepted_reading(store, thread.id)
    standing_before = store.get_thread(USER, thread.id).standing_reading_id
    artifact, v1 = _draft(store, thread)
    v2 = schedule.propose_revision(
        store, USER, artifact.id, content={"telling": "unaccepted"}
    )
    schedule.submit_for_review(store, USER, v2.id)
    assert schedule.render(store, USER, artifact.id) is None
    assert store.artifact_status(USER, artifact.id) == "in_review"
    assert (
        store.get_thread(USER, thread.id).standing_reading_id
        == standing_before
    )
    assert v1.status == "proposed"  # untouched by the later revision
    assert store.get_artifact_version(USER, v2.id).status == "in_review"


def test_step_derivation_across_the_pass(store):
    thread = _thread(store)
    artifact, v1 = _draft(store, thread)
    assert schedule.step_of_artifact(store, USER, artifact.id) == "draft"
    schedule.propose_revision(
        store, USER, artifact.id, content={"telling": "v2"}
    )
    assert schedule.step_of_artifact(store, USER, artifact.id) == "revision"
    schedule.submit_for_review(store, USER, v1.id)
    assert schedule.step_of_artifact(store, USER, artifact.id) == "review"


# -- Involvement per rewrite ---------------------------------------------------


def test_involvement_recorded_per_rewrite_with_split(store):
    thread = _thread(store)
    artifact, v1 = _draft(
        store,
        thread,
        involvement={
            "user_authored_units": 10.0,
            "synthesized_units": 90.0,
        },
    )
    assert (v1.user_authored_units, v1.user_edited_units) == (10.0, 0.0)
    assert v1.synthesized_units == 90.0
    assert v1.user_share == pytest.approx(0.1)
    # A user edit is a new version with the edit in the user's column.
    v2 = schedule.propose_revision(
        store,
        USER,
        artifact.id,
        content={"telling": "edited telling"},
        involvement={
            "user_authored_units": 10.0,
            "user_edited_units": 30.0,
            "synthesized_units": 60.0,
        },
        created_by="user",
    )
    assert v2.user_share == pytest.approx(0.4)
    assert v2.created_by == "user"
    # The ledger's current measure tracks the latest version.
    measure = store.involvement_for(USER, "artifact", artifact.id)
    assert measure is not None
    assert (measure.user_authored_units, measure.user_edited_units) == (
        10.0,
        30.0,
    )
    assert measure.synthesized_units == 60.0
    # The earlier version's split is untouched by the later rewrite.
    assert store.get_artifact_version(USER, v1.id).user_share == pytest.approx(
        0.1
    )
    with pytest.raises(ValueError, match="cannot be negative"):
        schedule.propose_revision(
            store,
            USER,
            artifact.id,
            content={"telling": "bad"},
            involvement={"synthesized_units": -1.0},
        )


# -- Verbatim evidence + accepted readings immutable ---------------------------


def test_revision_pass_alters_no_verbatim_evidence_byte_compare(store):
    thread = _thread(store)
    _accepted_reading(store, thread.id)
    before_evidence = [
        json.dumps(e.to_dict(), sort_keys=True)
        for e in store.evidence_for(USER, thread.id)
    ]
    before_reading = json.dumps(
        store.readings_for(USER, thread.id, status="accepted")[0].to_dict(),
        sort_keys=True,
    )
    artifact, _v1 = _draft(store, thread)
    v2 = schedule.propose_revision(
        store, USER, artifact.id, content={"telling": "revised"}
    )
    schedule.submit_for_review(store, USER, v2.id)
    review.apply_verdict(store, USER, f"revision:{v2.id}", "accepted")
    schedule.render(store, USER, artifact.id)
    after_evidence = [
        json.dumps(e.to_dict(), sort_keys=True)
        for e in store.evidence_for(USER, thread.id)
    ]
    after_reading = json.dumps(
        store.readings_for(USER, thread.id, status="accepted")[0].to_dict(),
        sort_keys=True,
    )
    assert after_evidence == before_evidence
    # Accepted readings are never rewritten without a new proposal:
    # the revision cited this one and left its row byte-identical.
    assert after_reading == before_reading


def test_tier_e_records_untouched_by_revision(store):
    thread = _thread(store)
    artifact, _v1 = _draft(store, thread)
    # The pass cites Tier-E rows by id only; it holds no writer
    # for them. Direct proof: row ids + row dicts survive a full pass.
    before = {
        e.id: json.dumps(e.to_dict(), sort_keys=True)
        for e in store.evidence_for(USER, thread.id)
    }
    v2 = schedule.propose_revision(
        store, USER, artifact.id, content={"telling": "v2"}
    )
    schedule.submit_for_review(store, USER, v2.id)
    review.apply_verdict(store, USER, f"revision:{v2.id}", "accepted")
    after = {
        e.id: json.dumps(e.to_dict(), sort_keys=True)
        for e in store.evidence_for(USER, thread.id)
    }
    assert after == before
    assert set(v2.evidence_refs) == set(before)


# -- Resolution rendering -------------------------------------------------------


def _resolution_fixture(store):
    thread = _thread(store, refs=(1,))
    accepted = _accepted_reading(store, thread.id, n=2)
    store.propose_reading(
        USER,
        thread.id,
        author="steward",
        reading={"tensions": ["open question"]},
        evidence_refs=[_ref(3)],
    )
    confirmed = store.record_change(
        USER, thread.id, kind="extended", evidence_refs=[_ref(4)]
    )
    store.set_change_status(USER, confirmed.id, "confirmed")
    store.record_change(
        USER, thread.id, kind="milestone", evidence_refs=[_ref(5)]
    )
    fitting = store.set_fitting(
        USER,
        thread.id,
        lens_id="descent_and_return",
        evidence_refs=[_ref(2)],
    )
    store.set_fitting_status(USER, fitting.id, "accepted")
    artifact, v1 = _draft(
        store,
        thread,
        involvement={
            "user_authored_units": 25.0,
            "synthesized_units": 75.0,
        },
    )
    return {
        "thread": store.get_thread(USER, thread.id),
        "accepted": accepted,
        "artifact": artifact,
        "v1": v1,
    }


def test_resolution_matches_store_state_on_fixtures(store):
    fx = _resolution_fixture(store)
    res = schedule.resolution_for_thread(store, USER, fx["thread"].id)
    # No single "resolved" bit: the two I4 axes stay separate.
    assert "resolved" not in res
    assert "resolved" not in json.dumps(res)
    # Epistemic axis: approval counts from store rows.
    approval = res["epistemic"]["approval"]
    assert approval["readings"] == {"accepted": 1, "proposed": 1}
    assert approval["changes"] == {"confirmed": 1, "proposed": 1}
    assert approval["fittings"] == {"accepted": 1}
    assert approval["revisions"] == {"proposed": 1}
    assert res["epistemic"]["standing_reading"]["id"] == fx["accepted"].id
    assert res["epistemic"]["standing_reading"]["status"] == "accepted"
    assert res["epistemic"]["lens"]["lens_id"] == "descent_and_return"
    assert res["epistemic"]["lens"]["proposed_by"] == "steward"
    # Developmental axis: status + latest confirmed change.
    assert res["developmental"]["status"] == "active"
    assert res["developmental"]["latest_confirmed_change"]["kind"] == (
        "extended"
    )
    # Involvement aggregates the thread's artifacts.
    assert res["involvement"]["user_share"] == pytest.approx(0.25)
    # Blend appears exactly once, labeled, under provenance only.
    assert res["provenance"]["blend"]["label"].startswith("provenance:")
    assert "not resolution" in res["provenance"]["blend"]["label"]
    assert res["provenance"]["blend"]["user_sourced"] == pytest.approx(0.25)
    assert res["provenance"]["blend"]["base_model_fill"] == pytest.approx(
        0.75
    )


def test_resolution_for_artifact_before_and_after_acceptance(store):
    fx = _resolution_fixture(store)
    artifact = fx["artifact"]
    before = schedule.resolution_for_artifact(store, USER, artifact.id)
    assert before["step"] == "draft"
    assert before["approval"]["version_status"] == "proposed"
    assert before["approval"]["verdict"] is None
    assert before["lens"]["lens_id"] == "descent_and_return"
    assert before["involvement"]["user_share"] == pytest.approx(0.25)
    # A draft's claimed lens never counts as fitted: claim a
    # different lens on a revision and the fitted lens stays put.
    v2 = schedule.propose_revision(
        store, USER, artifact.id, content={"telling": "v2"}, lens_id="other"
    )
    schedule.submit_for_review(store, USER, v2.id)
    review.apply_verdict(store, USER, f"revision:{v2.id}", "accepted")
    after = schedule.resolution_for_artifact(store, USER, artifact.id)
    assert after["step"] == "artifact"
    assert after["version_no"] == 2
    assert after["approval"] == {
        "version_status": "accepted",
        "verdict": "accepted",
    }
    assert after["lens"]["lens_id"] == "descent_and_return"
    assert after["draft_lens_id"] == "other"


def test_resolution_without_involvement_has_no_blend(store):
    thread = _thread(store)
    artifact, _v1 = schedule.start_draft(
        store,
        USER,
        thread.id,
        content={"telling": "unmeasured"},
        evidence_refs=_evidence_ids(store, thread.id),
    )
    res = schedule.resolution_for_artifact(store, USER, artifact.id)
    assert res["involvement"]["user_share"] is None
    assert res["provenance"] is None
    assert "blend" not in json.dumps(res)


def test_rejected_options_are_not_recorded(store):
    # §6.7 default: unproposed alternatives are never stored. Each
    # revision act records exactly one proposed version — no
    # alternatives table, no shadow rows.
    thread = _thread(store)
    artifact, _v1 = _draft(store, thread)
    schedule.propose_revision(
        store, USER, artifact.id, content={"telling": "chosen"}
    )
    versions = store.artifact_versions(USER, artifact.id)
    assert len(versions) == 2
    assert [v.version_no for v in versions] == [1, 2]


# -- Review-layer flow-through + routes ---------------------------------------


def test_revision_verdicts_flow_through_review_routes(
    store, tmp_path, monkeypatch
):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    import api.routes.steward_review_routes as review_routes
    from api.routes.auth_routes import get_current_user

    thread = _thread(store)
    artifact, v1 = _draft(store, thread)
    schedule.submit_for_review(store, USER, v1.id)
    app = FastAPI()
    app.include_router(review_routes.router)
    app.dependency_overrides[get_current_user] = lambda: {"id": USER}
    monkeypatch.setattr(
        review_routes,
        "get_narrative_store",
        lambda: NarrativeStore(db_path=tmp_path / "narrative.db"),
    )
    client = TestClient(app, raise_server_exceptions=False)
    kinds = {
        item["item_kind"]
        for item in client.get("/steward/review").json()["items"]
    }
    assert "revision" in kinds
    resp = client.post(f"/steward/review/revision/{v1.id}/accept")
    assert resp.status_code == 200
    assert resp.json()["status"] == "accepted"
    assert resp.json()["item_kind"] == "revision"
    assert client.get("/steward/review").json()["precision"]["per_kind"][
        "revision"
    ]["accepted"] == 1
    # Cross-user revision verdict is indistinguishable from unknown.
    other_thread = _thread(store, user=OTHER, title="Other", refs=(9,))
    _draft(store, other_thread, user=OTHER)
    other_artifacts = store.artifacts_for(OTHER, thread_id=other_thread.id)
    other_v = store.artifact_versions(OTHER, other_artifacts[0].id)[0]
    store.submit_artifact_version_for_review(OTHER, other_v.id)
    cross = client.post(f"/steward/review/revision/{other_v.id}/reject")
    assert cross.status_code == 404


# -- Deletion + isolation ------------------------------------------------------


def test_delete_thread_cascades_artifacts_and_revision_verdicts(store):
    thread = _thread(store)
    artifact, v1 = _draft(store, thread)
    schedule.submit_for_review(store, USER, v1.id)
    review.apply_verdict(store, USER, f"revision:{v1.id}", "accepted")
    assert store.render_artifact(USER, artifact.id) is not None
    assert store.delete_thread(USER, thread.id) is True
    assert store.get_artifact(USER, artifact.id) is None
    assert store.get_artifact_version(USER, v1.id) is None
    assert store.verdicts_for(USER, item_kind="revision") == []
    # Involvement measures are measures ABOUT a subject and survive,
    # as with every other subject kind.
    assert store.involvement_for(USER, "artifact", artifact.id) is not None


def test_cross_user_isolation(store):
    thread = _thread(store)
    artifact, v1 = _draft(store, thread)
    assert store.get_artifact(OTHER, artifact.id) is None
    assert store.get_artifact_version(OTHER, v1.id) is None
    with pytest.raises(ValueError, match="unknown artifact"):
        store.propose_artifact_revision(
            OTHER, artifact.id, content={"telling": "intruder"}
        )
    with pytest.raises(ValueError, match="unknown version"):
        store.submit_artifact_version_for_review(OTHER, v1.id)
    with pytest.raises(ValueError, match="unknown artifact"):
        schedule.resolution_for_artifact(store, OTHER, artifact.id)
