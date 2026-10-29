"""Steward increment C: friction-signal derivation, observables only.

C derives FACTS about recorded rows — never interpretations, never
messages, never scores. Four observables, recomputed from current
state on every pass (same state twice yields the same rows; a fact
that stops holding deletes its row on recompute):

- O1 ``impression_unanswered``: a complete meeting whose read-back
  impression was offered and never answered (meeting-scoped, no
  thread — thread_id NULL by construction, never invented).
- O2 ``correction_no_subsequent_activity``: a corrected claim
  attached to a live thread with no later reading or change on
  that thread. Absence-only: the row asserts the correction
  exists and no subsequent activity was recorded — nothing about
  whether the correction was incorporated, which would need an
  explicit correction-to-revision link the schema does not have.
- O3 ``thread_quiet``: a nascent/active thread with no recent
  recorded activity (operational notice window, strictly before
  prune — not a judgment that quiet is bad, and not a warning to
  the visitor until D/E surfaces exist and are discoverable).
- O4 ``divergent_reading_positions``: two proposed steward
  readings on one thread, same primary scale and lens, both
  positioned, different phases, overlapping evidence, no
  contradicted change. The row claims exactly that the fields
  differ — never that the readings conflict, contradict, or need
  resolution. Phases are descriptive, not an ordered ladder.

Judgments are deferred to a later increment: this pass proposes
no judgments, makes zero generation calls, creates no deferred
rows, and writes no change rows. It never traverses thread_links
(link-only relationships yield no signal of any kind), never
consults declines at creation (observables are facts; subject
declines govern what is OFFERED at serving, which D owns — a
decline must never silently restrict internal record-keeping),
and never touches a thread clock (observable writes land only in
the observables table, so observing quiet cannot break quiet).

Inputs are rows, not events: the caller supplies the narrative
store plus meeting rows and claim rows (as dicts, or as callables
taking user_id returning dicts — the sweep wires the real stores;
tests pass plain data). The consent gate is re-checked before
each thread's transaction and once before the meeting scan:
withdrawal mid-pass leaves committed transactions standing and
skips the rest, which is C's precise next-batch-boundary
equivalent with the thread transaction as the unit.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Iterable

from .derivation import EXTENDABLE_STATUSES
from .models import OBSERVABLE_KINDS
from .store import NarrativeStore

#: Operational notice window for O3 (proposal §4.4): fires strictly
#: before the 30-day prune window so the observation exists before
#: expiry. Provisional as operational; NOT a visitor warning.
FRICTION_QUIET_WINDOW_DAYS = 14

#: Thread scope for thread-scoped observables: the same live set
#: A's extension path uses (settled stories are the visitor's
#: reopening question, not automatic derivation).
LIVE_THREAD_STATUSES: tuple[str, ...] = EXTENDABLE_STATUSES

#: Claim type for a filed meeting impression (review_claims).
MEETING_IMPRESSION_CLAIM_TYPE = "meeting_impression"


@dataclass
class FrictionResult:
    """What one friction pass did (mirrors the sweep's deferred dict)."""

    written: int = 0
    refreshed: int = 0
    removed: int = 0
    threads_scanned: int = 0
    meetings_scanned: int = 0
    gate_skipped_threads: int = 0
    gate_skipped_meetings: bool = False
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "written": self.written,
            "refreshed": self.refreshed,
            "removed": self.removed,
            "threads_scanned": self.threads_scanned,
            "meetings_scanned": self.meetings_scanned,
            "gate_skipped_threads": self.gate_skipped_threads,
            "gate_skipped_meetings": self.gate_skipped_meetings,
            "error": self.error,
        }


def _parse_time(value: Any) -> datetime | None:
    """An ISO timestamp string → aware datetime, or None.

    None means "order cannot be established": callers treat that
    as silence (no observable), never as a guessed ordering.
    """
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


def _resolve_provider(
    value: Any, user_id: str
) -> list[dict]:
    """A provider value → row dicts: None, an iterable, or a callable."""
    if value is None:
        return []
    if callable(value):
        value = value(user_id)
    return [dict(row) for row in (value or [])]


def _meeting_key(meeting: dict) -> str:
    return (
        f"meeting-{meeting.get('archetype_id')}-"
        f"{meeting.get('keystone_index')}"
    )


def _latest_impression_claim(
    claims: list[dict], meeting_key: str
) -> dict | None:
    """The filed impression claim for a meeting, latest run wins.

    Matches agent_id == the meeting's transcript id and the
    meeting_impression claim type. A replay files a NEW claim under
    a new run key and filing it SUPERSEDES the archived run's claim
    (status "superseded", row retained), so the standing claim is
    the non-superseded one — latest-created among those. The
    superseded fallback matters only for rows whose status is
    missing (older readers): with no standing row, latest-created
    wins, as before. Returns None when no claim was filed (O1
    still fires — the meeting row alone is the evidence).
    """
    candidates = [
        c
        for c in claims
        if c.get("agent_id") == meeting_key
        and c.get("claim_type") == MEETING_IMPRESSION_CLAIM_TYPE
    ]
    if not candidates:
        return None
    standing = [c for c in candidates if c.get("status") != "superseded"]
    pool = standing if standing else candidates

    def _created_key(claim: dict) -> tuple[int, str]:
        parsed = _parse_time(claim.get("created_at"))
        return (1, parsed.isoformat()) if parsed else (0, "")

    return max(pool, key=_created_key)


def _derive_o1(
    meetings: list[dict], claims: list[dict]
) -> list[dict]:
    """O1 rows: complete + impression offered + no answer recorded.

    Does NOT fire on incomplete meetings, empty claims,
    non-empty responses, or pending claim verdicts (pending is the
    normal state of a claim, not a missing response — the response
    is the read-back answer field, not the verdict).
    """
    desired: list[dict] = []
    for meeting in meetings:
        if meeting.get("stage") != "complete":
            continue
        if meeting.get("status") != "complete":
            continue
        claim_text = meeting.get("readback_claim") or ""
        if not str(claim_text).strip():
            continue
        response = meeting.get("readback_response") or ""
        if str(response).strip():
            continue
        key = _meeting_key(meeting)
        filed = _latest_impression_claim(claims, key)
        evidence = [key]
        filed_id = (
            filed.get("id") or filed.get("claim_id") if filed else None
        )
        detail: dict[str, Any] = {
            "archetype_id": meeting.get("archetype_id"),
            "keystone_index": meeting.get("keystone_index"),
            "meeting_key": key,
            "claim_id": filed_id,
        }
        if filed_id is not None:
            evidence.append(str(filed_id))
        desired.append(
            {
                "thread_id": None,
                "kind": "impression_unanswered",
                "signal_key": f"o1:{key}:{filed_id or 'noclaim'}",
                "evidence_refs": evidence,
                "detail": detail,
            }
        )
    return desired


def _derive_thread_rows(
    store: NarrativeStore,
    user_id: str,
    thread: Any,
    claims_by_id: dict[str, dict],
    now: datetime,
) -> list[dict]:
    """O2 + O3 + O4 rows for one live thread (deterministic, no I/O
    beyond the store's row reads — no generation, no traversal)."""
    desired: list[dict] = []
    evidence = store.evidence_for(user_id, thread.id)
    readings = store.readings_for(user_id, thread.id)
    changes = store.changes_for(user_id, thread.id)

    # O2: corrected claim attached, no later reading or change.
    # Either a later change OR a later reading defeats it; verdicts
    # other than "corrected" never fire; unattached claims and
    # terminal threads never reach this scan (live set only).
    for row in evidence:
        if row.ref_kind != "claim":
            continue
        claim = claims_by_id.get(row.ref_id)
        if claim is None or claim.get("status") != "corrected":
            continue
        verdict_at = _parse_time(claim.get("updated_at"))
        if verdict_at is None:
            continue
        later = False
        for other in list(readings) + list(changes):
            created = _parse_time(other.created_at)
            if created is None:
                # Order cannot be established for this row: stay
                # silent for this claim rather than guess.
                later = True
                break
            if created > verdict_at:
                later = True
                break
        if later:
            continue
        claim_id = claim.get("id") or claim.get("claim_id")
        desired.append(
            {
                "thread_id": thread.id,
                "kind": "correction_no_subsequent_activity",
                "signal_key": f"o2:{thread.id}:{claim_id}",
                "evidence_refs": [row.id],
                "detail": {
                    "claim_id": claim_id,
                    "claim_updated_at": claim.get("updated_at"),
                },
            }
        )

    # O3: nascent/active, clock older than the window, and no row
    # newer than the thread clock (evidence attach without a touch
    # still counts as activity — it is the row's recency, not the
    # clock alone, that decides). Dormant is the quiet marker
    # itself, so it is excluded, not restated.
    if thread.status in ("nascent", "active"):
        updated_at = _parse_time(thread.updated_at)
        cutoff = now - timedelta(days=FRICTION_QUIET_WINDOW_DAYS)
        if updated_at is not None and updated_at < cutoff:
            newest_row = None
            for other in list(readings) + list(changes) + list(evidence):
                created = _parse_time(other.created_at)
                if created is not None and (
                    newest_row is None or created > newest_row
                ):
                    newest_row = created
            if newest_row is None or newest_row <= updated_at:
                desired.append(
                    {
                        "thread_id": thread.id,
                        "kind": "thread_quiet",
                        "signal_key": f"o3:{thread.id}",
                        "evidence_refs": [thread.id],
                        "detail": {
                            "thread_updated_at": thread.updated_at,
                            "window_days": FRICTION_QUIET_WINDOW_DAYS,
                        },
                    }
                )

    # O4: two proposed steward readings, same non-empty primary
    # scale, same lens, both positioned, different phases,
    # overlapping evidence, no contradicted change covering the
    # pair. The row claims the fields differ — nothing more.
    # Ruled readings, seat/user authors, unknown/inapplicable
    # positions, same phases, disjoint evidence, and recorded
    # contradictions all yield no row: silence, not a weak signal.
    contradicted_pairs = {
        frozenset(
            part
            for part in (c.prior_reading_id, c.new_reading_id)
            if part is not None
        )
        for c in changes
        if c.kind == "contradicted"
    }
    live = [
        r
        for r in readings
        if r.status == "proposed"
        and r.author == "steward"
        and r.primary_scale
        and r.progression.state == "positioned"
        and r.progression.lens_id
        and r.progression.phase
    ]
    for i in range(len(live)):
        for j in range(i + 1, len(live)):
            r1, r2 = live[i], live[j]
            if r1.primary_scale != r2.primary_scale:
                continue
            if r1.progression.lens_id != r2.progression.lens_id:
                continue
            if r1.progression.phase == r2.progression.phase:
                continue
            shared = sorted(set(r1.evidence_refs) & set(r2.evidence_refs))
            if not shared:
                continue
            if frozenset((r1.id, r2.id)) in contradicted_pairs:
                continue
            first, second = sorted((r1.id, r2.id))
            desired.append(
                {
                    "thread_id": thread.id,
                    "kind": "divergent_reading_positions",
                    "signal_key": (
                        f"o4:{thread.id}:{first}|{second}:"
                        f"{r1.progression.lens_id}"
                    ),
                    "evidence_refs": shared,
                    "detail": {
                        "reading_ids": [first, second],
                        "lens_id": r1.progression.lens_id,
                        "phases": {
                            r1.id: r1.progression.phase,
                            r2.id: r2.progression.phase,
                        },
                        "primary_scale": r1.primary_scale,
                    },
                }
            )
    return desired


def run_friction_pass(
    store: NarrativeStore,
    user_id: str,
    *,
    meetings: Any = None,
    claims: Any = None,
    gate_open: Callable[[], bool] | None = None,
    now: datetime | None = None,
) -> FrictionResult:
    """One recompute pass over the user's live threads + meetings.

    Per thread (then the meeting scan): re-check the gate, compute
    the desired observable set from current rows, and sync it in
    one transaction. A closed gate skips that unit entirely — no
    writes AND no deletes for it (recompute paused, not run).
    ``meetings`` / ``claims`` are row dicts, or callables taking
    user_id returning row dicts. No generation function exists
    here by design: this pass cannot spend generation.
    """
    gate = gate_open or (lambda: True)
    now_dt = now or datetime.now(timezone.utc)
    meeting_rows = _resolve_provider(meetings, user_id)
    claim_rows = _resolve_provider(claims, user_id)
    # Claim rows arrive as "id" (tests, plain dicts) or "claim_id"
    # (the intake store's claims_for_user rows) — accept both.
    claims_by_id = {}
    for c in claim_rows:
        cid = c.get("id") or c.get("claim_id")
        if cid:
            claims_by_id[str(cid)] = c
    result = FrictionResult(meetings_scanned=len(meeting_rows))

    threads = [
        t
        for t in store.threads_for(user_id, limit=None)
        if t.status in LIVE_THREAD_STATUSES
    ]
    for thread in threads:
        if not _safe_gate(gate):
            result.gate_skipped_threads += 1
            continue
        desired = _derive_thread_rows(
            store, user_id, thread, claims_by_id, now_dt
        )
        written, refreshed, removed = store.sync_thread_observables(
            user_id, thread.id, desired
        )
        result.written += written
        result.refreshed += refreshed
        result.removed += removed
        result.threads_scanned += 1

    if not _safe_gate(gate):
        result.gate_skipped_meetings = True
    else:
        desired_o1 = _derive_o1(meeting_rows, claim_rows)
        written, refreshed, removed = store.sync_meeting_observables(
            user_id, desired_o1
        )
        result.written += written
        result.refreshed += refreshed
        result.removed += removed
    return result


def _safe_gate(gate: Callable[[], bool]) -> bool:
    """A gate read that fails closed (mirrors the sweep's rule)."""
    try:
        return bool(gate())
    except Exception:
        return False


__all__ = [
    "FRICTION_QUIET_WINDOW_DAYS",
    "FrictionResult",
    "LIVE_THREAD_STATUSES",
    "MEETING_IMPRESSION_CLAIM_TYPE",
    "OBSERVABLE_KINDS",
    "run_friction_pass",
]
