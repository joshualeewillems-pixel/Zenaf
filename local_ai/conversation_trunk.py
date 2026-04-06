"""
Conversation trunk: classify question kind, select output contract, derive mediation profile.

Single-seat council (Thinking Partner / Zenaf) uses this before prompt construction.
**Trunk = decides how to think** (mediation_move, resolution_mode, ambiguity_type).
**Zenaf = executes in language only** — see ``conversational_partner_trunk_instructions``.
"""
from __future__ import annotations

import re
from typing import Any, Literal, TypedDict, get_args

from local_ai.integration_commit import user_signals_execution_commit

QuestionKind = Literal[
    "state_inventory",
    "missing_fields",
    "next_step",
    "priority_resolution",
    "resolution_collapse",
    "field_update_direct",
    "option_generation",
    "conversation_continuity",
    "user_providing_precision",
    "user_correcting_model",
    "integration_status",
    "integration_confirm",
    "reflective_inquiry",
]

OutputContract = Literal[
    "inventory_only",
    "inventory_then_recommend",
    "three_options_then_lean",
    "confirm_and_integrate",
    "continuity_forward",
    "refine_and_continue",
    "direct_integration",
    "direct_integration_commit",
    "reflective_synthesis",
]

AmbiguityType = Literal[
    "missing_definition",
    "unclear_priority",
    "competing_priorities",
    "unresolved_dependency",
    "ownership_gap",
    "unknown",
]

ResolutionMode = Literal["expand", "compress", "sharpen", "decide"]

MediationMove = Literal[
    "sequence_precision_layers",
    "compress_redundant_work",
    "expose_decision_axis",
    "recommend_first_collapse",
    "resolve_priority",
    "ask_discriminating_question",
    "enumerate",
    "acknowledge_integrate",
    "continue_from_subject",
    "update_and_continue",
    "integration_status_reply",
    "commit_and_confirm",
]


class MediationProfile(TypedDict):
    """Single source of truth for mediation decisions for this turn (trunk-owned)."""

    ambiguity_type: AmbiguityType
    resolution_mode: ResolutionMode
    mediation_move: MediationMove


CaptureConfidence = Literal["high", "medium", "low"]

FieldTarget = Literal[
    "desired_outcome",
    "brief",
    "summary",
    "acceptance_criteria",
    "audience_split",
    "next_step",
    "goal",
    "constraints",
    "notes",
    "title",
    "description",
    "unknown",
]


class CaptureTarget(TypedDict):
    """Trunk-only infer: where user precision likely belongs (confirm_and_integrate turns)."""

    field_target: FieldTarget
    entity_target: str | None
    capture_confidence: CaptureConfidence


class ConversationSubject(TypedDict, total=False):
    """
    Lightweight session thread anchor (client echoes via ``context.conversation_subject``).
    Not VE storage — a conversation-layer snapshot merged each Zenaf turn.
    """

    entity_id: str | None
    entity_type: str | None
    entity_display_name: str | None
    active_field: str
    last_user_contribution: str
    confidence: CaptureConfidence


ScopeType = Literal["subject", "explicit", "system_wide"]

RetrievalMode = Literal["subject", "scoped", "full_inventory"]


class ActiveEntityRef(TypedDict, total=False):
    """Resolved focus for this turn (conversation layer + preflight; no new storage)."""

    entity_id: str | None
    entity_type: str | None
    display_name: str | None
    scope_phrase: str | None


class QueryScopeResolution(TypedDict):
    """
    Strict retrieval priority **before** mediation (single-seat path).
    Drives trunk instructions only; VE snapshot assembly still uses ``classify_question_kind``.
    """

    active_entity: ActiveEntityRef
    scope_type: ScopeType
    retrieval_mode: RetrievalMode


# Visible in trunk block; system prompt references this heading for override behavior.
MEDIATION_CONTROL_HEADING = "**THIS TURN — MEDIATION CONTROL:**"
RETRIEVAL_SCOPE_HEADING = "**THIS TURN — RETRIEVAL SCOPE (mandatory; before mediation):**"
SCOPED_DIGRESSION_DEPTH_HEADING = "**THIS TURN — SCOPED DIGRESSION (mandatory):**"
GLOBAL_EXTERNAL_VOICE_HEADING = "**THIS TURN — USER-FACING VOICE (mandatory; all modes):**"
MODE_LOCK_HEADING = "**THIS TURN — MODE LOCK (mandatory):**"
PROGRESS_BIAS_HEADING = "**THIS TURN — PROGRESS OVER EXPLORATION (mandatory):**"


def _drift_banned_soft_line() -> str:
    return (
        "Phrases and patterns **forbidden in the user-visible reply** (they trigger generic-assistant drift): "
        "“consider …”, “you might …”, “perhaps …”, “would you like …”, “on one hand” / “on the other hand”, "
        "open-ended “what do you think?”, stacked exploratory questions, unprompted coaching or re-analysis.\n"
    )


def _progress_over_exploration_block() -> str:
    """Global bias: move system state forward; do not substitute conversation for progress."""
    return (
        f"\n\n{PROGRESS_BIAS_HEADING}\n\n"
        "- **Default momentum:** **Advance structured reality** — integrate, collapse, offer to persist — **not** open-ended "
        "dialogue for its own sake.\n"
        "- When the user gives **clarity, constraints, structure, refinements, outcomes, or specs** that are **enough to act**, "
        "**prioritize locking that in** (save/tweak offer or the mode’s single forward move) over **re-framing, expanded "
        "analysis, extra questions, or “decision axis” lectures**.\n"
        "- **MUST NOT** fish for more detail when their input is **already sufficient** for integration or the next concrete step.\n"
        "- **MUST NOT** re-explain their message at length or introduce **trade-offs** right after they supplied a **clear "
        "definition**, unless they explicitly asked to explore tensions.\n"
        "- **CAPTURE BIAS:** When they gave a **clear definition / structured outcome / desired end state**, collapse to **one** "
        "line, then: **OK to add** this to **[field from capture target / Context]** for **[entity from Context]** — **or tweak "
        "first?** (No hedge phrasing.)\n"
    )


def _global_external_voice_rules() -> str:
    """Shared Zenaf constraints: internal reasoning may be structured; user-visible reply must not expose it."""
    return (
        f"\n\n{GLOBAL_EXTERNAL_VOICE_HEADING}\n\n"
        "- **Internal vs external:** You may organize your reasoning privately (group gaps, compare constraints **silently**, detect fields). "
        "The **user-visible answer** must be **synthesized, compressed, and natural** — not a framework dump.\n"
        "- **Do not** expose internal structure (no step-by-step narration of your process).\n"
        "- **Do not** enumerate dimensions, lenses, or criteria **by name** in the reply.\n"
        "- **Do not** use “from a … perspective / standpoint” phrasing or consultant-style section headers.\n"
        "- **Do not** list rubrics or frameworks in the answer.\n"
        "- **Write as if speaking** to the user, **not presenting** a slide deck.\n"
    )


def _mode_lock_block(mediation_move: MediationMove, output_contract: OutputContract) -> str:
    """
    Mutually exclusive mode enforcement: forbid drifting into other mediation shapes and generic assistant tone.
    `enumerate` and `expose_decision_axis` get narrow exceptions where their charter requires it.
    """
    banned_soft = _drift_banned_soft_line()
    if mediation_move == "expose_decision_axis":
        return (
            f"\n\n{MODE_LOCK_HEADING}\n\n"
            "- Do **NOT** revert to generic assistant behavior: no facilitator hedging, no unsolicited option menus, "
            "no capture/store prompts, no full inventory dumps unless the user asked for status.\n"
            f"- {banned_soft}"
            "- **This mode (`expose_decision_axis`) allows:** naming **one** main tension or decision axis **when** grounded "
            "in Context and responsive to the ask — still **no** “would you like”, “consider”, “you might”, or three-equal-options "
            "layouts unless the user explicitly sought forks.\n"
            "- **Excludes behaviors from other modes:** integration capture offers, `resolve_priority` tournaments, "
            "`enumerate`-style peer menus unless the ask is truly multi-path, inventory-only listing.\n"
        )

    if mediation_move == "enumerate":
        return (
            f"\n\n{MODE_LOCK_HEADING}\n\n"
            "- Do **NOT** revert to generic assistant behavior outside **this** mode’s charter: the user asked for options — "
            "deliver **only** that, without life-coach hedging or extra facilitation.\n"
            f"- {banned_soft}"
            "- **This mode (`enumerate`) excludes:** acting inventory-only, collapsing to a single priority, integration capture, "
            "problem reframes, exploratory stacks beyond the 2–4 grounded options.\n"
        )

    if output_contract == "direct_integration_commit":
        return (
            f"\n\n{MODE_LOCK_HEADING}\n\n"
            "- **Pending integration affirmed:** This turn is **operational** — the user confirmed a proposed Vision & "
            "Execution write.\n"
            f"- {banned_soft}"
            "- **`commit_and_confirm` excludes:** “Would you like to proceed”, “Shall we integrate”, re-offering save, new "
            "questions, trade-offs, coaching, reframes, or claiming the text is only “in conversation” if Context shows a "
            "**successful DB write** this request.\n"
        )

    if output_contract == "direct_integration":
        return (
            f"\n\n{MODE_LOCK_HEADING}\n\n"
            "- Do **NOT** revert to generic assistant behavior.\n"
            f"- {banned_soft}"
            "- **`integration_status_reply` excludes:** decision-axis talk, prioritization lectures, enumerate menus, "
            "inventory dumps, re-analysis of their specs, exploratory stacks. **One** direct persistence answer + **at most** "
            "**one** OK-to-add / tweak line if Context implies pending substance.\n"
        )

    core = (
        f"\n\n{MODE_LOCK_HEADING}\n\n"
        "- Do **NOT** revert to generic assistant, coach, or open facilitator behavior. "
        "Do **NOT** introduce **trade-off framing**, **multiple peer options**, or **exploratory questioning** "
        "unless **this exact mediation_move** explicitly requires that shape (it does **not** on this turn).\n"
        f"- {banned_soft}"
    )

    if output_contract == "confirm_and_integrate":
        return (
            core
            + "- **`acknowledge_integrate` excludes:** explaining, elaborating, expanding, suggesting next steps beyond "
            "**add vs tweak** fork, listing options, prioritizing, roadmap language, reframing the problem, inventory dumps, "
            "any open-ended prompt beyond **one** closed fork tied to save/tweak.\n"
            "- **Progress lock:** **no** sectional breakdown of their substance, **no** “main decision axis” / tension essay "
            "after they supplied a definition — **collapse** and offer save/tweak only.\n"
        )

    if output_contract == "refine_and_continue":
        return (
            core
            + "- **`update_and_continue` excludes:** option lists, priority tournaments, inventory passes, integration capture, "
            "reframing the problem from scratch, trade-off essays, exploratory follow-ups, **new reasoning layers**.\n"
            "- **Progress lock:** **one** forward concrete step implied by the correction — **no** nested analysis.\n"
        )

    if mediation_move == "resolve_priority":
        return (
            core
            + "- **`resolve_priority` excludes:** listing peer options, naming multiple equal candidates, deferring the call "
            "to the user (“what do you prefer?”), inventory-only answers, capture/store offers, problem re-explanation.\n"
            "- **Progress lock:** after you state **the** priority, **do not** reopen reasoning, second-guess, or pivot to "
            "execution planning essays — hand off **one** move or refinement path only.\n"
        )

    if output_contract == "inventory_only":
        return (
            core
            + "- **Inventory excludes:** “I recommend…”, next-step planning, trade-off menus, priority resolution, option "
            "generation, capture offers, coaching tone.\n"
            "- **Progress lock:** compress gaps only — **do not** turn inventory into exploration, follow-up interviews, or "
            "“what if” threads.\n"
        )

    if output_contract == "continuity_forward":
        return (
            core
            + "- **`continue_from_subject` excludes:** fresh reframes, trade-off essays, option menus, full inventory unless "
            "one fact is needed to resume, generic “where to start” when a subject snapshot exists.\n"
        )

    if mediation_move == "recommend_first_collapse":
        return (
            core
            + "- **`recommend_first_collapse` excludes:** three equal options, enumerate layout, inventory-only listing, "
            "capture prompts, priority-style “what matters most” tournaments beyond **one** primary move.\n"
        )

    if mediation_move == "ask_discriminating_question":
        return (
            core
            + "- **`ask_discriminating_question` excludes:** option menus, trade-off essays, inventory dumps beyond one "
            "compress line, multiple unrelated questions.\n"
        )

    return (
        core
        + "- **Default:** No three-option template, no generic coaching; stay inside the stated mediation_move only.\n"
    )


_NAMED_IN_SCOPE_RE = re.compile(
    r"\bin\s+([A-Za-z][A-Za-z0-9\s'’&/-]{2,80}?)(?=\s*[,.?:!]|\s*$)",
    re.I,
)
_GENERIC_IN_SCOPE_SPANS = frozenset(
    {
        "the system",
        "this idea",
        "that idea",
        "this initiative",
        "that initiative",
        "this project",
        "that project",
        "the pipeline",
        "our pipeline",
        "this pipeline",
        "that pipeline",
    }
)


def _question_has_named_in_scope_phrase(question: str) -> bool:
    """True when the question names a concrete work span after ``in …`` (pipeline, program title, etc.)."""
    q = (question or "").strip()
    if len(q) < 6:
        return False
    m = _NAMED_IN_SCOPE_RE.search(q)
    if not m:
        return False
    span = m.group(1).strip().lower()
    return span not in _GENERIC_IN_SCOPE_SPANS and len(span) >= 3


def _full_system_inventory_signals(lower: str, question_raw: str) -> bool:
    """
    User wants enumeration from live working set / system state — not ideation or trade-offs.
    Excludes continuity phrasing (``what else … discuss``) and named ``in X`` scopes.
    """
    if _question_has_named_in_scope_phrase(question_raw):
        return False
    if "what else" in lower and "discuss" in lower:
        return False
    if "what else" in lower and ("about it" in lower or "about this" in lower):
        return False
    phrases = (
        "what else is there",
        "what else exists",
        "what else do we have",
        "what's in the system",
        "whats in the system",
        "what is in the system",
        "what do we have in the system",
        "everything in the system",
        "everything we have",
        "show me everything we",
        "list what's in",
        "list what is in",
        "list everything",
        "full list of",
        "what needs attention",
        "what requires attention",
        "anything i should know about",
        "anything we should know about",
        "open items across",
        "all open items",
    )
    if any(p in lower for p in phrases):
        return True
    if "what needs work" in lower and not _question_has_named_in_scope_phrase(question_raw):
        return True
    return False


def _agenda_schedule_working_set_signals(lower: str, question_raw: str) -> bool:
    """
    User is asking about their day / agenda / schedule in the sense of **in-app work**, not external calendar.
    Maps to state_inventory without requiring full_system_inventory phrasing (avoids forcing full_inventory scope).
    """
    if _question_has_named_in_scope_phrase(question_raw):
        return False
    phrases = (
        "what's on the schedule",
        "whats on the schedule",
        "what is on the schedule",
        "on the schedule today",
        "on my schedule",
        "on our schedule",
        "schedule today",
        "schedule for today",
        "today's schedule",
        "todays schedule",
        "my schedule today",
        "our schedule today",
        "what's on my agenda",
        "whats on my agenda",
        "what's on the agenda",
        "whats on the agenda",
        "what's on our agenda",
        "whats on our agenda",
        "on the agenda today",
        "what's lined up",
        "whats lined up",
        "what do i have today",
        "what do we have today",
    )
    return any(p in lower for p in phrases)


def _explicit_deictic_work_scope(lower: str) -> bool:
    return any(
        p in lower
        for p in (
            "for this idea",
            "for that idea",
            "about this idea",
            "about that idea",
            "for this initiative",
            "for that initiative",
            "this initiative",
            "that initiative",
            "for this project",
            "for that project",
            "this project",
            "that project",
            "for this task",
            "for that task",
        )
    )


def _active_entity_from_subject(sub: ConversationSubject) -> ActiveEntityRef:
    return {
        "entity_id": sub.get("entity_id"),
        "entity_type": sub.get("entity_type"),
        "display_name": sub.get("entity_display_name"),
    }


def _active_entity_from_ve_focus(vf: dict[str, Any] | None, title: str | None) -> ActiveEntityRef:
    if not vf:
        return {}
    return {
        "entity_id": str(vf["entity_id"]).strip() if vf.get("entity_id") else None,
        "entity_type": str(vf["entity_type"]).strip() if vf.get("entity_type") else None,
        "display_name": (title or "").strip() or None,
    }


def resolve_query_scope(
    *,
    question: str,
    question_kind: QuestionKind,
    conversation_subject: ConversationSubject | None,
    council_preflight_dict: dict[str, Any] | None,
    packet: str | None,
) -> QueryScopeResolution:
    """
    Retrieval priority before mediation (no DB calls here; uses merged subject + council_preflight + packet).

    1. System-wide inventory asks → ``full_inventory``.
    2. Explicit scope in question (named ``in …``, deictic this/that idea) → ``scoped`` (overrides subject).
    3. High-confidence ``conversation_subject`` → ``subject`` anchor.
    4. Else VE focus from preflight → ``scoped``; otherwise open context.
    """
    from local_ai.council_preflight import parse_preflight_from_request

    q = (question or "").strip()
    low = q.lower()
    ctx: dict[str, Any] | None = None
    if isinstance(council_preflight_dict, dict) and council_preflight_dict:
        ctx = {"council_preflight": council_preflight_dict}
    pf = parse_preflight_from_request(ctx, q)
    vf = pf.ve_focus if isinstance(pf.ve_focus, dict) else None
    vtitle = _clean_entity_label(pf.ve_focus_title) or _parse_primary_title_from_packet(packet)

    empty: ActiveEntityRef = {}

    if _full_system_inventory_signals(low, q):
        return QueryScopeResolution(
            active_entity=empty,
            scope_type="system_wide",
            retrieval_mode="full_inventory",
        )

    if _explicit_deictic_work_scope(low) and vf and vf.get("entity_id"):
        ae = _active_entity_from_ve_focus(vf, vtitle)
        return QueryScopeResolution(
            active_entity=ae,
            scope_type="explicit",
            retrieval_mode="scoped",
        )

    if _question_has_named_in_scope_phrase(q):
        m = _NAMED_IN_SCOPE_RE.search(q)
        phrase = (m.group(1).strip() if m else "") or ""
        ae_named: ActiveEntityRef = {"scope_phrase": phrase or None}
        if vf and vf.get("entity_id") and vtitle and phrase:
            pl, tl = phrase.lower(), vtitle.lower()
            if pl in tl or tl in pl or _token_overlap_named_scope(phrase, vtitle):
                ae_named.update(_active_entity_from_ve_focus(vf, vtitle))
        return QueryScopeResolution(
            active_entity=ae_named,
            scope_type="explicit",
            retrieval_mode="scoped",
        )

    subj = conversation_subject
    if (
        subj
        and subj.get("confidence") == "high"
        and question_kind
        not in (
            "user_providing_precision",
            "integration_status",
            "integration_confirm",
            "resolution_collapse",
            "field_update_direct",
        )
        and (subj.get("entity_id") or (subj.get("last_user_contribution") or "").strip())
    ):
        return QueryScopeResolution(
            active_entity=_active_entity_from_subject(subj),
            scope_type="subject",
            retrieval_mode="subject",
        )

    if vf and vf.get("entity_id"):
        return QueryScopeResolution(
            active_entity=_active_entity_from_ve_focus(vf, vtitle),
            scope_type="explicit",
            retrieval_mode="scoped",
        )

    return QueryScopeResolution(
        active_entity=empty,
        scope_type="system_wide",
        retrieval_mode="scoped",
    )


def _token_overlap_named_scope(phrase: str, title: str) -> bool:
    pt = {t for t in re.findall(r"[a-z0-9]{3,}", phrase.lower()) if len(t) >= 3}
    tt = {t for t in re.findall(r"[a-z0-9]{3,}", title.lower()) if len(t) >= 3}
    if not pt or not tt:
        return False
    return len(pt & tt) >= min(2, len(pt))


def _user_providing_precision_signals(q_raw: str) -> bool:
    """True when the user is supplying a definition / field (declarative), not asking for analysis."""
    # Pass 3C: short execution phrases (e.g. "go for it") must run before the length gate below.
    if user_signals_execution_commit(q_raw):
        return True
    q = (q_raw or "").strip()
    lower_head = q.lower()
    # Explicit field target ("put it in brief", "save this to notes", …) — must use confirm_and_integrate
    # even when the line is short or lacks other supply markers.
    if _field_from_placement_phrase(lower_head):
        return True
    if len(q) < 8:
        return False
    lower = lower_head

    # Question-shaped **capture** asks (tool intent): still `user_providing_precision` / confirm_and_integrate.
    if any(
        m in lower
        for m in (
            "record this as the desired outcome",
            "record that as the desired outcome",
            "record this as desired outcome",
            "save this as the desired outcome",
            "save that as the desired outcome",
        )
    ):
        return True
    if ("record this as" in lower or "record that as" in lower) and (
        "desired outcome" in lower or "desired outcomes" in lower or "goal" in lower
    ):
        return True

    if "?" in q:
        ql = lower
        ask_openers = (
            "what ",
            "which ",
            "how ",
            "why ",
            "when ",
            "where ",
            "who ",
            "are we ",
            "is it ",
            "is the ",
            "are the ",
            "can you ",
            "could you ",
            "should we ",
            "do you ",
            "does ",
            "did ",
        )
        # Allow "can you record …" (capture), not "can you explain …" (explore).
        if ql.startswith("can you record") or ql.startswith("could you record"):
            pass
        elif any(ql.startswith(p) for p in ask_openers):
            return False

    if any(
        p in lower
        for p in (
            "i'm not sure",
            "i am not sure",
            "not sure what",
            "don't know what",
            "do not know what",
            "we still need",
            "what we still need",
            "what's the desired",
            "what is the desired",
            "what should the outcome",
            "which outcome",
            "missing an outcome",
            "missing a goal",
        )
    ):
        return False

    if ("the outcome is" in lower or "the outcomes are" in lower) and any(
        x in lower for x in ("unclear", "vague", "not clear", "still fuzzy", "still open", "tbd", "unknown", "isn't clear")
    ):
        return False

    supply_markers = (
        "desired outcomes would be",
        "desired outcome would be",
        "the desired outcomes would be",
        "the desired outcome would be",
        "desired outcomes are",
        "the desired outcomes are",
        "the desired outcome is",
        "desired outcome is",
        "my desired outcome",
        "our desired outcome is",
        "the goal is",
        "our goal is",
        "my goal is",
        "success criteria:",
        "definition of done:",
        "definition of done is",
        "here's the outcome",
        "here is the outcome",
        "the outcome is to",
        "the outcomes are to",
        "the outcome is that",
        "let me clarify",
        "to clarify,",
        "the scope is",
        "our scope is",
        "success for this is",
        "success looks like",
        "i want the homepage",
        "we want the homepage",
        "homepage to always",
        "always show booking",
        "always-visible booking",
        "tech showcase",
        "into an intake funnel",
        "into a funnel",
        "redesign the site",
        "redesign the website",
        "reshape the site",
        "not salesy",
        "live from the heart",
    )
    if any(m in lower for m in supply_markers):
        return True
    # Structured outcome chain (arrows) without a leading question — supplying shape, not asking for analysis.
    if ("→" in q_raw or "->" in lower) and len(q) >= 28:
        if not re.match(
            r"^\s*(what|which|how|why|when|where|who|are|is|can|could|should|do|does|did|will|would)\b",
            lower,
        ):
            return True
    return False


def _integration_status_signals(lower: str) -> bool:
    """User asks whether work was saved / notes updated — needs direct answer, not decision-axis."""
    if "are you sure" in lower:
        return False
    return any(
        p in lower
        for p in (
            "are you updating the notes",
            "are you updating notes",
            "did you update the notes",
            "are the notes updated",
            "are you saving this",
            "are you saving that",
            "did you save this",
            "did you save that",
            "is this saved",
            "was this saved",
            "did this get saved",
            "has this been saved",
            "have you saved",
            "have you recorded",
            "are you recording this",
            "is it recorded",
            "is this recorded",
            "are you persisting",
            "did it persist",
            "are you writing this to",
            "did you write this to",
            "are you updating the record",
        )
    )


def _conversation_continuity_signals(lower: str) -> bool:
    """User wants to resume thread / context, not re-derive from scratch."""
    if any(
        p in lower
        for p in (
            "what do we still need",
            "still need to do",
            "what still needs",
            "what remains to",
            "what's left to",
        )
    ):
        return False
    if "where were we" in lower or "where did we leave" in lower:
        return True
    if "what were we working on" in lower or "what are we working on" in lower:
        return True
    if "remind me what we" in lower or "remind me where we" in lower:
        return True
    if "what did we decide" in lower or "what have we decided" in lower:
        return True
    if "continue" in lower and (
        "previous thread" in lower
        or "the thread" in lower
        or "where we left" in lower
        or "last thread" in lower
    ):
        return True
    if "pick up where" in lower or "pick up from" in lower:
        return True
    if "what else" in lower and (
        "discuss" in lower or "about it" in lower or "about this" in lower
    ):
        return True
    if "resume" in lower and ("thread" in lower or "conversation" in lower):
        return True
    stripped = lower.strip().rstrip(".!?")
    if stripped in ("continue", "go on", "and then"):
        return True
    return False


def _user_correcting_model_signals(lower: str) -> bool:
    """
    User is correcting or refining system understanding — not asking for priority, inventory, or new precision capture.
    Conservative: avoid bare 'instead' and 'what should we do instead'-style asks.
    """
    if re.match(
        r"^\s*what\s+(should|would|can|do)\s+(we|i|you)\s+",
        lower,
    ) and "instead" in lower:
        return False
    if re.search(r"\bno,?\s+actually\b", lower):
        return True
    if re.search(r"\b(we'?ve already|we already) (have|had|got)\b", lower):
        return True
    if re.search(r"\b(there'?s already|there is already|there already is)\b", lower):
        return True
    if "it just needs" in lower:
        return True
    if re.search(r"\bit already exists\b", lower) or re.search(r"\bwe already built\b", lower):
        return True
    if re.search(r"\bit'?s not .{2,120}? it'?s\b", lower):
        return True
    if re.search(r"\bnot quite\b", lower):
        return True
    if re.search(r"\bthat'?s (wrong|not right|not quite right)\b", lower):
        return True
    if re.search(r"\b(i meant|correction:|wait,?\s+no|hold on,?)\b", lower):
        return True
    if re.search(r"^(actually|wait|hold on)[,!.]?\s+", lower):
        return True
    if re.search(r"\binstead of [^.?!\n]{0,80}\b(it'?s|it is|we have|the real|the issue)\b", lower):
        return True
    return False


def _field_update_command_signals(lower: str) -> bool:
    """User directs a concrete field write (not open reflection) — collapse / decide posture."""
    if "put that in" in lower or "put this in" in lower:
        return True
    if re.search(r"\badd\s+(?:that|this|it)\s+to\s+", lower):
        return True
    if re.search(
        r"\badd\s+to\s+(?:the\s+)?(?:notes|description|completion\s*criteria|brief|summary|title)\b",
        lower,
    ):
        return True
    if re.search(
        r"\bupdate\s+(?:the\s+)?(?:notes|description|completion\s*criteria|brief|title)\b",
        lower,
    ):
        return True
    if re.search(r"\b(save|record)\s+(?:that|this|it)\s+to\s+", lower):
        return True
    return False


def _resolution_collapse_signals(lower: str) -> bool:
    """User wants to finalize / lock scope — collapse to one primary move, not open reflection.

    Phrase-based only: avoids compound entity titles like *the finalize website idea* (no ``finalize the``).
    """
    if "nail down" in lower or "nail it down" in lower:
        return True
    solid = (
        "solidify the",
        "solidify our",
        "solidify my",
        "solidify this",
        "solidify these",
        "solidify scope",
        "solidify requirements",
        "to solidify",
        "let's solidify",
        "lets solidify",
        "need to solidify",
        "help me solidify",
        "want to solidify",
    )
    if any(p in lower for p in solid):
        return True
    fin = (
        "finalize the",
        "finalise the",
        "finalize our",
        "finalize my",
        "finalize this",
        "finalize these",
        "finalize requirements",
        "finalize requirement",
        "finalize scope",
        "finalize spec",
        "to finalize",
        "to finalise",
        "let's finalize",
        "lets finalize",
        "let's finalise",
        "lets finalise",
        "need to finalize",
        "want to finalize",
        "help me finalize",
        "trying to finalize",
        "finalizing the",
        "finalising the",
    )
    return any(p in lower for p in fin)


def _priority_resolution_signals(lower: str) -> bool:
    """User asks what matters most / what to do first / where to focus — priority mediation, not generic next_step."""
    return any(
        p in lower
        for p in (
            "what should i do first",
            "what should we do first",
            "what comes first",
            "where should i start first",
            "what matters most",
            "what matters more",
            "most important thing",
            "most important next",
            "biggest priority",
            "real priority",
            "top priority",
            "highest priority",
            "what should i focus",
            "what should we focus",
            "where should i focus",
            "where should we focus",
            "what to focus on",
            "what's the priority",
            "whats the priority",
            "what is the priority",
            "what priority",
            "whats priority",
            "what's priority",
            "priority right now",
            "priority today",
            "which priority",
            "which should i prioritize",
            "which should we prioritize",
            "doing today",
            "we doing today",
            "are we doing",
            "what are we doing",
            "agenda",
            "focus for today",
            "our focus for today",
        )
    )


def _classify_question_kind_impl(question: str) -> QuestionKind:
    """Heuristic question kind from user text (lowercase substring rules)."""
    q_raw = (question or "").strip()
    q = q_raw.lower()
    if not q:
        return "reflective_inquiry"

    if _user_correcting_model_signals(q):
        return "user_correcting_model"

    if _integration_status_signals(q):
        return "integration_status"

    # Named field beats generic field-update collapse — enables deterministic integration targeting.
    if _field_from_placement_phrase(q):
        return "user_providing_precision"

    if _field_update_command_signals(q):
        return "field_update_direct"

    if _priority_resolution_signals(q):
        return "priority_resolution"

    if _resolution_collapse_signals(q):
        return "resolution_collapse"

    # State / introspection on the focused record (not action advice).
    if any(
        p in q
        for p in (
            "synopsis",
            "summary of what",
            "what it already",
            "what's already",
            "whats already",
            "already contains",
            "already has",
            "currently contains",
            "currently has",
            "what exists",
            "what's in this",
            "whats in this",
            "what is in this",
            "read me what",
            "tell me what",
            "what's on this",
            "whats on this",
            "what's filled",
            "whats filled",
            "what is filled",
            "what's associated",
            "whats associated",
            "associated context",
            "current state of",
            "ground truth",
            "actual content",
            "what the idea",
            "what this idea",
            "inventory of this",
            "describe this record",
            "contents of this",
        )
    ):
        return "state_inventory"

    # Explicit action-seeking (check before broad "what" inventory phrases).
    if any(
        p in q
        for p in (
            "what should i do",
            "what should we do",
            "what next",
            "where should i start",
            "how should i proceed",
            "how should we proceed",
            "what to do next",
            "what do you recommend we do",
        )
    ):
        return "next_step"

    if any(
        p in q
        for p in (
            "give me ideas",
            "give me options",
            "give me some options",
            "any ideas",
            "some ideas",
            "brainstorm",
            "options for",
            "list options",
            "different options",
            "ways to ",
            "way to ",
        )
    ) or (" ideas" in q and "?" in q):
        return "option_generation"

    if _full_system_inventory_signals(q, q_raw):
        return "state_inventory"

    if _agenda_schedule_working_set_signals(q, q_raw):
        return "state_inventory"

    if _conversation_continuity_signals(q):
        return "conversation_continuity"

    if _user_providing_precision_signals(q):
        return "user_providing_precision"

    # Field-oriented inventory (subset).
    if any(
        p in q
        for p in (
            "filled out",
            "missing fields",
            "missing field",
            "which fields",
            "which field",
            "what fields",
        )
    ):
        return "missing_fields"

    # Broad status / completeness inventory.
    if any(
        p in q
        for p in (
            "what is missing",
            "what are we missing",
            "what do we have",
            "what do we still need",
            "what we still need",
            "still need to do",
            "still need to",
            "what still needs",
            "still needs to be",
            "incomplete",
            "what's missing",
            "whats missing",
            "what remains",
            "what is left to",
            "what's left to",
        )
    ):
        return "state_inventory"

    if "which" in q and "need" in q:
        return "state_inventory"

    return "reflective_inquiry"


def classify_question_kind(question: str) -> QuestionKind:
    """Heuristic question kind from user text; logs classification for debugging trunk routing."""
    q_raw = (question or "").strip()
    kind = _classify_question_kind_impl(question)
    # Why a phrase landed in reflective_inquiry: no earlier rule matched (e.g. "whats priority" missed "whats the priority").
    print(f"[classify_question_kind] in={q_raw!r} -> {kind}", flush=True)
    return kind


def select_output_contract(kind: QuestionKind) -> OutputContract:
    """Map question kind → response shape (no recommendation leakage for inventory kinds)."""
    if kind in ("state_inventory", "missing_fields"):
        return "inventory_only"
    if kind == "user_providing_precision":
        return "confirm_and_integrate"
    if kind == "user_correcting_model":
        return "refine_and_continue"
    if kind == "integration_status":
        return "direct_integration"
    if kind == "integration_confirm":
        return "direct_integration_commit"
    if kind == "conversation_continuity":
        return "continuity_forward"
    if kind in ("next_step", "priority_resolution", "resolution_collapse", "field_update_direct"):
        return "three_options_then_lean"
    if kind == "option_generation":
        return "three_options_then_lean"
    return "reflective_synthesis"


def derive_mediation_profile(
    question: str,
    question_kind: QuestionKind,
    output_contract: OutputContract,
) -> MediationProfile:
    """
    Decide ambiguity_type, resolution_mode, and mediation_move for this turn.
    Single-seat Zenaf path: call before prompt assembly; do not override downstream.
    """
    _ = (question or "").strip()

    if output_contract == "inventory_only":
        if question_kind == "missing_fields":
            return MediationProfile(
                ambiguity_type="missing_definition",
                resolution_mode="compress",
                mediation_move="compress_redundant_work",
            )
        return MediationProfile(
            ambiguity_type="unclear_priority",
            resolution_mode="compress",
            mediation_move="sequence_precision_layers",
        )

    if output_contract == "confirm_and_integrate":
        return MediationProfile(
            ambiguity_type="unknown",
            resolution_mode="compress",
            mediation_move="acknowledge_integrate",
        )

    if output_contract == "direct_integration_commit":
        return MediationProfile(
            ambiguity_type="unknown",
            resolution_mode="compress",
            mediation_move="commit_and_confirm",
        )

    if output_contract == "direct_integration":
        return MediationProfile(
            ambiguity_type="unknown",
            resolution_mode="compress",
            mediation_move="integration_status_reply",
        )

    if output_contract == "refine_and_continue":
        return MediationProfile(
            ambiguity_type="unknown",
            resolution_mode="compress",
            mediation_move="update_and_continue",
        )

    if output_contract == "continuity_forward":
        return MediationProfile(
            ambiguity_type="unknown",
            resolution_mode="sharpen",
            mediation_move="continue_from_subject",
        )

    if output_contract == "three_options_then_lean":
        if question_kind == "priority_resolution":
            return MediationProfile(
                ambiguity_type="competing_priorities",
                resolution_mode="decide",
                mediation_move="resolve_priority",
            )
        if question_kind in ("next_step", "resolution_collapse", "field_update_direct"):
            return MediationProfile(
                ambiguity_type="unclear_priority",
                resolution_mode="decide",
                mediation_move="recommend_first_collapse",
            )
        if question_kind == "option_generation":
            return MediationProfile(
                ambiguity_type="unclear_priority",
                resolution_mode="expand",
                mediation_move="enumerate",
            )

    if output_contract == "inventory_then_recommend":
        return MediationProfile(
            ambiguity_type="unknown",
            resolution_mode="sharpen",
            mediation_move="expose_decision_axis",
        )

    return MediationProfile(
        ambiguity_type="unknown",
        resolution_mode="sharpen",
        mediation_move="expose_decision_axis",
    )


def _clean_entity_label(raw: str | None) -> str | None:
    if not raw:
        return None
    t = str(raw).strip()
    if not t:
        return None
    low = t.lower()
    if low.startswith("(") or "not provided" in low:
        return None
    return t


def _parse_primary_title_from_packet(packet: str | None) -> str | None:
    """Title line from PRIMARY CONTEXT in the assembled council packet (no new I/O)."""
    from local_ai.council_preflight import PRIMARY_CONTEXT_MARKER

    p = (packet or "").strip()
    if not p or PRIMARY_CONTEXT_MARKER not in p:
        return None
    i = p.find(PRIMARY_CONTEXT_MARKER)
    chunk = p[i : i + 12000]
    for line in chunk.splitlines():
        s = line.strip()
        if s.startswith("- Title:"):
            return _clean_entity_label(s[8:].strip())
    return None


def _placement_word_to_field_target(raw: str) -> FieldTarget | None:
    w = (raw or "").lower().strip().replace(" ", "")
    if w == "brief":
        return "brief"
    if w == "notes":
        return "notes"
    if w == "description":
        return "description"
    if w == "title":
        return "title"
    if w == "summary":
        return "summary"
    if w == "goal":
        return "goal"
    if "desiredoutcome" in w or (w.startswith("desired") and "outcome" in w):
        return "desired_outcome"
    if w.startswith("completion") and "criteria" in w:
        return "acceptance_criteria"
    if w in ("nextstep", "nextsteps") or (w.startswith("next") and "step" in w):
        return "next_step"
    return None


def _field_from_placement_phrase(lower: str) -> FieldTarget | None:
    """User explicitly names the VE field (verb + preposition + field) — authoritative for capture."""
    # Common typo: "but it in brief" / casual "it in brief"
    if re.search(r"\b(?:but|put)\s+it\s+in\s+(?:the\s+)?brief\b", lower):
        return "brief"
    if re.search(r"\bit\s+in\s+(?:the\s+)?brief\b", lower):
        return "brief"
    word = (
        r"(brief|notes|description|title|summary|goal|completion\s*criteria|desired\s*outcome|next\s*steps?)"
    )
    # "use this for the brief field" — distinct from ``use the brief`` / ``use brief`` above
    m_this_for = re.search(rf"\buse\s+this\s+for\s+(?:the\s+)?{word}(?:\s+field)?\b", lower)
    if m_this_for:
        ft = _placement_word_to_field_target(m_this_for.group(1))
        if ft:
            return ft
    if re.search(r"\buse\s+for\s+(?:the\s+)?brief\b", lower):
        return "brief"
    seq: tuple[tuple[str, int], ...] = (
        (rf"\bput\s+(?:it|this|that)\s+in\s+(?:the\s+)?{word}\b", 1),
        (rf"\b(?:place|stick)\s+(?:it|this|that)\s+in\s+(?:the\s+)?{word}\b", 1),
        (rf"\badd\s+(?:it|this|that)\s+to\s+(?:the\s+)?{word}\b", 1),
        (rf"\b(?:save|record)\s+(?:it|this|that)\s+to\s+(?:the\s+)?{word}\b", 1),
        (rf"\binto\s+(?:the\s+)?{word}\b", 1),
        (rf"\buse\s+(?:the\s+)?{word}\b(?:\s+field)?\b", 1),
    )
    for pat, group_idx in seq:
        m = re.search(pat, lower)
        if m:
            ft = _placement_word_to_field_target(m.group(group_idx))
            if ft:
                return ft
    return None


def _field_from_user_text(lower: str) -> FieldTarget | None:
    placed = _field_from_placement_phrase(lower)
    if placed:
        return placed
    # Brief edits (UI label **Brief**) — phrases that do not use "the brief" or placement verbs.
    if re.search(r"\b(?:change|update|set|edit|refine|fix|rewrite|expand)\s+(?:the\s+|this\s+)?brief\b", lower):
        return "brief"
    if re.search(r"\b(?:change|update)\s+this\s+brief\b", lower):
        return "brief"
    if re.search(r"\bbrief\s+to\s+(?:say|state|read|be|include)\b", lower):
        return "brief"
    if re.search(r'\bin\s+["\']brief["\']', lower):
        return "brief"
    if "this brief" in lower and re.search(
        r"\b(?:change|update|fix|refine|edit|make)\b",
        lower,
    ):
        return "brief"
    if re.search(r"\b(?:update|change)\s+the\s+brief\b", lower):
        return "brief"
    if "desired outcome" in lower or "desired outcomes" in lower:
        return "desired_outcome"
    if "acceptance criteria" in lower or "acceptance criterion" in lower:
        return "acceptance_criteria"
    if "success criteria" in lower or "definition of done" in lower:
        return "acceptance_criteria"
    if "completion criteria" in lower or "completion criterion" in lower:
        return "acceptance_criteria"
    if "audience" in lower and ("split" in lower or "segment" in lower):
        return "audience_split"
    if "constraint" in lower or "constraints" in lower:
        return "constraints"
    if "next step" in lower or "next steps" in lower:
        return "next_step"
    if (
        "the brief" in lower
        or lower.startswith("brief:")
        or lower.startswith("the brief ")
        or re.search(r"\brefine\s+the\s+brief\b", lower)
    ):
        return "brief"
    if "summary" in lower and (
        "the summary" in lower or lower.startswith("summary:") or "topic summary" in lower
    ):
        return "summary"
    if "our goal is" in lower or "my goal is" in lower or "the goal is" in lower:
        return "goal"
    return None


def _field_from_ve_focus(vf: dict[str, Any]) -> FieldTarget | None:
    fk = str(vf.get("field_key") or "").lower().replace(" ", "").replace("-", "")
    fl = str(vf.get("field_label") or "").lower()
    blob = fk + " " + fl
    if "desired" in blob and "outcome" in blob:
        return "desired_outcome"
    if "acceptance" in blob or "criteria" in blob:
        return "acceptance_criteria"
    if "brief" in blob:
        return "brief"
    if "summary" in blob:
        return "summary"
    if "audience" in blob:
        return "audience_split"
    if "constraint" in blob:
        return "constraints"
    if "next" in blob and "step" in blob:
        return "next_step"
    if "goal" in blob:
        return "goal"
    # Initiative: `notes` column → UI "Diagnostics / admin notes"
    if fk == "notes" or "diagnostics" in fl or ("admin" in fl and "notes" in fl):
        return "notes"
    return None


def field_display_label_for_capture(entity_type: str | None, field_target: str) -> str:
    """User-visible field phrase for integration copy; schema-backed only — never trunk tokens."""
    from local_ai.vision_execution.ve_integration_schema import (
        normalize_trunk_token_to_storage_key,
        ui_label_for_storage_key,
    )

    et = (entity_type or "").strip().lower()
    ft = (field_target or "").strip().lower()
    if not ft or ft == "unknown":
        return "this detail"
    if not et:
        return "this detail"
    sk = normalize_trunk_token_to_storage_key(et, ft)
    if sk:
        ul = ui_label_for_storage_key(et, sk)
        if ul:
            return ul
    return "this detail"


_KNOWN_FIELDS: frozenset[str] = frozenset(get_args(FieldTarget))


def _active_field_phrase(active_field: str, *, entity_type: str | None = None) -> str:
    if active_field in _KNOWN_FIELDS:
        return field_display_label_for_capture(entity_type, active_field)
    return "this detail"


def derive_capture_target(
    question: str,
    *,
    packet: str | None = None,
    council_preflight_dict: dict[str, Any] | None = None,
) -> CaptureTarget:
    """
    Infer field + entity for integration prompts. Only meaningful for ``user_providing_precision`` /
    ``confirm_and_integrate``; uses question text, optional preflight JSON, and PRIMARY Title in packet.
    """
    from local_ai.council_preflight import parse_preflight_from_request

    ctx: dict[str, Any] | None = None
    if isinstance(council_preflight_dict, dict) and council_preflight_dict:
        ctx = {"council_preflight": council_preflight_dict}
    pf = parse_preflight_from_request(ctx, question or "")
    lower = (question or "").strip().lower()

    vf = pf.ve_focus if isinstance(pf.ve_focus, dict) else None
    field_pf = _field_from_ve_focus(vf) if vf else None
    field_user = _field_from_user_text(lower)

    if field_user:
        field_target: FieldTarget = field_user
    elif field_pf:
        field_target = field_pf
    else:
        field_target = "unknown"

    ent_pf = _clean_entity_label(pf.ve_focus_title)
    ent_pkt = _parse_primary_title_from_packet(packet)
    entity_target = ent_pf or ent_pkt

    conflict = bool(field_user and field_pf and field_user != field_pf)

    if conflict:
        capture_confidence: CaptureConfidence = "medium"
    elif entity_target and field_target != "unknown":
        capture_confidence = "high"
    elif entity_target or field_target != "unknown":
        capture_confidence = "medium"
    else:
        capture_confidence = "low"

    return CaptureTarget(
        field_target=field_target,
        entity_target=entity_target,
        capture_confidence=capture_confidence,
    )


def parse_conversation_subject(raw: Any) -> ConversationSubject | None:
    """Parse client echo from ``context.conversation_subject`` (JSON object)."""
    if not isinstance(raw, dict):
        return None
    eid = raw.get("entity_id")
    et = raw.get("entity_type")
    edn = raw.get("entity_display_name")
    af = raw.get("active_field")
    luc = raw.get("last_user_contribution")
    conf = raw.get("confidence")
    if conf not in ("high", "medium", "low"):
        conf = "low"
    if (
        not eid
        and not (isinstance(luc, str) and luc.strip())
        and not af
        and not edn
    ):
        return None
    subj: ConversationSubject = {
        "active_field": str(af).strip() if af else "unknown",
        "last_user_contribution": (str(luc) if luc else "")[:4000],
        "confidence": conf,
    }
    if eid:
        subj["entity_id"] = str(eid).strip()
    if et:
        subj["entity_type"] = str(et).strip()
    if edn:
        subj["entity_display_name"] = str(edn).strip()
    return subj


def conversation_subject_to_json(subject: ConversationSubject) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k in (
        "entity_id",
        "entity_type",
        "entity_display_name",
        "active_field",
        "last_user_contribution",
        "confidence",
    ):
        v = subject.get(k)
        if v is None or v == "":
            continue
        out[k] = v
    return out


def merge_conversation_subject(
    *,
    previous: ConversationSubject | None,
    question: str,
    question_kind: QuestionKind,
    output_contract: OutputContract,
    capture_target: CaptureTarget | None,
    council_preflight_dict: dict[str, Any] | None,
    packet: str | None,
) -> ConversationSubject | None:
    """
    Merge prior client echo with this turn's question, capture target (integration), and VE/packet hints.
    Returns None when there is nothing to persist.
    """
    from local_ai.council_preflight import parse_preflight_from_request

    ctx: dict[str, Any] | None = None
    if isinstance(council_preflight_dict, dict) and council_preflight_dict:
        ctx = {"council_preflight": council_preflight_dict}
    pf = parse_preflight_from_request(ctx, question or "")
    vf = pf.ve_focus if isinstance(pf.ve_focus, dict) else None
    peid = str(vf["entity_id"]).strip() if vf and vf.get("entity_id") else None
    pet = str(vf["entity_type"]).strip() if vf and vf.get("entity_type") else None
    ptitle = _clean_entity_label(pf.ve_focus_title) or _parse_primary_title_from_packet(packet)

    base: dict[str, Any] = {}
    if previous:
        base.update(dict(previous))

    prev_eid = base.get("entity_id")
    if peid and prev_eid and str(prev_eid) != str(peid):
        base = {
            "entity_id": peid,
            "entity_type": pet,
            "entity_display_name": ptitle,
            "active_field": "unknown",
            "last_user_contribution": "",
            "confidence": "medium",
        }
    else:
        if peid:
            base["entity_id"] = peid
        if pet:
            base["entity_type"] = pet
        if ptitle:
            base["entity_display_name"] = ptitle

    if question_kind == "user_providing_precision" and capture_target:
        base["last_user_contribution"] = (question or "").strip()[:4000]
        ft = capture_target.get("field_target")
        if ft and ft != "unknown":
            base["active_field"] = ft
            base["confidence"] = capture_target["capture_confidence"]
            et_cap = capture_target.get("entity_target")
            if et_cap:
                base["entity_display_name"] = et_cap

    if question_kind == "user_correcting_model":
        base["last_user_contribution"] = (question or "").strip()[:4000]
        if base.get("entity_id") or peid:
            base["confidence"] = "high"
        elif base.get("confidence") not in ("high", "medium", "low"):
            base["confidence"] = "medium"

    if (
        question_kind not in ("user_providing_precision", "user_correcting_model")
        and vf
        and str(base.get("active_field") or "unknown") == "unknown"
    ):
        hinted = _field_from_ve_focus(vf)
        if hinted:
            base["active_field"] = hinted

    if not base.get("active_field"):
        base["active_field"] = "unknown"

    if base.get("confidence") not in ("high", "medium", "low"):
        has_body = bool((base.get("last_user_contribution") or "").strip())
        if base.get("entity_id") and has_body:
            base["confidence"] = "high"
        elif base.get("entity_id") or has_body:
            base["confidence"] = "medium"
        else:
            base["confidence"] = "low"

    eid_final = base.get("entity_id")
    luc_final = (base.get("last_user_contribution") or "").strip()
    if not eid_final and not luc_final:
        return None

    out: ConversationSubject = {
        "active_field": str(base.get("active_field") or "unknown"),
        "last_user_contribution": str(base.get("last_user_contribution") or "")[:4000],
        "confidence": base["confidence"],
    }
    if base.get("entity_id"):
        out["entity_id"] = str(base["entity_id"])
    if base.get("entity_type"):
        out["entity_type"] = str(base["entity_type"])
    if base.get("entity_display_name"):
        out["entity_display_name"] = str(base["entity_display_name"])
    return out


def _conversation_subject_block(subject: ConversationSubject | None) -> str:
    if not subject:
        return ""
    conf = subject.get("confidence") or "low"
    excerpt = (subject.get("last_user_contribution") or "")[:700]
    return (
        f"\n\n**CONVERSATION SUBJECT (session; client may echo as context.conversation_subject on the next turn):**\n"
        f"- entity_id={subject.get('entity_id')!r}\n"
        f"- entity_type={subject.get('entity_type')!r}\n"
        f"- entity_display_name={subject.get('entity_display_name')!r}\n"
        f"- active_field={subject.get('active_field')!r}\n"
        f"- confidence={conf!r}\n"
        f"- last_user_contribution_excerpt={excerpt!r}\n"
        "- If confidence is **high**, **continue from this thread** — do not re-derive the problem from scratch or "
        "erase the user's prior precision unless Context **clearly** contradicts this snapshot.\n"
    )


def _query_scope_instruction_block(scope: QueryScopeResolution | None) -> str:
    if not scope:
        return ""
    st = scope["scope_type"]
    rm = scope["retrieval_mode"]
    ae = scope["active_entity"]
    body = (
        f"\n\n{RETRIEVAL_SCOPE_HEADING}\n"
        f"- scope_type={st!r}, retrieval_mode={rm!r}\n"
        f"- active_entity: "
        f"entity_id={ae.get('entity_id')!r}, entity_type={ae.get('entity_type')!r}, "
        f"display_name={ae.get('display_name')!r}, scope_phrase={ae.get('scope_phrase')!r}\n"
    )
    if rm == "full_inventory":
        body += (
            "- **Semantic bridge:** The Vision Execution **working set** in Context is the user’s **in-product** work "
            "queue — tasks, projects, ideas, and initiatives. Treat **schedule**, **agenda**, **today**, and **what’s on "
            "the plate** as referring to this block unless they explicitly mean an external calendar (none is supplied).\n"
            "- **Primary job:** Treat this as a **system-state listing** turn. Use **only** items, rows, gaps, and "
            "status language already present in Context (Vision Execution working set, scoped block if present, "
            "PRIMARY, developmental lens). **MUST** ground in what exists — prefer a **compressed summary** by category "
            "unless the user asked to **list everything** or enumerate verbatim; **do not** invent net-new "
            "ideas, brainstorm, frame abstract trade-offs, or expand into “here are three directions.”\n"
            "- If the working set is empty or thin, say so plainly; **do not** fabricate work items.\n"
        )
    elif rm == "subject" and st == "subject":
        body += (
            "- **Primary job:** **Conversation subject (high confidence) is the anchor** for what “we” refer to — "
            "prefer it over a generic browse of unrelated items in the working set unless the user question **clearly** "
            "names a different object or the snapshot is contradicted by authoritative Context.\n"
            "- **Do not** replace this anchor with generic facilitation or fresh problem reframing.\n"
        )
    elif rm == "scoped" and st == "explicit":
        body += (
            "- **Primary job:** The user narrowed scope in **this question** (named pipeline / deictic this-that / "
            "VE focus alignment). Inventory, assess, or answer **within that span only**; "
            "**do not** pull in unrelated ideas from the wider working set unless needed to resolve the named scope.\n"
        )
    else:
        body += (
            "- **Semantic bridge:** When Context includes a Vision Execution **working set** snapshot, that is the user’s "
            "**in-product** backlog — **tasks, projects, agenda, and schedule** in this app. It is **not** an external "
            "calendar; use it to answer “what’s on today / the schedule / the plate” unless the question clearly excludes it.\n"
            "- **Primary job:** Use Context as assembled (runtime + PRIMARY + working set). "
            "Do not invent structure or items absent from Context.\n"
        )
    return body


def _scoped_digression_depth_block() -> str:
    """User chose a focused entity (chip); unlock granular, PRIMARY-grounded replies."""
    return (
        f"\n\n{SCOPED_DIGRESSION_DEPTH_HEADING}\n"
        "- The user **narrowed** this thread to a specific entity (scoped digression). Treat that as **high investment**.\n"
        "- Give **granular**, PRIMARY-grounded detail, field edits, and next steps for **that** entity; **do not** re-summarize "
        "the whole working set unless the question requires it.\n"
    )


def _entity_grounding_scope_continuity_block(
    packet: str | None,
    council_preflight_dict: dict[str, Any] | None,
) -> str:
    """Mandatory Zenaf rules when a focused record exists: anchor on PRIMARY, scope lock, continuity, no protocol leakage."""
    from local_ai.council_preflight import PRIMARY_CONTEXT_MARKER, parse_preflight_from_request

    p = (packet or "").strip()
    has_primary = bool(p and PRIMARY_CONTEXT_MARKER in p)

    entity_type = ""
    if isinstance(council_preflight_dict, dict) and council_preflight_dict:
        ctx = {"council_preflight": council_preflight_dict}
        pf = parse_preflight_from_request(ctx, "")
        vf = pf.ve_focus if isinstance(pf.ve_focus, dict) else None
        if vf:
            entity_type = str(vf.get("entity_type") or "").strip().lower()
    if not entity_type and has_primary:
        m = re.search(r"(?m)^-\s*Type:\s*(\w+)", p)
        if m:
            entity_type = m.group(1).strip().lower()

    if not has_primary and not entity_type:
        return ""

    parts: list[str] = [
        "\n\n**ENTITY GROUNDING + SCOPE (mandatory when focus / PRIMARY exists):**\n",
    ]
    if has_primary:
        parts.append(
            "- **Anchor first:** Before opinions, next steps, or field advice, **name or briefly quote** the PRIMARY record’s "
            "real **Title** and any **non-empty** field lines under PRIMARY CONTEXT. **Do not** treat fields as blank or "
            "invent “missing fields” / generic task titles that contradict PRIMARY.\n"
            "- **UI field truth:** When guiding “what to fill” or walking through the form, use **only** names from "
            "**UI FIELD SCHEMA** (in PRIMARY) and the non-empty bullets above. **Do not** invent fields (e.g. **Expanded description** "
            "on initiatives/projects/tasks). Colloquial “description” → **Brief** (initiative/project) or **Description** (task).\n"
            "- **State → sufficiency → move:** Lead with what PRIMARY shows, then **judge whether the setup is already enough** "
            "for the user’s stated goal (including role they describe in-thread). **Do not** default to “expand the brief” when "
            "a minimal or catch-all role is valid; then offer **concrete moves** (e.g. mark Active, optional guardrails, or "
            "confirm as-is). Only then note real gaps.\n"
            "- **Anti-loop:** If the user already clarified intent or asked you to apply their wording, **advance** — do not "
            "repeat the same expansion prescription.\n"
            "- **State vs action:** If the user asks what exists / what’s filled / summarize this record → answer **only** "
            "from PRIMARY + Context. If they ask what to write / how to improve / suggest intent → reason from those same lines.\n"
        )
    elif entity_type:
        parts.append(
            f"- **Focus:** Council preflight points at a **{entity_type}** record — stay aligned with that object; "
            "**do not** substitute a different row or invented placeholder title.\n"
        )

    if entity_type == "idea":
        parts.append(
            "- **Scope lock (idea):** PRIMARY is an **idea** row. Use **idea-level** vocabulary (intent, summary, notes, "
            "desired outcome). **Do not** reframe as a generic **task** workflow, initiative rollout, or unrelated "
            "working-set item unless the user explicitly widens scope.\n"
        )
    elif entity_type == "initiative":
        parts.append(
            "- **Scope lock (initiative):** PRIMARY is an **initiative** row. Use real surfaces: **Brief**, **Owner**, "
            "**Status**, **Source idea**, **Risks** / **Kill criteria**, **Decision fields** (after evaluation), "
            "**Execution steps** (checklist), **Diagnostics / admin notes** (the `notes` column — not shown as “Notes” in UI). "
            "**Do not** call checklist work a generic **Next steps** text field.\n"
            "- **Initiative + Draft:** Exiting Draft may require **role clarity**, not a longer brief. If the user defines "
            "the role, prefer **status / guardrails / confirm** over endless description expansion.\n"
        )
    elif entity_type in ("task", "project"):
        parts.append(
            f"- **Scope lock ({entity_type}):** PRIMARY is a **{entity_type}** record. Match vocabulary to that layer; "
            "**do not** silently reframe as a different entity type unless asked.\n"
        )

    parts.append(
        "- **Conversation continuity:** Continue this thread’s trajectory. **Do not** reset with generic-assistant openers "
        "such as “it seems you want”, “you might be looking to”, “this could involve”, or “let me help you understand the problem”. "
        "Collaborate from what Context already shows.\n"
        "- **No protocol leakage:** Never echo internal parser instructions, bracket-tag requirements, or placeholder contract text "
        "to the user.\n"
    )
    return "".join(parts)


def _continuity_executor(subject: ConversationSubject | None) -> str:
    base = (
        "- **Continuity mode (`continuity_forward`):** The user asked to **resume** the thread — not restart analysis.\n"
        "- **MUST NOT** re-list already resolved items, ask them to redefine outcomes they already stated, produce "
        "generic “where should we start” prompts when a subject snapshot exists, introduce trade-offs, option menus, "
        "exploratory stacks, or capture/store flows.\n"
    )
    if (
        subject
        and subject.get("confidence") == "high"
        and (subject.get("last_user_contribution") or "").strip()
    ):
        dn = subject.get("entity_display_name") or "this item"
        af = _active_field_phrase(
            str(subject.get("active_field") or "unknown"),
            entity_type=str(subject.get("entity_type") or "").strip() or None,
        )
        luc = (subject.get("last_user_contribution") or "").strip()
        snippet = luc if len(luc) <= 500 else luc[:497] + "…"
        base += (
            f"- **Thread anchor (high):** Work in scope: **{dn}**; field lens: **{af}**. Last user substance "
            f"(paraphrase in your voice, stay faithful): {snippet!r}\n"
            "- **MUST** reply with **one short recap** (what was settled) + **one forward move** (next decision or layer) "
            "— still grounded in Context.\n"
        )
    elif subject and subject.get("confidence") in ("high", "medium") and subject.get("entity_id"):
        dn = subject.get("entity_display_name") or "the focused entity"
        base += (
            f"- **Thread anchor (medium):** Entity **{dn}** — briefly recap what Context + subject imply. "
            "**If** a single missing piece blocks progress, end with **one** tight question; **otherwise** a short forward "
            "hook or statement is enough — **not** open-ended facilitation.\n"
        )
    else:
        base += (
            "- **No strong subject snapshot.** Say the prior thread is not in view; re-anchor from PRIMARY / Context. "
            "**Only** end with a question if you are **genuinely blocked**; otherwise offer a concise next move or hook.\n"
        )
    return base


def _mediation_control_block(profile: MediationProfile) -> str:
    base = (
        f"{MEDIATION_CONTROL_HEADING}\n\n"
        "The trunk has determined:\n"
        f"- ambiguity_type={profile['ambiguity_type']!r}\n"
        f"- resolution_mode={profile['resolution_mode']!r}\n"
        f"- mediation_move={profile['mediation_move']!r}\n\n"
        "You MUST follow this mediation approach.\n\n"
    )
    if profile["mediation_move"] == "acknowledge_integrate":
        base += (
            "When `mediation_move` = `acknowledge_integrate`:\n"
            "- You are in **capture mode**, not thinking mode — behave like a **tool recording input**, not a guide.\n"
            "- **Do not** interpret, expand, analyze, narrate trade-offs, or continue the conversation beyond capture.\n"
            "- **Do** acknowledge briefly and offer **store vs refine** only (see executor shape).\n\n"
        )
    if profile["mediation_move"] == "update_and_continue":
        base += (
            "When `mediation_move` = `update_and_continue`:\n"
            "- The user is **correcting or refining** what the system assumed — **not** opening a new problem or asking for inventory.\n"
            "- **Internally** fold the correction into your model of Context + thread; **do not** restart from scratch or "
            "re-run broad mediation.\n"
            "- **Do not** reintroduce trade-offs unless they explicitly asked for them.\n\n"
        )
    if profile["mediation_move"] == "integration_status_reply":
        base += (
            "When `mediation_move` = `integration_status_reply`:\n"
            "- The user asks whether state was **saved / recorded / updated**. Answer **directly** from Context; **no** "
            "decision-axis or priority lecture.\n"
            "- **One** optional **OK to add / tweak** line if pending substance is obvious from Context.\n\n"
        )
    if profile["mediation_move"] == "commit_and_confirm":
        base += (
            "When `mediation_move` = `commit_and_confirm`:\n"
            "- The user **affirmed** a pending save. **Do not** converse, clarify, or re-pitch integration — report the "
            "**integration result** from Context in **≤2 short sentences** only.\n\n"
        )
    base += (
        "Do NOT default to generic patterns (e.g. three options) unless the mediation_move "
        "explicitly calls for expansion (`enumerate`). For `acknowledge_integrate`, **do not** "
        "mediate or analyze — confirm and offer integrate/refine only. For `continue_from_subject`, "
        "resume the thread — brief recap, then forward motion. For `update_and_continue`, "
        "acknowledge the correction, state the updated understanding, then **one** forward move — no template dump. "
        "For `integration_status_reply`, answer persistence **directly** — no decision-axis. "
        "For `commit_and_confirm`, **confirm save outcome only** — no questions.\n\n"
        "Your job is to execute the mediation, not choose it."
    )
    return base


def _aspiration_recall_snippet_threeish() -> str:
    return (
        "\n- **Aspiration (internal vs external):** Internally, extract a **relevant** signal from the aspiration block "
        "only if it sharpens the move. **Externally:** weave **at most one sentence** into the **same** continuous reply "
        "— **no** separate aspiration paragraph or header, **no** abstract philosophy or “north star” essays. Use "
        "concrete phrases from the block when you weave; skip entirely if relevance is weak."
    )


def _aspiration_recall_snippet_reflective() -> str:
    return (
        "\n- **Aspiration (internal vs external):** Same rule as above — internally pick a sharp parallel if any; "
        "externally **one woven sentence max** in the main voice, no labeled aspiration block, no generic worldview talk."
    )


def _secondary_compression_bullet() -> str:
    """Lightweight expression pass: unify repeated gap wording; no new facts; mediation unchanged."""
    return (
        "\n- **Secondary compression (expression only):** When several lines reflect the **same underlying gap** "
        "(e.g. the same missing outcome, field, or definition), **collapse** them into **one** statement — name the "
        "core gap once, then note briefly where it shows up (e.g. “across A, B, and C” or “in these items: …”). "
        "**Do not** repeat the same phrasing as separate peer bullets. Use **only** Context; **do not** infer new work "
        "or missing items."
    )


def _confirm_integrate_executor(
    capture: CaptureTarget,
    conversation_subject: ConversationSubject | None = None,
) -> str:
    ft = capture["field_target"]
    ent = capture["entity_target"]
    conf = capture["capture_confidence"]
    subj_et = str(conversation_subject.get("entity_type") or "").strip() if conversation_subject else ""
    human = field_display_label_for_capture(subj_et or None, str(ft))
    ent_disp = ent or "the focused item in Context"

    base = (
        "- **Integration mode (`confirm_and_integrate` / `acknowledge_integrate`) — STRICT:** **Internal:** detect field/entity; "
        "decide offer-to-save vs refine fork. **External:** tool-like **proposed capture** only — **no database write** on "
        "this turn unless Context includes **INTEGRATION COMMITTED** from the server.\n"
        "- **Allowed (external):** at most **2 sentences** total; **~40 words max**; **one** short acknowledgment + **one** optional "
        f"precise reference to **{human}** / **{ent_disp}** + **one** closed fork (save vs tweak only — **not** open-ended).\n"
        "- **MUST NOT (external):** explain, expand, interpret, suggest next steps beyond the save/tweak fork, list options, "
        "prioritize, reframe the problem, quote or **restate the user’s full input**, add strategy/roadmap language, multiple "
        "bullets, or exploratory / coaching questions.\n"
        "- **MUST NOT** introduce **new concepts** not required to name the field/entity and the capture ask.\n"
        "- **MUST NOT** break their substance into **sections**, **subsections**, or a **mini-outline** — **one** collapsed "
        "acknowledgment only.\n"
        "- **MUST NOT** use **decision-axis** / **tension** / **balancing** language — this mode is **integrate**, not analyze.\n"
        "- **MUST NOT** say you **already recorded**, **saved**, **added**, **locked in**, or past-tense persistence claims. "
        f"Use a **direct offer** (no “would you like”, no “consider”): e.g. “**OK to add** this to **{human}** for **{ent_disp}** "
        "— **or tweak first?**”\n"
        "- **MUST NOT** use “Shall I finalize”, “Shall I proceed”, “Shall we proceed”, “Would you like to proceed”, "
        "or similar **meta-confirmation** phrases — the fork is **save vs tweak**, not a second approval pass.\n"
    )

    cap = (
        f"\n**CAPTURE TARGET (trunk infer only; use **one short phrase** for field + entity — do not read raw keys aloud; "
        f"do **not** replay the user message):**\n"
        f"- field_target={ft!r}\n"
        f"- entity_target={ent!r}\n"
        f"- capture_confidence={conf!r}\n"
    )

    if conf == "high":
        cap += (
            f"- **Fork shape:** **Offer only:** “**OK to add** this to **{human}** for **{ent_disp}** — **or tweak first?**” "
            "**No** “would you like”, **no** past-tense save claims.\n"
        )
    elif conf == "medium":
        if ent:
            cap += (
                f"- **Fork shape:** Offer to **add**/**record** as **{human}** for **{ent}**, or ask if a **different** field — "
                "**one** short question. **No** “saved” language.\n"
            )
        else:
            cap += (
                f"- **Fork shape:** Offer to **add**/**record** under **{human}** — **one** question to confirm field. "
                "**No** narrative.\n"
            )
    else:
        cap += (
            "- **Fork shape (low confidence):** Offer to **add** to **notes** (or closest neutral place Context implies) "
            "or refine first — **one** question. **Do not** invent titles or imply persistence.\n"
        )

    return base + cap


def _confirm_integrate_executor_commit_intent(
    capture: CaptureTarget,
    conversation_subject: ConversationSubject | None = None,
) -> str:
    """
    User already approved applying text from the thread — emit draft for pending_integration, no second ask.
    """
    ft = capture["field_target"]
    ent = capture["entity_target"]
    conf = capture["capture_confidence"]
    subj_et = str(conversation_subject.get("entity_type") or "").strip() if conversation_subject else ""
    human = field_display_label_for_capture(subj_et or None, str(ft))
    ent_disp = ent or "the focused item in Context"

    return (
        "- **Integration mode — EXECUTION COMMIT (mandatory):** The user’s message is an **instruction to apply** wording "
        "already discussed (approval / “go ahead” / “change it” / “use that definition”) — **not** an open question.\n"
        "- **MUST** take the **agreed final text** from your **prior turn** or the user’s explicit quote in the thread and "
        f"output **exactly one** ``[DRAFT_VALUE: …]`` tag with that full text for **{human}** on **{ent_disp}**.\n"
        "- **MUST NOT** ask “Shall I…”, “Would you like…”, “Proceed?”, “or tweak first?”, or any **second confirmation**.\n"
        "- **MUST NOT** restate the whole initiative analysis — at most **one short sentence** of acknowledgment, then the tag.\n"
        "- **MUST NOT** claim the database is already updated unless Context shows a commit for this turn; the tag **queues** the write for the user to confirm in the product if required.\n"
        f"- **CAPTURE TARGET:** field_target={ft!r}, entity_target={ent!r}, capture_confidence={conf!r}. "
        "If field_target is ``unknown``, infer the best field from PRIMARY + field in focus; still emit ``[DRAFT_VALUE: …]``.\n"
    )


def _update_and_continue_executor(subject: ConversationSubject | None) -> str:
    """State correction / refinement: tight external shape; internal model update without restarting mediation."""
    subj_hint = ""
    if subject and (subject.get("entity_display_name") or subject.get("entity_id")):
        dn = subject.get("entity_display_name") or "the focused item"
        subj_hint = (
            f"- **Thread:** CONVERSATION SUBJECT points at **{dn}** — treat the correction as updating that line of work; "
            "**do not** drop the anchor unless Context clearly contradicts.\n"
        )
    return (
        "- **Refinement mode (`refine_and_continue` / `update_and_continue`) — STRICT:**\n"
        "- **Internal:** Absorb the user’s correction into your understanding of Context + thread; update assumptions about "
        "what exists, what’s missing, or what the real shape of the work is. **Do not** re-run full mediation, re-frame "
        "the problem from zero, or reopen trade-offs unless the user explicitly asked.\n"
        f"{subj_hint}"
        "- **External (user-facing) — max 2–3 short sentences, one voice:** (1) **One line** acknowledging the correction "
        "(no long quote of their message). (2) **One line** stating the **updated** understanding in your words. "
        "(3) **One line** continuing **forward** — the next concrete decision or move implied by the corrected state.\n"
        "- **MUST NOT:** reframe the problem as if new, introduce trade-offs, restart analysis, list options, run priority "
        "tournaments, inventory dumps, integration capture offers, “would you like…”, “consider…”, “you might…”, exploratory "
        "question stacks, three-option menus, or consultant tone.\n"
        "- **MUST NOT** sound like you’re **starting over** — stay on the **same thread** with a sharper picture.\n"
        "- **Progress:** **no** new reasoning layers after the correction — **one** concrete next step only.\n"
    )


def _commit_and_confirm_executor() -> str:
    """User affirmed pending_integration — report commit result only; zero facilitation."""
    return (
        "- **Commit confirm (`direct_integration_commit` / `commit_and_confirm`) — STRICT:** The user **affirmed** a "
        "**proposed** Vision & Execution write (`pending_integration` in Context / prior turn).\n"
        "- **Internal:** If Context includes **INTEGRATION COMMITTED** or **THIS TURN — INTEGRATION RESULT**, that is **authoritative** "
        "for whether a row was written.\n"
        "- **External (max 2 short sentences):** State **saved** (past/present tense) with **entity + field** from Context, "
        "or state **blocked / failed** plainly. **One** optional clause: where to find it (**ui_surface**). "
        "**MUST NOT** ask whether to proceed, integrate, define outcomes, or offer next steps.\n"
        "- **MUST NOT:** “Would you like…”, “Shall we…”, clarifying questions, trade-off or decision-axis talk, coaching, "
        "re-analysis, false “captured” language if the save succeeded.\n"
    )


def _integration_status_executor() -> str:
    """Direct answer whether persistence happened; optional single save/tweak offer — no axis or lecture."""
    return (
        "- **Persistence Q&A (`direct_integration` / `integration_status_reply`) — STRICT:** The user asked whether notes/fields "
        "were **updated or saved**, **where something lives**, or **what changed** in storage.\n"
        "- **Internal:** Read **SAVE STATE (authoritative)** in this trunk **first**, then **INTEGRATION COMMITTED** / "
        "**LAST INTEGRATION** lines in Context if present. **Never** claim a database write unless **SAVE STATE** says "
        "**saved** or Context has an explicit committed line for **this** turn.\n"
        "- **External — order:** (1) **Save status first** in **one short sentence**. (2) **Field + entity** when known "
        "(plain language, e.g. “desired outcome for {title}”). (3) **Stop** — **no** analysis, trade-offs, coaching, "
        "priorities, or “what we should do next.”\n"
        "- **Preferred shapes (match SAVE STATE):**\n"
        "  - **saved:** “Yes — I saved that to the **{field_label_human}** field for **{entity_display_name}**.” "
        "(You may add where in the app only if Context gives **ui_surface** or path — one short clause.)\n"
        "  - **not saved, conversation only:** “Not yet — that’s only captured in the conversation right now.”\n"
        "  - **probable target, not saved (inferred):** “I think this belongs on the **{field_label_human}** field for "
        "**{entity_display_name}** — want me to save it there?”\n"
        "  - **proposed, awaiting yes:** “Not yet saved to Vision & Execution — say yes to write it to **{field_label_human}** "
        "for **{entity_display_name}**.”\n"
        "- **“Where does this live?”** If **saved** (this turn or **LAST INTEGRATION**): use **SAVE STATE** / **LAST INTEGRATION** "
        "path and field labels exactly — **do not** invent field names or use internal keys.\n"
        "- **MUST NOT:** decision axis, prioritization lecture, trade-off framing, re-explaining their specs, inventory dumps, "
        "enumerate menus, exploratory follow-ups, sectional breakdown.\n"
    )


def _executor_bullets_for_mediation(
    *,
    mediation_move: MediationMove,
    output_contract: OutputContract,
    aspiration_context_available: bool,
    capture_target: CaptureTarget | None = None,
    conversation_subject: ConversationSubject | None = None,
    query_scope: QueryScopeResolution | None = None,
    user_question: str = "",
) -> str:
    """Instruction text for Zenaf: how to write the answer, given trunk-chosen mediation."""
    asp_three = _aspiration_recall_snippet_threeish() if aspiration_context_available else ""
    asp_refl = _aspiration_recall_snippet_reflective() if aspiration_context_available else ""

    _inv_hard = ""
    if query_scope and query_scope["retrieval_mode"] == "full_inventory":
        if mediation_move == "resolve_priority":
            _inv_hard = (
                "\n- **RETRIEVAL (full working set):** Ground in **enumerable system state** from Context. The user asked "
                "**what matters most / what to do first** — give **one** priority recommendation from that state; "
                "**no** invented tasks, **no** peer option menu. User-facing answer still follows **USER-FACING VOICE** "
                "(natural prose, no lens labels).\n"
            )
        elif mediation_move == "update_and_continue":
            _inv_hard = (
                "\n- **RETRIEVAL (full working set):** User is **correcting** understanding. Integrate the correction with "
                "Context; **do not** force a flat system-state listing. **One** forward move; grounded in Context — "
                "**no** invented backlog.\n"
            )
        elif mediation_move == "integration_status_reply":
            _inv_hard = (
                "\n- **RETRIEVAL (full working set):** User asked **persistence status**. Answer from Context; **no** forced "
                "inventory listing; **no** decision-axis pivot.\n"
            )
        elif mediation_move == "commit_and_confirm":
            _inv_hard = (
                "\n- **RETRIEVAL (full working set):** User **confirmed** a pending save — report **integration result** from "
                "Context; **no** inventory, **no** new interview questions.\n"
            )
        else:
            _inv_hard = (
                "\n- **RETRIEVAL (inventory — hard):** You **must** ground the answer in **enumerable system state** from "
                "Context. **No** ideation, **no** net-new options, **no** trade-off menus unless the user explicitly "
                "asked for decision options (they did not here).\n"
            )

    if output_contract == "continuity_forward":
        return _continuity_executor(conversation_subject) + _inv_hard

    if output_contract == "confirm_and_integrate":
        ct = capture_target or derive_capture_target("", packet=None, council_preflight_dict=None)
        if user_signals_execution_commit(user_question):
            return _confirm_integrate_executor_commit_intent(ct, conversation_subject) + _inv_hard
        return _confirm_integrate_executor(ct, conversation_subject) + _inv_hard

    if output_contract == "refine_and_continue":
        return _update_and_continue_executor(conversation_subject) + _inv_hard

    if output_contract == "direct_integration":
        return _integration_status_executor() + _inv_hard

    if output_contract == "direct_integration_commit":
        return _commit_and_confirm_executor() + _inv_hard

    if output_contract == "inventory_only":
        base = (
            "- **Single-entity STATE:** If **PRIMARY CONTEXT** names one focused idea/task/project/initiative, **lead with the "
            "actual field values shown there** (title, brief, description, status, etc.) — quote or paraphrase faithfully. "
            "Only then note **empty** fields. **Never** imply a field is missing when PRIMARY shows text for it.\n"
            "- **Inventory — internal vs external:** **Internally** you may group by missing field, entity clusters, or "
            "dependencies before writing. **Externally** deliver a **compressed** summary — prefer **prose** or **very short** "
            "grouped lines; **avoid bullet spam** and **do not** repeat the same gap as separate bullets for each entity "
            "(e.g. bad: five lines each “missing outcome”; good: one line that the same gap spans those items).\n"
            "- **Progressive disclosure:** For broad discovery (what exists, what’s on today, what can we work on), give "
            "**2–3 thematic buckets** first and at most **three** concrete item names with `[ID: …]` unless the user asked to "
            "**list everything** or **enumerate all** — then you may go long. Offer a **hook** (where to go deeper) instead "
            "of a raw dump.\n"
            "- **MUST** ground in Context only (PRIMARY, Vision Execution working set, DEVELOPMENTAL GUIDANCE / WORK GUIDANCE "
            "LENS if present).\n"
            "- If the working set header says **scoped** (single named subject), inventory **only** that subject and "
            "the linked lines in that block — **do not** broaden to unrelated ideas or tasks from elsewhere in the app.\n"
            "- **MUST NOT** invent new tasks, assign work to people not named in Context, suggest coordination steps, "
            "or give “I recommend…” / roadmap / action menus.\n"
            "- **Progress:** surface gaps **only** — **do not** spin inventory into exploration, coaching, or stacked "
            "interview questions.\n"
        )
        if mediation_move == "sequence_precision_layers":
            base += (
                "- **Mediation (sequence_precision_layers):** **Internally** organize factual gaps into **non-overlapping "
                "layers** (e.g. outcome definition / experience or scope / execution or handoff) using **only** Context. "
                "**Externally** state the picture in **compressed** form. **End with a question only** if one missing layer "
                "clearly blocks progress; **otherwise** close with a short hook or statement — **no** option list or peer "
                "“ways forward.”\n"
            )
        elif mediation_move == "compress_redundant_work":
            base += (
                "- **Mediation (compress_redundant_work):** **Externally** prioritize **one dominant missingness pattern** "
                "if Context supports it (definition vs ownership vs criteria); cite entities **briefly** as a group when "
                "they share the same gap. **No** multi-option action menu.\n"
            )
        base += (
            "- **Closing:** You may end on a **statement** or **optional hook**; **do not** force a clarifying question "
            "every turn. **No** “would you like”, **no** “consider”, **no** coaching tone.\n"
            "- **Do not** use a multi-option action menu this turn."
        )
        return base + _inv_hard

    if mediation_move == "resolve_priority":
        body = (
            "- **Mediation (`resolve_priority`) — internal:** Privately weigh what to recommend using only Context: "
            "what **unblocks** other work, whether aspiration material (if present) **sharpens** the call without "
            "overriding facts, **downstream leverage**, and whether the work is **concrete enough to execute** now. "
            "**No** numeric scores.\n"
            "- **Handshake (`priority_resolution`):** ``resolution_mode`` for this turn is **decide** — you **must** end with a "
            "concrete priority call **and** a ``[DRAFT_VALUE: …]`` tag for the chosen focus (see below). **No** priority answer "
            "without that tag counts as a complete turn.\n"
            "- **No balanced “consultant” hands (`resolve_priority`):** You are **forbidden** from **“on the one hand / on the other hand”**, "
            "from offering a **symmetric choice** between two paths, or from **both-sides** framing. Pick **ONE** priority most "
            "grounded in **PRIMARY** notes, name it with **schema** ``Name [ID: uuid]`` when Context supplies an id, and **immediately** "
            "propose a ``[DRAFT_VALUE: …]`` update for that entity. **If you do not** output ``[DRAFT_VALUE: …]``, **you have failed the turn**.\n"
            "- **External (user-facing):** State **one** clear real priority in plain language (with **MANDATORY ID ECHO** "
            "when that priority is a specific Working Set row — `Title [ID: …]` exactly as in Context), then **1–3 short sentences** "
            "of **integrated** justification in **one voice** — same logic as the internal lenses, **without** naming "
            "lenses, dimensions, or frameworks.\n"
            "- **DRAFT_VALUE mandate (`resolve_priority`):** You are **forbidden** from asking **“Would you like…”** / "
            "**“Shall we…”** / similar **process** invitations. Once you identify **the** priority, you **must** **immediately** "
            "output a ``[DRAFT_VALUE: …]`` block proposing text to save — target **Short note** / **Expanded description** on **ideas**, "
            "**Brief** on **initiatives** and **projects**, **Description** or **Completion criteria** on **tasks** (whichever "
            "Context + **UI FIELD SCHEMA** show as empty or thin). **Propose the data;** "
            "**do not** discuss whether to capture it.\n"
            "- **PRIMARY gap-fill (`resolve_priority`):** Do **not** only **name** the priority. Look at **PRIMARY**: if the "
            "chosen focus is **missing** a usable **brief** / **description** / **completion criteria** (per entity schema), "
            "the ``[DRAFT_VALUE: …]`` on this turn is **mandatory** — concrete wording from Context + Question, **verbatim bias** per system rules.\n"
            "- **MUST NOT (external):** list peer options, name multiple equal candidates, defer the decision to the user "
            "(“what do you prefer?”, “which should we pick?”), peer menus, punting without a best-effort priority when "
            "Context names any candidate work, “from a … perspective” phrasing, capture offers, inventory-only answers, "
            "**or** permission-seeking openers (**“Would you like…”**, **“Shall we…”**), **or** two-handed / either-or coaching "
            "that replaces a single committed priority + draft.\n"
            "- **Candidates** must come only from Context; honor **RETRIEVAL SCOPE** (subject / scoped / full set).\n"
            "- **Progress:** once the priority is stated, **do not** reopen comparison shopping, second-guess menus, or "
            "“what do you think?” — move to **one** execution or refinement hook only.\n"
        )
        return body + asp_three + _inv_hard

    if mediation_move == "enumerate":
        body = (
            "- **Mediation (enumerate):** User asked for options. **First** merge overlapping directions already stated "
            "in Context or the question (**compress** redundancy). **Then** give **2–4** options that are **distinct** "
            "on a **named axis** (say the axis in one short phrase). Each option: short label or line, grounded in "
            "Context — not three variants of the same coordination task.\n"
            "- **MUST NOT** treat this turn as inventory-only, priority collapse, integration capture, or generic coach "
            "wrap-up unless the user asked only for status or missing fields.\n"
        )
        return body + asp_three + _inv_hard

    if mediation_move == "recommend_first_collapse":
        body = (
            "- **Mediation (recommend_first_collapse):** **Internally** identify bottleneck or decision axis from Context. "
            "**Externally** in **natural prose**: **one** primary next move (not three peer options); if you mention "
            "alternatives, keep them subordinate — **no** rigid three-label menu, **no** framework enumeration, **no** "
            "enumerate-mode option list, **no** open-ended coaching.\n"
        )
        return body + asp_three + _inv_hard

    if mediation_move == "expose_decision_axis":
        body = (
            "- **Mediation (expose_decision_axis):** Respond in one continuous voice; name the main trade-off or axis "
            "when helpful; integrate trade-offs without defaulting to a three-option template.\n"
            "- **PROGRESS GUARD:** If the user’s latest turn is **primarily supplying** a definition, outcome chain, or "
            "constraints (not asking you to analyze tensions), **do not** open a decision-axis essay — **compress** to what "
            "matters and **one** forward move; if routing were correct they would be in `acknowledge_integrate`.\n"
            "- Let structure follow the ask — short lists when they help, flowing prose when that fits.\n"
            "- Follow the general Thinking Partner rules above for tone and grounding.\n"
        )
        return body + asp_refl + _inv_hard

    if mediation_move == "ask_discriminating_question":
        return (
            "- **Mediation (ask_discriminating_question):** Compress what Context already says, then end with **one** "
            "sharp question that best splits the remaining ambiguity. **No** option menu, **no** trade-off essay, **no** "
            "exploratory stacks, unless the question itself asks for options.\n"
        ) + _inv_hard

    return (
        "- Execute the stated mediation_move and resolution_mode; do not substitute a generic three-option template.\n"
        "- **PRIMARY (when present):** If the Context includes **PRIMARY CONTEXT (authoritative)** for a focused record, "
        "base factual claims on those lines before offering opinions or next steps. Do not invent emptiness or generic "
        "“missing fields” lists that contradict PRIMARY.\n"
    ) + _inv_hard


def _ve_gap_elicitation_block(
    council_preflight_dict: dict[str, Any] | None,
    *,
    question_kind: str,
) -> str:
    """
    Structured elicitation: one gap at a time, or a short inventory for ``missing_fields``.
    Populated server-side in ``attach_ve_gap_to_preflight`` (vision_execution.ve_gap_elicitation).
    """
    if not isinstance(council_preflight_dict, dict):
        return ""
    mode = str(council_preflight_dict.get("ve_gap_mode") or "").strip()
    if not mode:
        return ""

    if mode == "inventory" and question_kind == "missing_fields":
        inv = council_preflight_dict.get("ve_gap_inventory")
        if not isinstance(inv, list) or not inv:
            return ""
        lines: list[str] = []
        for item in inv[:6]:
            if not isinstance(item, dict):
                continue
            q = str(item.get("question") or "").strip()
            lb = str(item.get("label") or "").strip()
            if q:
                lines.append(f"- **{lb}:** {q}" if lb else f"- {q}")
        if not lines:
            return ""
        inv_body = "\n".join(lines)
        primary = council_preflight_dict.get("ve_gap_primary")
        pq = ""
        if isinstance(primary, dict):
            pq = str(primary.get("question") or "").strip()
        tail = (
            f"\n- After summarizing, end with **exactly one** short follow-up question; prefer: {pq}"
            if pq
            else "\n- After summarizing, end with **exactly one** short follow-up question on the highest-priority gap."
        )
        return (
            "\n\n**STRUCTURED GAP ELICITATION (mandatory for this turn):** The user asked what is missing or weak. "
            "Respond with **two short groups**: (1) **Core fields** — the most important empty or weak items; "
            "(2) **Next structure** — execution shape (steps, seats, tasks, dependencies) only if relevant. "
            "Keep it compact (top 2–4 gaps total), not a dump of every column.\n"
            f"Authoritative prioritized gaps from the open record:\n{inv_body}"
            f"{tail}\n"
        )

    if mode == "decline_pivot":
        primary = council_preflight_dict.get("ve_gap_primary")
        if not isinstance(primary, dict):
            return ""
        q = str(primary.get("question") or "").strip()
        if not q:
            return ""
        return (
            "\n\n**LANE A + ELICITATION (mandatory):** A direct Vision Execution edit did **not** complete on this turn. "
            "**Do not** imply the change was saved. Briefly acknowledge the limitation, then pivot with **one** "
            f"forward question (use this or a natural equivalent): {q}\n"
        )

    if mode == "idle_close":
        if question_kind in ("missing_fields", "integration_confirm", "integration_status"):
            return ""
        primary = council_preflight_dict.get("ve_gap_primary")
        if not isinstance(primary, dict):
            return ""
        q = str(primary.get("question") or "").strip()
        if not q:
            return ""
        return (
            "\n\n**CLOSING ELICITATION (mandatory when substantive reply is otherwise complete):** "
            "The user did not issue a direct save-this-field imperative that Lane A handled. "
            "After your main answer, if you have not already asked a sharp forward question, add **one** short "
            f"question (prefer this): {q}\n"
        )

    return ""


def _lane_a_direct_action_guard_block(council_preflight_dict: dict[str, Any] | None) -> str:
    """
    When Lane A parsed a mutation-shaped intent but did not persist, forbid success hallucinations in council text.
    """
    if not isinstance(council_preflight_dict, dict):
        return ""
    if not council_preflight_dict.get("lane_a_mutation_intent_parsed"):
        return ""
    if not council_preflight_dict.get("lane_a_direct_action_declined"):
        return ""
    return (
        "\n\n**LANE A DIRECT ACTION (mandatory):** The user message matched an imperative **persist-to-VE** pattern, "
        "but the server **did not** apply a deterministic Vision Execution write on this turn. "
        "**Do not** claim the record was updated, saved, assigned, created, linked, or that any field changed. "
        "Avoid success language such as: Done, Updated, Added, Saved, Recorded, Successfully changed, or Owner changed. "
        "Explain what is missing (e.g. person not found, unsupported phrase) or the exact UI/API path.\n"
    )


def conversational_partner_trunk_instructions(
    *,
    question_kind: QuestionKind,
    output_contract: OutputContract,
    mediation_profile: MediationProfile,
    aspiration_context_available: bool = False,
    user_question: str = "",
    packet: str | None = None,
    council_preflight_dict: dict[str, Any] | None = None,
    capture_target: CaptureTarget | None = None,
    conversation_subject: ConversationSubject | None = None,
    query_scope: QueryScopeResolution | None = None,
    integration_save_state_block: str = "",
    scoped_digression: bool = False,
) -> str:
    """
    Mandatory block for single-seat Zenaf: mediation control + trunk metadata + executor-only rules.
    ``mediation_profile`` must come from ``derive_mediation_profile`` for this turn.
    For ``confirm_and_integrate``, pass ``capture_target`` from the caller (or omit to derive here).
    Pass merged ``conversation_subject`` for thread continuity (session echo).
    Pass ``query_scope`` from ``resolve_query_scope`` (retrieval before mediation).
    """
    control = _mediation_control_block(mediation_profile)
    subj_block = _conversation_subject_block(conversation_subject)
    scope_block = _query_scope_instruction_block(query_scope)
    scoped_block = _scoped_digression_depth_block() if scoped_digression else ""
    grounding_block = _entity_grounding_scope_continuity_block(packet, council_preflight_dict)
    lane_a_guard_block = _lane_a_direct_action_guard_block(council_preflight_dict)
    ve_gap_block = _ve_gap_elicitation_block(council_preflight_dict, question_kind=question_kind)
    trunk_header = (
        f"\n\n**THIS TURN — CONVERSATION TRUNK (mandatory):** "
        f"question_kind={question_kind!r}, output_contract={output_contract!r}.\n"
    )
    capture: CaptureTarget | None = None
    if output_contract in ("confirm_and_integrate", "direct_integration", "direct_integration_commit"):
        if capture_target is not None:
            capture = capture_target
        else:
            capture = derive_capture_target(
                user_question,
                packet=packet,
                council_preflight_dict=council_preflight_dict,
            )
    executor = _executor_bullets_for_mediation(
        mediation_move=mediation_profile["mediation_move"],
        output_contract=output_contract,
        aspiration_context_available=aspiration_context_available,
        capture_target=capture,
        conversation_subject=conversation_subject,
        query_scope=query_scope,
        user_question=user_question,
    )
    mode_lock = _mode_lock_block(mediation_profile["mediation_move"], output_contract)
    tail = (
        ""
        if output_contract
        in (
            "confirm_and_integrate",
            "continuity_forward",
            "refine_and_continue",
            "direct_integration",
            "direct_integration_commit",
        )
        else _secondary_compression_bullet()
    )
    return (
        control
        + subj_block
        + scope_block
        + scoped_block
        + grounding_block
        + lane_a_guard_block
        + ve_gap_block
        + trunk_header
        + _progress_over_exploration_block()
        + (integration_save_state_block or "")
        + executor
        + mode_lock
        + _global_external_voice_rules()
        + tail
    )
