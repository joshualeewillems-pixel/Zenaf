"""Steward sweep (increment A §3.2, §4): recovery + births from the log.

The sweep reconstructs fellowship events from the append-only JSONL
activity log and derives them into the narrative store, sharing one
store instance with the install path (§3.3). It exists because the
install path alone is incomplete: it cannot recover crashed
processes, failed scheduling, or pre-install events, and a single
event can only extend — never birth — a thread, so births need
multi-event batches.

Design decisions, stated so review can challenge them:

- ROLLOUT (proposal §2/§10, lifted in Phase 3): increment A
  derived ``meeting_completed`` events ONLY. Other fellowship kinds
  in the segment were consumed-and-skipped (the offset advances
  past them): widening later does NOT backfill pre-widening events
  of other kinds, because the offset has already passed them.
  Phase 3 widens to all kinds once its fixture criteria pass
  (§6.8 default); the live-divergence check (sweep vs live
  agreement in production) is NOT established by fixtures and
  remains a deploy-time consideration.
- GATE-CLOSED CONSUME-SKIP: when the consent gate is closed for a
  batch, the batch is NOT derived and the offset still advances
  past it. Derivation covers activity from opt-in forward; it
  never retroactively derives pre-consent activity, and a stalled
  offset would re-read (and, on later opt-in, backfill) events
  from before consent. The gate is re-checked before EVERY batch,
  so withdrawal stops derivation at the next batch boundary and
  re-enablement resumes from the current position.
- WORKER GATING: the deferred worker is gated the same way —
  withdrawal pauses rendering owed prose too (rendering creates
  a reading, which is future derivation). Rows persist and resume
  on re-enablement.
- EXPIRY IS NOT GATED: the ~month ignored-retention prune is
  standing policy, not withdrawal-triggered, so it runs
  regardless of gate state. It only ever touches steward-proposal
  nascent threads (never user-declared threads) with no
  visitor-engaged reading and no owed prose, and it logs every
  deletion loudly — nothing here erases silently.
- PER-USER LOCK: one lock wraps a user's whole pass
  (read → batches → offset advance → worker → expiry). The
  install path does not take it (its derives are offset-free and
  idempotency makes interleave benign); the shared store
  instance + this lock cover the sweep's derive → advance
  sequence.
"""

from __future__ import annotations

import json
import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

from local_ai.activity import _activity_log_path
from local_ai.fellowship.events import (
    EVENT_KINDS,
    FELLOWSHIP_ACTIVITY_SOURCE,
    FellowshipEvent,
)

from .consent import steward_consent_allowed
from .derivation import (
    STEWARD_DEFERRED_LEASE_SECONDS,
    DeferredWorkResult,
    derive_batch,
    event_to_item,
    work_deferred_prose,
)
from .friction import run_friction_pass
from .store import NarrativeStore

logger = logging.getLogger(__name__)

#: Max fellowship events for one user per batch (proposal §4.3).
STEWARD_SWEEP_BATCH_MAX = 50
#: Sweep cadence. Fellowship has no scheduler interval (it schedules
#: per event on daemon threads), so this is an implementation
#: choice for review: a modest operational interval, no
#: philosophical significance. The loop also runs once immediately
#: at start (startup-after-crash recovery).
STEWARD_SWEEP_INTERVAL_SECONDS = 60
#: Ignored-retention window (proposal §1.8, ruled by Joshua).
#: PROVISIONAL — he marked the month with "?"; a named constant
#: so the window is adjustable without a code hunt. The clock is
#: last activity (thread updated_at): recurring material refreshes
#: it and never expires while it still recurs. Whether surfacing
#: a pattern resets the clock is an open detail for increment E,
#: which owns surfacing.
STEWARD_IGNORED_RETENTION_WINDOW = timedelta(days=30)
#: Phase 3: all fellowship event kinds (was meeting-completed
#: only under increment A). See the ROLLOUT note above for the
#: no-backfill consequence.
STEWARD_SWEEP_KINDS: tuple[str, ...] = EVENT_KINDS

_USER_LOCKS: dict[str, threading.Lock] = {}
_USER_LOCKS_GUARD = threading.Lock()


def _user_lock(user_id: str) -> threading.Lock:
    with _USER_LOCKS_GUARD:
        return _USER_LOCKS.setdefault(user_id, threading.Lock())


def _file_identity(stat_result) -> str:
    return f"{stat_result.st_dev}:{stat_result.st_ino}"


def reconstruct_event(record: Any) -> FellowshipEvent | None:
    """An activity-log line dict → FellowshipEvent, or None.

    None means "not a fellowship event line": wrong source, unknown
    kind, missing actor, or unparseable detail. Such lines are
    consumed (the offset advances past them) but never derived.
    """
    if not isinstance(record, dict):
        return None
    if record.get("source") != FELLOWSHIP_ACTIVITY_SOURCE:
        return None
    kind = record.get("type", "")
    if kind not in EVENT_KINDS:
        return None
    actor = record.get("actor") or ""
    if not actor:
        return None
    detail = record.get("detail") or ""
    try:
        detail_obj = json.loads(detail) if isinstance(detail, str) else {}
    except json.JSONDecodeError:
        return None
    if not isinstance(detail_obj, dict):
        return None
    return FellowshipEvent(
        id=record.get("id", ""),
        kind=kind,
        user_id=actor,
        entity_type=record.get("entity_type", ""),
        entity_id=record.get("entity_id", ""),
        evidence_text=detail_obj.get("evidence", "") or "",
        summary=detail_obj.get("summary", "") or "",
        payload=detail_obj.get("payload") or {},
        created_at=record.get("created_at", ""),
    )


@dataclass
class SweepResult:
    """What one user's sweep pass did."""

    user_id: str = ""
    offset_before: int = 0
    offset_after: int = 0
    rescanned: bool = False
    batches: int = 0
    events_derived: int = 0
    events_gate_skipped: int = 0
    lines_consumed: int = 0
    has_partial_trailing_line: bool = False
    log_missing: bool = False
    deferred: dict | None = None
    friction: dict | None = None
    pruned: list[str] = field(default_factory=list)
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "user_id": self.user_id,
            "offset_before": self.offset_before,
            "offset_after": self.offset_after,
            "rescanned": self.rescanned,
            "batches": self.batches,
            "events_derived": self.events_derived,
            "events_gate_skipped": self.events_gate_skipped,
            "lines_consumed": self.lines_consumed,
            "has_partial_trailing_line": self.has_partial_trailing_line,
            "log_missing": self.log_missing,
            "deferred": self.deferred,
            "friction": self.friction,
            "pruned": list(self.pruned),
            "error": self.error,
        }


def _read_complete_lines(
    log_path: Path, offset: int
) -> tuple[list[tuple[int, Any]], bool]:
    """Complete lines from ``offset`` to EOF.

    Returns ([(end_offset, parsed_or_None)], has_partial_trailing).
    A trailing fragment without a newline is NEVER returned and
    never advanced past: the next pass re-reads it complete. A
    complete line that fails to parse is returned as None and IS
    consumed (it cannot be recovered by re-reading).
    """
    with log_path.open("rb") as f:
        f.seek(offset)
        data = f.read()
    if data == b"":
        return [], False
    chunks = data.split(b"\n")
    if data.endswith(b"\n"):
        complete, has_partial = chunks[:-1], False
    else:
        complete, has_partial = chunks[:-1], True
    out: list[tuple[int, Any]] = []
    pos = offset
    for chunk in complete:
        pos += len(chunk) + 1
        if not chunk.strip():
            out.append((pos, None))
            continue
        try:
            parsed = json.loads(chunk.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            parsed = None
        out.append((pos, parsed))
    return out, has_partial


def _gate_open(
    user_id: str,
    consent_reader: Callable[[str], bool] | None,
) -> bool:
    reader = consent_reader or steward_consent_allowed
    try:
        return bool(reader(user_id))
    except Exception:
        logger.exception(
            "steward sweep: consent read failed for user %r; failing closed",
            user_id,
        )
        return False


def run_sweep_for_user(
    store: NarrativeStore,
    user_id: str,
    *,
    log_path: Path | str | None = None,
    generate_fn: Callable | None = None,
    consent_reader: Callable[[str], bool] | None = None,
    batch_max: int = STEWARD_SWEEP_BATCH_MAX,
    meeting_provider: Callable[[str], Any] | None = None,
    claims_provider: Callable[[str], Any] | None = None,
) -> SweepResult:
    """Sweep the activity log for one user (increment A §3.2/§4).

    Reads from the user's stored byte offset, derives fellowship
    events in batches of ≤ ``batch_max``, advances
    the offset only past successfully consumed batches (cursor-last,
    §7), runs the deferred worker, runs the friction pass
    (increment C: after the deferred worker so it sees freshly
    rendered readings, before prune so it can observe quiet threads
    before they die), and prunes ignored threads.
    A failed batch leaves the offset unmoved so the next pass
    retries the same segment; reprocessing is a no-op by attach /
    coverage / dismissal idempotency, and deferred-row dedup
    prevents a second owed-prose row. Never raises for a single
    user's failure (the error is recorded on the result).
    ``meeting_provider`` / ``claims_provider`` supply the friction
    pass's meeting and claim rows for the user (callables taking
    user_id); when absent, O1/O2 have no source rows and only
    O3/O4 derive — the app assembly wires the real stores.
    """
    result = SweepResult(user_id=user_id)
    path = Path(log_path) if log_path is not None else _activity_log_path()
    try:
        stat = path.stat()
    except OSError:
        logger.info("steward sweep: activity log missing at %s", path)
        result.log_missing = True
        return result
    identity = _file_identity(stat)
    position = store.get_processing_position(user_id)
    if position is None:
        start_offset, result.rescanned = 0, False
    elif (
        position["file_identity"] != identity
        or position["byte_offset"] > stat.st_size
    ):
        # Rotation / truncation guard (§4.2): never trust a stale
        # offset. Bounded full rescan; idempotency makes it safe.
        logger.warning(
            "steward sweep: log identity/size changed for user %r "
            "(stored offset %s, size %s); full rescan",
            user_id,
            position["byte_offset"],
            stat.st_size,
        )
        start_offset, result.rescanned = 0, True
    else:
        start_offset = position["byte_offset"]
    result.offset_before = start_offset
    try:
        lines, has_partial = _read_complete_lines(path, start_offset)
    except OSError:
        logger.exception("steward sweep: could not read log at %s", path)
        result.error = "log read failed"
        return result
    result.has_partial_trailing_line = has_partial
    try:
        with _user_lock(user_id):
            committed = start_offset
            batch: list[FellowshipEvent] = []
            failed = False
            for end_offset, parsed in lines:
                event = reconstruct_event(parsed)
                if (
                    event is not None
                    and event.user_id == user_id
                    and event.kind in STEWARD_SWEEP_KINDS
                ):
                    batch.append(event)
                if len(batch) >= batch_max:
                    ok = _process_batch(
                        store, user_id, batch, generate_fn,
                        consent_reader, result,
                    )
                    if not ok:
                        failed = True
                        break
                    committed = end_offset
                    batch = []
            if not failed:
                if batch:
                    ok = _process_batch(
                        store, user_id, batch, generate_fn,
                        consent_reader, result,
                    )
                    if ok:
                        committed = lines[-1][0] if lines else start_offset
                    else:
                        failed = True
                else:
                    # Tail of skips only: all consumed.
                    committed = lines[-1][0] if lines else start_offset
            # Lines actually advanced past (a failed batch's lines
            # stay unconsumed for the next pass).
            result.lines_consumed = sum(
                1 for end_offset, _ in lines if end_offset <= committed
            )
            # Deferred worker and prune run even when a batch
            # failed: they are independent of the failed batch, and
            # the cursor commit below still lands last.
            if _gate_open(user_id, consent_reader):
                # Deferred worker (gated: withdrawal pauses rendering
                # too — a rendered reading is future derivation).
                try:
                    worked = work_deferred_prose(
                        store, user_id, generate_fn=generate_fn
                    )
                    result.deferred = worked.to_dict()
                except Exception:
                    logger.exception(
                        "steward sweep: deferred work failed for %r",
                        user_id,
                    )
            else:
                logger.info(
                    "steward sweep: consent closed for %r; "
                    "deferred work paused",
                    user_id,
                )
            # Friction pass (increment C, gated per thread inside
            # the pass — withdrawal pauses at the next thread
            # boundary, committed thread transactions stand).
            try:
                result.friction = run_friction_pass(
                    store,
                    user_id,
                    meetings=(
                        meeting_provider(user_id)
                        if meeting_provider is not None
                        else None
                    ),
                    claims=(
                        claims_provider(user_id)
                        if claims_provider is not None
                        else None
                    ),
                    gate_open=lambda: _gate_open(
                        user_id, consent_reader
                    ),
                ).to_dict()
            except Exception:
                logger.exception(
                    "steward sweep: friction pass failed for %r",
                    user_id,
                )
                result.friction = {"error": "friction pass failed"}
            # Ignored-retention prune (standing policy, ungated).
            try:
                result.pruned = prune_ignored_threads(store, user_id)
            except Exception:
                logger.exception(
                    "steward sweep: prune failed for %r", user_id
                )
            # Cursor-last (§7): separate commit, after all writes.
            store.set_processing_position(user_id, committed, identity)
            result.offset_after = committed
    except Exception as e:
        logger.exception("steward sweep: pass failed for user %r", user_id)
        result.error = str(e)
    return result


def _process_batch(
    store: NarrativeStore,
    user_id: str,
    batch: list[FellowshipEvent],
    generate_fn: Callable | None,
    consent_reader: Callable[[str], bool] | None,
    result: SweepResult,
) -> bool:
    """Derive one batch, or consume-skip it when the gate is closed.

    Returns True when the batch was consumed (derived or
    gate-skipped — the offset may advance past it) and False on
    derive failure (the offset must NOT advance past it).
    """
    result.batches += 1
    if not _gate_open(user_id, consent_reader):
        logger.info(
            "steward sweep: consent closed for %r; batch of %d "
            "consume-skipped (no retroactive derivation)",
            user_id,
            len(batch),
        )
        result.events_gate_skipped += len(batch)
        return True
    try:
        # Phase 3: detectors run before derivation, same ordering
        # as the live path — a change proposal attaches the
        # event's evidence first, so derivation finds it already
        # attached and proposes nothing twice. Detector failure
        # never fails the batch (derivation still runs).
        from local_ai.narrative.changes import detect_changes_for_event

        for event in batch:
            try:
                detect_changes_for_event(store, user_id, event)
            except Exception:
                logger.exception(
                    "steward sweep: change detection failed for "
                    "event %s",
                    event.id,
                )
        derive_batch(
            user_id,
            [event_to_item(event) for event in batch],
            store,
            generate_fn=generate_fn,
        )
    except Exception:
        logger.exception(
            "steward sweep: batch failed for user %r; offset unmoved",
            user_id,
        )
        return False
    result.events_derived += len(batch)
    return True


def prune_ignored_threads(
    store: NarrativeStore,
    user_id: str,
    *,
    window: timedelta = STEWARD_IGNORED_RETENTION_WINDOW,
    now: datetime | None = None,
) -> list[str]:
    """Hard-delete steward threads stored and ignored past the window.

    A thread is ignored when: it is a steward-proposal nascent
    thread, its last activity predates the window, every reading on
    it is still merely ``proposed`` (no visitor verdict of any
    kind), and it has no pending/rendering deferred prose (owed
    prose is an live obligation, not ignored material). Recurring
    material refreshes updated_at on extension, so it never expires
    while it still recurs. User-declared threads are NEVER pruned:
    they are not the steward's records. Deletions are logged
    loudly: nothing here erases silently.
    """
    cutoff = ((now or datetime.now(timezone.utc)) - window).isoformat()
    deleted: list[str] = []
    for thread in store.threads_for(user_id, status="nascent"):
        if thread.origin != "steward_proposal":
            continue
        if (thread.updated_at or "") >= cutoff:
            continue
        readings = store.readings_for(user_id, thread.id)
        if any(reading.status != "proposed" for reading in readings):
            continue
        owed = store.deferred_prose_for_thread(
            user_id, thread.id, statuses=("pending", "rendering")
        )
        if owed:
            continue
        if store.delete_thread(user_id, thread.id):
            logger.warning(
                "steward sweep: pruned ignored thread %s for user %r "
                "(no activity since %s)",
                thread.id,
                user_id,
                thread.updated_at,
            )
            deleted.append(thread.id)
    return deleted


def enumerate_sweep_users(store: NarrativeStore) -> list[str]:
    """User ids to sweep: permissions rows ∪ cursor rows.

    A user with neither a permissions row nor a cursor position is
    never visited (fail closed, nothing to do). Permissions
    enumeration failure falls back to cursor users only.
    """
    users = set(store.processing_position_users())
    try:
        from local_ai.vision_execution.storage import get_connection

        conn = get_connection()
        rows = conn.execute(
            "SELECT DISTINCT user_id FROM user_permissions_settings"
        ).fetchall()
        users.update(row[0] for row in rows)
    except Exception:
        logger.exception(
            "steward sweep: permissions enumeration failed; "
            "using cursor users only"
        )
    return sorted(users)


def run_sweep(
    store: NarrativeStore,
    *,
    log_path: Path | str | None = None,
    user_ids: list[str] | None = None,
    generate_fn: Callable | None = None,
    consent_reader: Callable[[str], bool] | None = None,
    batch_max: int = STEWARD_SWEEP_BATCH_MAX,
    meeting_provider: Callable[[str], Any] | None = None,
    claims_provider: Callable[[str], Any] | None = None,
) -> dict[str, SweepResult]:
    """One sweep pass over users (shared store instance, §3.3)."""
    if user_ids is None:
        user_ids = enumerate_sweep_users(store)
    results: dict[str, SweepResult] = {}
    for user_id in user_ids:
        results[user_id] = run_sweep_for_user(
            store,
            user_id,
            log_path=log_path,
            generate_fn=generate_fn,
            consent_reader=consent_reader,
            batch_max=batch_max,
            meeting_provider=meeting_provider,
            claims_provider=claims_provider,
        )
    return results


def start_sweep_loop(
    store: NarrativeStore,
    *,
    log_path: Path | str | None = None,
    interval_seconds: int = STEWARD_SWEEP_INTERVAL_SECONDS,
    generate_fn: Callable | None = None,
    consent_reader: Callable[[str], bool] | None = None,
    batch_max: int = STEWARD_SWEEP_BATCH_MAX,
    meeting_provider: Callable[[str], Any] | None = None,
    claims_provider: Callable[[str], Any] | None = None,
) -> tuple[threading.Thread, threading.Event]:
    """Start the daemon sweep loop (app assembly, guarded).

    Runs once immediately (startup-after-crash recovery does not
    wait for the next interval), then every interval. A failed pass
    is logged and never kills the loop. The loop shares the
    caller's store instance with the install path (§3.3).
    """
    stop = threading.Event()

    def _loop() -> None:
        while not stop.is_set():
            try:
                run_sweep(
                    store,
                    log_path=log_path,
                    generate_fn=generate_fn,
                    consent_reader=consent_reader,
                    batch_max=batch_max,
                    meeting_provider=meeting_provider,
                    claims_provider=claims_provider,
                )
            except Exception:
                logger.exception("steward sweep: pass failed")
            stop.wait(interval_seconds)

    thread = threading.Thread(target=_loop, name="steward-sweep", daemon=True)
    thread.start()
    return thread, stop
