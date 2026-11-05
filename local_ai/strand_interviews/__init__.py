"""Weaver strand interviews (rev2, as accepted by founder verdict 2026-11-04).

One ordinary Weaver (conductor) Talk thread per strand, opened from the
Tree's strand roots. Conversation-first: no upload prerequisite, one
question at a time, reciprocal contribution, continuity without pressure.

Design keys (rev2 / builder contract): the strand interview's strand_key
is the founder-facing name — heart, hands, logic, voice, ear, compass,
eye. The canonical taxonomy keys (people, body, number, word, sound,
self, image) live in ``local_ai/strands.py`` and are NOT the strand
interview's keys; reconciling the two key systems is Slice 3 noting
work, not strand work. The mapping between them lives here, in one
place, so no other module guesses it.

Governing principle (revised verdict, verbatim): "Weaver is endlessly
curious, not endlessly extractive. She asks because she wants to
understand, contributes because she has something to offer, and
remembers because the relationship is meant to deepen."
"""

from __future__ import annotations

from .boundaries import normalize_topic, recognize_explicit_boundary
from .evidence import ClaimKind, tier3_eligible
from .guidance import strand_guidance_block
from .keys import (
    DESIGN_STRAND_KEYS,
    DESIGN_TO_TAXONOMY,
    STRAND_DEFINITIONS,
    TAXONOMY_TO_DESIGN,
    is_valid_strand_key,
    validate_strand_key,
)
from .orientation import orientation_for

__all__ = [
    "DESIGN_STRAND_KEYS",
    "DESIGN_TO_TAXONOMY",
    "STRAND_DEFINITIONS",
    "TAXONOMY_TO_DESIGN",
    "ClaimKind",
    "is_valid_strand_key",
    "normalize_topic",
    "orientation_for",
    "recognize_explicit_boundary",
    "strand_guidance_block",
    "tier3_eligible",
    "validate_strand_key",
]
