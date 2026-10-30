"""Program runner for the Moneyball role-only comparison.

Runs the six experiment meetings sequentially under ONE program cap,
with a persistent cumulative ledger. This module never generates,
never spends on its own authority, and never runs without a cap.

CAP SEMANTICS — READ CAREFULLY. The cap is a RESERVATION-BUDGET
guarantee, not a guarantee against every possible provider billing
discrepancy, especially where actual usage is unavailable (only the
GPT seat settles to provider-reported usage; other seats settle to
retained estimates). What the runner guarantees:

- It REFUSES to execute without a cap (``cap_usd=None`` raises).
  No cap is hardcoded and no default exists in this module.
- Each meeting's maximum budget is ``min($0.50, remaining)`` and is
  enforced by the EXISTING admission machinery (batch atomicity
  refuses a batch whose reservations exceed the meeting budget).
  The estimated reservation table is used for PLANNING only, never
  as the enforcement ceiling — an estimate is not a ceiling.
- If the program requires all meetings to complete, the runner
  additionally checks, before starting each meeting, that the
  remaining budget covers the estimated reservations of that
  meeting plus all later meetings — and STOPS before beginning a
  meeting that cannot meet its required allocation. That stop
  decision uses estimates; enforcement still uses the actual
  allocation above. The two must not be confused.
- The cumulative ledger is persisted to disk (atomically) after
  every meeting and reloaded on start, so a restart cannot
  accidentally reset the program cap.
- The runner refuses to start at all if the pricing table is
  expired (admission already fails closed per generation; the
  runner check makes the program-level failure explicit first).

The actual cap figure and the spend authorization are both decided
immediately before execution, using the pricing table current at
that time. Nothing in this module chooses a cap, authorizes spend,
or runs a meeting on its own: ``run_program`` is a harness the
operator invokes with an explicit cap, after separate authorization.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from local_ai.build_room.meeting import (
    CAP_DEFAULT_MAX_COST_USD,
    CAP_PRICING_DEFAULT_EXPIRY,
    R2_MAX_GENERATIONS,
    Budget,
    EvidencePacket,
    run_multi_model_meeting,
)

# Default per-meeting budget: the room's standing default. A meeting
# never receives more than this, whatever the program cap is.
MEETING_BUDGET_USD = CAP_DEFAULT_MAX_COST_USD


def _today_iso() -> str:
    return time.strftime("%Y-%m-%d", time.localtime())


def pricing_expired(expiry: str, today: str | None = None) -> bool:
    """True when the pricing table expiry is before today."""
    return expiry < (today or _today_iso())


def allocation_for(cap_usd: float, cumulative_reserved_usd: float) -> float:
    """A meeting's enforceable allocation: min($0.50, remaining).

    Never negative: an exhausted program allocates $0.00, and the
    runner stops rather than starting a meeting on $0.00.
    """
    return max(0.0, min(MEETING_BUDGET_USD, cap_usd - cumulative_reserved_usd))


def reserve_needed(estimates: list[float | None]) -> float:
    """Budget that must remain to cover a list of upcoming meetings.

    Each estimate is that meeting's estimated reservation; a missing
    estimate defaults to the full per-meeting budget ($0.50), the
    conservative actual ceiling. This figure informs ONLY the
    stop/continue decision — enforcement always uses the actual
    allocation from :func:`allocation_for`.
    """
    return sum(e if e is not None else MEETING_BUDGET_USD for e in estimates)


def committed_from_cap_budget(cap_budget: dict[str, Any]) -> float:
    """Money committed by one meeting, from its cap_budget record.

    Estimated expenditure (settled + retained unverified +
    retained uncertain) PLUS outstanding reservations. Outstanding
    should be ~$0.00 at meeting end (everything settled or
    retained), but it is counted, not assumed away: a reservation
    that has not settled is still committed money for cap purposes.
    """
    return round(
        float(cap_budget.get("estimated_expenditure_usd", 0.0))
        + float(cap_budget.get("outstanding_reserved_usd", 0.0)),
        6,
    )


@dataclass
class MeetingSpec:
    """One program meeting. ``condition`` is "A" or "B".

    ``estimated_reservation_usd`` is a PLANNING figure for the
    reserve-or-stop decision only (None defaults to $0.50). It is
    never passed to admission and never enforced.
    """

    packet: EvidencePacket
    condition: str
    estimated_reservation_usd: float | None = None
    seats: list | None = None
    principal: Any | None = None
    tools_enabled: bool = False
    role_prompt_extras: dict[str, str] | None = None
    role_brief_version: str | None = None


@dataclass
class MeetingRecord:
    packet_work_item: str
    condition: str
    meeting_id: str
    allocation_usd: float
    committed_usd: float
    ok: bool
    artifact_path: str
    capture_path: str = ""


@dataclass
class ProgramResult:
    status: str  # "completed" | "stopped" | "refused"
    cap_usd: float
    cumulative_reserved_usd: float
    meetings: list[MeetingRecord] = field(default_factory=list)
    reason: str = ""


def packet_hash(packet: EvidencePacket) -> str:
    """Frozen-packet fingerprint: the rendered prompt, hashed."""
    return hashlib.sha256(packet.render_prompt().encode("utf-8")).hexdigest()


def build_meeting_capture(
    result: Any, spec: MeetingSpec, *, allocation_usd: float, committed_usd: float
) -> dict[str, Any]:
    """Assemble one meeting's deterministic capture record.

    Frozen packet, condition + brief version, base-prompt hashes,
    transcript, registry, outcomes, cap_budget, and raw responses.
    Raw responses are the transcript's contribution texts: the room
    appends full pre-parse generation text to contribution entries
    (verified in tests), so no separate raw log is needed — the
    transcript IS the raw record. If a future room change ever
    dropped pre-parse text, this builder must gain an append-only
    raw log; the ``raw_text_retained`` flag exists so that change
    is detectable, not assumed.
    """
    artifact = result.artifact
    transcript_entries = []
    raw_texts: list[dict[str, str]] = []
    transcript = getattr(result, "transcript", None)
    if transcript is not None:
        for entry in transcript.entries:
            transcript_entries.append(
                {"kind": entry.kind, "participant": entry.participant,
                 "text": entry.text}
            )
            if entry.kind == "contribution":
                raw_texts.append(
                    {"participant": entry.participant, "text": entry.text}
                )
    comparison = artifact.get("comparison_capture", {})
    return {
        "meeting_id": result.meeting_id,
        "packet_hash": packet_hash(spec.packet),
        "packet_work_item": spec.packet.work_item,
        "condition": spec.condition,
        "role_brief_version": spec.role_brief_version,
        "role_brief_seats": comparison.get("role_brief_seats", []),
        "base_prompt_hashes": comparison.get("base_prompt_hashes", {}),
        "allocation_usd": allocation_usd,
        "committed_usd": committed_usd,
        "ok": result.ok,
        "transcript": transcript_entries,
        "claim_registry": artifact.get("claim_registry", []),
        "cap_budget": artifact.get("cap_budget", {}),
        "raw_responses": raw_texts,
        "raw_text_retained": True,
    }


class ProgramLedger:
    """Persistent cumulative ledger for one program run.

    Stored as JSON, written atomically (temp file + rename) after
    every meeting. A ledger file created under a different cap
    refuses to load under this cap: caps are never silently mixed.
    """

    def __init__(self, path: Path | str, cap_usd: float):
        self.path = Path(path)
        self.cap_usd = cap_usd
        self.cumulative_reserved_usd = 0.0
        self.meetings: list[dict[str, Any]] = []
        if self.path.exists():
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if float(data.get("cap_usd", cap_usd)) != float(cap_usd):
                raise ValueError(
                    f"ledger cap mismatch: file holds cap "
                    f"${data.get('cap_usd')} but this run names "
                    f"${cap_usd}; refusing to mix programs"
                )
            self.cumulative_reserved_usd = float(
                data.get("cumulative_reserved_usd", 0.0)
            )
            self.meetings = list(data.get("meetings", []))

    def record(self, record: dict[str, Any], committed_usd: float) -> None:
        self.meetings.append(record)
        self.cumulative_reserved_usd = round(
            self.cumulative_reserved_usd + committed_usd, 6
        )
        self._persist()

    def _persist(self) -> None:
        payload = {
            "cap_usd": self.cap_usd,
            "cumulative_reserved_usd": self.cumulative_reserved_usd,
            "meetings": self.meetings,
        }
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n",
                       encoding="utf-8")
        os.replace(tmp, self.path)


def run_program(
    specs: list[MeetingSpec],
    *,
    cap_usd: float | None,
    ledger_path: Path | str,
    store_dir: Path | str,
    require_completion: bool = True,
    pricing_expiry: str = CAP_PRICING_DEFAULT_EXPIRY,
    today: str | None = None,
    meeting_fn: Callable[..., Any] | None = None,
) -> ProgramResult:
    """Run a program of meetings sequentially under one cap.

    ``cap_usd=None`` raises: the runner REFUSES to execute without
    a cap. There is no default and no hardcoded figure. ``store_dir``
    holds every meeting's transcript/artifact/capture files (names
    are per-meeting-id, so one directory serves the whole program).

    Returns a ProgramResult: "completed" (all specs ran),
    "stopped" (cap/reserve exhaustion — no partial meeting started
    past the stop), or "refused" (expired pricing — nothing ran).
    A stopped program's ledger still holds every completed meeting,
    so a later authorized run can resume accounting from it — it
    can never silently restart the cap.
    """
    if cap_usd is None:
        raise ValueError(
            "program cap is required: run_program refuses to execute "
            "without an explicit cap_usd. No default exists."
        )
    if cap_usd <= 0:
        raise ValueError(f"program cap must be positive, got ${cap_usd}")
    if pricing_expired(pricing_expiry, today):
        return ProgramResult(
            status="refused", cap_usd=cap_usd, cumulative_reserved_usd=0.0,
            reason=(
                f"pricing table expired {pricing_expiry}; admission "
                "fails closed until the table is refreshed. No "
                "meeting started."
            ),
        )
    store = Path(store_dir)
    store.mkdir(parents=True, exist_ok=True)
    ledger = ProgramLedger(ledger_path, cap_usd)
    fn = meeting_fn or run_multi_model_meeting
    records: list[MeetingRecord] = []
    for index, spec in enumerate(specs):
        remaining = cap_usd - ledger.cumulative_reserved_usd
        if require_completion:
            need = reserve_needed(
                [s.estimated_reservation_usd for s in specs[index:]]
            )
            if remaining < need:
                return ProgramResult(
                    status="stopped", cap_usd=cap_usd,
                    cumulative_reserved_usd=ledger.cumulative_reserved_usd,
                    meetings=records,
                    reason=(
                        f"reserve shortfall before meeting {index + 1} "
                        f"({spec.condition} {spec.packet.work_item!r}): "
                        f"remaining ${remaining:.4f} < required "
                        f"${need:.4f} for this and later meetings. "
                        "No partial meeting started."
                    ),
                )
        allocation = allocation_for(cap_usd, ledger.cumulative_reserved_usd)
        if allocation <= 0:
            return ProgramResult(
                status="stopped", cap_usd=cap_usd,
                cumulative_reserved_usd=ledger.cumulative_reserved_usd,
                meetings=records,
                reason=(
                    f"program budget exhausted before meeting {index + 1} "
                    f"({spec.condition} {spec.packet.work_item!r}): "
                    f"remaining ${remaining:.4f}. No partial meeting started."
                ),
            )
        budget = Budget(
            max_cost_usd=allocation, max_contributions=R2_MAX_GENERATIONS,
            timeout_seconds=120,
        )
        result = fn(
            spec.packet,
            store_dir=store,
            budget=budget,
            seats=spec.seats,
            principal=spec.principal,
            tools_enabled=spec.tools_enabled,
            role_prompt_extras=spec.role_prompt_extras,
            role_brief_version=spec.role_brief_version,
        )
        committed = committed_from_cap_budget(result.artifact["cap_budget"])
        capture = build_meeting_capture(
            result, spec, allocation_usd=allocation, committed_usd=committed
        )
        capture_path = store / f"meeting_{result.meeting_id}.comparison_capture.json"
        capture_path.write_text(
            json.dumps(capture, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        record = {
            "packet_work_item": spec.packet.work_item,
            "condition": spec.condition,
            "meeting_id": result.meeting_id,
            "allocation_usd": allocation,
            "committed_usd": committed,
            "ok": result.ok,
            "artifact_path": str(result.artifact_path),
            "capture_path": str(capture_path),
        }
        ledger.record(record, committed)
        records.append(MeetingRecord(**record))
    return ProgramResult(
        status="completed", cap_usd=cap_usd,
        cumulative_reserved_usd=ledger.cumulative_reserved_usd,
        meetings=records,
    )
