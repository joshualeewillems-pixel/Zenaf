"""Per-inference review claims for the agent intake review queue.

Joshua's direction: "what's being assimilated needs to be more granular and
human interactive." Instead of bulk-accepting a sort result or a list of mined
projects, every assimilated claim becomes its own conversational card:

1. **Evidence** — a verbatim quote from the transcript ("in the conversation
   where you responded with 'x'…"). Never invented; always from the stored
   examples or the miner's source_quote.
2. **Inference** — what the system thinks the moment reveals, in plain human
   language ("it seemed like you may prefer…"). No strand-keyword salad.
3. **The ask** — "Is that right? Would you like to say more about why?"
4. **Actions** — Accept (→ training signal), Correct (→ ideals-guidance),
   Explain (free text about *why* → ideals-guidance, linked to the evidence).

Claim types: "strand" (per-strand placement), "kind" (skill/talent/project),
"initiative" | "project" | "task" | "idea" (mined proposals).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .schema import ConnectedAgent

# Claim types
CLAIM_TYPES = ("strand", "kind", "initiative", "project", "task", "idea")
# Claim statuses
CLAIM_STATUSES = ("pending", "accepted", "corrected", "explained")

# Only strands scoring at or above this get their own claim card.
_CLAIM_SCORE_THRESHOLD = 0.25


@dataclass
class ReviewClaim:
    """One assimilated inference awaiting the user's review."""

    id: str  # stable: "strand:self", "kind", "initiative:0", "project:1", ...
    claim_type: str  # one of CLAIM_TYPES
    title: str  # short human label
    evidence: str  # verbatim quote from the transcript ("" if none found — never invented)
    inference: str  # plain-language interpretation
    detail: str = ""  # extra context (goal, status hint, etc.)
    status: str = "pending"  # one of CLAIM_STATUSES
    user_note: str = ""  # correction or explanation text from the user

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "claim_type": self.claim_type,
            "title": self.title,
            "evidence": self.evidence,
            "inference": self.inference,
            "detail": self.detail,
            "status": self.status,
            "user_note": self.user_note,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "ReviewClaim":
        return cls(
            id=str(d.get("id", "")),
            claim_type=str(d.get("claim_type", "")),
            title=str(d.get("title", "")),
            evidence=str(d.get("evidence", "")),
            inference=str(d.get("inference", "")),
            detail=str(d.get("detail", "")),
            status=str(d.get("status", "pending")),
            user_note=str(d.get("user_note", "")),
        )


# ---------------------------------------------------------------------------
# Evidence extraction: find the transcript chunk behind a strand claim.
# ---------------------------------------------------------------------------

def _score_chunk(chunk: str, markers: tuple[str, ...]) -> int:
    """Count marker hits in a chunk (case-insensitive substring)."""
    low = chunk.lower()
    return sum(1 for m in markers if m.lower() in low)


def find_evidence_chunk(examples: list[str], markers: tuple[str, ...]) -> str:
    """Return the verbatim example chunk with the most marker hits.

    Returns "" when nothing matches — the caller must not invent a quote.
    The chunk is trimmed to a readable length, keeping the speaker label.
    """
    if not examples or not markers:
        return ""
    best: str = ""
    best_score = 0
    for ex in examples:
        s = _score_chunk(ex, markers)
        if s > best_score:
            best_score = s
            best = ex
    if not best:
        return ""
    # Trim to a readable quote; keep the speaker prefix if present.
    if len(best) > 400:
        cut = best[:400]
        # Avoid cutting mid-word.
        space = cut.rfind(" ")
        if space > 300:
            cut = cut[:space]
        best = cut.rstrip() + "…"
    return best


# ---------------------------------------------------------------------------
# Inference humanization: reasoning -> plain human language.
# ---------------------------------------------------------------------------

_STRAND_PLAIN = {
    "word": "how you use language — writing, voice, the way you put things",
    "number": "how you think with numbers and patterns — analysis, evidence, logic",
    "image": "how you see and shape the visual — design, imagery, aesthetics",
    "sound": "how you work with sound — music, rhythm, what's heard",
    "body": "how you work with your hands and body — craft, making, the physical",
    "people": "how you relate to people — teaching, leading, mediating, community",
    "self": "how you steer your own life — decisions, values, purpose, direction",
}

_STRAND_NAME = {
    "word": "Storyteller",
    "number": "Patternist",
    "image": "Seer",
    "sound": "Songwriter",
    "body": "Maker",
    "people": "Mediator",
    "self": "Guide",
}


def humanize_strand_inference(strand_key: str, reasoning: str, score: float) -> str:
    """Turn a strand claim's reasoning into plain human language.

    Rule-based reasoning looks like "mentions purpose, values — strong self
    signals". The human version names what the person was doing, not the
    marker list.
    """
    plain = _STRAND_PLAIN.get(strand_key, strand_key)
    name = _STRAND_NAME.get(strand_key, strand_key)
    # Already-plain LLM reasoning: keep it, framed as a read.
    if "mentions" not in reasoning and "markers" not in reasoning:
        r = reasoning.strip()
        if r and not r.endswith((".", "!", "?")):
            r += "."
        return f"This reads as {name} material — {plain}. {r}".strip()
    # Rule-based: parse "mentions a, b — <strength> <faculty> signals".
    strength = "some"
    if "strong" in reasoning:
        strength = "a lot of"
    elif "moderate" in reasoning:
        strength = "a fair amount of"
    # Extract the cited markers for grounding (not as jargon — as topics).
    topics = ""
    if "mentions" in reasoning:
        try:
            topics = reasoning.split("mentions", 1)[1].split("—")[0].strip()
        except IndexError:
            topics = ""
    if topics:
        return (
            f"You kept coming back to {topics} — {strength} of what you said "
            f"was about {plain}."
        )
    return f"{strength.capitalize()} of this conversation was about {plain}."


def _kind_inference(kind: str, kind_reasoning: str) -> str:
    if kind == "skill":
        base = "This looks like a trained capability — something you do with a repeatable process."
    elif kind == "talent":
        base = "This looks like a natural aptitude — something you just do well."
    elif kind == "project":
        base = "This looks like goal-directed work — something you're building toward."
    else:
        base = "I couldn't tell yet whether this is a skill, a talent, or a project."
    r = (kind_reasoning or "").strip()
    if r:
        return f"{base} {r}"
    return base


# ---------------------------------------------------------------------------
# Claim builders.
# ---------------------------------------------------------------------------

def build_strand_claims(agent: ConnectedAgent) -> list[ReviewClaim]:
    """One claim card per strand the sorter placed above threshold."""
    from .sorter import _STRAND_MARKERS

    if not agent.sort:
        return []
    claims: list[ReviewClaim] = []
    for c in agent.sort.claims:
        if c.score < _CLAIM_SCORE_THRESHOLD:
            continue
        markers = _STRAND_MARKERS.get(c.strand, ())
        evidence = find_evidence_chunk(agent.examples, markers)
        inference = humanize_strand_inference(c.strand, c.reasoning, c.score)
        name = _STRAND_NAME.get(c.strand, c.strand)
        claims.append(
            ReviewClaim(
                id=f"strand:{c.strand}",
                claim_type="strand",
                title=f"{name} strand",
                evidence=evidence,
                inference=inference,
                detail=f"Sorter score {c.score:.1f}",
            )
        )
    return claims


def build_kind_claim(agent: ConnectedAgent) -> ReviewClaim | None:
    """A claim card for the skill/talent/project placement."""
    if not agent.sort or not agent.sort.kind or agent.sort.kind == "undecided":
        return None
    return ReviewClaim(
        id="kind",
        claim_type="kind",
        title=f"Kind: {agent.sort.kind}",
        evidence="",
        inference=_kind_inference(agent.sort.kind, agent.sort.kind_reasoning),
    )


def build_mined_claims(mining_result: Any) -> list[ReviewClaim]:
    """One claim card per mined initiative/project/task/idea.

    Evidence comes from the miner's source_quote (verbatim anchor).
    Inference is the proposal in plain language.
    """
    claims: list[ReviewClaim] = []
    sections = [
        ("initiatives", "initiative"),
        ("projects", "project"),
        ("standalone_tasks", "task"),
        ("ideas", "idea"),
    ]
    for attr, ctype in sections:
        items = getattr(mining_result, attr, None) or []
        for i, item in enumerate(items):
            title = getattr(item, "title", "") or "Untitled"
            quote = getattr(item, "source_quote", "") or ""
            # Plain-language inference from the proposal's own fields.
            goal = getattr(item, "goal", "") or ""
            detail_text = getattr(item, "detail", "") or ""
            brief = getattr(item, "brief", "") or ""
            status_hint = getattr(item, "status_hint", "") or ""
            if ctype == "initiative":
                inference = f"You seem to be building toward something larger: {title}."
                detail = brief
            elif ctype == "project":
                inference = f"This looks like an active endeavor: {title}."
                detail = goal + (f" ({status_hint})" if status_hint else "")
            elif ctype == "task":
                inference = f"This looks like a concrete next step: {title}."
                detail = detail_text
            else:  # idea
                inference = f"You've been turning this over: {title}."
                detail = detail_text
            claims.append(
                ReviewClaim(
                    id=f"{ctype}:{i}",
                    claim_type=ctype,
                    title=title,
                    evidence=quote,
                    inference=inference.strip(),
                    detail=detail.strip(),
                )
            )
    return claims
