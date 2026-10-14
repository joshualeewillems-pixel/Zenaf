"""Decision context: the coarse situational envelope on decision records.

Architecture (Joshua's directive): context is a CONDITIONER on the seven
strands, NOT an eighth strand. World stays excluded — you don't train the
environment, you train how the faculties behave inside it. The profile is a
function over situations, not a bag of traits.

Six canonical dimensions (ratified set), three levels each. Every dimension
defaults to `unknown`: honest gaps stay visible, never guessed.

Deliberately EXCLUDED: internal states (tired, grieving, stressed) —
surveillance territory, not consensual context. This envelope describes the
situation, never reads the person.

Storage: decision-type TrainingSignals carry the envelope in
`context_ref["decision_context"]` as a plain dict. Old records without the
key parse as all-unknown — migration-safe by construction, no DB change.

Capture discipline (his rules): coarse and consensual. Derived from the
conversation where the system honestly can (metadata, never a form field);
otherwise the caller passes it explicitly; otherwise unknown. No passive
inference of anything beyond these six situational dimensions.
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

UNKNOWN = "unknown"

#: Canonical dimensions, in stable order.
DIMENSIONS: tuple[str, ...] = (
    "stakes",
    "reversibility",
    "time_pressure",
    "information",
    "social_field",
    "resource_climate",
)

#: Canonical levels per dimension (excluding "unknown").
LEVELS: dict[str, tuple[str, ...]] = {
    "stakes": ("low", "significant", "life-altering"),
    "reversibility": ("easily", "costly", "irreversible"),
    "time_pressure": ("urgent", "deliberative", "open-ended"),
    "information": ("thin", "adequate", "rich"),
    "social_field": ("solo", "interpersonal", "publicly_accountable"),
    "resource_climate": ("scarcity", "sufficiency", "abundance"),
}

StakesLevel = Literal["unknown", "low", "significant", "life-altering"]
ReversibilityLevel = Literal["unknown", "easily", "costly", "irreversible"]
TimePressureLevel = Literal["unknown", "urgent", "deliberative", "open-ended"]
InformationLevel = Literal["unknown", "thin", "adequate", "rich"]
SocialFieldLevel = Literal["unknown", "solo", "interpersonal", "publicly_accountable"]
ResourceClimateLevel = Literal["unknown", "scarcity", "sufficiency", "abundance"]

#: Key inside TrainingSignal.context_ref carrying the envelope.
CONTEXT_REF_KEY = "decision_context"


def normalize_level(dimension: str, raw: Any) -> str:
    """Coerce a raw value to its canonical level, or "unknown".

    Tolerant of case and separator style ("Life-Altering",
    "publicly accountable" both work); anything unrecognized — including
    non-strings — becomes "unknown". Never guesses.
    """
    if not isinstance(raw, str):
        return UNKNOWN
    cand = raw.strip().lower().replace("-", "_").replace(" ", "_")
    if cand in ("", "unknown", "unk", "n_a", "na", "none"):
        return UNKNOWN
    for level in LEVELS.get(dimension, ()):
        if level.replace("-", "_") == cand:
            return level
    return UNKNOWN


class DecisionContext(BaseModel):
    """The coarse situational envelope of one decision."""

    stakes: StakesLevel = UNKNOWN
    reversibility: ReversibilityLevel = UNKNOWN
    time_pressure: TimePressureLevel = UNKNOWN
    information: InformationLevel = UNKNOWN
    social_field: SocialFieldLevel = UNKNOWN
    resource_climate: ResourceClimateLevel = UNKNOWN

    @model_validator(mode="before")
    @classmethod
    def _normalize_levels(cls, data: Any) -> dict[str, Any]:
        if not isinstance(data, dict):
            return {}
        out: dict[str, Any] = {}
        for dim in DIMENSIONS:
            if dim in data:
                out[dim] = normalize_level(dim, data[dim])
        return out

    def known(self) -> dict[str, str]:
        """Dimension -> level for the dimensions actually specified."""
        return {d: getattr(self, d) for d in DIMENSIONS if getattr(self, d) != UNKNOWN}

    def is_empty(self) -> bool:
        """True when every dimension is unknown (no usable context)."""
        return not self.known()

    def signature(self) -> str:
        """Canonical grouping key over known dimensions; "" when empty."""
        return "|".join(f"{d}={getattr(self, d)}" for d in DIMENSIONS if getattr(self, d) != UNKNOWN)

    def summarize(self) -> str:
        """Short human-readable summary, e.g. "significant stakes, urgent"."""
        templates = {
            "stakes": lambda v: f"{v} stakes",
            "reversibility": lambda v: {"easily": "easily reversible", "costly": "costly to reverse", "irreversible": "irreversible"}[v],
            "time_pressure": lambda v: {"urgent": "urgent", "deliberative": "deliberative pace", "open-ended": "open-ended timing"}[v],
            "information": lambda v: f"{v} information",
            "social_field": lambda v: {"solo": "deciding solo", "interpersonal": "interpersonal setting", "publicly_accountable": "publicly accountable"}[v],
            "resource_climate": lambda v: {"scarcity": "scarce resources", "sufficiency": "sufficient resources", "abundance": "abundant resources"}[v],
        }
        bits = [templates[d](getattr(self, d)) for d in DIMENSIONS if getattr(self, d) != UNKNOWN]
        return ", ".join(bits) if bits else "unspecified context"


def parse_decision_context(raw: Any) -> DecisionContext:
    """Parse anything into a DecisionContext. Never raises, never guesses.

    None, non-dicts, and dicts with bad values all yield (partially or
    fully) unknown contexts — this is what makes old signal records
    migration-safe.
    """
    if isinstance(raw, DecisionContext):
        return raw
    if not isinstance(raw, dict):
        return DecisionContext()
    try:
        return DecisionContext(**raw)
    except Exception:
        return DecisionContext()


def get_signal_context(signal: Any) -> DecisionContext:
    """Read the decision envelope off a TrainingSignal (or plain dict).

    Old records without the key read as all-unknown.
    """
    ref: Any = None
    if isinstance(signal, dict):
        ref = signal.get("context_ref")
    else:
        ref = getattr(signal, "context_ref", None)
    raw = ref.get(CONTEXT_REF_KEY) if isinstance(ref, dict) else None
    return parse_decision_context(raw)


def set_signal_context(signal: Any, context: DecisionContext) -> None:
    """Attach a decision envelope to a TrainingSignal (or plain dict)."""
    payload = context.model_dump()
    if isinstance(signal, dict):
        signal.setdefault("context_ref", {})[CONTEXT_REF_KEY] = payload
        return
    ref = getattr(signal, "context_ref", None)
    if not isinstance(ref, dict):
        try:
            signal.context_ref = {}
        except Exception:
            return
        ref = signal.context_ref
    ref[CONTEXT_REF_KEY] = payload


def context_similarity(a: DecisionContext, b: DecisionContext) -> float:
    """Similarity in [0.0, 1.0] between two envelopes.

    Over the dimensions where BOTH are known: fraction that match. Unknown
    dimensions neither help nor hurt — they are excluded, not penalized.
    0.0 when nothing is comparable.
    """
    compared = 0
    matches = 0
    for dim in DIMENSIONS:
        va, vb = getattr(a, dim), getattr(b, dim)
        if va != UNKNOWN and vb != UNKNOWN:
            compared += 1
            matches += int(va == vb)
    return (matches / compared) if compared else 0.0


# ---------------------------------------------------------------------------
# Conservative derivation from conversation text (metadata, not a form field)
# ---------------------------------------------------------------------------

#: Explicit-cue keywords per dimension -> level. Only unambiguous,
#: user-stated cues belong here. Checked most-specific level first.
_DERIVE_CUES: dict[str, dict[str, tuple[str, ...]]] = {
    "stakes": {
        "life-altering": ("life-altering", "life altering", "life-changing", "life changing", "bet the company", "bet-the-company"),
        "significant": ("high stakes", "high-stakes", "major decision", "big decision"),
        "low": ("low stakes", "low-stakes", "trivial", "no big deal", "doesn't matter much"),
    },
    "reversibility": {
        "irreversible": ("irreversible", "can't undo", "cannot undo", "one-way door", "point of no return"),
        "costly": ("hard to undo", "costly to reverse", "expensive to undo"),
        "easily": ("easily reversible", "easy to undo", "two-way door", "can always reverse", "can always undo"),
    },
    "time_pressure": {
        "urgent": ("urgent", "asap", "as soon as possible", "right now", "immediately", "deadline is"),
        "open-ended": ("no rush", "no deadline", "open-ended", "open ended", "whenever"),
    },
    "information": {
        "thin": ("flying blind", "no data", "don't know enough", "thin information", "not enough info"),
        "rich": ("all the data", "well understood", "rich information", "have all the facts"),
        "adequate": ("enough information", "adequate information", "sufficient info"),
    },
    "social_field": {
        "publicly_accountable": ("publicly", "everyone will see", "all hands", "accountable to"),
        "interpersonal": ("my team", "the team", "with my partner", "my co-founder"),
        "solo": ("just me", "my call alone", "deciding solo", "on my own"),
    },
    "resource_climate": {
        "scarcity": ("no budget", "scarce", "scarcity", "running out of runway", "can't afford"),
        "abundance": ("abundant", "plenty of", "well funded", "well-funded"),
        "sufficiency": ("enough runway", "sufficient resources", "covered for"),
    },
}


def derive_decision_context(text: str | None) -> DecisionContext:
    """Best-effort envelope from free text. Unknown unless explicitly cued.

    This is derived metadata — coarse, conservative, and always overridable
    by an explicit context. Anything ambiguous stays unknown.
    """
    found: dict[str, str] = {}
    blob = f" {(text or '').lower()} "
    for dim, levels in _DERIVE_CUES.items():
        for level, cues in levels.items():
            if any(cue in blob for cue in cues):
                found[dim] = level
                break
    return DecisionContext(**found)


__all__ = [
    "UNKNOWN",
    "DIMENSIONS",
    "LEVELS",
    "CONTEXT_REF_KEY",
    "DecisionContext",
    "normalize_level",
    "parse_decision_context",
    "get_signal_context",
    "set_signal_context",
    "context_similarity",
    "derive_decision_context",
]
