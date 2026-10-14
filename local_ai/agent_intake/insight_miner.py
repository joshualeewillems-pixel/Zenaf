"""Atomic insight miner: one specific moment -> one specific inference.

Joshua's direction: reviewable insights must be ATOMIC and transparent —
one observable moment, one falsifiable interpretation, genuine alternatives
shown explicitly (not hidden), and a conservative scope label (moment /
subject / pattern). "You objected to this use of a framework" -> "you are
allergic to reification" is a substantial interpretive jump; the miner must
expose the jump, not smuggle it.

Each insight becomes one primary ReviewClaim (claim_type in
value_inference | decision_pattern | stance | preference) plus one
"alternative" ReviewClaim per genuine alternative reading. Alternatives are
separate claims so each is individually respondable — confirming the
interpretation never silently approves the others.

Conservative by design: every insight must anchor to a VERBATIM quote from
the transcript. No quote, no claim. A false inference accepted as true
poisons training — precision over coverage.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

# Valid insight claim types (the primary interpretation's type).
INSIGHT_CLAIM_TYPES = ("value_inference", "decision_pattern", "stance", "preference")
# Valid scope labels. Default is "moment" — the miner may only claim broader
# scope when it can cite cross-moment evidence.
SCOPES = ("moment", "subject", "pattern")

# Cap LLM input so a very long conversation doesn't blow the context.
_MAX_TRANSCRIPT_CHARS = 12000
# Cap insights so one conversation can't flood the review queue.
_MAX_INSIGHTS = 12
_MAX_ALTERNATIVES = 3


@dataclass
class InsightAlternative:
    """One genuine alternative reading of the same moment."""

    text: str
    scope: str  # one of SCOPES
    question: str  # confirm question in the user's voice


@dataclass
class MinedInsight:
    """One atomic, anchored insight."""

    turn: int | None  # 1-based turn number in the numbered transcript
    evidence: str  # verbatim quote from the transcript
    claim_type: str  # one of INSIGHT_CLAIM_TYPES
    interpretation: str  # ONE specific, falsifiable claim
    interpretation_scope: str  # one of SCOPES
    interpretation_question: str
    strand: str | None  # strand key if it clearly maps, else None
    alternatives: list[InsightAlternative] = field(default_factory=list)


_INSIGHT_PROMPT = """You are reading a conversation transcript to surface precise, contestable insights about how this person thinks — their values, decision patterns, and stances. Each insight you produce becomes a review card the person themselves will confirm, qualify, or reject. A false inference accepted as true poisons their training data. Precision over coverage.

For each insight, identify ONE specific moment (a turn number and a VERBATIM quote), then provide:

1. INTERPRETATION: one specific, falsifiable claim about what that moment suggests. E.g. "You said X, which seems to imply you believe A matters more than B here." The person must be able to say "no, that's wrong" about something specific.

2. ALTERNATIVES: 1-2 OTHER plausible explanations of the same moment. These must be GENUINE — readings a thoughtful person could actually hold — never strawmen. Example: if the interpretation is "you're resistant to reification," a genuine alternative is "you objected to this specific summary / its application / the other person's claims, not to frameworks in general."

3. SCOPE for the interpretation AND each alternative, labeled conservatively:
   - "moment": about this specific moment only. DEFAULT — use this unless you can cite evidence for broader scope.
   - "subject": about this topic/domain across moments (cite the other turn numbers).
   - "pattern": a possible recurring trait. ONLY with 2+ distinct cited moments as evidence.
   "You objected to this use of a framework" -> "you are allergic to reification" is a substantial interpretive jump. Expose the jump: keep the broad reading at "moment" scope unless the cross-moment evidence is really there, and let the person upgrade it.

4. CLAIM TYPE: one of value_inference (what they seem to value / trade off), decision_pattern (how they decide), stance (a position they take), preference (a like/dislike or inclination).

5. QUESTION for the interpretation and each alternative: a confirm question in the person's own voice, e.g. "Does that sound right to you?" Make it specific to the claim.

6. STRAND: one of word/number/image/sound/body/people/self if the insight clearly maps to a faculty, else null. Most insights won't map — that's fine, use null.

Rules:
- One moment = one insight. Never summarize the whole conversation.
- Every insight MUST have a verbatim quote copied EXACTLY from the transcript. No quote, no insight.
- Quote and turn number must match the transcript. Paraphrases are not quotes.
- Prefer 3 sharp insights over 12 shaky ones. If the conversation has no contestable moments, return an empty list.
- Never invent beliefs, values, or traits the quote doesn't evidence.

Transcript (turns numbered):
{transcript}

Respond with ONLY valid JSON in this exact shape:
{{
  "insights": [
    {{
      "turn": 5,
      "evidence": "verbatim quote...",
      "claim_type": "stance",
      "interpretation": "one specific claim...",
      "interpretation_scope": "moment",
      "interpretation_question": "Does that sound right to you?",
      "strand": null,
      "alternatives": [
        {{"text": "genuine alternative...", "scope": "moment",
          "question": "Could it be this instead?"}}
      ]
    }}
  ]
}}"""


def _api_key(user_id: str | None = None) -> str | None:
    from . import llm_keys

    return llm_keys.resolve_key(llm_keys.resolve_intake_provider(), user_id, operation="insight")


def _normalize(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip()


def _anchors(quote: str, transcript: str) -> bool:
    """Check a quote appears verbatim in the transcript.

    Guards the no-invented-quotes rule: the miner's output is verified
    against the source text, and anything that doesn't anchor is dropped.
    """
    q = _normalize(quote)
    if len(q) < 12:
        return False
    return q in _normalize(transcript)


def _numbered_transcript(examples: list[str]) -> tuple[str, str]:
    """Number each example chunk as a turn; return (numbered, plain)."""
    chunks = [c.strip() for c in (examples or []) if c.strip()]
    numbered = "\n\n".join(f"Turn {i + 1}:\n{c}" for i, c in enumerate(chunks))
    plain = "\n\n".join(chunks)
    return numbered[:_MAX_TRANSCRIPT_CHARS], plain


def _clean_scope(s: str | None) -> str:
    s = (s or "").strip().lower()
    return s if s in SCOPES else "moment"


def _clean_claim_type(s: str | None) -> str:
    s = (s or "").strip().lower()
    return s if s in INSIGHT_CLAIM_TYPES else "value_inference"


def _parse_insights_json(raw: str, transcript: str, n_turns: int) -> list[MinedInsight]:
    m = re.search(r"\{.*\}", raw, re.S)
    if not m:
        raise RuntimeError("insight miner returned no JSON")
    data = json.loads(m.group(0))
    insights: list[MinedInsight] = []
    for item in (data.get("insights") or [])[:_MAX_INSIGHTS]:
        evidence = str(item.get("evidence", "") or "").strip()
        # No quote, no claim — the core conservatism rule.
        if not evidence or not _anchors(evidence, transcript):
            continue
        try:
            turn = int(item.get("turn") or 0)
        except (TypeError, ValueError):
            turn = 0
        turn = turn if 1 <= turn <= max(n_turns, 1) else None
        interpretation = str(item.get("interpretation", "") or "").strip()
        if not interpretation:
            continue
        alternatives: list[InsightAlternative] = []
        for alt in (item.get("alternatives") or [])[:_MAX_ALTERNATIVES]:
            text = str(alt.get("text", "") or "").strip()
            if not text:
                continue
            alternatives.append(
                InsightAlternative(
                    text=text[:800],
                    scope=_clean_scope(alt.get("scope")),
                    question=str(alt.get("question", "") or "").strip()[:300]
                    or "Could it be this instead?",
                )
            )
        strand = str(item.get("strand", "") or "").strip().lower() or None
        insights.append(
            MinedInsight(
                turn=turn,
                evidence=evidence[:600],
                claim_type=_clean_claim_type(item.get("claim_type")),
                interpretation=interpretation[:800],
                interpretation_scope=_clean_scope(item.get("interpretation_scope")),
                interpretation_question=(
                    str(item.get("interpretation_question", "") or "").strip()[:300]
                    or "Does that sound right to you?"
                ),
                strand=strand,
                alternatives=alternatives,
            )
        )
    return insights


def mine_insights(
    examples: list[str],
    model: str | None = None,
    user_id: str | None = None,
) -> tuple[list[MinedInsight], str]:
    """Mine atomic insights from transcript examples.

    Returns (insights, engine) where engine is "anthropic" | "rule_based".
    LLM-first; rule-based fallback is honest and minimal, never inventing.
    """
    chunks = [c.strip() for c in (examples or []) if c.strip()]
    if not chunks:
        return [], "rule_based"
    numbered, plain = _numbered_transcript(chunks)

    api_key = _api_key(user_id)
    if api_key:
        try:
            from . import llm_keys

            raw = llm_keys.generate(
                _INSIGHT_PROMPT.format(transcript=numbered),
                model=model,
                api_key=api_key,
                user_id=user_id,
                operation="insight",
            )
            return _parse_insights_json(raw, plain, len(chunks)), "anthropic"
        except Exception:
            pass  # fall through to rule-based

    return _rule_based_insights(chunks), "rule_based"


# ---------------------------------------------------------------------------
# Rule-based fallback: surface explicit stance statements, honestly minimal.
#
# It cannot generate nuanced interpretations or genuine alternatives, so it
# doesn't try. Each claim is just the person's own explicit statement plus
# the conservative null-hypothesis alternative ("this moment vs. a broader
# stance"). No invention, by construction.
# ---------------------------------------------------------------------------

_STANCE_RES = [
    re.compile(r"\bi\s+(believe|think|feel)\s+(that\s+)?(.{10,200})", re.I),
    re.compile(r"\bi\s+(prefer|value|trust|distrust)\s+(.{5,150})", re.I),
    re.compile(r"\bi\s+disagree\s+(with\s+)?(.{5,150})", re.I),
    re.compile(r"(.{5,120}?)\s+matters?\s+more\s+than\s+(.{5,120})", re.I),
    re.compile(r"\bi'?m\s+(allergic\s+to|resistant\s+to|suspicious\s+of)\s+(.{5,120})", re.I),
]

_MOMENT_ALTERNATIVE = InsightAlternative(
    text="This might reflect this specific moment — what was at stake right here — rather than a broader stance.",
    scope="moment",
    question="Was this about the moment, or does it hold more broadly?",
)


def _rule_based_insights(chunks: list[MinedInsight | str]) -> list[MinedInsight]:
    chunks = [c for c in chunks if isinstance(c, str)]
    insights: list[MinedInsight] = []
    for i, chunk in enumerate(chunks):
        if len(insights) >= 5:
            break
        for line in chunk.splitlines():
            line = line.strip()
            if len(line) < 20 or len(line) > 400:
                continue
            matched = any(rx.search(line) for rx in _STANCE_RES)
            if not matched:
                continue
            # Don't double-count near-duplicate lines.
            if any(_normalize(line) == _normalize(s.evidence) for s in insights):
                continue
            insights.append(
                MinedInsight(
                    turn=i + 1,
                    evidence=line,
                    claim_type="stance",
                    interpretation=f"You stated this outright: “{line[:200]}”",
                    interpretation_scope="moment",
                    interpretation_question=(
                        "You said this directly — is it a stable stance for you, "
                        "or was it specific to this moment?"
                    ),
                    strand=None,
                    alternatives=[_MOMENT_ALTERNATIVE],
                )
            )
            break  # one insight per chunk, keep it minimal
    return insights
