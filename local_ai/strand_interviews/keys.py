"""Strand keys for Weaver strand interviews (rev2).

The strand interview's strand_key is the founder-facing name: heart,
hands, logic, voice, ear, compass, eye. These are the keys the R1
permission rows use, and the keys the strand mapping stores.

The canonical taxonomy keys (people, body, number, word, sound, self,
image) live in ``local_ai/strands.py`` and are NOT the strand
interview's keys. The mapping between the two systems lives here, in
one place, so no other module guesses it. Reconciling the two key
systems is Slice 3 noting work, not strand work.
"""

from __future__ import annotations

DESIGN_STRAND_KEYS: tuple[str, ...] = (
    "heart",
    "hands",
    "logic",
    "voice",
    "ear",
    "compass",
    "eye",
)

#: Design key -> canonical taxonomy key (``local_ai/strands.py``).
DESIGN_TO_TAXONOMY: dict[str, str] = {
    "heart": "people",
    "hands": "body",
    "logic": "number",
    "voice": "word",
    "ear": "sound",
    "compass": "self",
    "eye": "image",
}

#: Canonical taxonomy key -> design key.
TAXONOMY_TO_DESIGN: dict[str, str] = {v: k for k, v in DESIGN_TO_TAXONOMY.items()}

#: Founder's definition for each strand (his words, rev2 appendix),
#: plus the canonical tagline and the warm agent name. Ear's definition
#: is the verdict-resolved OQ1: "music, rhythm, listening, and what
#: resonates."
STRAND_DEFINITIONS: dict[str, dict[str, str]] = {
    "heart": {
        "agent_name": "Heart",
        "definition": "things you care about",
        "tagline": "Leadership, teaching, care — how people get held.",
        "opener": (
            "What is something you have cared about long enough "
            "that it changed what you did?"
        ),
    },
    "hands": {
        "agent_name": "Hands",
        "definition": "things you've built or appreciate how they're built",
        "tagline": "Craft, making, doing — how things get built.",
        "opener": (
            "What is something you have made, or watched being made, "
            "that stayed with you — and what about the making?"
        ),
    },
    "logic": {
        "agent_name": "Logic",
        "definition": "how you think",
        "tagline": "Analysis, systems, evidence — how patterns get read.",
        "opener": (
            "What is a distinction you drew once that changed "
            "how you saw something?"
        ),
    },
    "voice": {
        "agent_name": "Voice",
        "definition": "how you express yourself",
        "tagline": "Language, rhetoric, writing, voice — how things get said.",
        "opener": (
            "Is there a way of saying something that feels "
            "unmistakably yours? What makes it yours?"
        ),
    },
    "ear": {
        "agent_name": "Ear",
        "definition": "music, rhythm, listening, and what resonates",
        "tagline": "Music, rhythm, listening — how things get heard.",
        "opener": (
            "What music do you keep coming back to — and what are "
            "you listening for in it?"
        ),
    },
    "compass": {
        "agent_name": "Compass",
        "definition": "aspirational, theological, philosophical",
        "tagline": "Judgment, values, direction — how choices get made.",
        "opener": (
            "What is a direction, claim, or question you have "
            "oriented yourself by?"
        ),
    },
    "eye": {
        "agent_name": "Eye",
        "definition": "things you find aesthetically beautiful",
        "tagline": "Visual taste, design, spatial thinking — how things get seen.",
        "opener": (
            "What is an image, a place, or a made thing that stopped "
            "you — and what held your attention in it?"
        ),
    },
}


def is_valid_strand_key(key: str | None) -> bool:
    """True only for one of the seven design strand keys."""
    return isinstance(key, str) and key.strip().lower() in DESIGN_STRAND_KEYS


def validate_strand_key(key: str | None) -> str:
    """Normalize a design strand key, or raise ValueError (fail closed).

    Never trust a client-supplied strand_key: callers must pass the
    key through here before using it for any read or write.
    """
    if not isinstance(key, str):
        raise ValueError(f"Unknown strand: {key!r}")
    normalized = key.strip().lower()
    if normalized not in DESIGN_STRAND_KEYS:
        raise ValueError(f"Unknown strand: {key!r}")
    return normalized
