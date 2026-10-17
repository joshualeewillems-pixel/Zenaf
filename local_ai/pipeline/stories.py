"""Story extraction: journal entry -> archetype story (spec §2).

On-demand ("Make this a story"). The LLM produces a title, a short
narrative of the growth moment, and one quotable key line — in the
product's 11th-grade plain register: short sentences, no stacked clauses.
Council context comes from the existing strand/archetype analysis in
`local_ai/journal/story.py` (rule-based, no extra LLM cost).
"""

from __future__ import annotations

import json
import re
from typing import Any

from local_ai.council.archetypes import get_archetype
from local_ai.journal.story import (
    analyze_entry_strands,
    detect_active_archetypes,
    select_cast,
)

_STORY_PROMPT = """You turn a journal entry into a short archetype story: the growth moment in it, told plainly.

REGISTER (non-negotiable): plain 11th-grade conversation. Short sentences. No stacked clauses inside questions or sentences. Say it simply, like telling a friend.

Journal entry:
---
{entry}
---

The council seats present in this moment: {cast_names}.
{cast_notes}

Respond with ONLY a JSON object (no markdown fences, no commentary):
{{
  "title": "a short evocative title, under 8 words",
  "narrative": "the growth moment as a short story, 120-200 words, plain register. Second person ('you') is fine. Name what shifted.",
  "key_line": "ONE quotable sentence from the story's heart, under 25 words. This will become a shareable quote card."
}}
"""


def _cast_context(
    cast: list[tuple[str, float]], user_id: str | None
) -> tuple[list[str], str]:
    names: list[str] = []
    notes: list[str] = []
    for archetype_id, _sim in cast:
        try:
            arch = get_archetype(archetype_id)
        except Exception:
            continue
        name = getattr(arch, "name", archetype_id)
        names.append(name)
        question = getattr(arch, "defining_question", "")
        if question:
            notes.append(f"- {name} asks: {question}")
    note_block = (
        "Each seat's defining question is listed; let the story honor what each seat would notice.\n" +
        "\n".join(notes)
        if notes else ""
    )
    return names, note_block


def _extract_json(reply: str) -> dict[str, Any]:
    """Pull a JSON object out of an LLM reply (tolerates fences/prose)."""
    text = reply.strip()
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        raise ValueError("LLM reply contained no JSON object")
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError as exc:
        raise ValueError(f"LLM reply was not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError("LLM reply JSON was not an object")
    return data


def extract_story(
    entry_text: str,
    *,
    user_id: str | None = None,
    api_key: str | None = None,
    model: str | None = None,
    timeout: int = 90,
) -> dict[str, Any]:
    """Extract a story artifact's content from a journal entry.

    Returns {title, narrative, key_line, archetype_cast, strand_weights}.
    Raises RuntimeError if the LLM call fails, ValueError on bad output.
    """
    from local_ai.providers import meta as _meta

    text = (entry_text or "").strip()
    if not text:
        raise ValueError("Entry text is empty.")

    strand_weights = analyze_entry_strands(text)
    ranked = detect_active_archetypes(strand_weights, user_id=user_id)
    cast = select_cast(ranked)
    cast_names, cast_notes = _cast_context(cast, user_id)

    prompt = _STORY_PROMPT.format(
        entry=text[:6000],
        cast_names=", ".join(cast_names) if cast_names else "the full council",
        cast_notes=cast_notes,
    )
    try:
        reply = _meta.generate(
            api_key or "", prompt, model=model, timeout=timeout,
            reasoning_effort="low",
        ).strip()
    except Exception as exc:
        raise RuntimeError(f"story extraction failed: {exc}") from exc

    data = _extract_json(reply)
    title = str(data.get("title") or "").strip()
    narrative = str(data.get("narrative") or "").strip()
    key_line = str(data.get("key_line") or "").strip()
    if not title or not narrative or not key_line:
        raise ValueError("LLM story was missing title, narrative, or key_line.")

    return {
        "title": title[:120],
        "narrative": narrative[:2000],
        "key_line": key_line[:280],
        "archetype_cast": cast_names,
        "strand_weights": {k: round(v, 3) for k, v in strand_weights.items()},
    }
