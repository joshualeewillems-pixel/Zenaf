"""Frontier-LLM sorter for Agent Intake ("The Sorting") — the primary engine.

Uses the existing Anthropic provider integration (local_ai/providers/anthropic.py)
to have the seven strand agents genuinely read and claim the connected agent's
material. Returns the same SortResult contract as the rule-based sorter, so the
pipeline is engine-agnostic.

The rule-based sorter (sorter.py) remains as the instant offline fallback when
no API key is configured or the LLM call fails.
"""
from __future__ import annotations

import json
import os
import re

from local_ai.strands import STRANDS

from .schema import SortResult, StrandClaim

# Sorter prompt budget: intake historically kept ~20 example turns, so the
# LLM sorter reads at most this many. Moment-level review reads the full
# stored example list separately.
_PROMPT_EXAMPLE_LIMIT = 20

_CLAIM_PROMPT = """You are the intake council for Zenaf, a system of seven trainable AI agents, each embodying a faculty of human intelligence. A user has connected an external AI agent and described it below. Your job: read the material the way each of the seven agents would, and decide how strongly this agent's material would train each of them.

The seven strands:
{strands}

The connected agent:
Name: {name}
Description: {description}
Instructions (system prompt, if provided): {instructions}
Example interactions: {examples}

For EACH strand, score 0.0–1.0 how strongly this agent's material would train that strand's agent. 0 = irrelevant, 1 = this is core training material for that strand. Give 1–2 sentences of reasoning per strand, citing specific phrases from the material.

Then classify the agent's kind:
- "skill": a trained capability — procedural language, produces artifacts, "it helps me do X"
- "talent": an innate aptitude — intuition/taste/judgment language, "it just gets X"
- "project": goal-directed work — "we're working on Y", named endeavors
- "undecided": genuinely ambiguous

Respond with ONLY valid JSON in this exact shape:
{{
  "claims": [
    {{"strand": "<strand_key>", "score": 0.0, "reasoning": "..."}},
    ... (all seven strands)
  ],
  "kind": "<skill|talent|project|undecided>",
  "kind_reasoning": "..."
}}

Strand keys must be exactly: word, number, image, sound, body, people, self."""


def _strand_block() -> str:
    lines = []
    for s in STRANDS:
        lines.append(f"- {s.key} ({s.faculty} / {s.agent_name}): {s.tagline}")
    return "\n".join(lines)


def _api_key(user_id: str | None = None) -> str | None:
    from . import llm_keys

    return llm_keys.resolve_key(llm_keys.resolve_intake_provider(), user_id, operation="sort")


def sort_with_llm(
    name: str,
    description: str,
    instructions: str | None = None,
    examples: list[str] | None = None,
    model: str | None = None,
    user_id: str | None = None,
) -> SortResult:
    """Sort via the intake provider. Raises on missing key or unparseable response."""
    from . import llm_keys

    api_key = _api_key(user_id)
    if not api_key:
        raise RuntimeError("No API key for the intake provider")

    prompt = _CLAIM_PROMPT.format(
        strands=_strand_block(),
        name=name or "(unnamed)",
        description=description or "(none)",
        instructions=instructions or "(none)",
        # Prompt budget: the sorter reads the first _PROMPT_EXAMPLE_LIMIT
        # turns (the pre-moment-cards behavior). The full example list stays
        # on the agent for moment-level review cards.
        examples="\n---\n".join((examples or [])[:_PROMPT_EXAMPLE_LIMIT]) or "(none)",
    )
    raw = llm_keys.generate(prompt, api_key=api_key, user_id=user_id, operation="sort")

    # Extract the JSON object (the model may wrap it in fences or prose).
    m = re.search(r"\{.*\}", raw, re.S)
    if not m:
        raise RuntimeError("LLM sorter returned no JSON")
    try:
        data = json.loads(m.group(0))
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"LLM sorter returned invalid JSON: {exc}")

    valid_keys = {s.key for s in STRANDS}
    claims: list[StrandClaim] = []
    for item in data.get("claims") or []:
        key = str(item.get("strand", "")).strip().lower()
        if key not in valid_keys:
            continue
        try:
            score = max(0.0, min(1.0, float(item.get("score", 0.0))))
        except (TypeError, ValueError):
            score = 0.0
        claims.append(
            StrandClaim(
                strand=key,
                score=round(score, 3),
                reasoning=str(item.get("reasoning", ""))[:500],
            )
        )
    # Ensure all seven strands are represented (missing = pass, score 0).
    seen = {c.strand for c in claims}
    for s in STRANDS:
        if s.key not in seen:
            claims.append(
                StrandClaim(strand=s.key, score=0.0, reasoning="no claim made — passing")
            )
    order = {s.key: i for i, s in enumerate(STRANDS)}
    claims.sort(key=lambda c: (-c.score, order.get(c.strand, 99)))
    primary = claims[0].strand

    kind = str(data.get("kind", "undecided")).strip().lower()
    if kind not in ("skill", "talent", "project", "undecided"):
        kind = "undecided"

    # Multi-frame weights: every strand at/above threshold trains.
    strand_weights = {c.strand: c.score for c in claims if c.score >= 0.25}

    top, second = claims[0].score, claims[1].score if len(claims) > 1 else 0.0
    confidence = round((top - second) / top, 3) if top > 0 else 0.0

    return SortResult(
        primary_strand=primary,
        claims=claims,
        strand_weights=strand_weights,
        kind=kind,  # type: ignore[arg-type]
        kind_reasoning=str(data.get("kind_reasoning", ""))[:500],
        linked_projects=[],
        confidence=confidence,
        needs_probing=confidence < 0.35,
    )


def sort_primary(
    name: str,
    description: str,
    instructions: str | None = None,
    examples: list[str] | None = None,
    user_id: str | None = None,
) -> tuple[SortResult, str]:
    """Primary entry point: LLM sorter first, rule-based fallback.

    Returns (SortResult, engine) where engine is "anthropic" or "rule_based".
    """
    if _api_key(user_id):
        try:
            return sort_with_llm(name, description, instructions, examples, user_id=user_id), "anthropic"
        except Exception:
            pass  # fall through to rule-based
    from .sorter import sort as rule_sort

    return rule_sort(name, description, instructions, examples), "rule_based"
