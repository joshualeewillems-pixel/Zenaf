"""PersonalityProfile (Phase 1): the user-defined side of each strand.

The aspirational defaults (BUILT_IN_PERSONA_DEFINITIONS) live elsewhere and
are never touched here. This package holds the user's version — structured,
versioned, human-readable — plus the propose/review/publish pipeline that is
the ONLY path by which a profile version comes into existence.
"""
from .blend import (
    MIN_EVIDENCE,
    BlendContext,
    apply_personality_blend,
    default_weight_for_strand,
    resolve_blend_context,
    resolve_weights,
    strand_evidence_depth,
)
from .schema import (
    DecisionFingerprint,
    DomainEntry,
    ExampleFragment,
    PersonalityProfile,
    ProfileCandidate,
    RedLine,
    StrandProfile,
    VoiceProfile,
)
from .seed import seed_from_signals
from .store import PersonalityStore

__all__ = [
    "MIN_EVIDENCE",
    "BlendContext",
    "DecisionFingerprint",
    "DomainEntry",
    "ExampleFragment",
    "PersonalityProfile",
    "PersonalityStore",
    "ProfileCandidate",
    "RedLine",
    "StrandProfile",
    "VoiceProfile",
    "apply_personality_blend",
    "default_weight_for_strand",
    "resolve_blend_context",
    "resolve_weights",
    "seed_from_signals",
    "strand_evidence_depth",
]
