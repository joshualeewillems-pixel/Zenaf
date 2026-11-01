"""Progression oversight: visibility, proposal, verdict routing (Phase 7, addendum I1).

Oversight consists of three named, deterministic functions. Each
is a pure function over store rows: no generation, no text
inference, no model call. Each output is a PROPOSAL through the
review layer — never a command, never a decision, never a state
change. Confirming an oversight proposal changes no thread,
reading, or branch state (the store enforces this by having no
transition for it); the confirmed row is a confirmed observation
the user may act on, nothing more.

Detectors (all take an explicit ``now`` so fixtures control time;
production callers pass the current time):

- **stall**: an active thread with no new evidence and no
  confirmed change inside the window. Silence, measured
  against the thread's own trajectory — not against other
  threads, and never against an assumed pace.
- **conflict**: two active threads sharing an entity ref while
  holding different standing readings. A development in one
  commitment touching another commitment's evidence, with
  incompatible standing interpretations — worth surfacing,
  not worth auto-resolving. One proposal per unordered pair,
  attached to the earlier thread id.
- **drift** (aspiration-drift proxy, stated honestly): an
  active thread with a standing reading whose recent evidence
  shares NO entity ref with its founding evidence, while
  recent evidence exists (movement, not silence — silence is
  stall's job). This measures the story moving away from what
  it was founded on, which is the observable half of
  aspiration-drift. Whether that movement still serves the
  aspiration the thread was understood to serve is NOT
  something a ref-disjointness check can judge — that
  judgment is exactly what the user verdict on the proposal
  is for. The detector proposes; it does not conclude.

Windows are parameters (default 30 days), not walkthrough
thresholds: they tune a detector's sensitivity, they do not
move any flag default or authorize any disclosure.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from .models import OversightProposal
from .store import NarrativeStore

#: Default detector window (days). A parameter, not a decision:
#: callers — and tests — pass explicit windows; nothing in
#: this module treats the default as ratified.
DEFAULT_WINDOW_DAYS = 30


def _parse_ts(value: str | None) -> datetime | None:
    """Parse a store timestamp, or None when unparseable.

    Unparseable timestamps count as NOT recent: a detector
    may not claim recency it cannot show.
    """
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _entity_refs(store: NarrativeStore, user_id: str, thread_id: str) -> set[str]:
    return {
        row.entity_ref
        for row in store.evidence_for(user_id, thread_id)
        if row.entity_ref
    }


def _recent_refs(
    store: NarrativeStore,
    user_id: str,
    thread_id: str,
    cutoff: datetime,
) -> tuple[set[str], set[str]]:
    """(recent entity refs, founding entity refs) for a thread.

    Recent = evidence created at or after the cutoff; founding
    = evidence created before it. Rows with unparseable
    timestamps land in founding: they are old by the only
    reading the detector can defend.
    """
    recent: set[str] = set()
    founding: set[str] = set()
    for row in store.evidence_for(user_id, thread_id):
        if not row.entity_ref:
            continue
        created = _parse_ts(row.created_at)
        if created is not None and created >= cutoff:
            recent.add(row.entity_ref)
        else:
            founding.add(row.entity_ref)
    return recent, founding


def detect_stall(
    store: NarrativeStore,
    user_id: str,
    thread_id: str,
    *,
    window_days: int = DEFAULT_WINDOW_DAYS,
    now: str | None = None,
) -> dict | None:
    """Stall observation for one thread, or None.

    Fires only for ACTIVE threads: a dormant, resolved, or
    retired thread is not stalled, it is finished or resting
    by its own status. Activity = new evidence or a confirmed
    change inside the window; the thread's own creation is
    the baseline when it has neither.
    """
    thread = store.get_thread(user_id, thread_id)
    if thread is None or thread.status != "active":
        return None
    moment = _parse_ts(now) or _parse_ts(_now_iso())
    assert moment is not None
    cutoff = moment - timedelta(days=window_days)
    # Story activity only: evidence + confirmed changes. The
    # thread's creation time is the baseline ONLY when the
    # thread has neither — otherwise a thread created today
    # around old evidence would never read as stalled.
    latest: datetime | None = None
    for row in store.evidence_for(user_id, thread_id):
        created = _parse_ts(row.created_at)
        if created is not None and (latest is None or created > latest):
            latest = created
    for change in store.changes_for(user_id, thread_id):
        if change.status != "confirmed":
            continue
        created = _parse_ts(change.created_at)
        if created is not None and (latest is None or created > latest):
            latest = created
    if latest is None:
        latest = _parse_ts(thread.created_at)
    if latest is not None and latest >= cutoff:
        return None
    return {
        "kind": "stall",
        "reason": (
            f"thread {thread_id!r} is active with no new "
            f"evidence and no confirmed change in the last "
            f"{window_days} days"
        ),
        "detail": {
            "window_days": window_days,
            "last_activity_at": (
                latest.isoformat() if latest is not None else None
            ),
        },
    }


def detect_conflicts(
    store: NarrativeStore,
    user_id: str,
) -> list[dict]:
    """Conflict observations over active-thread pairs.

    Two active threads conflict, for oversight purposes, when
    they share an entity ref while holding DIFFERENT standing
    readings: the same commitment-evidence under incompatible
    standing interpretations. Shared refs with identical or
    absent standing readings are not conflicts — agreement
    and absence are not problems to surface. Structural, not
    windowed: no time parameter.
    """
    active = [
        t
        for t in store.threads_for(user_id, limit=None)
        if t.status == "active"
        and t.standing_reading_id is not None
    ]
    refs_by_thread = {
        t.id: _entity_refs(store, user_id, t.id) for t in active
    }
    observations: list[dict] = []
    for i, first in enumerate(active):
        for second in active[i + 1 :]:
            if first.standing_reading_id == second.standing_reading_id:
                continue
            shared = refs_by_thread[first.id] & refs_by_thread[second.id]
            if not shared:
                continue
            observations.append({
                "kind": "conflict",
                "thread_id": first.id,
                "reason": (
                    f"threads {first.id!r} and {second.id!r} "
                    f"share evidence {sorted(shared)} while "
                    f"holding different standing readings"
                ),
                "detail": {
                    "other_thread_id": second.id,
                    "shared_entity_refs": sorted(shared),
                    "standing_reading_ids": [
                        first.standing_reading_id,
                        second.standing_reading_id,
                    ],
                },
            })
    return observations


def detect_drift(
    store: NarrativeStore,
    user_id: str,
    thread_id: str,
    *,
    window_days: int = DEFAULT_WINDOW_DAYS,
    now: str | None = None,
) -> dict | None:
    """Drift observation for one thread, or None.

    Fires only for ACTIVE threads with a standing reading,
    with non-empty recent evidence AND non-empty founding
    evidence, where the two ref sets are disjoint. Empty
    recent evidence is stall's signal, not drift's; empty
    founding evidence means there is nothing to have drifted
    from. See the module docstring for the proxy limitation:
    the detector shows movement away from founding evidence;
    the user verdict judges whether the aspiration is still
    served.
    """
    thread = store.get_thread(user_id, thread_id)
    if thread is None or thread.status != "active":
        return None
    if thread.standing_reading_id is None:
        return None
    moment = _parse_ts(now) or _parse_ts(_now_iso())
    assert moment is not None
    cutoff = moment - timedelta(days=window_days)
    recent, founding = _recent_refs(store, user_id, thread_id, cutoff)
    if not recent or not founding:
        return None
    if recent & founding:
        return None
    return {
        "kind": "drift",
        "reason": (
            f"thread {thread_id!r} has a standing reading, but "
            f"its recent evidence shares no entity ref with "
            f"its founding evidence"
        ),
        "detail": {
            "window_days": window_days,
            "recent_entity_refs": sorted(recent),
            "founding_entity_refs": sorted(founding),
            "standing_reading_id": thread.standing_reading_id,
        },
    }


def detect_oversight(
    store: NarrativeStore,
    user_id: str,
    *,
    window_days: int = DEFAULT_WINDOW_DAYS,
    now: str | None = None,
) -> list[OversightProposal]:
    """Run all three detectors; write proposals (deduped).

    Returns the proposals ensured by this run — newly created
    or already-proposed for the same (thread, kind). Detectors
    never write branch state and never spend a generation;
    the proposals surface through the review layer, where a
    user verdict confirms or dismisses each observation.
    """
    ensured: list[OversightProposal] = []
    for thread in store.threads_for(user_id, limit=None):
        for observation in (
            detect_stall(
                store, user_id, thread.id,
                window_days=window_days, now=now,
            ),
            detect_drift(
                store, user_id, thread.id,
                window_days=window_days, now=now,
            ),
        ):
            if observation is None:
                continue
            ensured.append(
                store.create_oversight_proposal(
                    user_id,
                    thread.id,
                    observation["kind"],
                    reason=observation["reason"],
                    detail=observation["detail"],
                )
            )
    for observation in detect_conflicts(store, user_id):
        ensured.append(
            store.create_oversight_proposal(
                user_id,
                observation["thread_id"],
                observation["kind"],
                reason=observation["reason"],
                detail=observation["detail"],
            )
        )
    return ensured
