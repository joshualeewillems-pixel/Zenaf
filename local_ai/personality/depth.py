"""Phase 6: visible training-depth metrics — the trust mechanism for rentals.

For each of the seven strands, a faithful, explainable summary of how much
real training evidence exists. Someone deciding whether to rent a
doppelganger — or the user judging their own mirror — needs to see, per
faculty, how deeply it is trained. And honest zeros where it is not:
zero evidence renders as zero ("not yet trained"), never a placeholder
score. No seed/demo data; the metric reads live stores only.

Depth formula (all components in [0.0, 1.0]; simple and explainable by
design — this is a faithful summary of evidence, not a vanity score):

    signal_breadth    = min(approved_signals_mapped_to_strand / 20, 1.0)
                        # raw approved observations; 20+ = full breadth
    profile_depth     = strand_evidence_depth(profile, strand, include_voice=False)
                        # curated, user-published content (PR #39 slot metric);
                        # 0 when nothing is published. Voice is excluded on
                        # purpose: it is global, not strand-specific, so it
                        # must not inflate any single faculty's depth.
    recency           = max(0.0, 1.0 - days_since_last_evidence / 365)
                        # stale training counts for less; a year silent = 0
    context_diversity = min(distinct_nonempty_decision_envelopes / 4, 1.0)
                        # a strand observed across 4+ distinct decision
                        # contexts (PR #41 envelopes) is fully diverse

    depth = (0.30 * signal_breadth + 0.30 * profile_depth
             + 0.20 * recency + 0.20 * context_diversity)
    score = round(depth * 100)   # 0..100, integer

Zero evidence (no mapped approved signals AND no published profile content
for the strand) scores exactly 0 and reports trained=False. Candidates and
proposals are inert — they never count as training.

Bands (glanceable, coarse by design — no fake precision):
    0        -> "not yet trained"
    1-24     -> "early"
    25-49    -> "developing"
    50-74    -> "trained"
    75-100   -> "deeply trained"

Extension point (zones): Joshua's zone taxonomy is free-form on the
surface; strands are the concrete structure today. When zones formalize,
add a zone rollup here — e.g. zone_training_depth(zone, strand_depths,
relevance_map) aggregating these per-strand depths weighted by
zone->strand relevance. The per-strand computation below is the leaf;
zone rollups must call it, not duplicate it.

Read-only: everything here takes already-loaded objects and computes.
Nothing in this module writes to any store.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from local_ai.strands import strand_keys

from .blend import strand_evidence_depth
from .context import get_signal_context

if TYPE_CHECKING:  # pragma: no cover
    from .schema import PersonalityProfile
    from local_ai.presence_ingest.schema import TrainingSignal

_STRAND_KEYS: tuple[str, ...] = strand_keys()

#: Approved signals mapped to a strand at/above this count = full breadth.
SIGNAL_BREADTH_REF = 20
#: Distinct decision contexts at/above this count = fully diverse.
CONTEXT_DIVERSITY_REF = 4
#: Recency decays linearly to zero over this many days of silence.
RECENCY_HALF_LIFE_DAYS = 365

_BANDS: tuple[tuple[int, int, str], ...] = (
    (0, 0, "not yet trained"),
    (1, 24, "early"),
    (25, 49, "developing"),
    (50, 74, "trained"),
    (75, 100, "deeply trained"),
)


def band_for_score(score: int) -> str:
    """Coarse human band for a 0..100 depth score."""
    for lo, hi, label in _BANDS:
        if lo <= score <= hi:
            return label
    return "not yet trained"  # unreachable for valid scores; honest default


def map_signal_to_strand(signal: "TrainingSignal") -> str | None:
    """Map a TrainingSignal to one strand key, or None when unmappable.

    Single source of truth is the keyword mapping in seed.py
    (_map_zone_to_strand); this wraps it so the depth metric and the
    seeding pipeline can never disagree about where a signal belongs.
    Unmapped signals contribute to no strand's depth — honest, not silent.
    """
    from .seed import _map_zone_to_strand

    text = f"{signal.summary}\n{signal.payload_redacted or ''}"
    key, _confidence, _how = _map_zone_to_strand(signal.zone, text)
    return key


def _signal_ts(signal: "TrainingSignal") -> datetime | None:
    try:
        return datetime.fromtimestamp(signal.ts_ms / 1000, tz=timezone.utc)
    except (TypeError, ValueError, OverflowError, OSError):
        return None


@dataclass
class StrandDepth:
    """Visible training depth of one strand. Plain data — JSON-serializable."""

    strand_key: str
    score: int  # 0..100
    band: str
    trained: bool
    components: dict[str, float] = field(default_factory=dict)
    approved_signals: int = 0
    profile_versions_touching: int = 0
    distinct_contexts: int = 0
    last_evidence_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "strand_key": self.strand_key,
            "score": self.score,
            "band": self.band,
            "trained": self.trained,
            "components": dict(self.components),
            "approved_signals": self.approved_signals,
            "profile_versions_touching": self.profile_versions_touching,
            "distinct_contexts": self.distinct_contexts,
            "last_evidence_at": self.last_evidence_at,
        }


def compute_strand_depth(
    strand_key: str,
    *,
    signals: list["TrainingSignal"],
    profile: "PersonalityProfile | None",
    versions_touching: int = 0,
    touching_version_ts: list[datetime] | None = None,
    now: datetime | None = None,
) -> StrandDepth:
    """Depth of one strand from real evidence. Pure: no store access.

    signals: approved TrainingSignals already mapped to this strand
             (caller maps via map_signal_to_strand) and already scoped
             to the user (caller filters by license sessions).
    profile: the user's current published PersonalityProfile, or None.
    versions_touching: how many published versions carry content for
             this strand (informational — the score reads the CURRENT
             profile's content, not the count).
    touching_version_ts: created_at of the touching versions (recency).
    """
    now = now or datetime.now(timezone.utc)
    n_signals = len(signals)

    signal_breadth = min(n_signals / SIGNAL_BREADTH_REF, 1.0)

    profile_depth = (
        strand_evidence_depth(profile, strand_key, include_voice=False)
        if profile is not None
        else 0.0
    )

    # Recency: freshest evidence across mapped signals and touching versions.
    latest: datetime | None = None
    for sig in signals:
        ts = _signal_ts(sig)
        if ts is not None and (latest is None or ts > latest):
            latest = ts
    for ts in touching_version_ts or []:
        if ts is not None and (latest is None or ts > latest):
            latest = ts
    if latest is None:
        recency = 0.0
    else:
        days = max(0.0, (now - latest).total_seconds() / 86400.0)
        recency = max(0.0, 1.0 - days / RECENCY_HALF_LIFE_DAYS)

    # Context diversity: distinct non-empty decision envelopes on
    # decision-layer signals. Unknown-everything envelopes don't count —
    # an unobserved context is not a diverse one.
    envelopes: set[str] = set()
    for sig in signals:
        if getattr(sig, "layer", None) != "decision":
            continue
        ctx = get_signal_context(sig)
        if not ctx.is_empty():
            envelopes.add(ctx.signature())
    context_diversity = min(len(envelopes) / CONTEXT_DIVERSITY_REF, 1.0)

    has_evidence = n_signals > 0 or profile_depth > 0
    if not has_evidence:
        depth01 = 0.0
    else:
        depth01 = (
            0.30 * signal_breadth
            + 0.30 * profile_depth
            + 0.20 * recency
            + 0.20 * context_diversity
        )
    score = int(round(depth01 * 100))

    return StrandDepth(
        strand_key=strand_key,
        score=score,
        band=band_for_score(score) if has_evidence else "not yet trained",
        trained=has_evidence,
        components={
            "signal_breadth": round(signal_breadth, 4),
            "profile_depth": round(profile_depth, 4),
            "recency": round(recency, 4),
            "context_diversity": round(context_diversity, 4),
        },
        approved_signals=n_signals,
        profile_versions_touching=versions_touching,
        distinct_contexts=len(envelopes),
        last_evidence_at=latest.isoformat() if latest else None,
    )


def compute_training_depth(
    *,
    signals: list["TrainingSignal"],
    profile: "PersonalityProfile | None",
    versions: list[tuple[int, "PersonalityProfile"]] | None = None,
    now: datetime | None = None,
) -> dict[str, StrandDepth]:
    """Per-strand training depth for all seven strands. Pure: no store access.

    signals: approved TrainingSignals, already scoped to the user by the
             caller (e.g. license-session scoping in the API layer).
    profile: the user's current published profile, or None.
    versions: published (version_number, profile) pairs for the
             versions-touching counts and recency; current profile's own
             content is read from `profile`.
    """
    now = now or datetime.now(timezone.utc)
    versions = versions or []

    by_strand: dict[str, list["TrainingSignal"]] = {k: [] for k in _STRAND_KEYS}
    for sig in signals:
        key = map_signal_to_strand(sig)
        if key is not None:
            by_strand[key].append(sig)

    touching: dict[str, int] = {k: 0 for k in _STRAND_KEYS}
    touching_ts: dict[str, list[datetime]] = {k: [] for k in _STRAND_KEYS}
    for _vnum, vprofile in versions:
        for k in _STRAND_KEYS:
            if strand_evidence_depth(vprofile, k, include_voice=False) > 0:
                touching[k] += 1
                ts = vprofile.created_at
                if ts is not None:
                    if ts.tzinfo is None:
                        ts = ts.replace(tzinfo=timezone.utc)
                    touching_ts[k].append(ts)

    return {
        k: compute_strand_depth(
            k,
            signals=by_strand[k],
            profile=profile,
            versions_touching=touching[k],
            touching_version_ts=touching_ts[k],
            now=now,
        )
        for k in _STRAND_KEYS
    }
