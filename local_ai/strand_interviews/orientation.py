"""Opening-turn lifecycle for strand threads (rev2 C3).

A fresh strand thread opens with a lightweight, NONBINDING orientation
plus a conversational invitation, rendered from pattern copy. NO model
call is triggered by opening the panel: this module is pure copy, and
the orientation is display data, never a persisted Weaver turn.

The first GENERATED Weaver question arrives via the standard Talk turn
endpoint, once the user sends a message. An auto-generated greeting on
open needs separate authorization (none granted); nothing here builds
one. A generated Weaver turn present on open, before any user turn,
FAILS T1b — which is why the orientation is a header, not a message.
"""

from __future__ import annotations

from typing import Any

from .keys import STRAND_DEFINITIONS, validate_strand_key


def orientation_for(strand_key: str, *, is_fresh: bool) -> dict[str, Any]:
    """Pattern-copy orientation for a strand thread opening.

    ``is_fresh`` means the thread has no messages yet. A fresh thread
    gets the strand definition and a single-sentence invitation. A
    returning thread gets a resume line only — no opener, no greeting,
    no recap demanded.
    """
    key = validate_strand_key(strand_key)
    definition = STRAND_DEFINITIONS[key]
    base: dict[str, Any] = {
        "strand_key": key,
        "strand_name": definition["agent_name"],
        "definition": definition["definition"],
        "tagline": definition["tagline"],
        "is_fresh": bool(is_fresh),
    }
    if is_fresh:
        # Single lead sentence only (UI cleanup 2026-11-12): the
        # explanatory sentences and the §3.3 opener question were
        # removed from the panel. The opener patterns remain in keys.py
        # as founder-authored appendix copy, unrendered.
        base["invitation"] = f"Talk with Weaver about {definition['definition']}."
        base["opening_question"] = None
        base["resume"] = None
    else:
        base["invitation"] = (
            "Pick up where you left off — no recap, no restart. "
            "Weaver remembers the thread; you decide where it goes next."
        )
        base["opening_question"] = None
        base["resume"] = True
    return base
