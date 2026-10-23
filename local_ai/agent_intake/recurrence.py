"""Recurrence mining: what does this person keep coming back to?

The sorter mines moments; the insight miner interprets moments. Neither
counts RETURNING. But what a person talks about repeatedly is some of
the strongest evidence of what matters to them — a topic raised once is
an event; a topic raised in turn 2 and again in turn 9 is a pull
(Joshua, 2026-10-23: "You can understand what's important to people by
what they talk about").

This pass reads a whole conversation for topics the speaker returns to
in at least two separate turns and proposes each as a PATTERN-scope
review claim: tentative, falsifiable, anchored in verbatim quotes from
the distinct turns that evidence the return. The same grounding
discipline as the rest of intake applies, enforced in code, not just
asked of the model:

- every quote must actually appear in the transcript;
- the quotes must come from at least two DIFFERENT turns;
- at most 4 patterns per conversation, strongest first;
- no LLM -> no claims. There is deliberately no keyword-counting
  fallback: a fabricated pattern is worse than an honest empty result.

Nothing here trains anything. Patterns become review claims; the user
accepts, corrects, explains, rejects, or leaves them unresolved —
exactly like insight claims.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

STRANDS = ("Voice", "Logic", "Eye", "Ear", "Hands", "Heart", "Compass")

_MAX_PATTERNS = 4


@dataclass
class RecurrencePattern:
    topic: str
    strand: str | None  # one of STRANDS, or None when the model hedged
    inference: str  # one tentative, falsifiable sentence
    quotes: list[str] = field(default_factory=list)  # verbatim, distinct turns
    turns: list[int] = field(default_factory=list)  # 1-based, parallel-ish to quotes


_RECURRENCE_PROMPT = """Read this conversation transcript and find what this person RETURNS TO.

A recurrence is a topic, concern, person, question, or image the speaker comes back to in at least TWO separate turns — not something mentioned once, however vividly. What a person returns to is evidence about what matters to them.

For each recurrence (at most 4, strongest first):
- "topic": a short label for what they return to (3-7 words).
- "strand": the ONE of the seven strands this recurrence most speaks to — Voice (how they say things), Logic (reasoning, systems), Eye (images, how things look), Ear (sound, rhythm), Hands (making, doing, the body), Heart (people, relationships, care), Compass (values, direction, decisions).
- "inference": ONE tentative, falsifiable sentence about what the returning suggests, phrased as a first read that may be wrong ("You keep coming back to X — it reads like ..."). Never invent beliefs, values, or traits the quotes don't evidence. When in doubt, leave it out.
- "quotes": 2 or 3 VERBATIM quotes, copied exactly, from DIFFERENT turns, that show the return happening.

Transcript (turns are numbered):
{transcript}

Respond with ONLY valid JSON in this shape:
{{"patterns": [{{"topic": "...", "strand": "Heart", "inference": "...", "quotes": ["...", "..."]}}]}}
If nothing recurs, return {{"patterns": []}}."""


def _api_key(user_id: str | None = None) -> str | None:
    from . import llm_keys

    return llm_keys.resolve_key(llm_keys.resolve_intake_provider(), user_id, operation="recurrence")


def _generate(prompt: str, user_id: str | None) -> str:
    from . import llm_keys

    return llm_keys.generate(
        prompt,
        api_key=_api_key(user_id),
        user_id=user_id,
        operation="recurrence",
    )


def _normalize(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip().lower()


def _quote_turns(quote: str, chunks: list[str]) -> list[int]:
    """1-based indices of the turns whose text contains the quote
    (whitespace/case-insensitive). Empty = the quote is not grounded."""
    needle = _normalize(quote)
    if not needle:
        return []
    return [i + 1 for i, c in enumerate(chunks) if needle in _normalize(c)]


def _parse_patterns(raw: str, chunks: list[str]) -> list[RecurrencePattern]:
    m = re.search(r"\{.*\}", raw, re.S)
    if not m:
        return []
    try:
        data = json.loads(m.group(0))
    except ValueError:
        return []
    patterns: list[RecurrencePattern] = []
    for item in data.get("patterns") or []:
        if not isinstance(item, dict):
            continue
        topic = str(item.get("topic") or "").strip()[:120]
        inference = str(item.get("inference") or "").strip()[:800]
        if not topic or not inference:
            continue
        strand_raw = str(item.get("strand") or "").strip()
        strand = next((s for s in STRANDS if s.lower() == strand_raw.lower()), None)
        # Grounding: every quote must be found, and the found turns must
        # span at least two distinct turns — that IS the recurrence.
        quotes: list[str] = []
        turns: list[int] = []
        grounded = True
        for q in item.get("quotes") or []:
            q = str(q).strip()
            found = _quote_turns(q, chunks)
            if not q or not found:
                grounded = False
                break
            quotes.append(q[:600])
            turns.append(found[0])
        if not grounded or len(quotes) < 2 or len(set(turns)) < 2:
            continue
        patterns.append(
            RecurrencePattern(
                topic=topic, strand=strand, inference=inference,
                quotes=quotes, turns=turns,
            )
        )
        if len(patterns) >= _MAX_PATTERNS:
            break
    return patterns


def mine_recurrences(
    examples: list[str],
    model: str | None = None,
    user_id: str | None = None,
) -> tuple[list[RecurrencePattern], str]:
    """Mine topic recurrences from transcript examples.

    Returns (patterns, engine). LLM-only by design: without a key (or on
    any failure) the result is an honest empty list — see module docstring.
    """
    from .insight_miner import _numbered_transcript

    chunks = [c.strip() for c in (examples or []) if c.strip()]
    if len(chunks) < 2:
        return [], "rule_based"  # a return needs at least two turns to exist in
    numbered, _plain = _numbered_transcript(chunks)

    if not _api_key(user_id):
        return [], "rule_based"
    try:
        raw = _generate(_RECURRENCE_PROMPT.format(transcript=numbered), user_id)
        return _parse_patterns(raw, chunks), "anthropic"
    except Exception:
        return [], "rule_based"
