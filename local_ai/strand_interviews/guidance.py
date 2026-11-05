"""Strand guidance block for conductor turns in strand threads (rev2 §6).

The strand_key turn-context extension carries strand identity and the
§3 curiosity guidance for conductor turns in strand threads. This
module builds that block as pure text: no model call, no store access.
The service supplies the active topic boundaries and the linked-source
excerpts; this module renders them, bounded.

The guidance is runtime guidance for the conductor's turns, not a
script: the §3.3 opener patterns shape Weaver's own questions, and the
§3 six moves are a repertoire, not a sequence. The block is explicit,
per-turn, and never silently persistent beyond the strand thread.

Caps follow the Capability C S5 pattern: 2000 chars per line, and the
whole block is bounded so a hostile or oversized stored record can
never expand the prompt.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from .keys import STRAND_DEFINITIONS, validate_strand_key

_LINE_CAP = 2000
_MAX_BOUNDARIES = 10
_MAX_SOURCES = 3
_MAX_SOURCE_EXCERPT_CHARS = 500


def _cap(text: str, limit: int = _LINE_CAP) -> str:
    text = (text or "").strip()
    return text[:limit] if len(text) > limit else text


def strand_guidance_block(
    strand_key: str,
    *,
    boundaries: Sequence[Mapping[str, Any]] | None = None,
    sources: Sequence[Mapping[str, Any]] | None = None,
) -> str:
    """Build the strand guidance block for one conductor turn.

    ``boundaries`` are active topic-boundary rows (each with a ``topic``
    display value); ``sources`` are linked-source rows (each with
    ``kind``, ``label``, and an optional redacted ``excerpt``).
    """
    key = validate_strand_key(strand_key)
    definition = STRAND_DEFINITIONS[key]
    lines: list[str] = [
        "Strand conversation — Weaver (Conductor) speaking with the user "
        f"about the {definition['agent_name']} strand "
        f"({definition['definition']}).",
        "Curiosity pattern: ask ONE question at a time, grounded in this "
        "thread, the user's answers, your own knowledge, or a linked "
        "source when one is present. Listen to the answer's actual "
        "wording. Offer tentative readings as questions, never as facts "
        "about the user. Connect answers to earlier answers when the "
        "user invites it. Offer comparisons and suggestions as your own "
        "contributions — never record a suggestion as a user preference. "
        "Test understanding before moving on. Never invent a premise "
        "about the user (a taste, history, or preference never "
        "expressed) and ask about it as if it were shared ground.",
        "Continuity without pressure: no guilt, no repeated demand, no "
        "obligation markers. A declined question stays declined unless "
        "the user reopens it. An unanswered question is not a debt. "
        "\"I've had enough of your poking around\" is always available "
        "and consequence-free.",
        "Durable insights (tier 3) are occasional, never the thread's "
        "goal. A specific expressed intention may be grounded in one "
        "clear declaration; a recurring preference, stable trait, or "
        "enduring worldview needs recurrence across the thread plus "
        "confirmation in the user's own words. A borderline claim is "
        "proposed only with its evidence strength stated. Confirmation "
        "of a tentative reading is NOT durable approval.",
    ]
    active = [b for b in (boundaries or [])][: _MAX_BOUNDARIES]
    if active:
        topics = "; ".join(
            _cap(str(b.get("topic") or "").strip(), 120)
            for b in active
            if str(b.get("topic") or "").strip()
        )
        if topics:
            lines.append(
                "Explicit topic boundaries the user set in this strand — "
                "do NOT raise these topics unprompted, in any phrasing: "
                f"{topics}. If the user raises one of these topics "
                "themselves, you may follow their lead."
            )
    linked = [s for s in (sources or [])][: _MAX_SOURCES]
    for source in linked:
        kind = str(source.get("kind") or "").strip() or "source"
        label = _cap(str(source.get("label") or "").strip(), 120)
        excerpt = _cap(
            str(source.get("excerpt") or "").strip(), _MAX_SOURCE_EXCERPT_CHARS
        )
        if excerpt:
            lines.append(
                f"Linked {kind} source for this strand ({label or 'untitled'}), "
                f"redacted at capture: {excerpt}"
            )
        elif label:
            lines.append(
                f"Linked {kind} source for this strand ({label}). "
                "Draw on it only through what the user or the thread "
                "has established about it."
            )
    return "\n".join(_cap(line) for line in lines if line.strip())
