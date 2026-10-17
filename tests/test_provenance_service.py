"""Provenance registry: store, service ops, reach, disputes (no network)."""

from __future__ import annotations

import base64
import io

import pytest
from PIL import Image, ImageDraw

from local_ai.provenance import service as prov
from local_ai.provenance.reach import WEIGHTS, compute_reach, perspective_reach
from local_ai.provenance.store import ProvenanceStore


def _img(kind: str) -> str:
    img = Image.new("RGB", (64, 64), "white")
    d = ImageDraw.Draw(img)
    if kind == "halves":
        d.rectangle([0, 0, 31, 63], fill="black")
    elif kind == "circle":
        d.ellipse([12, 12, 52, 52], fill="black")
    elif kind == "square":
        d.rectangle([12, 12, 52, 52], fill="black")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()


@pytest.fixture()
def store(tmp_path):
    s = ProvenanceStore(tmp_path / "prov.db")
    yield s
    s.close()


ALICE, BOB = "user-alice", "user-bob"


def _register(store, user=ALICE, kind="halves", **kw):
    return prov.register_artifact(
        store, image_base64=_img(kind), creator_user_id=user, title=kw.get("title", kind),
        remix_policy=kw.get("remix_policy", "open"),
    )


# -- registration / visibility --------------------------------------------------


def test_register_defaults_unlisted(store):
    a = _register(store)
    assert a["visibility"] == "unlisted"
    assert a["minted"] is False
    assert a["remix_policy"] == "open"
    assert a["creator_user_id"] == ALICE
    assert a["custodian_user_id"] == ALICE
    events = store.events_for(a["artifact_id"])
    assert [e["type"] for e in events] == ["minted"]


def test_mint_flips_unlisted_to_private(store):
    a = _register(store)
    minted = prov.mint_artifact(store, a["artifact_id"], ALICE)
    assert minted["minted"] is True
    assert minted["visibility"] == "private"


def test_mint_rejected_for_stranger(store):
    a = _register(store)
    with pytest.raises(PermissionError):
        prov.mint_artifact(store, a["artifact_id"], BOB)


def test_publish_is_explicit(store):
    a = _register(store)
    assert prov.publish_artifact(store, a["artifact_id"], ALICE)["visibility"] == "public"
    with pytest.raises(PermissionError):
        prov.publish_artifact(store, a["artifact_id"], BOB)


# -- derivation ---------------------------------------------------------------------


def test_derive_open_policy_links_immediately(store):
    parent = _register(store, user=ALICE, kind="halves")
    out = prov.derive_artifact(
        store, parent_ids=[parent["artifact_id"]], image_base64=_img("circle"),
        actor_user_id=BOB, title="bob remix",
    )
    assert out["links"][0]["status"] == "linked"
    assert out["artifact"]["creator_user_id"] == BOB  # deriver owns the child
    parent_events = store.events_for(parent["artifact_id"])
    assert any(
        e["type"] == "remixed" and e["context"]["child_id"] == out["artifact"]["artifact_id"]
        for e in parent_events
    )


def test_derive_approval_policy_stays_pending(store):
    parent = _register(store, user=ALICE, kind="halves", remix_policy="approval")
    out = prov.derive_artifact(
        store, parent_ids=[parent["artifact_id"]], image_base64=_img("circle"),
        actor_user_id=BOB,
    )
    assert out["links"][0]["status"] == "pending"
    # No upstream reach flows while pending.
    assert store.get_artifact(parent["artifact_id"])["reach_cached"] == 0
    assert not any(
        e["type"] == "remixed" for e in store.events_for(parent["artifact_id"])
    )


def test_approve_derivation_starts_reach_flowing(store):
    parent = _register(store, user=ALICE, kind="halves", remix_policy="approval")
    out = prov.derive_artifact(
        store, parent_ids=[parent["artifact_id"]], image_base64=_img("circle"),
        actor_user_id=BOB,
    )
    child_id = out["artifact"]["artifact_id"]
    prov.log_event(store, artifact_id=child_id, type="saved", actor_user_id=BOB)
    assert store.get_artifact(parent["artifact_id"])["reach_cached"] == 0
    link = prov.approve_derivation(
        store, parent_id=parent["artifact_id"], child_id=child_id, user_id=ALICE
    )
    assert link["status"] == "linked"
    assert store.get_artifact(parent["artifact_id"])["reach_cached"] == pytest.approx(10 + 5 * 0.6)
    with pytest.raises(PermissionError):
        prov.approve_derivation(
            store, parent_id=parent["artifact_id"], child_id=child_id, user_id=BOB
        )


# -- reach ------------------------------------------------------------------------------


def test_reach_weights_and_decay(store):
    parent = _register(store, user=ALICE, kind="halves")
    child = prov.derive_artifact(
        store, parent_ids=[parent["artifact_id"]], image_base64=_img("circle"),
        actor_user_id=BOB,
    )["artifact"]
    prov.log_event(store, artifact_id=child["artifact_id"], type="saved", actor_user_id=BOB)
    prov.log_event(store, artifact_id=parent["artifact_id"], type="viewed", actor_user_id=BOB)
    # child: own saved at d=0 -> 5.
    # parent: remixed 10 @d0 + viewed 0.1 @d0 + saved 5*0.6 @d1 = 13.1
    assert compute_reach(store, child["artifact_id"]) == pytest.approx(5.0)
    assert compute_reach(store, parent["artifact_id"]) == pytest.approx(13.1)
    assert store.get_artifact(parent["artifact_id"])["reach_cached"] == pytest.approx(13.1)


def test_journal_sparked_outweighs_remixed():
    assert WEIGHTS["journal_sparked"] > WEIGHTS["remixed"]
    assert WEIGHTS["viewed"] < 1  # significantly nominal


def test_grandchild_decay(store):
    root = _register(store, user=ALICE, kind="halves")
    mid = prov.derive_artifact(
        store, parent_ids=[root["artifact_id"]], image_base64=_img("circle"),
        actor_user_id=BOB,
    )["artifact"]
    leaf = prov.derive_artifact(
        store, parent_ids=[mid["artifact_id"]], image_base64=_img("square"),
        actor_user_id=BOB,
    )["artifact"]
    prov.log_event(store, artifact_id=leaf["artifact_id"], type="journal_sparked",
                   actor_user_id=ALICE)
    # leaf: journal 14 @d0 = 14.
    # mid: remixed 10 @d0 + journal 14*0.6 @d1 = 18.4.
    # root: remixed 10 @d0 + mid remixed 10*0.6 @d1 + journal 14*0.36 @d2 = 21.04.
    assert compute_reach(store, leaf["artifact_id"]) == pytest.approx(14.0)
    assert compute_reach(store, mid["artifact_id"]) == pytest.approx(18.4)
    assert compute_reach(store, root["artifact_id"]) == pytest.approx(21.04)


def test_perspective_reach_sums_created_artifacts(store):
    parent = _register(store, user=ALICE, kind="halves")
    child = prov.derive_artifact(
        store, parent_ids=[parent["artifact_id"]], image_base64=_img("circle"),
        actor_user_id=BOB,
    )["artifact"]
    prov.log_event(store, artifact_id=child["artifact_id"], type="saved", actor_user_id=ALICE)
    # alice: remixed 10 + saved tithe 3.0 = 13.0. bob: saved 5.0 on his child.
    assert perspective_reach(store, ALICE) == pytest.approx(13.0)
    assert perspective_reach(store, BOB) == pytest.approx(5.0)


def test_unknown_event_type_rejected(store):
    a = _register(store)
    with pytest.raises(ValueError):
        prov.log_event(store, artifact_id=a["artifact_id"], type="exploded")


# -- ingest: the three outcomes ---------------------------------------------------------------


def test_ingest_exact_dedups(store):
    a = _register(store, user=ALICE, kind="halves")
    out = prov.identify_upload(store, image_base64=_img("halves"), user_id=BOB)
    assert out["outcome"] == "exact"
    assert out["artifact"]["artifact_id"] == a["artifact_id"]
    assert len(store.list_artifacts()) == 1  # no duplicate registered


def test_ingest_near_suggests_parent(store):
    a = _register(store, user=ALICE, kind="halves")
    # JPEG recompression: same picture, different bytes -> near match.
    img = Image.open(io.BytesIO(base64.b64decode(_img("halves"))))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=70)
    near_b64 = base64.b64encode(buf.getvalue()).decode()
    out = prov.identify_upload(store, image_base64=near_b64, user_id=BOB, title="found")
    assert out["outcome"] == "near"
    assert out["suggested_parent"]["artifact_id"] == a["artifact_id"]
    imported = out["artifact"]
    assert imported["imported"] is True
    assert imported["custodian_user_id"] == BOB
    assert imported["creator_user_id"] is None  # importer != creator
    # Confirm the suggestion grafts it onto the tree.
    link = prov.confirm_derivation_link(
        store, child_id=imported["artifact_id"],
        parent_id=a["artifact_id"], user_id=BOB,
    )
    assert link["status"] == "linked"


def test_ingest_none_registers_imported(store):
    _register(store, user=ALICE, kind="halves")
    out = prov.identify_upload(
        store, image_base64=_img("square"), user_id=BOB, claim_creator=True
    )
    assert out["outcome"] == "none"
    assert out["artifact"]["imported"] is True
    assert out["artifact"]["creator_user_id"] == BOB  # claimed
    assert out["artifact"]["creator_declared"] is True


# -- lineage & visibility -----------------------------------------------------------------------------


def test_lineage_private_child_renders_as_stub(store):
    parent = _register(store, user=ALICE, kind="halves")
    prov.publish_artifact(store, parent["artifact_id"], ALICE)
    child = prov.derive_artifact(
        store, parent_ids=[parent["artifact_id"]], image_base64=_img("circle"),
        actor_user_id=BOB,
    )["artifact"]
    prov.mint_artifact(store, child["artifact_id"], BOB)  # private
    lineage = prov.get_lineage(store, parent["artifact_id"], viewer_user_id=ALICE)
    kids = lineage["tree"]["children"]
    assert len(kids) == 1
    assert kids[0].get("stub") is True
    assert kids[0]["label"] == "private remix"
    assert "creator_user_id" not in kids[0]
    # Bob sees his own child fully.
    own = prov.get_lineage(store, parent["artifact_id"], viewer_user_id=BOB)
    assert own["tree"]["children"][0].get("stub") is not True


def test_private_root_blocked_for_stranger(store):
    a = _register(store, user=ALICE, kind="halves")
    prov.mint_artifact(store, a["artifact_id"], ALICE)
    with pytest.raises(PermissionError):
        prov.get_lineage(store, a["artifact_id"], viewer_user_id=BOB)


def test_ledger(store):
    _register(store, user=ALICE, kind="halves")
    ledger = prov.get_ledger(store, ALICE)
    assert ledger["user_id"] == ALICE
    assert len(ledger["artifacts"]) == 1
    assert ledger["reputation"] == {
        "user_id": ALICE, "false_claims": 0, "frivolous_challenges": 0,
    }
    assert prov.get_ledger(store, BOB)["artifacts"] == []  # honest empty


# -- contesting ---------------------------------------------------------------------------------


def test_dispute_verified_reattributes_and_costs_false_claim(store):
    a = _register(store, user=BOB, kind="halves")  # bob claimed creatorship
    dispute = prov.file_dispute(
        store, artifact_id=a["artifact_id"], challenger_user_id=ALICE,
        evidence="spotify verified artist, released 2019",
    )
    assert dispute["status"] == "open"
    assert store.get_artifact(a["artifact_id"])["disputed"] is True
    resolved = prov.resolve_dispute(
        store, dispute_id=dispute["dispute_id"], outcome="verified",
        resolution_note="evidence checks out",
    )
    assert resolved["status"] == "verified"
    updated = store.get_artifact(a["artifact_id"])
    assert updated["creator_user_id"] == ALICE
    assert updated["disputed"] is False
    assert store.get_reputation(BOB)["false_claims"] == 1  # reputation cost


def test_dispute_rejected_costs_challenger(store):
    a = _register(store, user=ALICE, kind="halves")
    dispute = prov.file_dispute(store, artifact_id=a["artifact_id"],
                                challenger_user_id=BOB, evidence="trust me")
    prov.resolve_dispute(store, dispute_id=dispute["dispute_id"], outcome="rejected")
    assert store.get_artifact(a["artifact_id"])["creator_user_id"] == ALICE
    assert store.get_artifact(a["artifact_id"])["disputed"] is False
    assert store.get_reputation(BOB)["frivolous_challenges"] == 1


def test_dispute_ambiguous_freezes_reach(store):
    a = _register(store, user=ALICE, kind="halves")
    prov.log_event(store, artifact_id=a["artifact_id"], type="saved", actor_user_id=BOB)
    before = store.get_artifact(a["artifact_id"])["reach_cached"]
    assert before == pytest.approx(5.0)
    dispute = prov.file_dispute(store, artifact_id=a["artifact_id"],
                                challenger_user_id=BOB, evidence="unclear")
    # More engagement arrives while disputed...
    prov.log_event(store, artifact_id=a["artifact_id"], type="shared", actor_user_id=BOB)
    prov.resolve_dispute(store, dispute_id=dispute["dispute_id"], outcome="disputed",
                         resolution_note="needs more evidence")
    frozen = store.get_artifact(a["artifact_id"])
    assert frozen["disputed"] is True
    assert frozen["reach_cached"] == pytest.approx(before)  # frozen, not 11.0
