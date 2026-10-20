"""Compose a seat's "You" profile from its ground-truth stores.

Read model for the Zenaf/You switch and the per-seat QC surface ("what's
being fashioned"). Everything here is a REFERENCE assembled at read time:

  - familiarity/depth     → local_ai.council.naming.archetype_depths
                            (per-archetype depth points over approved signals)
  - approved signals      → canonical TrainingSignal store, license-scoped
                            exactly as the depth machinery scopes them
  - persona version       → PersonalityStore current published version
  - snapshots             → PersonalityStore snapshot METADATA + the pinned
                            snapshot_id stored on the You record (pointer)
  - recognition status    → DERIVED from keystone task completion in
                            vision_execution — never stored twice

The only writes live in YouProfileStore (the echo's own identity fields).
They are NOT gated: the user may name their echo or pin a snapshot at any
time. Keystone 4 gates exactly two things — (a) the identity REVEAL (the
character card's name/face/presentation, expressed here as `revealed`), and
(b) rentability (in the recognition block). Training runs continuously per
user approval, and the QC data below is visible from day one: watching the
You side being fashioned is the point of the switch.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable

from local_ai.council import archetypes, keystones as KD, naming
from local_ai.council.archetypes import KEY_TO_PLAIN, get_archetype
from local_ai.personality.depth import map_signal_to_strand
from local_ai.personality.temporal import find_parallels
from local_ai.vision_execution import keystone_seeding
from local_ai.vision_execution import service as ve

from .store import UNSET, YouProfileStore

#: Cap on approved signals returned in one QC payload (newest-weighted first).
SIGNAL_LIMIT = 50

#: Valences that record the user pushing back — divergences, not parallels.
DIVERGENCE_VALENCES = ("rejected", "corrected")


# --------------------------------------------------------------------------
# Recognition — derived from keystone tasks (ground truth: vision_execution)
# --------------------------------------------------------------------------


def _chain_order(tasks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Order a seat's keystone tasks by their dependency chain 1→2→3→4."""
    if not tasks:
        return []
    depended_on: dict[str, dict[str, Any]] = {}
    for task in tasks:
        for dep in task.get("dependency_ids") or []:
            depended_on[dep] = task
    roots = [t for t in tasks if not (t.get("dependency_ids") or [])]
    ordered: list[dict[str, Any]] = []
    seen: set[str] = set()
    current = roots[0] if roots else None
    while current is not None and current["id"] not in seen:
        ordered.append(current)
        seen.add(current["id"])
        current = depended_on.get(current["id"])
    for task in tasks:  # defensive: never drop a task on a broken chain
        if task["id"] not in seen:
            ordered.append(task)
            seen.add(task["id"])
    return ordered


def keystone_progress(user_id: str, archetype_id: str) -> dict[str, Any]:
    """Keystone completion for one seat, derived live from the task store."""
    total = len(KD.keystones_for(KD.SEATS[0]))
    empty = {
        "seeded": False,
        "keystones": [],
        "completed": 0,
        "total": total,
        "echo_complete": False,
        "status": "unmet",
        "rentable": False,
    }
    initiative = keystone_seeding.find_keystone_initiative(user_id)
    if initiative is None:
        return empty
    tasks: list[dict[str, Any]] = []
    for project in ve.list_projects(user_id):
        if project.get("initiative_id") != initiative["id"]:
            continue
        tasks.extend(ve.list_tasks(user_id, project_id=project["id"]))
    mine = [t for t in tasks if t.get("seat_ref") == archetype_id]
    if not mine:
        return empty
    ordered = _chain_order(mine)
    keystones = [
        {
            "index": i,
            "title": task.get("title") or "",
            "status": task.get("status") or "",
            "done": task.get("status") == "Done",
        }
        for i, task in enumerate(ordered)
    ]
    completed = sum(1 for k in keystones if k["done"])
    # Keystone 4 is the last task in the chain ("The echo").
    echo_complete = bool(keystones) and keystones[-1]["done"]
    status = (
        "recognized" if echo_complete else "meeting" if completed > 0 else "unmet"
    )
    return {
        "seeded": True,
        "keystones": keystones,
        "completed": completed,
        "total": len(keystones),
        "echo_complete": echo_complete,
        "status": status,
        "rentable": echo_complete,
    }


# --------------------------------------------------------------------------
# Signal mapping — which approved signals fashion this seat's echo
# --------------------------------------------------------------------------


def _seat_weights(user_id: str | None, archetype_id: str) -> dict[str, float]:
    arch = get_archetype(archetype_id)
    if arch is not None and arch.strand_weights is not None:
        return arch.strand_weights
    # Skeptic: dynamically computed inverse of the user's dominant strands.
    return archetypes.compute_skeptic_weights(user_id, mode="trained")


def seat_signals(
    signals: list, user_id: str | None, archetype_id: str
) -> list[dict[str, Any]]:
    """Approved signals that fashion this seat, strongest contribution first.

    Each entry carries the signal's own read-only anchor text (its redacted
    summary / payload — redaction happened at capture; nothing raw exists
    downstream) plus parallels (corroborating signals) and a divergence flag
    (the user rejected or corrected this reading).
    """
    weights = _seat_weights(user_id, archetype_id)
    mapped: list[tuple[float, Any]] = []
    for sig in signals:
        strand_key = map_signal_to_strand(sig)
        if not strand_key:
            continue
        plain = KEY_TO_PLAIN.get(strand_key)
        if not plain:
            continue
        contribution = float(weights.get(plain, 0.0))
        if contribution <= 0:
            continue
        mapped.append((contribution, sig))

    mapped.sort(key=lambda pair: (-pair[0], -int(getattr(pair[1], "ts_ms", 0) or 0)))
    sig_objs = [sig for _c, sig in mapped]

    out: list[dict[str, Any]] = []
    for contribution, sig in mapped[:SIGNAL_LIMIT]:
        parallels = find_parallels(sig, sig_objs)
        provenance = sig.provenance or {}
        out.append(
            {
                "signal_id": sig.signal_id,
                "summary": sig.summary,
                # The anchored text the reading rests on (already redacted).
                "anchor": (sig.payload_redacted or sig.summary or "").strip(),
                "layer": sig.layer,
                "zone": sig.zone,
                "valence": sig.valence,
                "kind": sig.kind,
                "ts_ms": sig.ts_ms,
                "session_id": sig.session_id,
                "source": provenance.get("source"),
                "contribution": round(contribution, 4),
                "parallels": len(parallels),
                "is_divergence": sig.valence in DIVERGENCE_VALENCES,
            }
        )
    return out


def _default_signals() -> list:
    """Approved signals license-scoped exactly as the depth machinery does."""
    return naming._load_approved_signals()


# --------------------------------------------------------------------------
# The composed profile
# --------------------------------------------------------------------------


class YouProfileService:
    """Composes and updates per-seat You profiles. Stores are injectable."""

    def __init__(
        self,
        *,
        you_store: YouProfileStore | None = None,
        personality_store_factory: Callable[[str], Any] | None = None,
        signals_provider: Callable[[], list] | None = None,
    ) -> None:
        self._you_store = you_store or YouProfileStore()
        self._personality_store_factory = personality_store_factory
        self._signals_provider = signals_provider or _default_signals

    def _personality_store(self, user_id: str):
        if self._personality_store_factory is not None:
            return self._personality_store_factory(user_id)
        from local_ai.personality.store import PersonalityStore

        return PersonalityStore(user_id=user_id)

    # -- read ---------------------------------------------------------------

    def get_profile(self, user_id: str, archetype_id: str) -> dict[str, Any]:
        """The full switch + QC payload for one seat. Never raises on
        missing stores — absent evidence reads as honest zeros/empties."""
        arch = get_archetype(archetype_id)
        if arch is None:
            raise ValueError(f"Unknown archetype: {archetype_id!r}")
        seat = next(
            (s for s in KD.SEATS if s["seat_ref"] == archetype_id), None
        )
        record = self._you_store.get(user_id, archetype_id) or {}
        recognition = keystone_progress(user_id, archetype_id)
        unlocked = bool(recognition["echo_complete"])

        depths = naming.archetype_depths(user_id)
        depth_points = round(float(depths.get(archetype_id, 0.0)), 1)

        signals = self._signals_provider()
        fashioned = seat_signals(signals, user_id, archetype_id)

        persona_version: int | None = None
        version_count = 0
        snapshots: list[dict[str, Any]] = []
        pinned_snapshot: dict[str, Any] | None = None
        store = self._personality_store(user_id)
        try:
            current = store.get_current()
            if current is not None:
                persona_version = current.version
            version_count = store.version_count()
            snapshots = [
                {
                    "snapshot_id": s.get("snapshot_id"),
                    "version": s.get("version"),
                    "trigger": s.get("trigger"),
                    "era_name": s.get("era_name"),
                    "label": s.get("auto_label"),
                    "created_at": s.get("created_at"),
                }
                for s in store.list_snapshots()
            ]
            pinned_id = record.get("current_snapshot_id")
            if pinned_id:
                snap = store.get_snapshot(pinned_id)
                if snap is not None:
                    pinned_snapshot = {
                        "snapshot_id": snap.snapshot_id,
                        "version": snap.version,
                        "trigger": snap.trigger,
                        "era_name": snap.era_name,
                        "label": snap.auto_label,
                        "created_at": snap.created_at.isoformat()
                        if isinstance(snap.created_at, datetime)
                        else snap.created_at,
                    }
        finally:
            store.close()

        return {
            "archetype_id": archetype_id,
            "zenaf": {
                "character": seat["character"] if seat else arch.display_name,
                "seat_name": naming.get_display_name(user_id, archetype_id),
                "demeanor": seat["demeanor"] if seat else "",
                "voice_color": archetypes.voice_color(archetype_id),
                # The switch renders the Zenaf side with the base voice.
                "mode": "base",
                "has_training": depth_points > 0,
            },
            "you": {
                # The switch renders the You side with the trained voice —
                # the same trained rendering /voice/chat and
                # /conversation/turn already serve for mode="trained".
                "mode": "trained",
                # `revealed` is PRESENTATIONAL, not a data gate: keystone 4
                # ("The echo") is where the echo's card — name, face, full
                # character presentation — is unveiled to the user. The
                # record itself is the user's own and readable (and writable)
                # from day one; the card stays blank until recognition.
                "revealed": unlocked,
                "state": "recognized" if unlocked else "unmet",
                "personal_name": record.get("personal_name"),
                "avatar_ref": record.get("avatar_ref"),
                "current_snapshot_id": record.get("current_snapshot_id"),
                "pinned_snapshot": pinned_snapshot,
            },
            "recognition": recognition,
            "fashioning": {
                "depth_points": depth_points,
                "milestones": {
                    "avatar_threshold": naming.AVATAR_DEPTH_THRESHOLD,
                    "avatar_unlocked": depth_points >= naming.AVATAR_DEPTH_THRESHOLD,
                    "rename_threshold": naming.RENAME_DEPTH_THRESHOLD,
                    "rename_unlocked": depth_points
                    >= naming.RENAME_DEPTH_THRESHOLD,
                },
                "approved_signals": fashioned,
                "signal_total": len(fashioned),
                "persona_version": persona_version,
                "persona_version_count": version_count,
                "snapshots": snapshots,
            },
        }

    # -- write (ungated; the reveal is presentational) ------------------------

    def update_profile(
        self,
        user_id: str,
        archetype_id: str,
        *,
        personal_name: Any = UNSET,
        avatar_ref: Any = UNSET,
        current_snapshot_id: Any = UNSET,
    ) -> dict[str, Any]:
        """Set the echo's identity fields. NOT gated on keystone 4.

        Keystone 4 gates the card reveal and rentability — not the record.
        The user can name their echo, set its avatar reference, or pin a
        snapshot from day one (the name is usually co-given in the
        recognition conversation, but the store doesn't police ceremony).
        Raises ValueError on bad input, including a snapshot pointer that
        doesn't resolve.
        """
        arch = get_archetype(archetype_id)
        if arch is None:
            raise ValueError(f"Unknown archetype: {archetype_id!r}")
        if current_snapshot_id is not UNSET and current_snapshot_id is not None:
            store = self._personality_store(user_id)
            try:
                if store.get_snapshot(str(current_snapshot_id)) is None:
                    raise ValueError(
                        f"Unknown snapshot: {current_snapshot_id!r} "
                        "(the pin is a pointer — it must resolve)"
                    )
            finally:
                store.close()
        cleaned_name = personal_name
        if isinstance(personal_name, str):
            cleaned_name = personal_name.strip() or None
        record = self._you_store.upsert(
            user_id,
            archetype_id,
            personal_name=cleaned_name,
            avatar_ref=avatar_ref,
            current_snapshot_id=current_snapshot_id,
        )
        return record
