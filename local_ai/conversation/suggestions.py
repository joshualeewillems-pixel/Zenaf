"""Suggestion engine for the conversation skeleton — Phase 2.

Reads conversation history + the latest live-context snapshot and produces
exactly three kinds of suggestions:

  1. trainable_moments  → draft payloads shaped like ReviewClaim dicts
     (review_claims.py conventions: verbatim evidence quote, plain-language
     inference, a confirm question, scope "moment"). DRAFTS ONLY — they are
     never written to the review queue here. Filing still goes through the
     normal amber confirmation flow; nothing trains without his verdict.
  2. project_proposals   → drafts shaped like the project miner's proposals
     (kind: initiative | project | task | idea; title; source_quote; detail).
     Meant for the mining confirmation flow, not direct creation.
  3. mint_suggestions    → drafts for the standalone-mint flow
     (POST /pipeline/mint-standalone + the anchoring question
     "How does this piece express this moment to you?").

Suggestions are open threads, never pushes: computed on demand by
GET /conversation/suggestions, cached per message watermark so a repeat GET
doesn't re-run the LLM. Review gating holds everywhere — this module writes
no training data, creates no entities, mints nothing.

Honesty rule: when the LLM is unavailable or its output doesn't parse, the
engine returns the empty triple — no suggestions rather than junk. Precision
beats coverage.
"""

from __future__ import annotations

import json
from typing import Any, Callable

from local_ai.agent_intake.review_claims import CLAIM_TYPES, ReviewClaim

GenerateFn = Callable[..., str]

_SUGGESTION_PROMPT = """\
You are reading an ongoing one-on-one conversation between a user and one of
their council voices. Look at the recent turns and the live context, then
suggest at most a few items in each of three categories. Be conservative:
only suggest what the conversation genuinely supports. If nothing qualifies,
return empty lists.

Categories:
1. trainable_moments — moments that reveal the user's values, decision
   patterns, preferences, or stances: things worth their explicit review as
   potential training signal. Each needs: a verbatim quote from the user
   ("evidence" — never invent one; use "" only if truly none), a
   plain-language interpretation ("inference"), and one confirm question in
   the user's voice ("question"). Keep the interpretive jump small and
   falsifiable.
2. project_proposals — concrete undertakings, commitments, or things to
   organize that the user named. Each needs: kind (one of "initiative",
   "project", "task", "idea"), a short title, the user's own words
   ("source_quote"), and one line on why it matters ("detail").
3. mint_suggestions — moments with narrative or creative charge: a turning
   point, a vivid image, something the user might want captured as a story
   or artifact. Each needs: a title, the moment in one line ("moment"), the
   user's words ("source_quote"), and why it might be worth keeping ("why").

Live context: {live_context}

Recent turns:
{transcript}

Respond with STRICT JSON only, no prose, no code fences:
{{"trainable_moments": [{{"title": "...", "claim_type": "value_inference",
"evidence": "...", "inference": "...", "question": "..."}}],
"project_proposals": [{{"kind": "task", "title": "...", "source_quote": "...",
"detail": "..."}}],
"mint_suggestions": [{{"title": "...", "moment": "...", "source_quote": "...",
"why": "..."}}]}}
"""

_CLAIM_TYPE_FALLBACK = "value_inference"
_PROJECT_KINDS = ("initiative", "project", "task", "idea")
_MAX_PER_KIND = 5


def empty_suggestions() -> dict[str, list]:
    return {"trainable_moments": [], "project_proposals": [], "mint_suggestions": []}


def rule_based_suggestions() -> dict[str, list]:
    """The honest offline fallback: no suggestions rather than junk.

    Kept as a named function (mirroring the miners' _rule_based_* pattern)
    so the fallback is explicit and testable.
    """
    return empty_suggestions()


def _transcript(turns: list[dict[str, Any]], seat_names: dict[str, str] | None = None) -> str:
    lines = []
    for t in turns[-30:]:
        role = t.get("role", "")
        body = (t.get("body") or "")[:800]
        if role == "user":
            who = "User"
        else:
            arch = t.get("archetype_id") or ""
            who = (seat_names or {}).get(arch, arch or "Voice")
        lines.append(f"{who}: {body}")
    return "\n".join(lines)


def _clean_claim_type(raw: Any) -> str:
    ctype = str(raw or "").strip().lower()
    return ctype if ctype in CLAIM_TYPES else _CLAIM_TYPE_FALLBACK


def _shape_trainable_moment(item: dict[str, Any], n: int) -> dict[str, Any]:
    claim = ReviewClaim(
        id=f"skeleton:insight:{n}",
        claim_type=_clean_claim_type(item.get("claim_type")),
        title=str(item.get("title") or "Noted moment")[:120],
        evidence=str(item.get("evidence") or "")[:600],
        inference=str(item.get("inference") or "")[:600],
        detail="Suggested from the ongoing conversation.",
        status="draft",
        question=str(item.get("question") or "Does that sound right to you?")[:300],
        scope="moment",
        turn_ref="",
    )
    d = claim.to_dict()
    d["draft"] = True
    d["source"] = "conversation-skeleton"
    return d


def _shape_project_proposal(item: dict[str, Any], n: int) -> dict[str, Any]:
    kind = str(item.get("kind") or "").strip().lower()
    if kind not in _PROJECT_KINDS:
        kind = "idea"
    return {
        "id": f"skeleton:proposal:{n}",
        "kind": kind,
        "title": str(item.get("title") or "Untitled")[:160],
        "source_quote": str(item.get("source_quote") or "")[:600],
        "detail": str(item.get("detail") or "")[:600],
        "draft": True,
        "status": "draft",
        "source": "conversation-skeleton",
    }


def _shape_mint_suggestion(item: dict[str, Any], n: int) -> dict[str, Any]:
    return {
        "id": f"skeleton:mint:{n}",
        "title": str(item.get("title") or "Untitled moment")[:160],
        "moment": str(item.get("moment") or "")[:600],
        "source_quote": str(item.get("source_quote") or "")[:600],
        "why": str(item.get("why") or "")[:600],
        "suggested_action": "mint-standalone",
        "anchor_question": "How does this piece express this moment to you?",
        "draft": True,
        "source": "conversation-skeleton",
    }


def _parse(raw: str) -> dict[str, Any]:
    """Strict-parse the LLM's JSON; raise on anything unexpected."""
    data = json.loads(raw.strip())
    if not isinstance(data, dict):
        raise ValueError("suggestions payload is not an object")
    return data


def generate_suggestions(
    turns: list[dict[str, Any]],
    live_context: dict[str, Any] | None = None,
    generate_fn: GenerateFn | None = None,
    seat_names: dict[str, str] | None = None,
    user_id: str | None = None,
) -> dict[str, list]:
    """Produce the three suggestion kinds. Never raises — failures yield the
    empty triple (honest empty state, never junk)."""
    try:
        if not turns:
            return empty_suggestions()
        gen = generate_fn
        if gen is None:
            from local_ai.agent_intake.llm_keys import generate as _gen

            gen = _gen
        ctx = live_context or {}
        ctx_line = (
            f"sheet={ctx.get('sheet_type')}, entity={ctx.get('entity_type')}:{ctx.get('entity_id')}"
            if (ctx.get("sheet_type") or ctx.get("entity_type"))
            else "(none)"
        )
        prompt = _SUGGESTION_PROMPT.format(
            live_context=ctx_line,
            transcript=_transcript(turns, seat_names),
        )
        raw = gen(
            prompt, provider_id="meta", user_id=user_id,
            operation="conversation-suggestions", timeout=90,
        )
        data = _parse(raw)
        out = empty_suggestions()
        for n, item in enumerate((data.get("trainable_moments") or [])[:_MAX_PER_KIND]):
            if isinstance(item, dict):
                out["trainable_moments"].append(_shape_trainable_moment(item, n))
        for n, item in enumerate((data.get("project_proposals") or [])[:_MAX_PER_KIND]):
            if isinstance(item, dict):
                out["project_proposals"].append(_shape_project_proposal(item, n))
        for n, item in enumerate((data.get("mint_suggestions") or [])[:_MAX_PER_KIND]):
            if isinstance(item, dict):
                out["mint_suggestions"].append(_shape_mint_suggestion(item, n))
        return out
    except Exception:
        return empty_suggestions()


def asdict_suggestion_payload(suggestions: dict[str, list]) -> dict[str, list]:
    """Normalize for JSON transport (all shapers already return dicts)."""
    return {
        "trainable_moments": list(suggestions.get("trainable_moments") or []),
        "project_proposals": list(suggestions.get("project_proposals") or []),
        "mint_suggestions": list(suggestions.get("mint_suggestions") or []),
    }
