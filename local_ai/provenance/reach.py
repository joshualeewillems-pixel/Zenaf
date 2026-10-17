"""Reach: marking value accumulation on the butterfly effect.

reach(A) = SUM weight(type(e)) * decay^dist(A, artifact(e))
           over all events e in A's downstream subtree (linked edges only).

Weights (Joshua 2026-10-17; tunable):
    viewed 0.1 (significantly nominal, provisional), saved 5, shared 6,
    remixed 10, response_minted 10, journal_sparked 14, minted 0.
Decay: 0.6^d — direct engagement counts in full; a grandchild's engagement
credits the ancestor at 0.36. Remixes keep most of their own reach;
ancestors collect a meaningful tithe.

Per-artifact reach is cached in the registry and recomputed when a new
event lands in its subtree (i.e. on the artifact or any descendant):
recompute_upward() walks ancestors and refreshes each. A disputed artifact
keeps its cached score (reach frozen) until the dispute resolves.

per-user perspective_reach = SUM reach over artifacts they created — the
long-term pricing input for the doppelganger marketplace.
"""

from __future__ import annotations

from collections import deque
from datetime import datetime, timezone

from .store import ProvenanceStore

#: Engagement weights, spec §4 (Joshua 2026-10-17). Unknown types weigh 0.
WEIGHTS: dict[str, float] = {
    "viewed": 0.1,
    "saved": 5.0,
    "shared": 6.0,
    "remixed": 10.0,
    "response_minted": 10.0,
    "journal_sparked": 14.0,
    "minted": 0.0,
}

#: Reach decay per hop downstream.
DECAY = 0.6


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def downstream_distances(store: ProvenanceStore, root_id: str) -> dict[str, int]:
    """Shortest downstream distance (in linked edges) from root to every node
    in its subtree, including root itself at distance 0."""
    distances: dict[str, int] = {root_id: 0}
    queue: deque[str] = deque([root_id])
    while queue:
        node = queue.popleft()
        for link in store.children_of(node, linked_only=True):
            child = link["child_id"]
            if child not in distances:
                distances[child] = distances[node] + 1
                queue.append(child)
    return distances


def compute_reach(store: ProvenanceStore, artifact_id: str) -> float:
    """Compute (not cache) reach for one artifact over its downstream subtree."""
    artifact = store.get_artifact(artifact_id)
    if artifact is None:
        raise KeyError(f"unknown artifact: {artifact_id}")
    if artifact["disputed"]:
        # Reach frozen while a creatorship dispute is open.
        return float(artifact["reach_cached"])
    distances = downstream_distances(store, artifact_id)
    total = 0.0
    for node_id, dist in distances.items():
        for event in store.events_for(node_id):
            total += WEIGHTS.get(event["type"], 0.0) * (DECAY ** dist)
    return total


def refresh_reach(store: ProvenanceStore, artifact_id: str) -> float:
    """Recompute and cache reach for one artifact. Returns the new score."""
    score = compute_reach(store, artifact_id)
    artifact = store.get_artifact(artifact_id)
    if artifact is not None and not artifact["disputed"]:
        store.update_artifact(
            artifact_id, reach_cached=score, reach_updated_at=_now_iso()
        )
    return score


def ancestors(store: ProvenanceStore, artifact_id: str) -> list[str]:
    """All ancestors of an artifact (transitively, linked edges), nearest first."""
    seen: list[str] = []
    queue: deque[str] = deque([artifact_id])
    visited = {artifact_id}
    while queue:
        node = queue.popleft()
        for link in store.parents_of(node, linked_only=True):
            parent = link["parent_id"]
            if parent not in visited:
                visited.add(parent)
                seen.append(parent)
                queue.append(parent)
    return seen


def recompute_upward(store: ProvenanceStore, artifact_id: str) -> dict[str, float]:
    """Recompute cached reach for an artifact and all its ancestors.

    Call after any event logged on the artifact, or after a derivation link
    becomes linked (creation with open policy, or approval under the approval
    policy). Returns {artifact_id: new_score}.
    """
    scores: dict[str, float] = {}
    for node_id in [artifact_id, *ancestors(store, artifact_id)]:
        scores[node_id] = refresh_reach(store, node_id)
    return scores


def recompute_all(store: ProvenanceStore) -> int:
    """Batch recompute cached reach for every undisputed artifact."""
    count = 0
    for artifact in store.list_artifacts():
        if not artifact["disputed"]:
            refresh_reach(store, artifact["artifact_id"])
            count += 1
    return count


def perspective_reach(store: ProvenanceStore, user_id: str) -> float:
    """Sum of cached reach over artifacts the user created."""
    total = 0.0
    for artifact in store.list_user_artifacts(user_id):
        if artifact["creator_user_id"] == user_id:
            total += float(artifact["reach_cached"])
    return total
