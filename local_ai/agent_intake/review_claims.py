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
4. **Actions** — Confirm (→ training signal), Qualify or Explain (→
   ideals-guidance, linked to the evidence), Reject (→ negative signal),
   Leave unresolved (explicit, first-class, never a silent approval).

Claim types: "strand" (per-moment strand placement), "kind"
(skill/talent/project), "alternative" (a nested alternative reading of a
placement or insight), "initiative" | "project" | "task" | "idea" (mined
proposals), plus the atomic insight types.

Moment-level placements: a long conversation holds many distinct training
moments. The transcript is segmented into moments (speaker turns; trivially
short adjacent turns merge into the next), each moment is scored on every
strand with the sorter's marker machinery, and every (moment, strand) at or
above threshold gets its own card — its own quote, inference, and verdict.
No whole-conversation blanket summaries, and no dilution: one strong moment
in a long conversation surfaces on its own.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from .schema import ConnectedAgent

# Claim types
CLAIM_TYPES = (
    "strand",
    "kind",
    "initiative",
    "project",
    "task",
    "idea",
    # Atomic insight claims (one moment -> one interpretation + alternatives).
    "value_inference",
    "decision_pattern",
    "stance",
    "preference",
    "alternative",
)
# Claim statuses. "rejected" = the user judged the inference wrong.
# "unresolved" = the user actively left it open — first-class, not a verdict,
# and never a silent approval.
CLAIM_STATUSES = ("pending", "accepted", "corrected", "explained", "rejected", "unresolved")
# Scope labels for insight claims: how broad the claim is.
SCOPES = ("moment", "subject", "pattern")

# Only strands scoring at or above this get their own claim card.
_CLAIM_SCORE_THRESHOLD = 0.25


@dataclass
class ReviewClaim:
    """One assimilated inference awaiting the user's review."""

    id: str  # stable per agent, namespaced by agent id:
    # "{agent_id}:strand:{strand}:m{turn}", "{agent_id}:kind",
    # "{agent_id}:strand:{strand}:m{turn}:alt:0", "{agent_id}:initiative:{i}",
    # "{agent_id}:insight:{n}". The review_claims table keys rows by
    # claim_id alone, so a bare id would silently overwrite another agent's
    # cards and verdicts.
    claim_type: str  # one of CLAIM_TYPES
    title: str  # short human label
    evidence: str  # verbatim quote from the transcript ("" if none found — never invented)
    inference: str  # plain-language interpretation
    detail: str = ""  # extra context (goal, status hint, etc.)
    status: str = "pending"  # one of CLAIM_STATUSES
    user_note: str = ""  # correction or explanation text from the user
    question: str = ""  # confirm question in the user's voice ("Does that sound right to you?")
    scope: str = "moment"  # one of SCOPES — how broad the claim is
    turn_ref: str = ""  # e.g. "Turn 5" — where the evidence comes from

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
            "question": self.question,
            "scope": self.scope,
            "turn_ref": self.turn_ref,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "ReviewClaim":
        scope = str(d.get("scope", "") or "").strip().lower()
        return cls(
            id=str(d.get("id", "")),
            claim_type=str(d.get("claim_type", "")),
            title=str(d.get("title", "")),
            evidence=str(d.get("evidence", "")),
            inference=str(d.get("inference", "")),
            detail=str(d.get("detail", "")),
            status=str(d.get("status", "pending")),
            user_note=str(d.get("user_note", "")),
            question=str(d.get("question", "") or ""),
            scope=scope if scope in SCOPES else "moment",
            turn_ref=str(d.get("turn_ref", "") or ""),
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

def _trim_quote(text: str, limit: int = 400) -> str:
    if len(text) <= limit:
        return text
    cut = text[:limit]
    space = cut.rfind(" ")
    if space > limit - 100:
        cut = cut[:space]
    return cut.rstrip() + "…"


def _atomic_strand_inference(strand_key: str, matched: list[str]) -> str:
    """One specific, falsifiable placement claim for a single passage.

    Explains what the passage does and why that belongs to the strand —
    so the user can say "no, that's wrong" about something specific, not
    blanket-approve a whole-conversation summary.
    """
    name = _STRAND_NAME.get(strand_key, strand_key)
    if not matched:
        return f"Routed to {name}."
    words = ", ".join(f"'{w}'" for w in matched[:3])
    # Name the behavior the words indicate, not just the keywords.
    behaviors = {
        "word": f"you shape language with {words}",
        "number": f"you quantify or structure with {words}",
        "image": f"you think visually with {words}",
        "sound": f"you attend to rhythm or tone with {words}",
        "body": f"you make or act physically with {words}",
        "people": f"you attend to others with {words}",
        "self": f"you direct yourself with {words}",
    }
    behavior = behaviors.get(strand_key, f"you use {words}")
    return f"Here {behavior} — that's {name}'s territory."


# Max moment-level placement cards per strand — enough to cover a long
# conversation's distinct training moments, not so many it floods the
# review. Strongest moments first; the constant is the cap's single knob.
_MAX_MOMENT_CARDS_PER_STRAND = 8


# ---------------------------------------------------------------------------
# Moment segmentation: the transcript -> traceable speaker turns.
# ---------------------------------------------------------------------------

# Speaker-label line starts, e.g. "USER:", "assistant:". Matches both the
# bookmarklet's uppercase labels and share_link's lowercase "user:"/"assistant:".
_LABEL_RE = re.compile(r"(?m)^[ \t]*(USER|ASSISTANT|HUMAN|AI)[ \t]*:", re.I)

# Turns whose body (label stripped) is shorter than this merge into the next
# same-speaker turn — a lone "yes" is not a training moment, but its words
# stay verbatim in the merged quote.
_SHORT_TURN_CHARS = 60


@dataclass
class Moment:
    """One traceable unit of a conversation: a speaker turn (or a few merged
    trivially-short ones), numbered by transcript position."""

    turn: int  # 1-based number of the moment's first turn
    last_turn: int  # 1-based number of the moment's last turn (>= turn)
    speaker: str  # "user" | "assistant" | "unknown"
    text: str  # verbatim text, speaker labels preserved

    @property
    def turn_ref(self) -> str:
        base = (
            f"Turn {self.turn}"
            if self.turn == self.last_turn
            else f"Turns {self.turn}-{self.last_turn}"
        )
        who = {"user": "You", "assistant": "Assistant"}.get(self.speaker, "")
        return f"{base} · {who}" if who else base


def _strip_labels(text: str) -> str:
    return _LABEL_RE.sub("", text).strip()


def _merge_short_turns(moments: list[Moment]) -> list[Moment]:
    """Fold trivially short turns into the following same-speaker turn.

    Verbatim text is preserved; the merged moment spans both turn numbers so
    the quote stays traceable. Turn numbers of later moments are unchanged.
    """
    out: list[Moment] = []
    i = 0
    while i < len(moments):
        m = moments[i]
        nxt = moments[i + 1] if i + 1 < len(moments) else None
        if (
            nxt is not None
            and nxt.speaker == m.speaker
            and len(_strip_labels(m.text)) < _SHORT_TURN_CHARS
        ):
            out.append(
                Moment(
                    turn=m.turn,
                    last_turn=nxt.last_turn,
                    speaker=m.speaker,
                    text=(m.text.rstrip() + "\n" + nxt.text).strip(),
                )
            )
            i += 2
        else:
            out.append(m)
            i += 1
    return out


def segment_moments(examples: list[str] | None) -> list[Moment]:
    """Split stored examples into numbered speaker-turn moments.

    Each example is usually one labeled turn already; examples that contain
    several label lines (or none) are split (or kept whole) so every moment
    is one speaker's contiguous passage with a stable turn number.
    """
    raw: list[tuple[str, str]] = []
    for ex in examples or []:
        ex = (ex or "").strip()
        if not ex:
            continue
        matches = list(_LABEL_RE.finditer(ex))
        if not matches:
            raw.append(("unknown", ex))
            continue
        head = ex[: matches[0].start()].strip()
        if head:
            raw.append(("unknown", head))
        for i, m in enumerate(matches):
            start = m.start()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(ex)
            seg = ex[start:end].strip()
            if not seg:
                continue
            label = m.group(1).lower()
            speaker = "user" if label in ("user", "human") else "assistant"
            raw.append((speaker, seg))
    moments = [
        Moment(turn=i + 1, last_turn=i + 1, speaker=s, text=t)
        for i, (s, t) in enumerate(raw)
    ]
    return _merge_short_turns(moments)


def build_strand_claims(agent: ConnectedAgent) -> list[ReviewClaim]:
    """Moment-level strand placement claims: one training moment -> one routing.

    Every moment of the transcript is scored on every strand with the
    sorter's marker machinery; every (moment, strand) at or above
    _CLAIM_SCORE_THRESHOLD gets its own card — its own verbatim quote,
    inference, and verdict. No whole-conversation blanket summaries, and no
    dilution: one strong moment in a long conversation surfaces on its own.

    Cap: _MAX_MOMENT_CARDS_PER_STRAND strongest moments per strand.
    The top strand of a moment that also qualifies elsewhere gets a nested
    alternative reading naming the runner-up strand — individually
    respondable, so confirming the placement never approves the alternative.

    Claim ids are namespaced by agent id: the review_claims table keys rows
    by claim_id alone, so un-namespaced ids (e.g. "strand:self:m3") would
    silently overwrite another agent's cards and verdicts.
    """
    from .sorter import (
        _SCORE_SATURATION,
        _STRAND_RES,
        _matched_markers as _regex_matched_markers,
    )
    from local_ai.strands import strand_keys

    if not agent.sort:
        return []
    moments = segment_moments(agent.examples)
    if not moments:
        return []

    strand_order = {k: i for i, k in enumerate(strand_keys())}

    # Score every moment on every strand; keep qualifiers sorted best-first.
    per_moment: list[tuple[Moment, list[tuple[str, float, list[str]]]]] = []
    for m in moments:
        # The sorter's marker regexes are case-sensitive; the sorter itself
        # scores lowercased text, so do the same. The evidence quote keeps
        # the original casing.
        low = m.text.lower()
        scored: list[tuple[str, float, list[str]]] = []
        for strand in strand_keys():
            matched = _regex_matched_markers(_STRAND_RES[strand], low)
            score = min(1.0, len(matched) / _SCORE_SATURATION)
            if score >= _CLAIM_SCORE_THRESHOLD:
                scored.append((strand, score, matched))
        scored.sort(key=lambda t: (-t[1], strand_order.get(t[0], 99)))
        if scored:
            per_moment.append((m, scored))

    # Per-strand cap: strongest moments first (ties: earliest turn).
    kept: set[tuple[int, str]] = set()
    for strand in strand_keys():
        ranked = sorted(
            (
                (m, score, words)
                for m, scored in per_moment
                for (s, score, words) in scored
                if s == strand
            ),
            key=lambda t: (-t[1], t[0].turn),
        )
        for m, _score, _words in ranked[:_MAX_MOMENT_CARDS_PER_STRAND]:
            kept.add((m.turn, strand))

    # Emit chronologically so the review reads like the conversation.
    claims: list[ReviewClaim] = []
    for m, scored in per_moment:
        for rank, (strand, score, words) in enumerate(scored):
            if (m.turn, strand) not in kept:
                continue
            name = _STRAND_NAME.get(strand, strand)
            claims.append(
                ReviewClaim(
                    id=f"{agent.id}:strand:{strand}:m{m.turn}",
                    claim_type="strand",
                    title=f"{name} strand",
                    evidence=_trim_quote(m.text),
                    inference=_atomic_strand_inference(strand, words),
                    detail=f"Moment score {score:.1f}",
                    question="Does that placement sound right? Want to say more about why?",
                    scope="moment",
                    turn_ref=m.turn_ref,
                )
            )
            # Alternative reading: the runner-up strand, only when it genuinely
            # qualified on this moment too. Individually respondable.
            if rank == 0 and len(scored) > 1:
                alt_strand, _alt_score, alt_words = scored[1]
                alt_name = _STRAND_NAME.get(alt_strand, alt_strand)
                alt_word_list = ", ".join(f"'{w}'" for w in alt_words[:5])
                claims.append(
                    ReviewClaim(
                        id=f"{agent.id}:strand:{strand}:m{m.turn}:alt:0",
                        claim_type="alternative",
                        title="Alternative reading",
                        evidence="",
                        inference=(
                            f"This could also be {alt_name} material instead — "
                            f"it uses {alt_word_list}."
                            if alt_word_list
                            else f"This could also read as {alt_name} material."
                        ),
                        question="Could it be this instead?",
                        scope="moment",
                        turn_ref=m.turn_ref,
                    )
                )
    return claims


def build_kind_claim(agent: ConnectedAgent) -> ReviewClaim | None:
    """A claim card for the skill/talent/project placement."""
    if not agent.sort or not agent.sort.kind or agent.sort.kind == "undecided":
        return None
    # Namespaced by agent id — review_claims keys rows by claim_id alone,
    # so a bare "kind" would overwrite another agent's kind card.
    return ReviewClaim(
        id=f"{agent.id}:kind",
        claim_type="kind",
        title=f"Kind: {agent.sort.kind}",
        evidence="",
        inference=_kind_inference(agent.sort.kind, agent.sort.kind_reasoning),
    )


def build_mined_claims(mining_result: Any, agent_id: str) -> list[ReviewClaim]:
    """One claim card per mined initiative/project/task/idea.

    Evidence comes from the miner's source_quote (verbatim anchor).
    Inference is the proposal in plain language.

    Ids are namespaced by agent_id ("{agent_id}:initiative:{i}") because the
    review_claims table keys rows by claim_id alone.
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
                    id=f"{agent_id}:{ctype}:{i}",
                    claim_type=ctype,
                    title=title,
                    evidence=quote,
                    inference=inference.strip(),
                    detail=detail.strip(),
                )
            )
    return claims


# ---------------------------------------------------------------------------
# Atomic insight claims: one moment -> one interpretation + alternatives.
# ---------------------------------------------------------------------------

_INSIGHT_TITLES = {
    "value_inference": "Value read",
    "decision_pattern": "Decision pattern",
    "stance": "Stance",
    "preference": "Preference",
}


def build_insight_claims(insights: list, agent_id: str) -> list[ReviewClaim]:
    """One claim per mined insight, plus one "alternative" claim per genuine
    alternative reading.

    Alternatives are separate claims (id "{agent_id}:insight:{n}:alt:{m}") so
    each is individually respondable — confirming the interpretation never
    silently approves the others. Scope rides on each claim: the interpretive
    jump from moment to pattern is exposed, not smuggled.

    Ids are namespaced by agent_id because the review_claims table keys rows
    by claim_id alone.
    """
    claims: list[ReviewClaim] = []
    for n, ins in enumerate(insights):
        turn_label = f"Turn {ins.turn}" if getattr(ins, "turn", None) else ""
        ctype = getattr(ins, "claim_type", "") or "value_inference"
        if ctype not in _INSIGHT_TITLES:
            ctype = "value_inference"
        scope = getattr(ins, "interpretation_scope", "") or "moment"
        if scope not in SCOPES:
            scope = "moment"
        claims.append(
            ReviewClaim(
                id=f"{agent_id}:insight:{n}",
                claim_type=ctype,
                title=_INSIGHT_TITLES[ctype],
                evidence=getattr(ins, "evidence", "") or "",
                inference=getattr(ins, "interpretation", "") or "",
                detail=turn_label,
                question=getattr(ins, "interpretation_question", "")
                or "Does that sound right to you?",
                scope=scope,
                turn_ref=turn_label,
            )
        )
        for m, alt in enumerate(getattr(ins, "alternatives", None) or []):
            alt_scope = getattr(alt, "scope", "") or "moment"
            if alt_scope not in SCOPES:
                alt_scope = "moment"
            claims.append(
                ReviewClaim(
                    id=f"{agent_id}:insight:{n}:alt:{m}",
                    claim_type="alternative",
                    title="Alternative reading",
                    # Parent shows the quote; repeating it per alternative is noise.
                    evidence="",
                    inference=getattr(alt, "text", "") or "",
                    detail=turn_label,
                    question=getattr(alt, "question", "") or "Could it be this instead?",
                    scope=alt_scope,
                    turn_ref=turn_label,
                )
            )
    return claims
