"""Canonical 7-strand taxonomy for Zenaf — the single source of truth.

A *strand* is a fixed faculty of human learning and expression (synthesized
from Gardner's multiple intelligences). Strands never proliferate: free-form
skills and specialization zones branch *under* them, and new skill trees
declare which strand they belong to.

The *agent name* is the warm handshake identity for the trainable agent that
embodies the strand — the name a person would proudly claim as "my main
thing". Strand keys are stable taxonomy; agent names are the human register.

"World" (the environment) is deliberately NOT a strand: you don't train the
environment, you train yourself to perceive and interact within it.
Environment is context, parsed at increasing resolution in relation to
user choice — never a container.

Everything else (council personas, the Living Tree frontend, strand colors)
imports from here. Do not duplicate this table.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Strand:
    key: str          # stable taxonomy key: word | number | image | sound | body | people | self
    faculty: str      # faculty label
    agent_name: str   # warm handshake name for the trainable agent
    color: str        # canonical hex
    gardner: str      # Gardner's multiple-intelligences mapping (reference)
    tagline: str      # one-line description


STRANDS: tuple[Strand, ...] = (
    Strand(
        key="word",
        faculty="Word",
        agent_name="Voice",
        color="#c98f6a",
        gardner="linguistic",
        tagline="Language, rhetoric, writing, voice — how things get said.",
    ),
    Strand(
        key="number",
        faculty="Number",
        agent_name="Logic",
        color="#7aa3b8",
        gardner="logical-mathematical",
        tagline="Analysis, systems, evidence — how patterns get read.",
    ),
    Strand(
        key="image",
        faculty="Image",
        agent_name="Eye",
        color="#c9a86a",
        gardner="spatial",
        tagline="Visual taste, design, spatial thinking — how things get seen.",
    ),
    Strand(
        key="sound",
        faculty="Sound",
        agent_name="Ear",
        color="#b983a8",
        gardner="musical",
        tagline="Music, rhythm, listening — how things get heard.",
    ),
    Strand(
        key="body",
        faculty="Body",
        agent_name="Hands",
        color="#9db87a",
        gardner="bodily-kinesthetic",
        tagline="Craft, making, doing — how things get built.",
    ),
    Strand(
        key="people",
        faculty="People",
        agent_name="Heart",
        color="#a88fc9",
        gardner="interpersonal",
        tagline="Leadership, teaching, care — how people get held.",
    ),
    Strand(
        key="self",
        faculty="Self",
        agent_name="Compass",
        color="#7ba889",
        gardner="intrapersonal",
        tagline="Judgment, values, direction — how choices get made.",
    ),
)

# Display order for the braid: image, self, sound, word, number, body, people
# (keeps the original three demo strands first).
BRAID_ORDER: tuple[str, ...] = ("image", "self", "sound", "word", "number", "body", "people")

_BY_KEY: dict[str, Strand] = {s.key: s for s in STRANDS}
_BY_AGENT: dict[str, Strand] = {s.agent_name.lower(): s for s in STRANDS}


def strand(key: str) -> Strand:
    """Return the Strand for a faculty key (e.g. "word")."""
    return _BY_KEY[key.strip().lower()]


def strand_for_agent(agent_name: str) -> Strand:
    """Return the Strand for a warm agent name (e.g. "Voice")."""
    return _BY_AGENT[agent_name.strip().lower()]


def strand_color(key: str) -> str:
    """Canonical hex color for a faculty key."""
    return strand(key).color


def agent_names() -> tuple[str, ...]:
    """Warm handshake names, one per strand, in canonical order."""
    return tuple(s.agent_name for s in STRANDS)


def strand_keys() -> tuple[str, ...]:
    """Faculty keys in canonical order."""
    return tuple(s.key for s in STRANDS)
