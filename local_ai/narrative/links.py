"""Cycle-safe traversal of thread containment links (Phase 3).

Audit Part XI constraint: any traversal of containment links MUST
prevent cycles or handle them explicitly. The store deliberately
does not walk links (``link_threads`` guards only self-containment),
so links stay inert until a caller uses this module — the single
sanctioned traversal. It terminates on cyclic fixtures by
construction: every visited thread id is recorded before its
neighbors are enqueued, so a cycle revisits nothing.

No production code traverses links yet; this module exists so the
discipline exists before the first traversal does.
"""

from __future__ import annotations

from collections import deque

from .store import NarrativeStore


def walk_links(
    store: NarrativeStore,
    user_id: str,
    start_thread_id: str,
    *,
    direction: str = "descendants",
) -> list[str]:
    """Thread ids reachable from ``start`` via containment links.

    ``direction="descendants"`` follows parent → child edges
    (``links_as_parent``); ``direction="ancestors"`` follows child
    → parent edges (``links_as_child``). Breadth-first, unique ids
    in visit order, start id excluded. Cyclic link graphs
    terminate: visited ids are never re-enqueued.
    """
    if direction not in ("descendants", "ancestors"):
        raise ValueError(
            f"unknown direction: {direction!r} "
            "(descendants | ancestors)"
        )
    if store.get_thread(user_id, start_thread_id) is None:
        raise ValueError(f"unknown thread: {start_thread_id!r}")
    visited = {start_thread_id}
    order: list[str] = []
    queue: deque[str] = deque([start_thread_id])
    while queue:
        current = queue.popleft()
        if direction == "descendants":
            neighbors = [
                link.child_thread_id
                for link in store.links_as_parent(user_id, current)
            ]
        else:
            neighbors = [
                link.parent_thread_id
                for link in store.links_as_child(user_id, current)
            ]
        for neighbor in neighbors:
            if neighbor in visited:
                continue
            visited.add(neighbor)
            order.append(neighbor)
            queue.append(neighbor)
    return order
