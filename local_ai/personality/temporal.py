"""Phase 5: temporal modeling — signal decay, profile snapshots, era addressing.

Joshua's design (non-negotiable shape):
  - Training signals DECAY unless parallels persist. Decay affects how
    evidence is ranked/weighted; it NEVER deletes anything (park, don't
    delete).
  - Profile builds are archived as temporal SNAPSHOTS: annual by default,
    plus triggered after substantial training volume, plus user-initiated.
    Snapshots are immutable, named, addressable eras — the foundation of
    era rental (e.g. rent "early Zenaf era" vs a later era). Rental
    mechanics themselves are NOT built here.

Contents:
  - Signal decay: `signal_relevance`, `find_parallels`,
    `rank_signals_by_relevance` (pure functions over TrainingSignal).
  - Snapshots: `ProfileSnapshot` (frozen), trigger constants, and
    `run_temporal_maintenance` — the scheduler entry point. The actual
    storage methods live on `PersonalityStore` (same DB, per-user
    scoping) so snapshots inherit the no-silent-write guarantees:
    snapshots are created only by the three sanctioned triggers
    (manual / volume / annual); there is no update or delete path.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

if TYPE_CHECKING:  # pragma: no cover
    from local_ai.presence_ingest.schema import TrainingSignal
    from .store import PersonalityStore


# ---------------------------------------------------------------------------
# Signal decay
# ---------------------------------------------------------------------------
# Formula (documented so it stays explainable):
#
#   relevance(signal) = min(1.0, base + boost)
#
#   base  = 0.5 ** (age_days / SIGNAL_HALF_LIFE_DAYS)
#   boost = sum(CORROBORATION_WEIGHT * 0.5 ** (p_age_days / SIGNAL_HALF_LIFE_DAYS)
#               for each parallel p)
#
# A fresh signal starts at relevance 1.0 and halves every SIGNAL_HALF_LIFE_DAYS
# unless parallels persist: each corroborating (parallel) signal adds back up
# to CORROBORATION_WEIGHT, scaled by the parallel's own freshness — a fresh
# parallel recharges more than a stale one. The cap at 1.0 keeps relevance a
# weight, not a score that compounds without bound.
#
# "Parallel" = same training layer + same zone (see find_parallels). The
# intuition: a decision pattern observed once, long ago, in one zone is weak
# evidence; the same pattern re-observed recently, in the same zone, stays
# alive. Decay only ever re-orders evidence — rows are never deleted.
SIGNAL_HALF_LIFE_DAYS = 180.0
CORROBORATION_WEIGHT = 0.25


def _age_days(ts_ms: int, now: datetime) -> float:
    age_seconds = (now - datetime.fromtimestamp(ts_ms / 1000.0, tz=timezone.utc)).total_seconds()
    return max(0.0, age_seconds / 86400.0)


def find_parallels(
    signal: "TrainingSignal", candidates: list["TrainingSignal"]
) -> list["TrainingSignal"]:
    """Signals that corroborate `signal`: same layer + same zone.

    Excludes the signal itself (by signal_id). Kept deliberately coarse —
    parallels are about "this pattern showed up again", not deep semantic
    matching (that's a future, bandwidth-dependent refinement).
    """
    return [
        c
        for c in candidates
        if c.signal_id != signal.signal_id and c.layer == signal.layer and c.zone == signal.zone
    ]


def signal_relevance(
    signal: "TrainingSignal",
    parallels: list["TrainingSignal"] | None = None,
    *,
    now: datetime | None = None,
) -> float:
    """Relevance weight in (0.0, 1.0] for one training signal.

    `parallels` should be pre-filtered with `find_parallels` (or any
    caller-chosen corroboration set). Pure function: no I/O, never raises
    on sane input, never mutates.
    """
    now = now or datetime.now(timezone.utc)
    base = 0.5 ** (_age_days(signal.ts_ms, now) / SIGNAL_HALF_LIFE_DAYS)
    boost = 0.0
    for p in parallels or ():
        boost += CORROBORATION_WEIGHT * (
            0.5 ** (_age_days(p.ts_ms, now) / SIGNAL_HALF_LIFE_DAYS)
        )
    return min(1.0, max(1e-9, base + boost))


def rank_signals_by_relevance(
    signals: list["TrainingSignal"], *, now: datetime | None = None
) -> list[tuple["TrainingSignal", float]]:
    """Rank signals by current relevance, highest first.

    Parallels are computed within the given set. The input list is never
    mutated and nothing is dropped — decay re-orders evidence; deletion is
    not a thing this module does.
    """
    now = now or datetime.now(timezone.utc)
    scored = [
        (s, signal_relevance(s, find_parallels(s, signals), now=now)) for s in signals
    ]
    scored.sort(key=lambda pair: pair[1], reverse=True)
    return scored


# ---------------------------------------------------------------------------
# Snapshots
# ---------------------------------------------------------------------------
SNAPSHOT_TRIGGER_MANUAL = "manual"
SNAPSHOT_TRIGGER_VOLUME = "volume"
SNAPSHOT_TRIGGER_ANNUAL = "annual"
SNAPSHOT_TRIGGERS: tuple[str, ...] = (
    SNAPSHOT_TRIGGER_MANUAL,
    SNAPSHOT_TRIGGER_VOLUME,
    SNAPSHOT_TRIGGER_ANNUAL,
)

# Training-volume trigger: a snapshot fires after this many NEW published
# profile versions since the last volume-triggered snapshot. Rationale: a
# published version is one full propose -> review -> publish cycle, i.e. one
# unit of real training the user signed off on. Ten such cycles is a
# substantial uptick worth archiving as an era boundary, while small enough
# to actually fire during active use. Tunable.
VOLUME_TRIGGER_VERSIONS = 10

# Annual cadence: a scheduler should call run_temporal_maintenance()
# (below) periodically — e.g. daily. This constant is the policy: one
# annual snapshot per 365 days, marking the year's era boundary.
ANNUAL_SNAPSHOT_DAYS = 365


class ProfileSnapshot(BaseModel):
    """An IMMUTABLE, named archive of one published profile version.

    Frozen by construction (pydantic frozen model): attribute assignment
    raises. The store offers no update/delete path for snapshots at all —
    the only writes are the three sanctioned triggers. Era addressing:
    `snapshot_id` (stable) or `era_name` (user-given, unique per user).
    """

    model_config = ConfigDict(frozen=True)

    snapshot_id: str
    user_id: str
    profile_id: str
    version: int = Field(ge=1)
    trigger: Literal["manual", "volume", "annual"]
    era_name: str | None = None  # user label, e.g. "early Zenaf era"
    auto_label: str  # e.g. "2026-10-14 · v12 · volume"
    note: str = ""
    created_at: datetime
    # Full immutable copy of the profile at snapshot time — the payload
    # era rental will one day serve.
    profile_json: str


def snapshot_auto_label(version: int, trigger: str, created_at: datetime) -> str:
    return f"{created_at.date().isoformat()} · v{version} · {trigger}"


def run_temporal_maintenance(store: "PersonalityStore") -> dict[str, Any]:
    """Scheduler entry point: run the automatic snapshot triggers.

    Call periodically (e.g. daily cron). Checks the volume trigger and the
    annual cadence; creates snapshots only when due (idempotent — re-running
    without new training volume creates nothing). Returns a report dict.
    No scheduler is built here; this is the function a scheduler calls.
    """
    report: dict[str, Any] = {
        "volume": {"due": False, "created": False},
        "annual": {"due": False, "created": False},
    }
    if store.check_volume_trigger():
        snap, created = store.ensure_snapshot(SNAPSHOT_TRIGGER_VOLUME)
        report["volume"] = {
            "due": True,
            "created": created,
            "snapshot_id": snap.snapshot_id,
        }
    if store.annual_snapshot_due():
        snap, created = store.ensure_snapshot(SNAPSHOT_TRIGGER_ANNUAL)
        report["annual"] = {
            "due": True,
            "created": created,
            "snapshot_id": snap.snapshot_id,
        }
    return report
