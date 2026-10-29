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
    # Recurrence claims (a topic returned to across turns -> one pattern).
    "recurrence",
    # Meeting impressions (a seat's first-meeting read-back -> one claim).
    "meeting_impression",
)
# Claim statuses. "rejected" = the user judged the inference wrong.
# "unresolved" = the user actively left it open — first-class, not a verdict,
# and never a silent approval.
# "superseded" = a later run's filing replaced this claim as the standing
# one (Fellowship supersede rule, 2026-10-28). It is NOT a user verdict:
# nothing may write it except the filing chokepoint superseding a prior
# meeting_impression claim, it never writes a training signal, and the
# row is retained — its prior verdict is recorded in its detail (see
# supersede_claim) so history stays inspectable.
CLAIM_STATUSES = ("pending", "accepted", "corrected", "explained", "rejected", "unresolved", "superseded")
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
    "word": "Voice",
    "number": "Logic",
    "image": "Eye",
    "sound": "Ear",
    "body": "Hands",
    "people": "Heart",
    "self": "Compass",
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
    # Strip metadata header (Title/URL/Date lines) that the render job
    # prepends — the evidence should be conversation content, not metadata.
    lines = (text or "").split("\n")
    # Skip leading Title:/URL:/Date: lines, CONVERSATION SUMMARY header,
    # and blank lines within the header block.
    i = 0
    while i < len(lines):
        s = lines[i].strip()
        if s.startswith("Title:") or s.startswith("URL:") or s.startswith("Date:"):
            i += 1
            continue
        if s.startswith("CONVERSATION SUMMARY"):
            i += 1
            continue
        if not s and i < 5:
            # Blank line within the header block
            i += 1
            continue
        break
    text = "\n".join(lines[i:]).strip()
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


def _build_from_llm_moments(agent: ConnectedAgent) -> list[ReviewClaim]:
    """Build ReviewClaims from LLM-identified moments.

    The sorter (sorter_llm.py) asks the LLM to identify specific training
    moments with genuine one-sentence inferences. This converts those
    MomentClaims into ReviewClaims for the review UI.
    """
    claims: list[ReviewClaim] = []
    for i, m in enumerate(agent.sort.moments):
        name = _STRAND_NAME.get(m.strand, m.strand)
        claims.append(
            ReviewClaim(
                id=f"{agent.id}:strand:{m.strand}:llm:{i}",
                claim_type="strand",
                title=f"{name} strand",
                evidence=_trim_quote(m.quote),
                inference=m.inference,
                detail="LLM-identified training moment",
                question="Does that placement sound right? Want to say more about why?",
                scope="moment",
                turn_ref="",
            )
        )
    return claims


def build_strand_claims(agent: ConnectedAgent) -> list[ReviewClaim]:
    """Moment-level strand placement claims: one training moment -> one routing.

    Prefers LLM-identified moments from the sorter (genuine context-aware
    inferences). Falls back to rule-based keyword matching when the sorter
    didn't produce moments (offline mode or older agents).

    Every moment gets its own card — its own verbatim quote, inference,
    and verdict. No whole-conversation blanket summaries, and no dilution:
    one strong moment in a long conversation surfaces on its own.

    Claim ids are namespaced by agent id: the review_claims table keys rows
    by claim_id alone, so un-namespaced ids (e.g. "strand:self:m3") would
    silently overwrite another agent's cards and verdicts.
    """
    # Prefer LLM moments when available — they have genuine inferences,
    # not keyword templates.
    if agent.sort and getattr(agent.sort, 'moments', None):
        return _build_from_llm_moments(agent)

    # Fallback: rule-based keyword matching (offline or legacy).
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
            # Dedupe annotation (project_miner.annotate_existing): the
            # card says plainly that this is already in the workspace
            # and what accepting does instead of duplicating it.
            if getattr(item, "existing_id", None):
                existing_title = getattr(item, "existing_title", None) or title
                if ctype in ("initiative", "project"):
                    inference = (
                        f"This matches work already in your workspace: “{existing_title}”. "
                        "Accepting files the new pieces under it — it won't be created twice."
                    )
                elif ctype == "task":
                    inference = (
                        f"This already exists as a task in your workspace: “{existing_title}”. "
                        "Accepting won't create it twice."
                    )
                else:  # idea
                    inference = (
                        f"This idea is already captured in your workspace: “{existing_title}”. "
                        "Accepting won't capture it twice."
                    )
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


def build_meeting_impression_claim(
    *,
    agent_id: str,
    seat_name: str,
    readback_claim: str,
    readback_response: str,
    strand_keys: list[str],
    run_key: str,
) -> ReviewClaim:
    """The one claim a completed first meeting files: the seat's read-back
    impression, with the user's answer as its verbatim evidence.

    The Weaver's orientation promises the user both texts "wait in your
    review, word for word" — so the card carries them complete, never
    excerpted: the inference IS the full read-back (weave markers are
    markup, not words, and are stripped for display), the evidence is the
    user's answer verbatim, and the detail repeats both in full alongside
    the strands the read-back named, so the filing is inspectable from
    the card alone.

    Claim id: "{agent_id}:impression:{strands}:{run_key}". agent_id is
    the meeting's transcript id ("meeting-{seat}-{keystone}"), so the
    claim is anchored to the meeting it came from. The strand segment
    ("self+people", or "none") is the machine channel the verdict-signal
    routing reads (signals.claim_strands) — the same id-parsing precedent
    strand claims set. run_key discriminates runs: a replay files a NEW
    claim under a new run_key, and filing it SUPERSEDES the archived
    run's claim (see supersede_claim) — the old row is retained with
    its prior verdict recorded, but only the new claim stands.
    """
    from local_ai.conversation.weave import strip_weave_markers

    plain_claim = strip_weave_markers(readback_claim or "").strip()
    keys = [k for k in (strand_keys or []) if k in _STRAND_NAME]
    strand_segment = "+".join(keys) if keys else "none"
    detail_parts: list[str] = []
    if keys:
        names = [_STRAND_NAME[k] for k in keys]
        if len(names) == 1:
            detail_parts.append(f"Heard under the {names[0]} strand.")
        else:
            detail_parts.append(
                f"Heard under the {' and '.join(names)} strands."
            )
    detail_parts.append(f"The read-back, word for word:\n{plain_claim}")
    detail_parts.append(f"Your answer, word for word:\n{readback_response or ''}")
    return ReviewClaim(
        id=f"{agent_id}:impression:{strand_segment}:{run_key}",
        claim_type="meeting_impression",
        title=f"First impression — {seat_name}",
        evidence=readback_response or "",
        inference=plain_claim,
        detail="\n\n".join(detail_parts),
        question="Does that first impression sound right to you?",
        scope="moment",
        turn_ref="",
    )


# ---------------------------------------------------------------------------
# Supersede: a new run's filing replaces prior runs' claims as standing.
# ---------------------------------------------------------------------------

def supersede_claim(claim: ReviewClaim, superseding_claim_id: str) -> ReviewClaim:
    """Return `claim` marked superseded by `superseding_claim_id`.

    The row is NEVER deleted and its verdict is NEVER silently
    overwritten: the prior status is recorded in the detail's
    supersession note, and evidence, inference, title, and user_note
    (the user's own correction/explanation text) are carried over
    untouched. Supersede is a system bookkeeping move on a new filing,
    not a user verdict — it must never write a training signal, and it
    must never be applied to a claim that is already superseded
    (already-superseded input returns unchanged, so re-running the
    supersede pass cannot stack notes or rewrite history).
    """
    if claim.status == "superseded":
        return claim
    note = (
        f"Superseded by a later first meeting (claim {superseding_claim_id}). "
        f"Prior verdict: {claim.status}."
    )
    detail = claim.detail
    if "Superseded by a later first meeting" not in detail:
        detail = f"{detail}\n\n{note}" if detail else note
    return ReviewClaim(
        id=claim.id,
        claim_type=claim.claim_type,
        title=claim.title,
        evidence=claim.evidence,
        inference=claim.inference,
        detail=detail,
        status="superseded",
        user_note=claim.user_note,
        question=claim.question,
        scope=claim.scope,
        turn_ref=claim.turn_ref,
    )


def standing_impression_claim(
    claims: list[ReviewClaim], agent_id: str
) -> ReviewClaim | None:
    """The one standing meeting_impression claim for an agent, or None.

    Standing = filed for this agent, of meeting_impression type, and
    not superseded. Claims arrive oldest-first (AgentStore.get_claims
    order), so the last standing one is the current run's — which is
    also how legacy rows heal: runs filed before the supersede rule
    landed stay standing until the next filing supersedes them all,
    and after that exactly one remains standing.
    """
    prefix = f"{agent_id}:"
    standing = [
        c
        for c in claims
        if c.id.startswith(prefix)
        and c.claim_type == "meeting_impression"
        and c.status != "superseded"
    ]
    return standing[-1] if standing else None


def build_recurrence_claims(patterns: list, agent_id: str) -> list[ReviewClaim]:
    """One claim per mined recurrence (recurrence.py).

    A recurrence is pattern-scope by construction: the claim exists
    because the topic returned across turns. The first evidencing quote
    is the card's anchor; the remaining quotes ride in detail so the
    reviewer can see the return, not just be told about it. The strand
    the recurrence speaks to is named in detail — accepting the claim
    files it as evidence heard under that strand.
    """
    claims: list[ReviewClaim] = []
    for n, p in enumerate(patterns):
        quotes = list(getattr(p, "quotes", None) or [])
        turns = list(getattr(p, "turns", None) or [])
        turn_label = ", ".join(f"Turn {t}" for t in turns)
        meta = []
        strand = getattr(p, "strand", None)
        if strand:
            meta.append(f"Heard under the {strand} strand")
        if turn_label:
            meta.append(f"Returns in {turn_label}")
        detail = " · ".join(meta)
        extra = "\n".join(f"“{q}”" for q in quotes[1:])
        if extra:
            detail = f"{detail}\n{extra}" if detail else extra
        claims.append(
            ReviewClaim(
                id=f"{agent_id}:recurrence:{n}",
                claim_type="recurrence",
                title=f"Keeps coming back to: {getattr(p, 'topic', '') or 'Untitled'}",
                evidence=quotes[0] if quotes else "",
                inference=getattr(p, "inference", "") or "",
                detail=detail,
                question="Does that sound right to you?",
                scope="pattern",
                turn_ref=turn_label,
            )
        )
    return claims
