"""High-level provenance operations.

This is the seam other subsystems call:
- mint/derive/event/dispute flows for the API routes,
- `identify_upload()` for the intake pipeline (uploads, bookmarklet captures,
  imports): fingerprint at ingestion with the three outcomes
  (exact -> dedup link, near -> suggest derivation for confirmation,
  none -> register as imported, importer recorded as custodian).

Visibility & consent (spec §8): unlisted at creation; the mint act flips to
private; public is always explicit. Private artifacts are visible only to
their creator/custodian; private remixes render as anonymized stubs in
other users' lineage views.
"""

from __future__ import annotations

import base64
from typing import Any

from . import c2pa
from .fingerprints import NEAR_THRESHOLD, fingerprint_image, phash_distance
from .reach import (
    ancestors,
    compute_reach,
    perspective_reach,
    recompute_all,
    recompute_upward,
    refresh_reach,
)
from .store import LINK_STATUSES, ProvenanceStore

EVENT_TYPES = (
    "minted", "viewed", "saved", "shared",
    "remixed", "response_minted", "journal_sparked",
)


def _decode_image(image_base64: str) -> bytes:
    raw = image_base64.strip()
    if "," in raw and raw.startswith("data:"):
        raw = raw.split(",", 1)[1]
    try:
        return base64.b64decode(raw, validate=True)
    except Exception as exc:
        raise ValueError("image_base64 is not valid base64") from exc


def can_view(artifact: dict[str, Any], viewer_user_id: str | None) -> bool:
    """Private artifacts are visible only to creator/custodian."""
    if artifact["visibility"] != "private":
        return True
    return viewer_user_id in (artifact["creator_user_id"], artifact["custodian_user_id"])


def anonymized_stub(artifact_id: str) -> dict[str, Any]:
    """What a private remix looks like in someone else's lineage view:
    an anonymized stub — never content or identity (spec §8)."""
    return {
        "artifact_id": artifact_id,
        "stub": True,
        "label": "private remix",
        "visibility": "private",
    }


# -- registration / minting -------------------------------------------------


def register_artifact(
    store: ProvenanceStore,
    *,
    image_base64: str,
    creator_user_id: str,
    title: str = "",
    description: str = "",
    archetype_cast: list[str] | None = None,
    source_hash: str | None = None,
    remix_policy: str = "open",
    # Phase 4 (tier enforcement): passed through to the artifact
    # row. None = unlabeled; callers that know the artifact's tier
    # (e.g. the quote-card path) must pass it explicitly.
    tier: str | None = None,
) -> dict[str, Any]:
    """Register a new artifact (creation -> unlisted). Logs the `minted` event
    (weight 0 — creation isn't reach)."""
    data = _decode_image(image_base64)
    fp = fingerprint_image(data)  # raises ValueError on bad input
    manifest = c2pa.embed_manifest(data, artifact_id="pending", creator=creator_user_id)
    artifact = store.create_artifact(
        creator_user_id=creator_user_id,
        custodian_user_id=creator_user_id,
        title=title,
        description=description,
        archetype_cast=archetype_cast,
        source_hash=source_hash,
        modality="image",
        phash=fp.phash,
        sha256=fp.sha256,
        visibility="unlisted",
        remix_policy=remix_policy,
        imported=False,
        creator_declared=True,
        c2pa_manifest=manifest,
        tier=tier,
    )
    store.log_event(artifact["artifact_id"], "minted", actor_user_id=creator_user_id)
    return artifact


def mint_artifact(store: ProvenanceStore, artifact_id: str, user_id: str) -> dict[str, Any]:
    """The mint act: flips an unlisted artifact to private (spec §8).
    Creator (or custodian) only."""
    artifact = store.get_artifact(artifact_id)
    if artifact is None:
        raise KeyError(f"unknown artifact: {artifact_id}")
    if user_id not in (artifact["creator_user_id"], artifact["custodian_user_id"]):
        raise PermissionError("only the creator/custodian can mint this artifact")
    return store.update_artifact(artifact_id, minted=True, visibility="private")


def publish_artifact(store: ProvenanceStore, artifact_id: str, user_id: str) -> dict[str, Any]:
    """Going public is always an explicit user action. Creator/custodian only."""
    artifact = store.get_artifact(artifact_id)
    if artifact is None:
        raise KeyError(f"unknown artifact: {artifact_id}")
    if user_id not in (artifact["creator_user_id"], artifact["custodian_user_id"]):
        raise PermissionError("only the creator/custodian can publish this artifact")
    return store.update_artifact(artifact_id, visibility="public")


# -- derivation ---------------------------------------------------------------


def derive_artifact(
    store: ProvenanceStore,
    *,
    parent_ids: list[str],
    image_base64: str | None,
    actor_user_id: str,
    title: str = "",
    description: str = "",
    archetype_cast: list[str] | None = None,
) -> dict[str, Any]:
    """Register a child artifact with parent link(s).

    The deriver is the child's creator (they made something new). For each
    parent: under remix_policy=open the link is live immediately; under
    approval the link stays pending until the parent creator approves — no
    upstream reach flows while pending (spec §8). The `remixed` event on the
    parent is logged only once the link is live.
    """
    if not parent_ids:
        raise ValueError("derive requires at least one parent_id")
    data = _decode_image(image_base64) if image_base64 else None
    fp = fingerprint_image(data) if data else None
    child = store.create_artifact(
        creator_user_id=actor_user_id,
        custodian_user_id=actor_user_id,
        title=title,
        description=description,
        archetype_cast=archetype_cast,
        modality="image" if data else "image",
        phash=fp.phash if fp else None,
        sha256=fp.sha256 if fp else None,
        visibility="unlisted",
        remix_policy="open",
        imported=False,
        creator_declared=True,
    )
    store.log_event(child["artifact_id"], "minted", actor_user_id=actor_user_id)
    links = []
    for parent_id in parent_ids:
        parent = store.get_artifact(parent_id)
        if parent is None:
            raise KeyError(f"unknown parent artifact: {parent_id}")
        needs_approval = (
            parent["remix_policy"] == "approval"
            and actor_user_id != parent["creator_user_id"]
        )
        link = store.add_link(
            child["artifact_id"], parent_id,
            status="pending" if needs_approval else "linked",
        )
        links.append(link)
        if not needs_approval:
            store.log_event(
                parent_id, "remixed", actor_user_id=actor_user_id,
                context={"child_id": child["artifact_id"]},
            )
    recompute_upward(store, child["artifact_id"])
    return {"artifact": child, "links": links}


def approve_derivation(
    store: ProvenanceStore, *, parent_id: str, child_id: str, user_id: str
) -> dict[str, Any]:
    """Parent creator approves a pending derivation: the link goes live, the
    `remixed` event lands on the parent, and upstream reach starts flowing."""
    parent = store.get_artifact(parent_id)
    if parent is None:
        raise KeyError(f"unknown parent artifact: {parent_id}")
    if user_id != parent["creator_user_id"]:
        raise PermissionError("only the parent creator can approve derivations")
    link = store.get_link(child_id, parent_id)
    if link is None:
        raise KeyError("no such derivation link")
    store.set_link_status(child_id, parent_id, "linked")
    child = store.get_artifact(child_id)
    store.log_event(
        parent_id, "remixed",
        actor_user_id=child["custodian_user_id"] if child else None,
        context={"child_id": child_id},
    )
    recompute_upward(store, parent_id)
    return store.get_link(child_id, parent_id)


def confirm_derivation_link(
    store: ProvenanceStore, *, child_id: str, parent_id: str, user_id: str
) -> dict[str, Any]:
    """Confirm a near-match suggestion from ingest: graft the import onto the
    tree. Respects the parent's remix policy (approval -> pending)."""
    child = store.get_artifact(child_id)
    if child is None:
        raise KeyError(f"unknown artifact: {child_id}")
    if user_id not in (child["creator_user_id"], child["custodian_user_id"]):
        raise PermissionError("only the importer can confirm this link")
    parent = store.get_artifact(parent_id)
    if parent is None:
        raise KeyError(f"unknown parent artifact: {parent_id}")
    needs_approval = (
        parent["remix_policy"] == "approval"
        and user_id != parent["creator_user_id"]
    )
    link = store.add_link(child_id, parent_id,
                          status="pending" if needs_approval else "linked")
    if not needs_approval:
        store.log_event(
            parent_id, "remixed", actor_user_id=user_id,
            context={"child_id": child_id},
        )
        recompute_upward(store, parent_id)
    return link


# -- events ---------------------------------------------------------------------


def log_event(
    store: ProvenanceStore,
    *,
    artifact_id: str,
    type: str,
    actor_user_id: str | None = None,
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if type not in EVENT_TYPES:
        raise ValueError(f"unknown event type: {type}")
    if store.get_artifact(artifact_id) is None:
        raise KeyError(f"unknown artifact: {artifact_id}")
    event = store.log_event(artifact_id, type, actor_user_id=actor_user_id, context=context)
    recompute_upward(store, artifact_id)
    return event


# -- ingest: fingerprint at ingestion ---------------------------------------------


def identify_upload(
    store: ProvenanceStore,
    *,
    image_base64: str,
    user_id: str,
    title: str = "",
    description: str = "",
    claim_creator: bool = False,
    declared_parent_ids: list[str] | None = None,
) -> dict[str, Any]:
    """Fingerprint an imported image at ingestion. Three outcomes (spec §5):

    - exact  -> dedup: return the existing artifact, register nothing new.
    - near   -> re-identify: register as imported (importer = custodian,
                creator only if claim_creator) and suggest the nearest artifact
                as a derivation parent for confirmation.
    - none   -> register fresh as imported.

    `declared_parent_ids` links the new artifact to declared parents
    (e.g. the prompt pack it was rendered from), respecting each parent's
    remix policy. Not applied on exact (dedup) — never reparent an
    artifact that already exists.

    Also harvests C2PA/EXIF hints as free provenance.
    """
    data = _decode_image(image_base64)
    fp = fingerprint_image(data)
    hints = c2pa.harvest_hints(data)

    for parent_id in declared_parent_ids or []:
        if store.get_artifact(parent_id) is None:
            raise KeyError(f"unknown declared parent: {parent_id}")

    exact = store.find_by_sha256(fp.sha256)
    if exact is not None:
        return {"outcome": "exact", "artifact": exact, "hints": hints}

    best: dict[str, Any] | None = None
    best_dist = NEAR_THRESHOLD + 1
    for candidate in store.list_artifacts():
        if not candidate.get("phash"):
            continue
        dist = phash_distance(fp.phash, candidate["phash"])
        if dist < best_dist:
            best, best_dist = candidate, dist
    near = best if best_dist <= NEAR_THRESHOLD else None

    artifact = store.create_artifact(
        creator_user_id=user_id if claim_creator else None,
        custodian_user_id=user_id,
        title=title,
        description=description,
        modality="image",
        phash=fp.phash,
        sha256=fp.sha256,
        visibility="unlisted",
        remix_policy="open",
        imported=True,
        creator_declared=claim_creator,
    )
    store.log_event(artifact["artifact_id"], "minted", actor_user_id=user_id)
    result: dict[str, Any] = {
        "outcome": "near" if near else "none",
        "artifact": artifact,
        "hints": hints,
    }
    if near:
        result["suggested_parent"] = near
        result["suggested_distance"] = best_dist
    # Declared parents (e.g. the prompt pack an import was rendered from):
    # graft the new artifact onto them, respecting remix policy.
    linked_parents = []
    for parent_id in declared_parent_ids or []:
        link = confirm_derivation_link(
            store, child_id=artifact["artifact_id"],
            parent_id=parent_id, user_id=user_id,
        )
        linked_parents.append({"parent_id": parent_id, "status": link["status"]})
    if linked_parents:
        result["linked_parents"] = linked_parents
    return result


# -- lineage / ledger ---------------------------------------------------------------


def _visible_node(
    store: ProvenanceStore, artifact_id: str, viewer_user_id: str | None
) -> dict[str, Any]:
    artifact = store.get_artifact(artifact_id)
    if artifact is None:
        return anonymized_stub(artifact_id)
    if not can_view(artifact, viewer_user_id):
        return anonymized_stub(artifact_id)
    node = dict(artifact)
    node.pop("c2pa_manifest", None)
    return node


def get_lineage(
    store: ProvenanceStore, artifact_id: str, viewer_user_id: str | None
) -> dict[str, Any]:
    """Butterfly-effect view: the derivation tree rooted at this artifact plus
    a downstream timeline of engagement events. Private nodes the viewer may
    not see render as anonymized stubs (spec §8)."""
    root = store.get_artifact(artifact_id)
    if root is None:
        raise KeyError(f"unknown artifact: {artifact_id}")
    if not can_view(root, viewer_user_id):
        raise PermissionError("artifact is private")

    def build_tree(node_id: str, depth: int = 0, seen: set[str] | None = None) -> dict[str, Any]:
        seen = seen or set()
        node = _visible_node(store, node_id, viewer_user_id)
        if node.get("stub") or node_id in seen or depth > 12:
            node["children"] = []
            return node
        seen.add(node_id)
        children = []
        for link in store.children_of(node_id, linked_only=True):
            children.append(build_tree(link["child_id"], depth + 1, set(seen)))
        node["children"] = children
        node["engagement"] = _engagement_summary(store, node_id)
        return node

    tree = build_tree(artifact_id)

    # Downstream timeline: every event in the subtree, chronological.
    timeline: list[dict[str, Any]] = []
    stack = [artifact_id]
    visited: set[str] = set()
    while stack:
        node_id = stack.pop()
        if node_id in visited:
            continue
        visited.add(node_id)
        node = _visible_node(store, node_id, viewer_user_id)
        label = node.get("title") or ("private remix" if node.get("stub") else node_id[:8])
        for event in store.events_for(node_id):
            entry = dict(event)
            entry["artifact_label"] = label
            entry["artifact_stub"] = bool(node.get("stub"))
            timeline.append(entry)
        if not node.get("stub"):
            for link in store.children_of(node_id, linked_only=True):
                stack.append(link["child_id"])
    timeline.sort(key=lambda e: e["at"])
    return {"tree": tree, "timeline": timeline}


def _engagement_summary(store: ProvenanceStore, artifact_id: str) -> dict[str, int]:
    summary: dict[str, int] = {}
    for event in store.events_for(artifact_id):
        summary[event["type"]] = summary.get(event["type"], 0) + 1
    return summary


def get_ledger(store: ProvenanceStore, user_id: str) -> dict[str, Any]:
    """Per-user ledger: their artifacts, downstream reach, reputation."""
    artifacts = []
    for artifact in store.list_user_artifacts(user_id):
        entry = dict(artifact)
        entry.pop("c2pa_manifest", None)
        entry["engagement"] = _engagement_summary(store, artifact["artifact_id"])
        entry["children_count"] = len(store.children_of(artifact["artifact_id"], linked_only=True))
        artifacts.append(entry)
    return {
        "user_id": user_id,
        "perspective_reach": perspective_reach(store, user_id),
        "artifacts": artifacts,
        "reputation": store.get_reputation(user_id),
    }


# -- contesting -------------------------------------------------------------------------


def file_dispute(
    store: ProvenanceStore,
    *,
    artifact_id: str,
    challenger_user_id: str,
    evidence: str = "",
) -> dict[str, Any]:
    """Challenge a creatorship claim. Filing freezes the artifact's reach
    (disputed=1) until resolution. Returns the dispute record."""
    artifact = store.get_artifact(artifact_id)
    if artifact is None:
        raise KeyError(f"unknown artifact: {artifact_id}")
    if challenger_user_id == artifact["creator_user_id"]:
        raise ValueError("the recorded creator cannot dispute their own artifact")
    return store.file_dispute(artifact_id, challenger_user_id, evidence=evidence)


def resolve_dispute(
    store: ProvenanceStore,
    *,
    dispute_id: str,
    outcome: str,
    resolution_note: str = "",
) -> dict[str, Any]:
    """Resolve a creatorship dispute (admin action).

    - verified: re-attribute to the challenger; if the previous creator had
      explicitly claimed creatorship, that's a false claim (reputation cost).
    - rejected: record stands; the challenger pays a frivolous-challenge cost.
    - disputed: genuinely ambiguous — stays visible, both claims shown, reach
      stays frozen.
    """
    dispute = store.get_dispute(dispute_id)
    if dispute is None:
        raise KeyError(f"unknown dispute: {dispute_id}")
    if dispute["status"] != "open":
        raise ValueError(f"dispute already resolved: {dispute['status']}")
    artifact = store.get_artifact(dispute["artifact_id"])
    resolved = store.resolve_dispute(dispute_id, outcome, resolution_note=resolution_note)
    if artifact is None:
        return resolved
    if outcome == "verified":
        if artifact["creator_declared"] and artifact["creator_user_id"]:
            store.bump_reputation(artifact["creator_user_id"], "false_claims")
        store.update_artifact(
            artifact["artifact_id"],
            creator_user_id=dispute["challenger_user_id"],
            creator_declared=True,
            disputed=False,
        )
        refresh_reach(store, artifact["artifact_id"])
    elif outcome == "rejected":
        store.bump_reputation(dispute["challenger_user_id"], "frivolous_challenges")
        store.update_artifact(artifact["artifact_id"], disputed=False)
        refresh_reach(store, artifact["artifact_id"])
    # outcome == "disputed": stays disputed=1, reach frozen, both claims visible.
    return resolved


__all__ = [
    "EVENT_TYPES",
    "LINK_STATUSES",
    "ProvenanceStore",
    "anonymized_stub",
    "approve_derivation",
    "can_view",
    "compute_reach",
    "confirm_derivation_link",
    "derive_artifact",
    "file_dispute",
    "get_ledger",
    "get_lineage",
    "identify_upload",
    "log_event",
    "mint_artifact",
    "perspective_reach",
    "publish_artifact",
    "recompute_all",
    "recompute_upward",
    "refresh_reach",
    "register_artifact",
    "resolve_dispute",
    "ancestors",
]
