"""Pydantic schemas for the PersonalityProfile (Phase 1: the user-defined side).

Architecture note (non-negotiable): this module models ONLY the
user-defined version of each strand. The aspirational defaults
(`BUILT_IN_PERSONA_DEFINITIONS` in `local_ai/zenaf_tools.py`) are a separate
object and must NEVER be imported, modified, or contaminated here. A later
phase adds the runtime weighting layer that blends the two per seat.

Person vs Profile vs Seat (per docs/PERSONALITY_PROFILE.md):
  - Person: the human; out of scope except as the source of signals.
  - Profile: this module. A versioned, structured, human-readable cognitive
    model. Immutable once published; changes are new versions.
  - Seat: a later-phase runtime binding of profile + version + policy.

Privacy contract: profiles hold distilled, structured traits and
user-curated fragments — never raw logs, transcripts, or PII. Candidates
are proposed diffs; nothing persists as a profile version without an
explicit user publish (see store.publish).
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from local_ai.strands import strand_keys

CandidateStatus = Literal["proposed", "accepted", "rejected", "published"]
CandidateOpKind = Literal["add", "set"]

_STRAND_KEYS = set(strand_keys())


class VoiceProfile(BaseModel):
    """How this person sounds. Global (not per-strand)."""

    description: str = ""  # free text: tone, register, vocabulary
    tags: list[str] = Field(default_factory=list)  # e.g. "concise", "direct"


class ReasoningProfile(BaseModel):
    """How this person tends to reason within one strand."""

    descriptors: list[str] = Field(default_factory=list)
    # e.g. "prefer trade-off framing before recommending"
    notes: str = ""


class DecisionFingerprint(BaseModel):
    """Distilled decision-making pattern for one strand.

    All fields optional, human-readable or ordinal. Derived from signals
    (VE decisions, sorter promotions, content choices); proposed, never
    inferred silently.
    """

    risk_bias: str = ""  # e.g. "reversible first", "default no"
    exploration_vs_exploitation: str = ""
    time_horizon: str = ""  # e.g. "quarter", "decade"
    evidence_preference: str = ""  # e.g. "one strong signal", "aggregate first"
    decision_style: str = ""  # e.g. "decide fast, iterate"
    conflict_style: str = ""  # e.g. "explicit trade-off", "defer to owner"
    failure_tolerance: str = ""  # e.g. "fail fast", "minimize downside"


class DomainEntry(BaseModel):
    """One domain the user has a defined stance in."""

    domain: str  # label, e.g. "product"
    stance: str = ""  # e.g. "lead", "defer", "strong views"


class RedLine(BaseModel):
    """A non-negotiable constraint / never-do rule."""

    rule: str
    rationale: str = ""


class ExampleFragment(BaseModel):
    """Short sanitized example of preferred phrasing/reasoning/decision."""

    context: str = ""
    fragment: str = ""
    tag: str = ""


class StrandProfile(BaseModel):
    """The user's version of ONE strand: how THEY use this intelligence style.

    This is the delta from the aspirational ideal — the trainable signal.
    """

    reasoning: ReasoningProfile = Field(default_factory=ReasoningProfile)
    fingerprint: DecisionFingerprint = Field(default_factory=DecisionFingerprint)
    heuristics: list[str] = Field(default_factory=list)
    domain_map: list[DomainEntry] = Field(default_factory=list)
    red_lines: list[RedLine] = Field(default_factory=list)
    examples: list[ExampleFragment] = Field(default_factory=list)


def _empty_strands() -> dict[str, StrandProfile]:
    return {k: StrandProfile() for k in strand_keys()}


class PersonalityProfile(BaseModel):
    """One IMMUTABLE published version of a user's personality profile."""

    profile_id: str
    user_id: str
    version: int = Field(ge=1)
    supersedes: int | None = None  # previous version number, if any
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    source_summary: str = ""  # high-level labels, e.g. "3 candidates from intake corrections"
    approved_by: str = "user"

    voice: VoiceProfile = Field(default_factory=VoiceProfile)
    strands: dict[str, StrandProfile] = Field(default_factory=_empty_strands)

    @field_validator("strands")
    @classmethod
    def _seven_strands(cls, v: dict[str, StrandProfile]) -> dict[str, StrandProfile]:
        keys = set(v.keys())
        if keys != _STRAND_KEYS:
            raise ValueError(f"strands must carry exactly the 7 canonical keys; got {sorted(keys)}")
        return v


class CandidateOp(BaseModel):
    """One structured field operation inside a candidate diff."""

    # NOTE: `field` is declared before `op` so the op/field consistency
    # validator (on `op`) can see the already-validated field value.
    field: str  # dotted path, e.g. "heuristics", "fingerprint.risk_bias", "voice.tags"
    op: CandidateOpKind  # "add" appends to a list field; "set" replaces a scalar
    value: Any

    @field_validator("field")
    @classmethod
    def _known_field(cls, v: str) -> str:
        allowed = {
            # profile-global (strand_key=None)
            "voice.description",
            "voice.tags",
            # per-strand
            "reasoning.descriptors",
            "reasoning.notes",
            "heuristics",
            "domain_map",
            "red_lines",
            "examples",
            "fingerprint.risk_bias",
            "fingerprint.exploration_vs_exploitation",
            "fingerprint.time_horizon",
            "fingerprint.evidence_preference",
            "fingerprint.decision_style",
            "fingerprint.conflict_style",
            "fingerprint.failure_tolerance",
        }
        if v not in allowed:
            raise ValueError(f"unknown candidate field {v!r}")
        return v

    @field_validator("op")
    @classmethod
    def _op_matches_field(cls, v: str, info) -> str:
        field = (info.data or {}).get("field", "")
        list_fields = {
            "voice.tags",
            "reasoning.descriptors",
            "heuristics",
            "domain_map",
            "red_lines",
            "examples",
        }
        if v == "add" and field not in list_fields:
            raise ValueError(f"op 'add' needs a list field, got {field!r}")
        if v == "set" and field in list_fields:
            raise ValueError(f"op 'set' needs a scalar field, got {field!r}")
        return v


class ProfileCandidate(BaseModel):
    """A PROPOSED profile update. Inert until published — never auto-applied."""

    candidate_id: str
    user_id: str
    strand_key: str | None = None  # None = profile-global (voice)
    ops: list[CandidateOp] = Field(min_length=1)
    source: str = ""  # e.g. "seed:signal:<signal_id>", "manual", "intake-correction"
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    rationale: str = ""
    status: CandidateStatus = "proposed"
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @field_validator("strand_key")
    @classmethod
    def _known_strand(cls, v: str | None) -> str | None:
        if v is not None and v not in _STRAND_KEYS:
            raise ValueError(f"unknown strand key {v!r}; want one of {sorted(_STRAND_KEYS)}")
        return v

    @field_validator("ops")
    @classmethod
    def _global_ops_need_global_strand(cls, v: list[CandidateOp], info) -> list[CandidateOp]:
        strand_key = (info.data or {}).get("strand_key")
        for op in v:
            is_global = op.field.startswith("voice.")
            if is_global and strand_key is not None:
                raise ValueError("voice.* fields need strand_key=None")
            if not is_global and strand_key is None:
                raise ValueError(f"strand field {op.field!r} needs a strand_key")
        return v
