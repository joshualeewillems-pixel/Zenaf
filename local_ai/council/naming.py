"""Council archetype naming unlocks — per-archetype depth milestones.

Principle (Joshua): naming is intimate. You must know something deeply
before you can name it. Thresholds are per-archetype depth, not raw
signal counts.

Depth model: each approved training signal maps to one strand
(`map_signal_to_strand`). It contributes depth to every archetype equal
to that archetype's weight on the signal's strand — i.e. 1.0 depth point
per signal distributed across archetypes by the (signal strand x
archetype strand) dot product. A signal routing to Compass deepens the
Mentor (0.35 Compass) more than the Guardian (0.20 Compass). The Skeptic
uses its dynamically computed weights (`compute_skeptic_weights`).

Milestones (build plan §3):
- 25 depth points on one archetype  -> rename that seat
- 25 depth points on all 7          -> rename every seat
- 50 per archetype + 100 total      -> custom archetype creation (tracked,
                                      not yet implemented)
"""

from __future__ import annotations

import math

from local_ai.council.archetypes import (
    KEY_TO_PLAIN,
    compute_skeptic_weights,
    get_archetype,
    stock_archetype_ids,
)

#: Depth points on one archetype required to unlock renaming that seat.
RENAME_DEPTH_THRESHOLD = 25.0

#: Custom-archetype milestone: per-archetype and total depth (tracked only).
CUSTOM_ARCHETYPE_DEPTH_PER = 50.0
CUSTOM_ARCHETYPE_TOTAL = 100.0

#: Max length for a user-chosen archetype display name.
MAX_DISPLAY_NAME_LEN = 60


def _load_approved_signals() -> list:
    """Approved training signals scoped to the active identity license.

    Same pattern as compute_skeptic_weights: only signals re-anchored
    under the active license count. Never raises — returns [] on failure.
    """
    try:
        from local_ai.identity.service import get_license
        from local_ai.presence_ingest.store import PresenceStore

        lic = get_license()
        if lic is None or getattr(lic, "status", "") != "active":
            return []
        license_id = lic.license_id
        store = PresenceStore()
        try:
            sessions = {s.session_id: s for s in store.list_sessions()}
            out = []
            for sig in store.list_signals(status="approved"):
                sess = sessions.get(sig.session_id)
                prov = (sess.provenance if sess else {}) or {}
                if prov.get("license_id") == license_id:
                    out.append(sig)
            return out
        finally:
            store.close()
    except Exception:
        return []


def archetype_depths(user_id: str | None) -> dict[str, float]:
    """Per-archetype training depth for a user, in depth points.

    Each approved signal contributes depth to every archetype equal to
    that archetype's weight on the signal's strand. Returns 0.0 for every
    archetype when there is no user or no approved signals. Never raises.
    """
    depths: dict[str, float] = {aid: 0.0 for aid in stock_archetype_ids()}
    if not user_id:
        return depths
    try:
        signals = _load_approved_signals()
        if not signals:
            return depths

        # Resolve weight vectors (plain-spoken strand name -> weight).
        vectors: dict[str, dict[str, float]] = {}
        for aid in stock_archetype_ids():
            arch = get_archetype(aid)
            if arch is None:
                continue
            if arch.strand_weights is not None:
                vectors[aid] = arch.strand_weights
            else:
                # Skeptic: dynamic inverse of the user's dominant strands.
                vectors[aid] = compute_skeptic_weights(user_id)

        from local_ai.personality.depth import map_signal_to_strand

        for sig in signals:
            strand_key = map_signal_to_strand(sig)  # lowercase key or None
            if not strand_key:
                continue
            plain = KEY_TO_PLAIN.get(strand_key)
            if not plain:
                continue
            for aid, vec in vectors.items():
                depths[aid] += vec.get(plain, 0.0)
        return depths
    except Exception:
        return {aid: 0.0 for aid in stock_archetype_ids()}


def get_display_name(user_id: str | None, archetype_id: str) -> str:
    """The display name for an archetype seat: user custom or stock.

    Never raises — falls back to the stock name (or the id) on any failure.
    """
    arch = get_archetype(archetype_id)
    if arch is None:
        return (archetype_id or "").strip() or "Unknown"
    if not user_id:
        return arch.display_name
    try:
        from local_ai.personality.store import PersonalityStore

        store = PersonalityStore(user_id=user_id)
        try:
            custom = store.get_archetype_name(arch.id)
        finally:
            store.close()
        return custom or arch.display_name
    except Exception:
        return arch.display_name


def rename_status(user_id: str | None) -> dict:
    """Naming unlock status for every archetype, plus milestone progress.

    Plain data — JSON-serializable. Never raises.
    """
    depths = archetype_depths(user_id)
    entries = []
    for aid in stock_archetype_ids():
        d = depths.get(aid, 0.0)
        unlocked = d >= RENAME_DEPTH_THRESHOLD
        entries.append(
            {
                "id": aid,
                "display_name": get_display_name(user_id, aid),
                "depth": round(d, 1),
                "rename_unlocked": unlocked,
                "signals_to_unlock": (
                    0 if unlocked else max(0, math.ceil(RENAME_DEPTH_THRESHOLD - d))
                ),
            }
        )
    total = sum(depths.values())
    custom_ready = (
        all(d >= CUSTOM_ARCHETYPE_DEPTH_PER for d in depths.values())
        and total >= CUSTOM_ARCHETYPE_TOTAL
    )
    return {
        "archetypes": entries,
        "all_rename_unlocked": all(e["rename_unlocked"] for e in entries),
        "custom_archetype": {
            "unlocked": custom_ready,
            "depth_per_archetype": {
                aid: round(depths.get(aid, 0.0), 1) for aid in stock_archetype_ids()
            },
            "total_depth": round(total, 1),
            "required_per_archetype": CUSTOM_ARCHETYPE_DEPTH_PER,
            "required_total": CUSTOM_ARCHETYPE_TOTAL,
        },
        "rename_threshold": RENAME_DEPTH_THRESHOLD,
    }
