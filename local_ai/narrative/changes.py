"""Narrative Steward Phase 3 — change recognition detectors.

Deterministic, generation-free detectors over fellowship events and
thread state. Every detector produces ``thread_changes`` PROPOSALS
(status ``proposed``) through the Phase 1 review wiring — never
silent state edits, never auto-execution. A confirmed change is a
user verdict away; a rejected one is dismissed, not deleted.

Detectors, in precedence order for one event (first match wins per
thread — an event yields at most one change per thread):

1. **Verdict change** (``claim_decided``): the claim is thread
   evidence. When the verdict rejects a claim the thread's standing
   reading cites, the change is ``contradicted`` (the verdict
   undercuts the reading's support, prior reading linked); any other
   verdict on thread evidence is ``extended`` (new verdict
   information about the interpretation, by construction).
2. **Milestone** (``task_completed``, ``decision_recorded``): the
   event's entity ref matches a live thread's evidence entity ref.
   Dormant threads take the recurrence branch instead (below) — a
   dormant story moving again is a reopening first.
3. **Recurrence / reopening** (any event carrying an entity ref):
   the entity ref matches a DORMANT thread's evidence entity ref.
   Retired, archived, and resolved threads never reopen quietly:
   reopening one is a user act, not a detector's.

Dedupe: a thread with an already-``proposed`` change of the same
kind is skipped — one item in the review queue per movement, not
one per re-analysis. Re-analysis with no new evidence yields zero
proposals twice over: the store's anti-manufacture rule (invariant
2) refuses a change citing only already-attached evidence, and
the detectors catch that refusal as "already recorded".

Retirement proposals (not event-driven):

- ``detect_outgrown``: an active thread with no new evidence in
  the decay window. The proposal cites the absence pattern (window
  + last-evidence timestamp, both verified by the store) plus the
  last confirming evidence row. See ``store.record_change`` for
  the structural-basis rule.
- ``propose_reinterpretation``: an explicit proposal that a
  thread's evidence now belongs to a successor thread. The
  successor link is the basis; both threads' readings are
  preserved, never moved.

No generation happens anywhere here: no ``generate_fn`` parameter
exists, and nothing in this module imports generation machinery.
Discovery lives in :mod:`discovery`; link traversal in
:mod:`links`.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from local_ai.fellowship.events import (
    CLAIM_DECIDED,
    DECISION_RECORDED,
    TASK_COMPLETED,
    FellowshipEvent,
)

from .models import NarrativeThread, ThreadChange
from .refs import SourceRef
from .store import NarrativeStore

logger = logging.getLogger(__name__)

#: Default decay window for the outgrown detector (audit Part II §5:
#: parallels cease across the decay window). Tests pass short
#: windows; production uses the 180-day machinery's window.
DEFAULT_OUTGROWN_WINDOW_DAYS = 180

#: Thread statuses a detector may propose a change for. Nascent
#: threads are proposals themselves; resolved/retired/archived
#: threads are finished business — detectors never revive them.
_LIVE_STATUSES = ("active", "dormant")

#: Event kinds that carry a completion/milestone entity.
_MILESTONE_KINDS = (TASK_COMPLETED, DECISION_RECORDED)


def _event_ref(event: FellowshipEvent) -> SourceRef:
    """The event itself as an evidence ref (mirrors event_to_item).

    Verbatim user words anchor as a quote; wordless records anchor
    as an entity ref. The event ref is what makes a detector's
    change "new evidence" under invariant 2.
    """
    return SourceRef(
        kind="event",
        ref_id=event.id,
        evidence_kind="quote" if (event.evidence_text or "").strip() else "entity_ref",
    )


def _entity_ref(event: FellowshipEvent) -> str | None:
    if (event.entity_type or "").strip() and (event.entity_id or "").strip():
        return f"{event.entity_type}:{event.entity_id}"
    return None


def _claim_row_id(
    store: NarrativeStore, user_id: str, thread_id: str, claim_id: str
) -> str | None:
    for row in store.evidence_for(user_id, thread_id):
        if row.ref_kind == "claim" and row.ref_id == claim_id:
            return row.id
    return None


def _thread_entity_refs(
    store: NarrativeStore, user_id: str, thread_id: str
) -> set[str]:
    return {
        row.entity_ref
        for row in store.evidence_for(user_id, thread_id)
        if row.entity_ref
    }


def _has_proposed_change(
    store: NarrativeStore, user_id: str, thread_id: str, kind: str
) -> bool:
    return any(
        change.kind == kind and change.status == "proposed"
        for change in store.changes_for(user_id, thread_id)
    )


def _standing_reading(
    store: NarrativeStore, user_id: str, thread: NarrativeThread
):
    if not thread.standing_reading_id:
        return None
    for reading in store.readings_for(user_id, thread.id):
        if reading.id == thread.standing_reading_id:
            return reading
    return None


def _record(
    store: NarrativeStore,
    user_id: str,
    thread: NarrativeThread,
    *,
    kind: str,
    refs: list,
    prior_reading_id: str | None = None,
    reason: str | None = None,
    successor_thread_id: str | None = None,
    absence_basis: dict | None = None,
) -> ThreadChange | None:
    """Record one change proposal, or None when it is a duplicate.

    Store refusals (anti-manufacture: no new evidence) are
    duplicates by construction — the movement was already
    recorded — not errors.
    """
    try:
        return store.record_change(
            user_id,
            thread.id,
            kind=kind,
            evidence_refs=refs,
            prior_reading_id=prior_reading_id,
            reason=reason,
            successor_thread_id=successor_thread_id,
            absence_basis=absence_basis,
        )
    except ValueError:
        logger.debug(
            "narrative: change %s for thread %s refused (duplicate "
            "or already recorded)",
            kind,
            thread.id,
        )
        return None


def detect_changes_for_event(
    store: NarrativeStore, user_id: str, event: FellowshipEvent
) -> list[ThreadChange]:
    """Run the Phase 3 detectors over one fellowship event.

    Pure detection + proposal recording. Never raises for a
    single thread's refusal; threads that do not match yield
    nothing. Returns the proposals recorded (possibly empty).
    """
    proposals: list[ThreadChange] = []
    event_ref = _event_ref(event)
    entity_ref = _entity_ref(event)
    action = (event.payload or {}).get("action")

    for thread in store.threads_for(user_id, limit=None):
        if thread.status not in _LIVE_STATUSES:
            continue
        # 1. Verdict change: the claim is thread evidence.
        if event.kind == CLAIM_DECIDED and event.entity_type == "claim":
            claim_row_id = _claim_row_id(
                store, user_id, thread.id, event.entity_id
            )
            if claim_row_id is None:
                continue
            standing = _standing_reading(store, user_id, thread)
            contradicted = (
                standing is not None
                and action == "rejected"
                and claim_row_id in (standing.evidence_refs or [])
            )
            kind = "contradicted" if contradicted else "extended"
            if _has_proposed_change(store, user_id, thread.id, kind):
                continue
            refs: list = [event_ref]
            if contradicted and standing is not None:
                refs.append(claim_row_id)
            change = _record(
                store,
                user_id,
                thread,
                kind=kind,
                refs=refs,
                prior_reading_id=(
                    standing.id if contradicted and standing else None
                ),
            )
            if change is not None:
                proposals.append(change)
            continue
        # 2./3. Entity-ref match: milestone, or reopening when dormant.
        if entity_ref is None:
            continue
        if entity_ref not in _thread_entity_refs(store, user_id, thread.id):
            continue
        if thread.status == "dormant":
            kind = "reopened"
        elif event.kind in _MILESTONE_KINDS:
            kind = "milestone"
        else:
            # Active thread, non-milestone event: the normal
            # derivation extension path owns this movement.
            continue
        if _has_proposed_change(store, user_id, thread.id, kind):
            continue
        change = _record(
            store, user_id, thread, kind=kind, refs=[event_ref]
        )
        if change is not None:
            proposals.append(change)
    return proposals


def detect_outgrown(
    store: NarrativeStore,
    user_id: str,
    *,
    window_days: int = DEFAULT_OUTGROWN_WINDOW_DAYS,
) -> list[ThreadChange]:
    """Propose retirement (reason ``outgrown``) for stale threads.

    A thread qualifies when it is active, has at least one
    evidence row, and its most recent evidence predates now minus
    the window. The store re-verifies the absence against the
    same clock before writing; a thread that gained evidence
    since is refused, not proposed. Threads with an
    already-proposed retired change are skipped. (No ``now``
    parameter by design: detector and store must share one clock,
    or the store's verification would refuse the detector's
    proposal. Tests backdate evidence rows instead.)
    """
    if window_days <= 0:
        raise ValueError("window_days must be positive")
    moment = datetime.now(timezone.utc)
    cutoff = moment - timedelta(days=window_days)
    proposals: list[ThreadChange] = []
    for thread in store.threads_for(user_id, limit=None):
        if thread.status != "active":
            continue
        if _has_proposed_change(store, user_id, thread.id, "retired"):
            continue
        rows = store.evidence_for(user_id, thread.id)
        if not rows:
            continue
        last_seen = max(row.created_at for row in rows)
        last_dt = _parse_ts(last_seen)
        if last_dt is None:
            continue
        if last_dt > cutoff:
            continue
        last_row = max(rows, key=lambda row: row.created_at)
        change = _record(
            store,
            user_id,
            thread,
            kind="retired",
            refs=[last_row.id],
            reason="outgrown",
            absence_basis={
                "window_days": window_days,
                "last_evidence_at": last_seen,
            },
        )
        if change is not None:
            proposals.append(change)
    return proposals


def propose_reinterpretation(
    store: NarrativeStore,
    user_id: str,
    thread_id: str,
    successor_thread_id: str,
    *,
    evidence_refs: list | None = None,
) -> ThreadChange:
    """Propose retiring a thread as reinterpreted into a successor.

    The successor must already exist (created by derivation, user
    declaration, or discovery). Both threads' readings are
    preserved — nothing is moved, edited, or deleted. The thread's
    status changes only when the user accepts the proposal
    (review verdict → thread status ``retired``).
    """
    thread = store.get_thread(user_id, thread_id)
    if thread is None:
        raise ValueError(f"unknown thread: {thread_id!r}")
    if _has_proposed_change(store, user_id, thread_id, "retired"):
        raise ValueError(
            "thread already has a proposed retirement; verdict it "
            "before proposing another"
        )
    change = store.record_change(
        user_id,
        thread_id,
        kind="retired",
        evidence_refs=evidence_refs or [],
        reason="reinterpreted",
        successor_thread_id=successor_thread_id,
    )
    return change


def thread_history(
    store: NarrativeStore,
    user_id: str,
    thread_id: str,
    *,
    since: str | None = None,
    until: str | None = None,
) -> list[ThreadChange]:
    """A thread's change log, oldest first, optionally windowed.

    This IS the thread's temporal state (base plan D2: no separate
    snapshot store — a thread's history is its change log).
    Comparing two windows is comparing two slices of this list.
    ``since``/``until`` are ISO timestamps, inclusive of ``since``,
    exclusive of ``until``.
    """
    changes = store.changes_for(user_id, thread_id)
    changes = sorted(changes, key=lambda change: change.created_at)
    if since is not None:
        changes = [c for c in changes if c.created_at >= since]
    if until is not None:
        changes = [c for c in changes if c.created_at < until]
    return changes


def _parse_ts(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed
