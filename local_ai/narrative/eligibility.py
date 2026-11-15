"""Steward D2: provenance eligibility, barrier integrity, audits.

Implements the packet's §§8.1/9.3 (source eligibility by provenance
resolution), §9.4 as corrected through Revision 4 (the barrier-
integrity check, record-first), and §9.5 (independent recount +
full-set provenance verification of survivors).

Eligibility rule (§9.3): for a user with a standing erasure
boundary T, a source is admissible only when its provenance
resolves to an origin record whose chronology is strictly after
T. The governing chronology is the ORIGIN record's, never a
derivative's own timestamps:

- ordinary log events: the activity-log line is the origin;
- culminations (``meeting_completed``, ``claim_decided``): the
  event resolves through its entity reference to the origin record
  (the meeting row). Claims are governed by the founder's Option B
  election (2026-11-15): claim rows carry no field dating their
  underlying evidence, so claims are excluded as post-erasure
  sources entirely — no exception for assimilation timestamps —
  and a ``claim_decided`` event is ineligible (consumed-skipped);
- deferred-prose rows at completion: every ref the row cites
  resolves through its family's rule; the row's own ``created_at``
  is only a sanity bound;
- observations: the event they derive from, resolved as an event;
- anything whose provenance cannot be established (missing,
  unparseable, conflicting, or a family with no origin record
  reachable from here — journal entries, commitments, VE entities)
  fails closed: ineligible.

Barrier integrity (§9.4 Rev 4): the check reads the signed
operation record FIRST. A standing opened/incomplete record holds
derivation for the pass while either barrier is missing or
unreconciled — whatever the tombstones say, including neither
tombstone existing; missing barriers are recovered at the record's
original T (a barrier write, permitted during the hold), and
derivation resumes on the NEXT pass. Once both barriers
independently verify against the record, derivation may proceed
under the eligibility + manifest rules even though the operation
is still incomplete: barrier integrity is not a claim of deletion
completion. A record that fails signature verification, or a
tombstone that conflicts with the record, fails closed: hold, no
barrier written, nothing proceeds.

This module holds no store of its own. Stores arrive as duck-typed
parameters; identity/vision/meeting access is function-local
imports, the codebase's cycle-avoidance pattern.
"""

from __future__ import annotations

import json
import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

logger = logging.getLogger(__name__)

#: One attested source: (source_kind, source_id, source_time) with
#: source_time a canonical UTC ISO timestamp strictly after the
#: boundary it was evaluated against.
AdmittedSource = tuple[str, str, str]

#: The authorized scope the operation record binds (§9.4 Rev 4).
OPERATION_SCOPE = "delete:execute"


def parse_time(value: Any) -> datetime | None:
    """An ISO timestamp → aware datetime, or None (unestablishable)."""
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _canon(moment: datetime) -> str:
    """Canonical UTC ISO form — the shape every timestamp this
    system writes already takes (``_utcnow`` discipline), so the
    manifest's text comparisons in the §9.2 triggers order the
    same way the parsed comparisons here do."""
    return moment.astimezone(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Signed operation records (§9.4 Rev 3 + Rev 4 Correction B)
# ---------------------------------------------------------------------------


@dataclass
class OperationRecord:
    """A signature-verified operation record for one operation."""

    operation_id: str
    covered_user: str
    erased_at: str
    scope: str
    status: str  # latest transition: opened | incomplete | completed
    license_id: str = ""
    counts: dict[str, Any] = field(default_factory=dict)


@dataclass
class OperationRecords:
    """The operation-record state for one user."""

    standing: OperationRecord | None = None  # opened / incomplete
    completed: OperationRecord | None = None
    conflict: str | None = None


def read_operation_records(identity_store: Any, user_id: str) -> OperationRecords:
    """Read and verify the signed operation rows bound to a user.

    Operation rows live in the identity store's existing
    ``deletion_receipts`` table (§9.4): a row is an operation row
    when its summary carries the bound field set. Verification is
    the one procedure used at retry and at autonomous recovery:
    recompute the HMAC over the row's payload and compare each
    bound element against ground truth. Any signature failure on
    any operation row fails closed (``conflict`` set, nothing
    trusted) — the bound set is inside the signed payload, so
    substituting a bound element (covered_user included) is a
    signature failure. Signature-valid rows binding a different
    user are that user's records and are skipped: this reader is
    always scoped to one consumer's user.
    """
    from local_ai.identity.service import _receipt_payload
    from local_ai.identity.signing import verify_mapping

    out = OperationRecords()
    by_operation: dict[str, OperationRecord] = {}
    order: list[str] = []
    for row in identity_store.list_receipts():  # rowid DESC: latest first
        summary = row.summary if isinstance(row.summary, dict) else {}
        operation_id = summary.get("operation_id")
        status = summary.get("op_status")
        if not operation_id or not status:
            continue  # a plain receipt, not an operation row
        if not verify_mapping(_receipt_payload(row), row.signature):
            out.conflict = (
                f"operation record {row.receipt_id} for operation "
                f"{operation_id} failed signature verification"
            )
            return out
        # A signature-valid record binding a DIFFERENT user is that
        # user's record, not this consumer's evidence — skip it.
        # (Substitution of the binding itself breaks the signature,
        # handled above: the bound set is inside the signed payload,
        # so a forged covered_user never reaches this line.)
        if summary.get("covered_user") != user_id:
            continue
        erased_at = summary.get("erased_at")
        scope = summary.get("scope")
        if not isinstance(erased_at, str) or not erased_at.strip():
            out.conflict = (
                f"operation record {row.receipt_id} carries no "
                "erased_at in its signed binding"
            )
            return out
        if scope != OPERATION_SCOPE:
            out.conflict = (
                f"operation record {row.receipt_id} binds scope "
                f"{scope!r}, not the authorized {OPERATION_SCOPE!r}"
            )
            return out
        if operation_id not in by_operation:
            counts = summary.get("counts")
            by_operation[operation_id] = OperationRecord(
                operation_id=str(operation_id),
                covered_user=user_id,
                erased_at=erased_at,
                scope=str(scope),
                status=str(status),
                license_id=row.license_id,
                counts=dict(counts) if isinstance(counts, dict) else {},
            )
            order.append(operation_id)
        else:
            standing_row = by_operation[operation_id]
            if standing_row.erased_at != erased_at:
                out.conflict = (
                    f"operation {operation_id} rows disagree on the "
                    "boundary they bind"
                )
                return out
    for operation_id in order:
        record = by_operation[operation_id]
        if record.status in ("opened", "incomplete"):
            if out.standing is None:
                out.standing = record
        elif record.status == "completed":
            if out.completed is None:
                out.completed = record
    return out


def default_operation_reader(user_id: str) -> OperationRecords:
    """The production operation-record reader (identity store).

    Used by derivation entry points that were not handed an
    explicit reader (the sweep's ``consent_reader`` precedent:
    injection for tests, this default for production). A read
    failure is a conflict — fail closed, never "no record".

    Deliberately a read-only SELECT, not an IdentityStore
    construction: this runs at the head of derivation entry points,
    and constructing the store per call would run its schema DDL
    (writes) against the identity database on every event. The
    default path is resolved at call time, exactly as the store
    resolves it, so ZENAF_DATA_DIR redirection stays effective.
    A missing database or receipts table means no operation has
    ever been recorded — an empty result, not a conflict.

    The read-only connection is cached per resolved path (opened
    once, reused) and rolled back before each SELECT, releasing
    any read snapshot a previous fetch left pinned, so newly
    committed records are visible immediately; the cache exists so
    the hot path pays one SELECT per event, not a file open.
    """
    import sqlite3 as _sqlite3

    try:
        from local_ai.identity import identity_data_dir
        from local_ai.identity.store import _receipt_from_row

        db_path = identity_data_dir() / "identity.db"
        if not db_path.exists():
            return OperationRecords()
        conn = _reader_connection(str(db_path))
        try:
            # Serialized: one cached connection serves every
            # derivation thread; the SELECT itself is sub-ms.
            with _READER_CONNECTIONS_LOCK:
                # Release any read snapshot a previous fetch left
                # pinned on the cached connection, so this SELECT
                # sees the latest committed records. The connection
                # is read-only — there is never a write to lose.
                conn.rollback()
                rows = conn.execute(
                    "SELECT * FROM deletion_receipts ORDER BY rowid DESC"
                ).fetchall()
        except _sqlite3.OperationalError:
            return OperationRecords()  # table not created yet
        receipts = [_receipt_from_row(r) for r in rows]

        class _ReadOnlyReceipts:
            def list_receipts(self):
                return receipts

        return read_operation_records(_ReadOnlyReceipts(), user_id)
    except Exception:
        logger.exception(
            "erasure: operation-record read failed for user %r", user_id
        )
        return OperationRecords(
            conflict="operation records could not be read"
        )


_READER_CONNECTIONS: dict[str, Any] = {}
_READER_CONNECTIONS_LOCK = threading.Lock()


def _reader_connection(db_path: str):
    """The cached read-only connection for one identity database.

    Keyed by the resolved path so a ZENAF_DATA_DIR change opens a
    fresh connection for the new location. A path's connection is
    opened once and kept for the life of the process — it is never
    dropped and reopened, so if the database file at a path is
    replaced, the cached connection keeps reading the file it
    originally opened (whole-directory restore is the packet's
    documented residual risk, not something this reader can
    detect). Staleness within the file is the caller's side of
    the bargain: default_operation_reader rolls the connection
    back before each SELECT, releasing any pinned read snapshot.
    """
    import sqlite3 as _sqlite3

    with _READER_CONNECTIONS_LOCK:
        conn = _READER_CONNECTIONS.get(db_path)
        if conn is None:
            conn = _sqlite3.connect(
                f"file:{db_path}?mode=ro", uri=True, check_same_thread=False
            )
            conn.row_factory = _sqlite3.Row
            _READER_CONNECTIONS[db_path] = conn
        return conn


# ---------------------------------------------------------------------------
# Barrier integrity (§9.4 Rev 4)
# ---------------------------------------------------------------------------


@dataclass
class BarrierVerdict:
    """The barrier-integrity check's outcome for one user."""

    state: str  # "clear" | "proceed" | "hold"
    reason: str = ""
    erased_at: str | None = None
    operation_id: str | None = None
    recovered: list[str] = field(default_factory=list)
    conflict: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "state": self.state,
            "reason": self.reason,
            "erased_at": self.erased_at,
            "operation_id": self.operation_id,
            "recovered": list(self.recovered),
            "conflict": self.conflict,
        }


def check_barrier_integrity(
    user_id: str,
    *,
    narrative_store: Any = None,
    observation_store: Any = None,
    operation_reader: Callable[[str], OperationRecords] | None = None,
) -> BarrierVerdict:
    """The record-first barrier-integrity check (§9.4 Rev 4).

    Runs at the head of every derivation entry point. Stores not
    supplied are constructed on their production paths ONLY when a
    signal exists (a record, or a tombstone on the supplied side):
    the states the lazy path cannot see (a lone tombstone on the
    unsupplied side with no record anywhere) are unreachable in
    this implementation — the operation record is written before
    either tombstone exists — and whenever any signal exists the
    full three-read classification runs.
    """
    reader = operation_reader or default_operation_reader
    try:
        records = reader(user_id)
    except Exception:
        logger.exception(
            "erasure: operation reader failed for user %r", user_id
        )
        return BarrierVerdict(
            state="hold",
            reason="operation-record read failed; failing closed",
            conflict="operation-record read failed",
        )
    if records.conflict:
        return BarrierVerdict(
            state="hold",
            reason=(
                "the signed operation record failed verification; "
                "derivation holds and no barrier is written"
            ),
            conflict=records.conflict,
        )
    record = records.standing or records.completed
    try:
        n_tomb = (
            narrative_store.get_erasure_tombstone(user_id)
            if narrative_store is not None
            else None
        )
        o_tomb = (
            observation_store.get_erasure_tombstone(user_id)
            if observation_store is not None
            else None
        )
        if record is not None or n_tomb is not None or o_tomb is not None:
            if narrative_store is None:
                from .store import NarrativeStore

                narrative_store = NarrativeStore()
                n_tomb = narrative_store.get_erasure_tombstone(user_id)
            if observation_store is None:
                from local_ai.fellowship.observations import ObservationStore

                observation_store = ObservationStore()
                o_tomb = observation_store.get_erasure_tombstone(user_id)
    except Exception:
        logger.exception(
            "erasure: tombstone read failed for user %r", user_id
        )
        return BarrierVerdict(
            state="hold",
            reason="barrier state could not be read; failing closed",
            conflict="barrier state could not be read",
        )
    if record is None and n_tomb is None and o_tomb is None:
        return BarrierVerdict(state="clear")
    if record is None:
        # Tombstones with no authoritative record: hold and report.
        # No boundary is invented, ever (§9.4).
        if n_tomb is not None and o_tomb is not None:
            if n_tomb["erased_at"] != o_tomb["erased_at"]:
                return BarrierVerdict(
                    state="hold",
                    reason=(
                        "the two erasure tombstones disagree and no "
                        "operation record stands to reconcile them"
                    ),
                    conflict=(
                        f"narrative tombstone at {n_tomb['erased_at']}, "
                        f"observations tombstone at {o_tomb['erased_at']}, "
                        "no operation record"
                    ),
                )
            return BarrierVerdict(
                state="hold",
                reason=(
                    "erasure tombstones stand but no operation record "
                    "exists; derivation holds and no boundary is invented"
                ),
                conflict="tombstones without an operation record",
            )
        return BarrierVerdict(
            state="hold",
            reason=(
                "exactly one erasure tombstone stands and no operation "
                "record exists to reconcile from; derivation holds"
            ),
            conflict="one tombstone without an operation record",
        )
    # A verified record governs. A tombstone conflicting with it
    # fails closed: hold, no barrier written (§9.4 Correction A).
    boundary = record.erased_at
    for tomb, name in ((n_tomb, "narrative"), (o_tomb, "observations")):
        if tomb is not None and tomb["erased_at"] != boundary:
            return BarrierVerdict(
                state="hold",
                reason=(
                    f"the {name} tombstone conflicts with the signed "
                    "operation record; derivation holds, no barrier "
                    "is written, and the conflict is reported"
                ),
                operation_id=record.operation_id,
                erased_at=boundary,
                conflict=(
                    f"{name} tombstone at {tomb['erased_at']} vs "
                    f"operation record {record.operation_id} at {boundary}"
                ),
            )
    missing: list[str] = []
    try:
        if n_tomb is None:
            narrative_store.write_erasure_tombstone(
                user_id, boundary, record.operation_id
            )
            missing.append("narrative")
        if o_tomb is None:
            observation_store.write_erasure_tombstone(
                user_id, boundary, record.operation_id
            )
            missing.append("observations")
    except Exception:
        logger.exception(
            "erasure: barrier recovery write failed for user %r", user_id
        )
        return BarrierVerdict(
            state="hold",
            reason="barrier recovery failed; failing closed",
            operation_id=record.operation_id,
            erased_at=boundary,
            conflict="barrier recovery write failed",
        )
    if missing:
        # Recovery happened during this hold; derivation resumes on
        # the NEXT pass, not the reconciling one (§9.4).
        return BarrierVerdict(
            state="hold",
            reason=(
                "barrier integrity was missing and has been recovered "
                f"at the operation record's boundary ({', '.join(missing)} "
                "barrier written); derivation resumes on the next pass"
            ),
            operation_id=record.operation_id,
            erased_at=boundary,
            recovered=missing,
        )
    return BarrierVerdict(
        state="proceed",
        reason=(
            "both barriers verify against the signed operation record; "
            "derivation proceeds from eligible post-erasure sources "
            "only"
            + (
                " (the operation is still incomplete — barrier "
                "integrity is not deletion completion)"
                if records.standing is not None
                else ""
            )
        ),
        operation_id=record.operation_id,
        erased_at=boundary,
    )


# ---------------------------------------------------------------------------
# Provenance resolution (§9.3)
# ---------------------------------------------------------------------------


class ProvenanceResolver:
    """Resolves sources to their origin records' chronology.

    One resolver is built per derivation pass (or per audit) for a
    user with a verified boundary. All origin lookups fail closed:
    a source whose provenance cannot be established resolves to
    None and is ineligible.
    """

    def __init__(
        self,
        user_id: str,
        erased_at: str,
        *,
        narrative_store: Any = None,
        observation_store: Any = None,
        log_path: str | Path | None = None,
        meeting_rows: Iterable[dict] | None = None,
    ) -> None:
        self.user_id = user_id
        self.erased_at = erased_at
        self._boundary = parse_time(erased_at)
        self._narrative = narrative_store
        self._observations = observation_store
        self._log_path = Path(log_path) if log_path is not None else None
        self._meeting_rows = (
            [dict(r) for r in meeting_rows] if meeting_rows is not None else None
        )
        self._log_index: dict[str, dict] | None = None
        self._meetings_cache: list[dict] | None = None

    # -- time discipline ----------------------------------------------------

    def eligible_time(self, value: Any) -> str | None:
        """``value`` canonicalized, iff it parses and is strictly
        after the boundary; otherwise None (equality fails, §9.3)."""
        moment = parse_time(value)
        if moment is None or self._boundary is None:
            return None
        if moment <= self._boundary:
            return None
        return _canon(moment)

    # -- origin access ------------------------------------------------------

    def _narrative_store(self) -> Any:
        if self._narrative is None:
            from .store import NarrativeStore

            self._narrative = NarrativeStore()
        return self._narrative

    def _observation_store(self) -> Any:
        if self._observations is None:
            from local_ai.fellowship.observations import ObservationStore

            self._observations = ObservationStore()
        return self._observations

    def _log_line(self, event_id: str) -> dict | None:
        if self._log_index is None:
            self._log_index = {}
            try:
                from local_ai.activity import _activity_log_path

                path = self._log_path or _activity_log_path()
                with Path(path).open("r", encoding="utf-8") as handle:
                    for line in handle:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            record = json.loads(line)
                        except (json.JSONDecodeError, TypeError):
                            continue
                        if isinstance(record, dict) and record.get("id"):
                            self._log_index[record["id"]] = record
            except OSError:
                logger.warning(
                    "erasure: activity log unreadable for provenance "
                    "resolution; event origins fail closed"
                )
        return self._log_index.get(event_id)

    def _meetings(self) -> list[dict]:
        # Meeting rows come only from injection (the sweep's
        # meeting_provider, friction's resolved rows, the delete
        # flow). The narrative package does not import the
        # conversation package (S0 separation pin); uninjected,
        # meeting origins are unresolvable and fail closed (§9.3).
        if self._meeting_rows is not None:
            return self._meeting_rows
        return []

    def _meeting_by_key(self, meeting_key: str) -> dict | None:
        for row in self._meetings():
            key = (
                f"meeting-{row.get('archetype_id')}-"
                f"{row.get('keystone_index')}"
            )
            if key == meeting_key:
                return row
        return None

    def _meeting_for_event(self, entity_id: str) -> dict | None:
        for row in self._meetings():
            conversation_id = row.get("conversation_id")
            if not conversation_id:
                # The stored column is authoritative; the fallback
                # is the deterministic id format (the same format
                # friction's _meeting_key replicates — the narrative
                # package does not import the conversation package,
                # S0 separation pin).
                conversation_id = (
                    f"meeting-{row.get('archetype_id')}-"
                    f"{row.get('keystone_index')}"
                )
            if conversation_id and conversation_id == entity_id:
                return row
        return None

    # -- resolution ---------------------------------------------------------

    def _event_origin(self, event_id: str) -> tuple[str, list[str]] | None:
        """(origin time, [corroborating times]) for a log event id.

        None when the origin cannot be established or the event is
        excluded by rule. Culminations resolve to their origin
        record; the culmination event's own timestamp corroborates
        (both must postdate the boundary — a backdated culmination
        row or a pre-boundary culmination event each fail, §9.3).
        """
        line = self._log_line(event_id)
        if line is None:
            return None
        kind = line.get("type", "")
        if kind == "claim_decided":
            # Founder election, Option B: claims carry no evidence
            # chronology, so a claim culmination is excluded as a
            # post-erasure source. No assimilation exception.
            return None
        if kind == "meeting_completed":
            meeting = self._meeting_for_event(line.get("entity_id", ""))
            if meeting is None:
                return None
            origin = meeting.get("created_at")
            own = line.get("created_at")
            if not origin or not own:
                return None
            return (str(origin), [str(own)])
        created = line.get("created_at")
        if not created:
            return None
        return (str(created), [])

    def _checked_origin(
        self, origin: tuple[str, list[str]] | None
    ) -> str | None:
        if origin is None:
            return None
        head, corroborating = origin
        resolved = self.eligible_time(head)
        if resolved is None:
            return None
        for other in corroborating:
            if self.eligible_time(other) is None:
                return None
        return resolved

    def origin_time_for_event(self, event: Any) -> str | None:
        """The event's governing provenance time, or None.

        The log line is the origin record; when no line exists, an
        ordinary event may still establish its time by carriage
        (the ``created_at`` emit_event now sets from the same log
        record). A culmination without its origin record fails
        closed — its own timestamp never governs.
        """
        resolved = self._checked_origin(self._event_origin(event.id))
        if resolved is not None:
            return resolved
        if event.kind in ("meeting_completed", "claim_decided"):
            return None
        if self._log_line(event.id) is not None:
            # A line exists but its chronology failed (or the event
            # is a culmination handled above): carriage cannot
            # rescue a failed origin.
            return None
        return self.eligible_time(getattr(event, "created_at", ""))

    def origin_time_for_ref(
        self, kind: str, ref_id: str, *, _depth: int = 0
    ) -> str | None:
        """The origin time for one source reference, or None."""
        if kind == "event":
            return self._checked_origin(self._event_origin(ref_id))
        if kind == "claim":
            # Option B: claims are excluded as post-erasure sources.
            return None
        if kind == "observation":
            if _depth > 0:
                return None
            try:
                obs = self._observation_store().get(self.user_id, ref_id)
            except Exception:
                return None
            if obs is None or not obs.event_ref:
                return None
            return self.origin_time_for_ref(
                "event", obs.event_ref, _depth=_depth + 1
            )
        if kind == "thread":
            try:
                thread = self._narrative_store().get_thread(
                    self.user_id, ref_id
                )
            except Exception:
                return None
            if thread is None:
                return None
            return self.eligible_time(thread.created_at)
        if kind == "meeting":
            row = self._meeting_by_key(ref_id)
            if row is None:
                return None
            return self.eligible_time(row.get("created_at"))
        if kind == "deferred_prose":
            if _depth > 0:
                return None
            try:
                rows = self._narrative_store().deferred_prose_for(self.user_id)
            except Exception:
                return None
            row = next((r for r in rows if r.get("id") == ref_id), None)
            if row is None:
                return None
            # The row's own created_at is only a sanity bound: a
            # row born at or before the boundary cannot complete,
            # whatever its refs say (§9.3).
            if self.eligible_time(row.get("created_at")) is None:
                return None
            try:
                keys = json.loads(row.get("evidence_refs_json") or "[]")
            except (json.JSONDecodeError, TypeError):
                return None
            times: list[str] = []
            for key in keys:
                ref_kind, _, sub_id = str(key).partition(":")
                resolved = self.origin_time_for_ref(
                    ref_kind, sub_id, _depth=_depth + 1
                )
                if resolved is None:
                    return None
                times.append(resolved)
            if not times:
                return None
            # The weakest link governs: min > T iff every ref > T.
            return min(times)
        # journal_entry, commitment, ve_entity, and any other family
        # have no origin record reachable from here: fail closed.
        return None

    # -- admitted sets --------------------------------------------------------

    def admitted_entry(self, kind: str, ref_id: str) -> AdmittedSource | None:
        resolved = self.origin_time_for_ref(kind, ref_id)
        if resolved is None:
            return None
        return (kind, ref_id, resolved)

    def admitted_for_refs(
        self, refs: Iterable[Any]
    ) -> list[AdmittedSource] | None:
        """The admitted set for a set of SourceRefs, or None when
        ANY ref is ineligible (a write's dependencies bind jointly)."""
        out: list[AdmittedSource] = []
        for ref in refs:
            entry = self.admitted_entry(ref.kind, ref.ref_id)
            if entry is None:
                return None
            out.append(entry)
        return out

    def admitted_for_event(self, event: Any) -> AdmittedSource | None:
        resolved = self.origin_time_for_event(event)
        if resolved is None:
            return None
        return ("event", event.id, resolved)


def resolver_from_verdict(
    user_id: str,
    verdict: BarrierVerdict,
    *,
    narrative_store: Any = None,
    observation_store: Any = None,
    log_path: str | Path | None = None,
    meeting_rows: Iterable[dict] | None = None,
) -> ProvenanceResolver | None:
    """A resolver for a "proceed" verdict; None for any other state."""
    if verdict.state != "proceed" or not verdict.erased_at:
        return None
    return ProvenanceResolver(
        user_id,
        verdict.erased_at,
        narrative_store=narrative_store,
        observation_store=observation_store,
        log_path=log_path,
        meeting_rows=meeting_rows,
    )


# ---------------------------------------------------------------------------
# Provenance verification of survivors (§9.5)
# ---------------------------------------------------------------------------


def audit_narrative_store(
    store: Any, user_id: str, resolver: ProvenanceResolver
) -> dict[str, Any]:
    """Full-set provenance audit of the narrative store.

    Every surviving record of the user is verified the way §9.5
    requires: each thread through every evidence row it carries
    (resolved to its origin record — a thread whose founding
    evidence resolves to at-or-before the boundary, or that
    predates the boundary itself, is deleted whole); each reading
    and change through its cited evidence rows (dangling ids fail
    closed), with the structural bases checked for outgrown and
    reinterpreted changes; each deferred row through its refs; each
    observable through its cited ids (evidence rows, thread
    dependencies, meeting dependencies — a claim citation can
    never resolve, so claim-citing survivors fail mechanically);
    each candidate-mention sighting through its event ref, and
    each candidate through its linked sightings (Steward D1).

    The audit derives eligibility HERE, from the origin records —
    never from the erasure operation's own filter. Returns counts
    plus the (family, id) failure list for the operation's report;
    receipts carry the counts only.
    """
    checked = 0
    removed = 0
    failures: list[tuple[str, str]] = []

    threads = store.threads_for(user_id, limit=None)
    surviving = []
    for thread in threads:
        checked += 1
        ok = resolver.eligible_time(thread.created_at) is not None
        if ok:
            for evidence in store.evidence_for(user_id, thread.id):
                if (
                    resolver.origin_time_for_ref(
                        evidence.ref_kind, evidence.ref_id
                    )
                    is None
                ):
                    ok = False
                    break
        if ok:
            surviving.append(thread)
        else:
            failures.append(("thread", thread.id))
            if store.delete_thread(user_id, thread.id):
                removed += 1

    evidence_by_thread: dict[str, dict[str, Any]] = {}

    def _evidence_map(thread_id: str) -> dict[str, Any]:
        if thread_id not in evidence_by_thread:
            evidence_by_thread[thread_id] = {
                row.id: row
                for row in store.evidence_for(user_id, thread_id)
            }
        return evidence_by_thread[thread_id]

    def _cited_ok(thread_id: str, cited_ids: Iterable[str]) -> bool:
        rows = _evidence_map(thread_id)
        for cited in cited_ids:
            row = rows.get(cited)
            if row is None:
                return False  # dangling citation: fail closed
            if (
                resolver.origin_time_for_ref(row.ref_kind, row.ref_id)
                is None
            ):
                return False
        return True

    bad_readings: list[str] = []
    bad_changes: list[str] = []
    surviving_ids = {t.id for t in surviving}
    for thread in surviving:
        for reading in store.readings_for(user_id, thread.id):
            checked += 1
            if not _cited_ok(thread.id, reading.evidence_refs or []):
                bad_readings.append(reading.id)
                failures.append(("reading", reading.id))
        for change in store.changes_for(user_id, thread.id):
            checked += 1
            bad = not _cited_ok(thread.id, change.evidence_refs or [])
            if not bad and change.reason == "outgrown":
                basis = change.absence_last_evidence_at
                if basis:
                    for evidence in store.evidence_for(user_id, thread.id):
                        if evidence.created_at != basis:
                            continue
                        if (
                            resolver.origin_time_for_ref(
                                evidence.ref_kind, evidence.ref_id
                            )
                            is None
                        ):
                            bad = True
                            break
            if not bad and change.reason == "reinterpreted":
                successor = (
                    store.get_thread(user_id, change.successor_thread_id)
                    if change.successor_thread_id
                    else None
                )
                if (
                    successor is None
                    or successor.id not in surviving_ids
                    or resolver.eligible_time(successor.created_at) is None
                ):
                    bad = True
            if bad:
                bad_changes.append(change.id)
                failures.append(("change", change.id))

    bad_deferred: list[str] = []
    for row in store.deferred_prose_for(user_id):
        checked += 1
        if (
            resolver.origin_time_for_ref("deferred_prose", row["id"])
            is None
        ):
            bad_deferred.append(row["id"])
            failures.append(("deferred_prose", row["id"]))

    bad_observables: list[str] = []
    for observable in store.observables_for(user_id):
        checked += 1
        bad = False
        for cited in observable.evidence_refs or []:
            if cited in surviving_ids:
                if resolver.origin_time_for_ref("thread", cited) is None:
                    bad = True
                    break
                continue
            found = None
            for thread in surviving:
                rows = _evidence_map(thread.id)
                if cited in rows:
                    found = rows[cited]
                    break
            if found is None or (
                resolver.origin_time_for_ref(found.ref_kind, found.ref_id)
                is None
            ):
                bad = True
                break
        if not bad and observable.thread_id is None:
            meeting_key = (observable.detail or {}).get("meeting_key")
            if not meeting_key or (
                resolver.origin_time_for_ref("meeting", str(meeting_key))
                is None
            ):
                bad = True
        if bad:
            bad_observables.append(observable.id)
            failures.append(("observable", observable.id))

    if bad_readings or bad_changes or bad_deferred or bad_observables:
        outcome = store.delete_rows_for_audit(
            user_id,
            reading_ids=bad_readings,
            change_ids=bad_changes,
            deferred_ids=bad_deferred,
            observable_ids=bad_observables,
        )
        removed += sum(outcome.values())

    # Steward D1 (packet §8.2 point 3): the audit reaches the
    # candidate-mention family with the same standard — every
    # surviving sighting's event ref is resolved to its origin
    # and must be eligible there; a candidate survives only on
    # at least one currently-linked eligible sighting (a
    # candidate all of whose sightings fail is removed, with its
    # links and the acts that name it).
    bad_sightings: list[str] = []
    for sighting in store.sightings_for(user_id):
        checked += 1
        if (
            resolver.origin_time_for_ref(sighting.ref_kind, sighting.ref_id)
            is None
        ):
            bad_sightings.append(sighting.id)
            failures.append(("candidate_sighting", sighting.id))
    bad_sighting_set = set(bad_sightings)
    bad_candidates: list[str] = []
    for candidate in store.candidates_for(user_id):
        checked += 1
        linked = store.sightings_for_candidate(user_id, candidate.id)
        if not any(s.id not in bad_sighting_set for s in linked):
            bad_candidates.append(candidate.id)
            failures.append(("candidate_mention", candidate.id))
    if bad_sightings or bad_candidates:
        outcome = store.delete_candidates_for_audit(
            user_id,
            sighting_ids=bad_sightings,
            candidate_ids=bad_candidates,
        )
        removed += sum(outcome.values())
    return {"checked": checked, "removed": removed, "failures": failures}


def audit_observation_store(
    store: Any, user_id: str, resolver: ProvenanceResolver
) -> dict[str, Any]:
    """Full-set provenance audit of the fellowship observations:
    every surviving observation's event resolves to its origin
    record and must postdate the boundary (§9.5)."""
    checked = 0
    removed = 0
    failures: list[tuple[str, str]] = []
    for observation in store.list_for_user(user_id, limit=1_000_000):
        checked += 1
        if (
            resolver.origin_time_for_ref("observation", observation.id)
            is None
        ):
            failures.append(("observation", observation.id))
            if store.delete_observation(user_id, observation.id):
                removed += 1
    return {"checked": checked, "removed": removed, "failures": failures}


__all__ = [
    "AdmittedSource",
    "BarrierVerdict",
    "OPERATION_SCOPE",
    "OperationRecord",
    "OperationRecords",
    "ProvenanceResolver",
    "audit_narrative_store",
    "audit_observation_store",
    "check_barrier_integrity",
    "default_operation_reader",
    "parse_time",
    "read_operation_records",
    "resolver_from_verdict",
]
