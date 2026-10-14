"""PersonalityProfile (Phase 1): the user-defined side of each strand.

The aspirational defaults (BUILT_IN_PERSONA_DEFINITIONS) live elsewhere and
are never touched here. This package holds the user's version — structured,
versioned, human-readable — plus the propose/review/publish pipeline that is
the ONLY path by which a profile version comes into existence.
"""
from .blend import (
    MIN_EVIDENCE,
    CONTEXT_SIMILARITY_THRESHOLD,
    BlendContext,
    apply_personality_blend,
    default_weight_for_strand,
    resolve_blend_context,
    resolve_weights,
    strand_evidence_depth,
)
from .depth import (
    StrandDepth,
    band_for_score,
    compute_strand_depth,
    compute_training_depth,
    map_signal_to_strand,
)
from .context import (
    CONTEXT_REF_KEY,
    DIMENSIONS,
    LEVELS,
    DecisionContext,
    context_similarity,
    derive_decision_context,
    get_signal_context,
    parse_decision_context,
    set_signal_context,
)
from .schema import (
    ContextualFingerprint,
    DecisionFingerprint,
    DomainEntry,
    ExampleFragment,
    PersonalityProfile,
    ProfileCandidate,
    RedLine,
    StrandProfile,
    VoiceProfile,
)
from .seed import seed_contextual_fingerprints, seed_from_signals
from .store import PersonalityStore

__all__ = [
    "MIN_EVIDENCE",
    "CONTEXT_SIMILARITY_THRESHOLD",
    "DIMENSIONS",
    "LEVELS",
    "CONTEXT_REF_KEY",
    "BlendContext",
    "ContextualFingerprint",
    "StrandDepth",
    "DecisionContext",
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
    "band_for_score",
    "compute_strand_depth",
    "compute_training_depth",
    "context_similarity",
    "map_signal_to_strand",
    "default_weight_for_strand",
    "derive_decision_context",
    "get_signal_context",
    "parse_decision_context",
    "resolve_blend_context",
    "resolve_weights",
    "seed_contextual_fingerprints",
    "seed_from_signals",
    "set_signal_context",
    "strand_evidence_depth",
]
