"""Keystone unlock initiative — seed data ("Meet your council").

Pure data: the initiative, its 7 per-seat projects, and the 4 keystone tasks
per seat, exactly as Joshua approved in the design (no quotes, no mottos —
name and face first, like meeting someone in real life). Content revisions are
data edits here, never rebuilds.

Order is fixed and starts with the Conductor (entry seat): in optimal form it
is the amalgamation of the others' strengths and weaknesses and the
negotiation between them, so it introduces the council. The other six follow
in the user's choice of order. Keystone 4 gates RENTABILITY, not training —
training runs continuously throughout normal usage, per user approval.

Seeding logic lives in local_ai/vision_execution/keystone_seeding.py.
The keystone *conversations* themselves are a separate build (intro-conversation
unlock) — this is the scaffolding: initiative, checklist, dependencies, seed.
"""

from __future__ import annotations

INITIATIVE_KEY = "meet-your-council"
INITIATIVE_TITLE = "Meet your council"
INITIATIVE_STATUS = "Active"
INITIATIVE_BRIEF = (
    "Meet the seven seats of your council. Start with the Conductor — the one "
    "who hears how the others fit together — and it will introduce the rest. "
    "Like meeting someone in real life: name and face first, then what each "
    "one is good at, what each one is not good at, and finally the part of "
    "you that echoes each of them. No quotes, no mottos — just getting to "
    "know them."
)

PROJECT_STATUS = "Ready"

#: Canonical seat ids (local_ai/council/archetypes.py stock_archetype_ids).
#: Conductor first — it is the ENTRY seat (see module docstring).
SEATS: tuple[dict[str, str], ...] = (
    {
        "seat_ref": "conductor",
        "character": "Weaver",
        "demeanor": "Hears how parts fit; cannot leave a loose thread.",
        "echo": "the part that arranges; also the anxious planner when blended",
        "entry": "true",
    },
    {
        "seat_ref": "mentor",
        "character": "Gardener",
        "demeanor": "Patient, unhurried; sees seasons, not days.",
        "echo": "the part of you that tends growth; patience with yourself",
    },
    {
        "seat_ref": "champion",
        "character": "Firebrand",
        "demeanor": "Urgent, fierce; picks fights worth having.",
        "echo": "the part that fights; anger as courage",
    },
    {
        "seat_ref": "guardian",
        "character": "Bear",
        "demeanor": "Steady, sheltering; slow to move, impossible to move once moved.",
        "echo": "the protector part",
    },
    {
        "seat_ref": "ambassador",
        "character": "Bridge",
        "demeanor": "Curious about the other side; holds two truths lightly.",
        "echo": "the part that translates between your warring inner voices",
    },
    {
        "seat_ref": "skeptic",
        "character": "Neighbor",
        "demeanor": "Flint-eyed, unimpressed by performance; asks the question no one wants.",
        "echo": "the inner questioner; the critic when blended",
    },
    {
        "seat_ref": "maverick",
        "character": "Fox",
        "demeanor": "Restless, allergic to locked doors; lightning-quick.",
        "echo": "the rebel; the rule-breaker",
    },
)


def _keystone(title: str, description: str, completion_criteria: str) -> dict[str, str]:
    return {
        "title": title,
        "description": description,
        "completion_criteria": completion_criteria,
    }


def keystones_for(seat: dict[str, str]) -> list[dict[str, str]]:
    """The 4 keystone tasks for one seat, in dependency order 1→2→3→4."""
    character = seat["character"]
    demeanor = seat["demeanor"]
    return [
        _keystone(
            title="First meeting",
            description=(
                f"{character} — {demeanor} First meetings are mutual: "
                f"{character} introduces themselves and asks an opening "
                "question. No flaw, no systems talk yet."
            ),
            completion_criteria="Unlocked: face, name, one-line demeanor.",
        ),
        _keystone(
            title="Strengths",
            description=(
                f"What {character} is good at — experienced, not described. A "
                f"guided exchange where {character} demonstrates their faculty "
                "on something real from your life."
            ),
            completion_criteria="Unlocked: role, element, core ideal.",
        ),
        _keystone(
            title="Weaknesses",
            description=(
                f"What {character} is NOT good at. The flaw ceremony: "
                f"{character} shows their failure mode honestly, in their own "
                "voice — a confession, not a warning label."
            ),
            completion_criteria="Unlocked: fatal flaw.",
        ),
        _keystone(
            title="The echo",
            description=(
                f"Not a solo exercise — a conversation {character} initiates "
                "when the system senses readiness. Training has been running "
                "all along, with your approval, so there is something real to "
                "talk about: what the seat has discovered about you over "
                "usage. Personal recognition, parallels and divergences "
                "between the archetype and your echo of it. Expect questions "
                "like: what does the image that parallels us look like? What "
                "name feels right for it?"
            ),
            completion_criteria=(
                "Unlocked: full character sheet; the seat's 'You' profile "
                "becomes visible and interactable (the Zenaf / You switch). "
                f"{character} becomes RENTABLE — viable to rent to someone "
                "else. Training is not gated by this keystone: it runs "
                "continuously throughout normal usage, per your approval."
            ),
        ),
    ]


def project_title(seat: dict[str, str]) -> str:
    return f"Meet the {seat['character']}"


def project_brief(seat: dict[str, str]) -> str:
    return (
        f"{seat['demeanor']} Four meetings, in order: first meeting, "
        "strengths, weaknesses, and the echo in you."
    )
