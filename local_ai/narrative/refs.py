"""Typed source references and the three evidence tiers (Steward S0).

Every fact the Narrative Steward keeps hangs off a *reference* to a
record owned by another store: a fellowship event, a review claim, a
journal entry, a commitment, a pipeline artifact. References are typed
by *kind*, and every kind belongs to exactly one of the three evidence
tiers (audit Part II §7):

  E — Evidence        the user's verbatim words; system records of
                      what happened. Never generated. The ONLY tier
                      anything may cite as evidence.
  I — Interpretation  attributable readings of evidence (a thread
                      reading, an observation, an inference). Citable
                      as context, never as evidence: an interpretation
                      cannot ground another interpretation.
  D — Dramatization   stories, scenes, packs, quote cards — tellings
                      shaped for effect. Inadmissible as evidence,
                      mechanically, not by convention.

The store (store.py) resolves every evidence citation through
:func:`require_evidence_tier`. A caller holding a dramatization ref
and asking to attach it as evidence gets a refusal from this module —
there is no ref kind a story artifact can wear that the evidence path
accepts, so the tier boundary cannot be crossed by prompt wording,
surface code, or a future caller being careless.

Kinds are deliberately a closed vocabulary. An unknown kind is a
programming error and raises, mirroring the fellowship event
vocabulary's discipline (events.py).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class RefTier(str, Enum):
    """The three evidence tiers (audit Part II §7)."""

    EVIDENCE = "evidence"
    INTERPRETATION = "interpretation"
    DRAMATIZATION = "dramatization"


class InadmissibleEvidenceError(ValueError):
    """A non-Evidence-tier ref was offered where evidence is required.

    Subclasses ValueError so store-level validation handling catches
    it with the store's other loud failures, while tests and callers
    can still name the tier violation specifically.
    """


#: Ref kinds whose records are Tier E — evidence. These are exactly
#: the ref_kind values ``thread_evidence`` may carry (audit Part II
#: §2): records owned by stores with verbatim-evidence discipline.
EVIDENCE_REF_KINDS: tuple[str, ...] = (
    "event",          # fellowship event (local_ai/fellowship/events.py)
    "claim",          # review claim (local_ai/agent_intake/review_claims.py)
    "observation",    # fellowship observation — its evidence is a
                      # verbatim quote or entity ref by construction
    "journal_entry",  # pipeline journal entry (user's own text)
    "ve_entity",      # vision-execution entity (initiative/project/task)
    "commitment",     # follow-through commitment (carries source_quote)
)

#: Ref kinds whose records are Tier I — interpretations. A reading may
#: be *referenced* (a change can supersede one, a fitting can answer
#: one) but can never serve as the evidence for another reading.
INTERPRETATION_REF_KINDS: tuple[str, ...] = (
    "reading",        # a thread reading (this package)
)

#: Ref kinds whose records are Tier D — dramatizations.
DRAMATIZATION_REF_KINDS: tuple[str, ...] = (
    "story_artifact",  # pipeline provenance artifact: story / pack /
                       # quote card (local_ai/pipeline/, provenance)
    "scene_render",    # journal scene renderer output (retired in
                       # Phase 4 — kind retained so any old rows stay
                       # Tier D, inadmissible as evidence)
                       # (local_ai/journal/story.py)
)

REF_KIND_TIERS: dict[str, RefTier] = {
    **{kind: RefTier.EVIDENCE for kind in EVIDENCE_REF_KINDS},
    **{kind: RefTier.INTERPRETATION for kind in INTERPRETATION_REF_KINDS},
    **{kind: RefTier.DRAMATIZATION for kind in DRAMATIZATION_REF_KINDS},
}

#: How a piece of evidence anchors, in the fellowship observations'
#: vocabulary (observations.py): the verbatim quote itself, or the
#: entity reference "<entity_type>:<entity_id>".
EVIDENCE_KINDS: tuple[str, ...] = ("quote", "entity_ref")


def tier_of(ref_kind: str) -> RefTier:
    """The tier a ref kind belongs to. Raises ValueError if unknown."""
    try:
        return REF_KIND_TIERS[ref_kind]
    except KeyError:
        raise ValueError(f"unknown narrative ref kind: {ref_kind!r}") from None


@dataclass(frozen=True)
class SourceRef:
    """A typed pointer to a record owned by another store.

    ``evidence_kind`` says how the referenced record anchors as
    evidence: ``"quote"`` when the record carries the user's verbatim
    words, ``"entity_ref"`` when it is referenced as an entity. It is
    validated but never reinterpreted by this package — the owning
    store's discipline is what makes a quote verbatim.
    """

    kind: str
    ref_id: str
    evidence_kind: str = "entity_ref"

    def __post_init__(self) -> None:
        tier_of(self.kind)  # raises for unknown kinds
        if self.evidence_kind not in EVIDENCE_KINDS:
            raise ValueError(f"unknown evidence_kind: {self.evidence_kind!r}")
        if not str(self.ref_id):
            raise ValueError("a source ref needs a non-empty ref_id")

    @property
    def tier(self) -> RefTier:
        return REF_KIND_TIERS[self.kind]

    def to_dict(self) -> dict[str, str]:
        return {
            "kind": self.kind,
            "ref_id": self.ref_id,
            "evidence_kind": self.evidence_kind,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "SourceRef":
        return cls(
            kind=str(data["kind"]),
            ref_id=str(data["ref_id"]),
            evidence_kind=str(data.get("evidence_kind") or "entity_ref"),
        )


def require_evidence_tier(ref: SourceRef) -> SourceRef:
    """Return ``ref`` if it may serve as evidence; refuse otherwise.

    This is the tier boundary made mechanical: Tier I and Tier D refs
    raise :class:`InadmissibleEvidenceError` here, at the single choke
    point every evidence citation in the store passes through.
    """
    if ref.tier is not RefTier.EVIDENCE:
        raise InadmissibleEvidenceError(
            f"ref kind {ref.kind!r} is tier {ref.tier.value!r}; only "
            f"evidence-tier refs {list(EVIDENCE_REF_KINDS)} may be "
            "cited as evidence"
        )
    return ref
