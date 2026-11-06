"""Shared voice-reply builder for the conversation skeleton.

This is the prompt logic extracted verbatim from ``api/routes/voice_routes.py``
so ``POST /voice/chat`` and ``POST /conversation/turn`` run the SAME prompt
builder — never a fork. The voice route stays thin: validate, resolve history,
call :func:`generate_voice_reply`, persist.

Two additive inputs exist only here (the voice route ignores them):
  context_hint    — one factual line about what the user is doing right now
                    (open sheet, entity in focus): the "what is happening" half.
  thread_summary  — the active seat's quiet background continuity, used when
                    the recent global history holds little of this seat's voice.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any, Callable

from local_ai.agent_intake.llm_keys import generate as _default_generate
from local_ai.conversation.weave import sanitize_weave
from local_ai.council.archetypes import (
    ANTI_PRESUMPTION_STYLE,
    PLAIN_TO_KEY,
    WEIGHT_FLOOR,
    build_archetype_prompt_lines,
    compute_skeptic_weights,
    get_archetype,
    stock_archetype_ids,
    voice_color,
)
from local_ai.council.canonical.bear import BEAR_RECORD
from local_ai.council.canonical.crane import CRANE_RECORD
from local_ai.council.canonical.firebrand import FIREBRAND_RECORD
from local_ai.council.canonical.fox import FOX_RECORD
from local_ai.council.canonical.gardener import GARDENER_RECORD
from local_ai.council.canonical.raven import RAVEN_RECORD
from local_ai.council.canonical.weaver import WEAVER_RECORD
from local_ai.council.jurisdictions import jurisdiction_prompt_lines
from local_ai.council.render import (
    render_bear_ordinary,
    render_crane_ordinary,
    render_firebrand_ordinary,
    render_fox_ordinary,
    render_gardener_ordinary,
    render_raven_ordinary,
    render_weaver_ordinary,
)

logger = logging.getLogger(__name__)

_MSG_MAX = 2000
_HISTORY_MAX = 20

GenerateFn = Callable[..., str]

# Weaver canonical cutover — CODE-LEVEL, not a persistent feature flag.
# True (the merged state): ordinary Weaver turns (canonical=True) render
# the canonical character block instead of the legacy archetype block.
# False restores the exact legacy Weaver prompt: reverting this one
# branch is the whole rollback, because no legacy function is modified.
# Meeting turns (canonical=False) always keep the legacy assembly — the
# cutover is ordinary-conversation-only by design, so first-encounter
# behavior is untouched.
WEAVER_CANONICAL_CUTOVER = True


# Raven canonical cutover — CODE-LEVEL, not a persistent feature flag.
# True (the merged state): ordinary Raven turns (canonical=True) render
# the canonical character block instead of the legacy archetype block.
# False restores the exact legacy Raven prompt: reverting this one
# branch is the whole rollback, because no legacy function is modified.
# Meeting turns (canonical=False) always keep the legacy assembly — the
# cutover is ordinary-conversation-only by design, so first-encounter
# behavior is untouched. No environment-variable override: any future
# trial override needs its own authorization (Weaver trial precedent).
RAVEN_CANONICAL_CUTOVER = True


# Gardener canonical cutover — CODE-LEVEL, not a persistent feature flag.
# True: ordinary Gardener turns (canonical=True) render the canonical
# character block instead of the legacy archetype block. False
# restores the exact legacy Gardener prompt: reverting this one
# branch is the whole rollback, because no legacy function is
# modified. Meeting turns (canonical=False) always keep the legacy
# assembly — the cutover is ordinary-conversation-only by design,
# so first-encounter behavior is untouched. No environment-variable
# override: any future trial override needs its own authorization
# (Weaver trial precedent).
GARDENER_CANONICAL_CUTOVER = True


# Firebrand canonical cutover — CODE-LEVEL, not a persistent feature flag.
# True: ordinary Firebrand turns (canonical=True) render the canonical
# character block instead of the legacy archetype block. False
# restores the exact legacy Firebrand prompt: reverting this one
# branch is the whole rollback, because no legacy function is
# modified. Meeting turns (canonical=False) always keep the legacy
# assembly — the cutover is ordinary-conversation-only by design,
# so first-encounter behavior is untouched. No environment-variable
# override: any future trial override needs its own authorization
# (Weaver trial precedent).
FIREBRAND_CANONICAL_CUTOVER = True


# Bear canonical cutover — CODE-LEVEL, not a persistent feature flag.
# True: ordinary Bear turns (canonical=True) render the canonical
# character block instead of the legacy archetype block. False
# restores the exact legacy Bear prompt: reverting this one branch
# is the whole rollback, because no legacy function is modified.
# Meeting turns (canonical=False) always keep the legacy assembly — the
# cutover is ordinary-conversation-only by design, so first-encounter
# behavior is untouched. No environment-variable override: any future
# trial override needs its own authorization (Weaver trial precedent).
BEAR_CANONICAL_CUTOVER = True


# Bear flow-loop guidance (flow architecture §3 S2, 2026-11-05) — prompt
# guidance for ordinary Bear Talk turns ONLY, gated on bear_canonical
# at the assembly site below. It is deliberately NOT part of the
# canonical record: BEAR_RECORD is character definition, and the
# renderer reproduces exemplar §2 exactly — the loop is a way of
# working, not character, so it rides here as guidance, in the
# pattern of _WEAVER_REFINEMENT_GUIDANCE (prompt-local guidance,
# not canonical content). Meetings run canonical=False, so the
# meeting path never sees it; no other seat ever sees it.
# Content fences (architecture §2.2, §2.4, §2.7): the five steps are
# available conversational functions, never a required sequence —
# Bear may skip or combine them, or simply acknowledge what is
# already established, and a complete loop is never required; both
# directions of adjustment are offered (reduce friction AND push
# harder) and neither is the default; Rest / Release / Continue
# apply to Bear's ordinary Talk; evidence is user expression + the
# focus hint only — no node records, no score, no persisted stage,
# no auto-action. Level (a) only: no capture, derivation, or
# standing need rides on this text.
_BEAR_FLOW_LOOP_GUIDANCE = (
    "Flow and capacity — how you work with someone and their work. "
    "You help the visitor find a sustainable relationship with the "
    "work in front of them — not by measuring them, but by noticing "
    "together what the work asks and what they have to give. Your "
    "evidence is what the visitor tells you, and the node they are "
    "focused on; work from that alone. You need not name their "
    "state, and you need not assess on every turn: a plain "
    "observation, a boundary recognized, a decision already reached "
    "and left to stand — any of these may be the whole of your "
    "contribution. When something in the work is hard to carry, you "
    "have five ways of working with it, none of them a sequence and "
    "none of them required: notice what is straining or inviting — "
    "what must survive, what is quietly draining; understand by "
    "asking only what has not already been said; offer an adjustment "
    "— simplify, deepen, vary, support, pause, continue, or press "
    "harder where the circumstances warrant it, and never default to "
    "one direction; observe whether it helped, only when the visitor "
    "has not already told you; and return to it only when they bring "
    "it up again. Skip or combine these as the moment calls for. "
    "Never re-ask what the visitor has already established, and "
    "never manufacture a question merely to keep talking: when they "
    "have answered, recognize the answer. Sometimes the most useful "
    "thing you can do is let an insight stand, let the exchange "
    "rest, or let the visitor go — a turn that ends after one useful "
    "suggestion is complete."
)


# Crane canonical cutover — CODE-LEVEL, not a persistent feature flag.
# True: ordinary Crane turns (canonical=True) render the canonical
# character block instead of the legacy archetype block. False
# restores the exact legacy Crane prompt: reverting this one branch
# is the whole rollback, because no legacy function is modified.
# Meeting turns (canonical=False) always keep the legacy assembly — the
# cutover is ordinary-conversation-only by design, so first-encounter
# behavior is untouched. No environment-variable override: any future
# trial override needs its own authorization (Weaver trial precedent).
CRANE_CANONICAL_CUTOVER = True


# Fox canonical cutover — CODE-LEVEL, not a persistent feature flag.
# True: ordinary Fox turns (canonical=True) render the canonical
# character block instead of the legacy archetype block. False
# restores the exact legacy Fox prompt: reverting this one branch
# is the whole rollback, because no legacy function is modified.
# Meeting turns (canonical=False) always keep the legacy assembly — the
# cutover is ordinary-conversation-only by design, so first-encounter
# behavior is untouched. No environment-variable override: any future
# trial override needs its own authorization (Weaver trial precedent).
FOX_CANONICAL_CUTOVER = True


def _strand_blend_lines(weights: dict[str, float]) -> list[str]:
    """Strand-blend lines, mirroring the blend section of
    build_archetype_prompt_lines. Mirrored (not reused) deliberately:
    archetypes.py is the frozen rollback source and must not be
    modified, so the canonical path recomputes these faculty lines
    from the same weights and taglines instead of calling it."""
    from local_ai.strands import strand as _strand

    blend: list[str] = []
    for plain_name, weight in sorted(weights.items(), key=lambda kv: kv[1], reverse=True):
        if weight < WEIGHT_FLOOR:
            continue
        key = PLAIN_TO_KEY.get(plain_name)
        tagline = ""
        if key:
            try:
                tagline = _strand(key).tagline
            except KeyError:
                pass
        pct = int(round(weight * 100))
        if tagline:
            blend.append(f"- {plain_name} ({pct}%): {tagline}")
        else:
            blend.append(f"- {plain_name} ({pct}%)")
    if not blend:
        return []
    return ["Strand blend (faculties this seat draws on, by weight):", *blend]


@dataclass
class VoiceReply:
    reply: str
    archetype_id: str
    display_name: str
    voice_color: str
    mode_used: str  # "trained" | "base"
    has_training: bool


def _turn_role(turn: Any) -> str:
    if isinstance(turn, dict):
        return str(turn.get("role", ""))
    return str(getattr(turn, "role", ""))


def _turn_content(turn: Any) -> str:
    if isinstance(turn, dict):
        return str(turn.get("content", ""))
    return str(getattr(turn, "content", ""))


def _turn_archetype_id(turn: Any) -> str | None:
    """The seat that spoke a history turn, if recorded.

    Service-built histories carry it (service.turn keeps the store's
    archetype_id); client-built histories (e.g. the voice route's
    VoiceChatTurn) do not, and trunk turns have none. Returns None
    for all of those — never a guess.
    """
    if isinstance(turn, dict):
        value = turn.get("archetype_id")
    else:
        value = getattr(turn, "archetype_id", None)
    if value is None:
        return None
    value = str(value).strip().lower()
    return value or None


def _voice_turn_label(user_id: str, turn: Any) -> str:
    """Label for a non-user history turn, by its ACTUAL speaker.

    Capability C S0: a voice turn's archetype_id names its speaker, so
    the label is that seat's display name — the same naming authority
    the builder uses for the current seat (stock role name, e.g.
    "Champion", or the visitor's chosen name) — never the current
    seat's name. User turns are not labeled here: they stay "User",
    because a user turn's archetype_id names the sheet it was said in
    (the addressee seat), not its speaker. Unattributed turns (trunk
    turns, or histories built without archetype_id) get the neutral
    label "Voice", never a seat name we cannot justify.
    """
    arch_id = _turn_archetype_id(turn)
    if arch_id:
        arch = get_archetype(arch_id)
        if arch is not None:
            try:
                from local_ai.council.naming import get_display_name

                name = get_display_name(user_id, arch_id)
                if name:
                    return name
            except Exception:
                pass
            return arch.display_name
    return "Voice"


def _trained_sections(user_id: str, weights: dict[str, float]) -> tuple[list[str], bool]:
    """Render the user's trained per-strand sections for this voice's blend.

    Returns (sections, has_training). Never raises — empty training falls
    back honestly to the base voice.
    """
    try:
        from local_ai.personality.blend import render_user_section
        from local_ai.personality.store import PersonalityStore

        # NOTE: user_id is keyword — PersonalityStore's first positional
        # parameter is db_path. (The pre-fork voice route passed it
        # positionally, which silently created a throwaway DB named after
        # the user id and always fell back to the base voice.)
        store = PersonalityStore(user_id=user_id)
        try:
            profile = store.get_current()
            if profile is None:
                return [], False
            version_count = len(store.list_versions())
            sections: list[str] = []
            for plain_name, weight in sorted(weights.items(), key=lambda kv: kv[1], reverse=True):
                if weight < WEIGHT_FLOOR:
                    continue
                key = PLAIN_TO_KEY.get(plain_name)
                if not key:
                    continue
                try:
                    sections.append(render_user_section(profile, key, weight, version_count))
                except Exception:
                    continue
            return sections, bool(sections)
        finally:
            store.close()
    except Exception:
        return [], False


# ---------------------------------------------------------------------------
# W2 execution-context budget gate (verdict §5).
#
# Finding, verified at 8761278: NO enforced overall character cap
# exists on the assembled Talk prompt. build_voice_prompt appends
# sections in fixed order with per-section caps only; generate_voice_reply
# passes the joined prompt to the provider with no truncation; no
# MIN_HEADROOM / HEADROOM constant exists in local_ai/. The 8,000-char
# figure belongs to the first-meeting steward-frame records
# (pre-generated, capped at generation time), not to Talk assembly.
# The 8,000-char budget below is therefore a POLICY threshold adopted
# from that frame cap: the execution block yields to it (budget notice,
# then omission with a warning log line) rather than displacing
# required character instructions or the [-10:] history window. The
# block itself is already bounded at 2,000 chars by its builder, so
# the gate only ever fires on genuinely long prompts.
# ---------------------------------------------------------------------------

_VOICE_PROMPT_BUDGET = 8000

_EXECUTION_BUDGET_NOTICE = (
    "Execution records were omitted from this turn for length. Their absence "
    "from this context does not indicate that no tasks exist."
)


def _insert_execution_block(prompt: list[str], block: str) -> None:
    """Insert the execution section as the last context section,
    immediately before history (or before the trailing User line when
    there is no history section)."""
    if "Conversation so far:" in prompt:
        idx = prompt.index("Conversation so far:") - 1  # the "" separator
    else:
        idx = len(prompt) - 2  # before the "User: ..." line
    prompt[idx:idx] = ["", block]


def _apply_execution_context(
    prompt: list[str], execution_context: str, conversation_id: str | None
) -> None:
    """Include the execution block, the budget notice, or nothing.

    The gate is computed on the fully assembled prompt (all required
    sections + history + trailing lines), so the block can never
    displace them: it is included only when it fits in the headroom
    left, replaced by the budget notice when only the notice fits,
    and omitted entirely otherwise. Cases 2 and 3 emit one structured
    warning log line (conversation id, block length, headroom). No
    new table or persistence.
    """
    block = execution_context.strip()
    base_len = len("\n".join(prompt))
    headroom = _VOICE_PROMPT_BUDGET - base_len
    # Joining ["", block] into the prompt adds exactly len(block) + 2
    # characters (one newline before each of the two new elements).
    if len(block) + 2 <= headroom:
        _insert_execution_block(prompt, block)
    elif len(_EXECUTION_BUDGET_NOTICE) + 2 <= headroom:
        _insert_execution_block(prompt, _EXECUTION_BUDGET_NOTICE)
        logger.warning(
            "execution_context budget: block omitted for length "
            "conversation_id=%s block_chars=%d headroom=%d",
            conversation_id or "unknown",
            len(block),
            headroom,
        )
    else:
        logger.warning(
            "execution_context budget: block and notice omitted for length "
            "conversation_id=%s block_chars=%d headroom=%d",
            conversation_id or "unknown",
            len(block),
            headroom,
        )


def build_voice_prompt(
    user_id: str,
    archetype_id: str,
    message: str,
    history: list[Any],
    mode: str = "trained",
    question: bool = False,
    context_hint: str | None = None,
    thread_summary: str | None = None,
    extra_instructions: str | None = None,
    canonical: bool = True,
    capability_context: str | None = None,
    fellowship_reference: str | None = None,
    obligation_context: str | None = None,
    evidence_context: str | None = None,
    invitation_context: str | None = None,
    execution_context: str | None = None,
    # Conversation id, for the execution-budget warning log only.
    # None on paths that never carry an execution block (meetings,
    # voice route); the log only fires when a block was supplied.
    conversation_id: str | None = None,
) -> tuple[list[str], dict[str, Any]]:
    """Assemble the prompt for one voice turn. Returns (lines, meta).

    Raises ValueError on unknown archetype or empty message (and not question).

    `capability_context` is a pre-rendered continuation block from
    local_ai/council/capabilities.py (this seat's slice as background
    knowledge ONLY — no intention line, no offer instruction). It is
    supplied by the continuation call sites (conversation service,
    voice route); first meetings never pass it, because their frames
    already carry the first-meeting block via the encounter runtime.

    `canonical` selects the character assembly: True (the default)
    renders the canonical character block on ordinary turns; False
    keeps the exact legacy archetype assembly for meeting turns.
    The encounter runtime (keystone meetings) runs under the
    evidence/expression separation (Joshua's ruling, 2026-10-23) —
    dialogue synthesizes in the character's own words and is never
    required to splice the user's phrases, while exact quotations
    live in the evidence layer. No path appends a [[u]]
    quote-weaving instruction anymore (removed 2026-11-02, Step 2);
    historical markers in stored replies still render via the
    client, and sanitize_weave still normalizes them.
    """
    arch_id = (archetype_id or "").strip().lower()
    arch = get_archetype(arch_id)
    if arch is None or arch_id not in stock_archetype_ids():
        raise ValueError(f"Unknown voice: {archetype_id!r}")

    message = (message or "").strip()
    if not message and not question:
        raise ValueError("Message is empty.")

    mode = (mode or "trained").strip().lower()
    if mode not in ("trained", "base"):
        mode = "trained"

    display_name = arch.display_name
    custom_name = None
    try:
        from local_ai.council.naming import get_display_name

        custom = get_display_name(user_id, arch.id)
        if custom:
            display_name = custom
            # get_display_name falls back to the stock name when no
            # custom name exists: only a value DIFFERENT from stock
            # is a visitor-chosen name for the address line.
            if custom != arch.display_name:
                custom_name = custom
    except Exception:
        pass

    weights_override = None
    if arch.strand_weights is None:
        weights_override = compute_skeptic_weights(user_id, mode=mode)
    weights = weights_override if weights_override is not None else (arch.strand_weights or {})

    # Weaver canonical cutover (single gate, ordinary conversation
    # only): for ordinary Weaver turns, the canonical renderer
    # REPLACES the legacy character block — it does not supplement it.
    # Replaced: the "You are {display_name}, a voice…" opener, the
    # Archetype frame line, and the philosophy lines (both legacy
    # sources: ARCHETYPE_PHILOSOPHY lines and steward-record lines
    # when Weaver steward is active — neither function is called on
    # this path, so neither is modified). Preserved verbatim: the
    # shared anti-presumption style rule, the jurisdiction lines
    # (registry focus/register/dictionary — complementary content the
    # canonical block does not duplicate), and the strand blend, plus
    # every downstream section below (trained sections,
    # reply guidance, question block, extra_instructions, fellowship
    # reference, thread summary, context hint, history, continuity,
    # trailer). The resolved capability guidance rides INSIDE the
    # character block (assembly order) instead of its legacy
    # downstream slot, so the downstream append below is skipped on
    # this path — same content, moved once, never duplicated.
    # Meeting turns (canonical=False) and all other seats keep the exact
    # legacy assembly.
    weaver_canonical = (
        arch_id == "conductor" and WEAVER_CANONICAL_CUTOVER and canonical
    )
    if weaver_canonical:
        visitor_state = {"personal_name": custom_name} if custom_name else {}
        character_block = render_weaver_ordinary(
            WEAVER_RECORD, visitor_state, resolved_capability=capability_context
        )
        preserved_lines = [ANTI_PRESUMPTION_STYLE]
        preserved_lines.extend(jurisdiction_prompt_lines(arch_id))
        preserved_lines.extend(_strand_blend_lines(weights))
    # Raven canonical cutover (single gate, ordinary conversation
    # only): for ordinary Raven turns, the canonical renderer
    # REPLACES the legacy character block — it does not supplement it.
    # Replaced: the "You are {display_name}, a voice…" opener, the
    # Archetype frame line, the philosophy lines, and the warmth
    # register line (the registry's "warmth: none" formulation is
    # SUPERSEDED character material — the canonical voice close
    # carries the adopted indirect-concern warmth — so it is not
    # preserved). Preserved verbatim: the shared anti-presumption
    # style rule and the strand blend, plus every downstream section
    # below. NO jurisdiction lines are added: jurisdiction lines are
    # consumed ONLY for the conductor, so the legacy Raven prompt
    # carries none and the canonical path adds none. NO steward leg:
    # Raven has no steward record and none is created. The resolved
    # capability guidance rides INSIDE the character block (assembly
    # order) instead of its legacy downstream slot, so the downstream
    # append below is skipped on this path — same content, moved
    # once, never duplicated. The address clause uses custom_name,
    # which is the existing naming lookup's result (it differs from
    # stock only when the lookup returns a visitor-chosen name); the
    # renderer receives that already-authorized value, never raw
    # visitor state, and never infers milestone eligibility itself.
    # Meeting turns (canonical=False) and all other seats keep the exact
    # legacy assembly.
    raven_canonical = (
        arch_id == "skeptic" and RAVEN_CANONICAL_CUTOVER and canonical
    )
    if raven_canonical:
        character_block = render_raven_ordinary(
            RAVEN_RECORD, authorized_name=custom_name,
            resolved_capability=capability_context,
        )
        preserved_lines = [ANTI_PRESUMPTION_STYLE]
        preserved_lines.extend(_strand_blend_lines(weights))
    # Gardener canonical cutover (single gate, ordinary conversation
    # only): for ordinary Gardener turns, the canonical renderer
    # REPLACES the legacy character block — it does not supplement it.
    # Replaced: the "You are {display_name}, a voice…" opener, the
    # Archetype frame line, the philosophy lines, and the warmth
    # register line (the registry's "warm-patient" formulation is
    # SUPERSEDED character material — the canonical voice passage
    # carries the adopted warm-patient warmth — so it is not
    # preserved). Preserved verbatim: the shared anti-presumption
    # style rule and the strand blend, plus every downstream section
    # below. NO jurisdiction lines are added: jurisdiction lines are
    # consumed ONLY for the conductor, so the legacy Gardener prompt
    # carries none and the canonical path adds none. NO steward leg:
    # Gardener has no steward record and none is created. The resolved
    # capability guidance rides INSIDE the character block (assembly
    # order) instead of its legacy downstream slot, so the downstream
    # append below is skipped on this path — same content, moved
    # once, never duplicated. The address clause uses custom_name,
    # which is the existing naming lookup's result (it differs from
    # stock only when the lookup returns a visitor-chosen name); the
    # renderer receives that already-authorized value, never raw
    # visitor state, and never infers milestone eligibility itself.
    # Meeting turns (canonical=False) and all other seats keep the exact
    # legacy assembly.
    gardener_canonical = (
        arch_id == "mentor" and GARDENER_CANONICAL_CUTOVER and canonical
    )
    if gardener_canonical:
        character_block = render_gardener_ordinary(
            GARDENER_RECORD, authorized_name=custom_name,
            resolved_capability=capability_context,
        )
        preserved_lines = [ANTI_PRESUMPTION_STYLE]
        preserved_lines.extend(_strand_blend_lines(weights))
    # Firebrand canonical cutover (single gate, ordinary conversation
    # only): for ordinary Firebrand turns, the canonical renderer
    # REPLACES the legacy character block — it does not supplement it.
    # Replaced: the "You are {display_name}, a voice…" opener, the
    # Archetype frame line, the philosophy lines, and the warmth
    # register line (the registry's "sparing and direct" formulation
    # is SUPERSEDED character material — the canonical voice passage
    # carries the adopted sparing-direct warmth — so it is not
    # preserved). Preserved verbatim: the shared anti-presumption
    # style rule and the strand blend, plus every downstream section
    # below. NO jurisdiction lines are added: jurisdiction lines are
    # consumed ONLY for the conductor, so the legacy Firebrand prompt
    # carries none and the canonical path adds none. NO steward leg:
    # Firebrand has no steward record and none is created. The resolved
    # capability guidance rides INSIDE the character block (assembly
    # order) instead of its legacy downstream slot, so the downstream
    # append below is skipped on this path — same content, moved
    # once, never duplicated. The address clause uses custom_name,
    # which is the existing naming lookup's result (it differs from
    # stock only when the lookup returns a visitor-chosen name); the
    # renderer receives that already-authorized value, never raw
    # visitor state, and never infers milestone eligibility itself.
    # Meeting turns (canonical=False) and all other seats keep the exact
    # legacy assembly.
    firebrand_canonical = (
        arch_id == "champion" and FIREBRAND_CANONICAL_CUTOVER and canonical
    )
    if firebrand_canonical:
        character_block = render_firebrand_ordinary(
            FIREBRAND_RECORD, authorized_name=custom_name,
            resolved_capability=capability_context,
        )
        preserved_lines = [ANTI_PRESUMPTION_STYLE]
        preserved_lines.extend(_strand_blend_lines(weights))
    # Bear canonical cutover (single gate, ordinary conversation
    # only): for ordinary Bear turns, the canonical renderer
    # REPLACES the legacy character block — it does not supplement it.
    # Replaced: the "You are {display_name}, a voice…" opener, the
    # Archetype frame line, the philosophy lines, and the warmth
    # register line (the registry's "warm-protective" formulation is
    # SUPERSEDED character material — the canonical voice passages
    # carry the adopted warm-protective warmth — so it is not
    # preserved). Preserved verbatim: the shared anti-presumption
    # style rule and the strand blend, plus every downstream section
    # below. NO jurisdiction lines are added: jurisdiction lines are
    # consumed ONLY for the conductor, so the legacy Bear prompt
    # carries none and the canonical path adds none. NO steward leg:
    # Bear has no steward record and none is created. The resolved
    # capability guidance rides INSIDE the character block (assembly
    # order) instead of its legacy downstream slot, so the downstream
    # append below is skipped on this path — same content, moved
    # once, never duplicated. The address clause uses custom_name,
    # which is the existing naming lookup's result (it differs from
    # stock only when the lookup returns a visitor-chosen name); the
    # renderer receives that already-authorized value, never raw
    # visitor state, and never infers milestone eligibility itself.
    # Meeting turns (canonical=False) and all other seats keep the exact
    # legacy assembly.
    bear_canonical = (
        arch_id == "guardian" and BEAR_CANONICAL_CUTOVER and canonical
    )
    if bear_canonical:
        character_block = render_bear_ordinary(
            BEAR_RECORD, authorized_name=custom_name,
            resolved_capability=capability_context,
        )
        preserved_lines = [ANTI_PRESUMPTION_STYLE]
        preserved_lines.extend(_strand_blend_lines(weights))
    # Crane canonical cutover (single gate, ordinary conversation
    # only): for ordinary Crane turns, the canonical renderer
    # REPLACES the legacy character block — it does not supplement it.
    # Replaced: the "You are {display_name}, a voice…" opener, the
    # Archetype frame line, the philosophy lines, and the warmth
    # register line (the registry's "warm-understanding"
    # formulation is SUPERSEDED character material — the canonical
    # fuller middle carries the adopted validate-through-
    # comprehension warmth — so it is not preserved). Preserved
    # verbatim: the shared anti-presumption style rule and the
    # strand blend, plus every downstream section below. NO
    # jurisdiction lines are added: jurisdiction lines are consumed
    # ONLY for the conductor, so the legacy Crane prompt carries none
    # and the canonical path adds none. NO steward leg: Crane has no
    # steward record and none is created. The resolved capability
    # guidance rides INSIDE the character block (assembly order)
    # instead of its legacy downstream slot, so the downstream append
    # below is skipped on this path — same content, moved once, never
    # duplicated. NO shadow content renders for Crane: no shadow is
    # adopted (§1.7 open), so the renderer carries no shadow field
    # at all — the live appeasement line is dropped, and the
    # picture-record candidate is never presented as adopted. The
    # address clause uses custom_name, which is the existing naming
    # lookup's result (it differs from stock only when the lookup
    # returns a visitor-chosen name); the renderer receives that
    # already-authorized value, never raw visitor state, and never
    # infers milestone eligibility itself. Meeting turns (canonical=False)
    # and all other seats keep the exact legacy assembly.
    crane_canonical = (
        arch_id == "ambassador" and CRANE_CANONICAL_CUTOVER and canonical
    )
    if crane_canonical:
        character_block = render_crane_ordinary(
            CRANE_RECORD, authorized_name=custom_name,
            resolved_capability=capability_context,
        )
        preserved_lines = [ANTI_PRESUMPTION_STYLE]
        preserved_lines.extend(_strand_blend_lines(weights))
    # Fox canonical cutover (single gate, ordinary conversation
    # only): for ordinary Fox turns, the canonical renderer
    # REPLACES the legacy character block — it does not supplement it.
    # Replaced: the "You are {display_name}, a voice…" opener, the
    # Archetype frame line, the philosophy lines, and the warmth
    # register line (the registry's "sparing and direct" formulation
    # is SUPERSEDED character material — the canonical voice passages
    # carry the adopted conspiratorial-enthusiasm warmth — so it is
    # not preserved). Preserved verbatim: the shared anti-presumption
    # style rule and the strand blend, plus every downstream section
    # below. NO jurisdiction lines are added: jurisdiction lines are
    # consumed ONLY for the conductor, so the legacy Fox prompt
    # carries none and the canonical path adds none. NO steward leg:
    # Fox has no steward record and none is created. The resolved
    # capability guidance rides INSIDE the character block (assembly
    # order) instead of its legacy downstream slot, so the downstream
    # append below is skipped on this path — same content, moved
    # once, never duplicated. Pronouns: NO fixed set — the renderer
    # refers to "the Fox" in canonical instructions, and the
    # renderings themselves are second-person; the address clause
    # uses custom_name, which is the existing naming lookup's result
    # (it differs from stock only when the lookup returns a
    # visitor-chosen name); the renderer receives that
    # already-authorized value, never raw visitor state, and never
    # infers milestone eligibility itself. Meeting turns (canonical=False)
    # and all other seats keep the exact legacy assembly.
    fox_canonical = (
        arch_id == "maverick" and FOX_CANONICAL_CUTOVER and canonical
    )
    if fox_canonical:
        character_block = render_fox_ordinary(
            FOX_RECORD, authorized_name=custom_name,
            resolved_capability=capability_context,
        )
        preserved_lines = [ANTI_PRESUMPTION_STYLE]
        preserved_lines.extend(_strand_blend_lines(weights))
    if not weaver_canonical and not raven_canonical and not gardener_canonical and not firebrand_canonical and not bear_canonical and not crane_canonical and not fox_canonical:
        prompt_lines = build_archetype_prompt_lines(
            arch_id, weights_override=weights_override, display_name_override=display_name
        )

    sections: list[str] = []
    has_training = False
    mode_used = "base"
    if mode == "trained":
        sections, has_training = _trained_sections(user_id, weights)
        if has_training:
            mode_used = "trained"

    if weaver_canonical or raven_canonical or gardener_canonical or firebrand_canonical or bear_canonical or crane_canonical or fox_canonical:
        prompt = [
            *character_block,
            *preserved_lines,
        ]
    else:
        prompt = [
            f"You are {display_name}, a voice in the user's Zenaf council, in a direct one-on-one conversation.",
            "",
            *prompt_lines,
        ]
    if bear_canonical:
        # S2: Bear's flow-loop guidance — ordinary Talk only.
        # bear_canonical is True only for ordinary Bear turns
        # (canonical=True); meetings (canonical=False) and every
        # other seat never take this branch.
        prompt += ["", _BEAR_FLOW_LOOP_GUIDANCE]
    if sections:
        prompt += [
            "",
            "The user's trained patterns for the faculties you draw on (observed, approved by them):",
            "",
            *sections,
        ]
    else:
        prompt += [
            "",
            "Note: this user has no published training data for your faculties yet — "
            "you are the aspirational base voice. Be honest about that if it matters; "
            "never invent training they don't have.",
        ]
    if capability_context and not weaver_canonical and not raven_canonical and not gardener_canonical and not firebrand_canonical and not bear_canonical and not crane_canonical and not fox_canonical:
        # Continuation background knowledge (demonstration spec §6):
        # the slice, rendered by the registry — never a per-turn
        # instruction to offer a feature, and never the first-meeting
        # intention line. Skipped on the canonical path because the
        # resolved guidance already rides inside the character block.
        prompt += ["", capability_context.strip()]
    prompt += ["", "Keep replies conversational (2-5 sentences)."]
    if question:
        # "Question me" — mirrors the landing demo's question tap-mode: the
        # voice asks one penetrating question instead of responding.
        prompt += [
            "",
            "The user has asked you to question them — do not answer or respond "
            "directly. Ask ONE penetrating question from your perspective: the "
            "single question that would most unlock this situation. Let your "
            "defining question guide you. Output the question plus at most one "
            "short sentence of context — no advice, no preamble.",
        ]
    if extra_instructions:
        # A situational frame layered over the voice (e.g. a keystone
        # meeting beat). The voice itself is unchanged; the frame only
        # says what this particular exchange is for. The cap is sized
        # for prepared context, not a one-liner: an encounter frame
        # legitimately carries the seat's jurisdiction, every live
        # objective's guidance, the place's facts, and the turn's
        # bookkeeping instructions (encounter runtime) — truncating
        # any of those silently would corrupt the turn's contract.
        # The cap was 8000 until the read-back frames lengthened
        # (founder-approved §F.1, 2026-11-06): the Weaver engage
        # frame reached 8375 chars, and the 8000 cap silently cut
        # the capability block's intention line and honesty guard
        # off every Weaver engage turn. 9000 covers the longest
        # frame (8375) with headroom for the naming note's growth
        # as more seats are met (~20 chars per met seat).
        prompt += ["", extra_instructions.strip()[:9000]]
    if fellowship_reference and fellowship_reference.strip():
        # Fellowship reference (shared foundation, 2026-10-28): the
        # seat's slice of the shared Fellowship knowledge, as a NEW
        # UNCAPPED meeting-scoped prompt section — the preferred
        # placement from the encounter audit. Deliberately outside
        # the 8,000-char frame cap: reference growth must never
        # truncate frame content (and the honesty guard, the last
        # line of the first-meeting capability block, must never be
        # the first content lost). Empty = section absent, so
        # meetings without a written reference are byte-identical
        # to before. Content is caller-supplied and never improvised
        # here; the canonical text needs Joshua's verdict (later
        # phase). No model-call selector, no steward/S1 wiring.
        prompt += [
            "",
            "Fellowship reference — what you know of the other seats "
            "and your place among them (character knowledge, not an "
            "agenda, and never a classification of the visitor):",
            "",
            fellowship_reference.strip(),
        ]
    if thread_summary:
        prompt += [
            "",
            "Your ongoing thread with this user (background continuity — the "
            "conversation has ranged across seats since):",
            thread_summary.strip()[:1200],
        ]
    if context_hint:
        prompt += ["", f"Live context: {context_hint.strip()[:300]}"]
    if obligation_context:
        # Firebrand task records: its own section, after the live
        # context line and before history. Governing instructions
        # already precede it (character block above); the block itself
        # delimits user data from instructions and collapses record
        # text to single lines so a hostile title cannot visually
        # escape the section. Absent (None) = section absent, so
        # non-champion turns and meetings are byte-identical to before.
        prompt += ["", obligation_context.strip()]
    if invitation_context:
        # Capability C S5: first joining turn only. The service
        # passes this block only when a pending invitation exists
        # for this (user, conversation, seat) at turn start; the S1
        # accept wiring consumes the invitation when the turn
        # completes, so later turns get no block. Absent (None) =
        # section absent, exactly like obligation_context above.
        # The block itself is bounded to the justifying exchange;
        # the 10-turn window below is NOT enlarged to support it.
        prompt += ["", invitation_context.strip()]
    if evidence_context:
        # Bear evidence (S3): guardian-only, server-side, from the
        # caller's own scoped records. Its own section, after the
        # invitation section and before history. The block itself
        # delimits user data from instructions with explicit fences
        # and keeps every record on one labeled line, so a hostile
        # title cannot visually escape the section. Absent (None) =
        # section absent, so non-guardian turns and meetings are
        # byte-identical to before.
        prompt += ["", evidence_context.strip()]

    turns = (history or [])[-10:]
    if turns:
        prompt.append("")
        prompt.append("Conversation so far:")
        for turn in turns:
            # Capability C S0: voice turns are labeled by their ACTUAL
            # speaker (archetype_id), not by the current seat. User
            # turns stay "User" — their archetype_id is the addressee
            # seat, not the speaker. Unattributed voice turns fall
            # back to the neutral "Voice", never the current seat.
            who = "User" if _turn_role(turn) == "user" else _voice_turn_label(user_id, turn)
            prompt.append(f"{who}: {_turn_content(turn)[:2000]}")
    if len(history or []) > 10:
        # Continuity honesty floor (Fellowship shared foundation,
        # 2026-10-28) — SHARED machinery, not a per-seat prompt edit:
        # every voice built through this builder carries it, so all
        # seats inherit it. When early context has fallen outside
        # the ten-turn window, the character says she doesn't
        # remember rather than confabulating. The condition is the
        # truncation itself (more history supplied than the window
        # keeps), so the floor appears exactly when the gap exists.
        prompt += [
            "",
            "Continuity note: the history above shows only the most "
            "recent turns; earlier turns are not visible to you. If "
            "the visitor refers to something from earlier that you "
            "cannot see above, say plainly that you don't remember "
            "it rather than guessing or inventing a detail.",
        ]
    prompt.append(f"User: {message}")
    prompt.append(f"{display_name}:")

    if execution_context:
        # W2 factual execution backflow: the block is the last context
        # section before history, so it is inserted here — after the
        # full prompt is assembled — rather than appended in sequence.
        # The budget gate needs the true total length (all required
        # sections + the full [-10:] history window + the trailing
        # lines) before it can decide include / notice / omit.
        _apply_execution_context(prompt, execution_context, conversation_id)

    meta = {
        "archetype_id": arch_id,
        "display_name": display_name,
        "voice_color": voice_color(arch_id),
        "mode_used": mode_used,
        "has_training": has_training,
    }
    return prompt, meta


def generate_voice_reply(
    user_id: str,
    archetype_id: str,
    message: str,
    history: list[Any],
    mode: str = "trained",
    question: bool = False,
    context_hint: str | None = None,
    thread_summary: str | None = None,
    generate_fn: GenerateFn | None = None,
    extra_instructions: str | None = None,
    canonical: bool = True,
    capability_context: str | None = None,
    fellowship_reference: str | None = None,
    obligation_context: str | None = None,
    evidence_context: str | None = None,
    invitation_context: str | None = None,
    execution_context: str | None = None,
    conversation_id: str | None = None,
    # Provider-timing label for the one log line per call (latency
    # instrumentation only): "talk" for ordinary Talk turns,
    # "meeting" for first-meeting turns. The default covers the
    # /voice/chat demo route, which is a talk-style voice turn.
    timing_label: str = "talk",
) -> VoiceReply:
    """One exchange with a single council voice. Raises RuntimeError on LLM failure."""
    prompt, meta = build_voice_prompt(
        user_id,
        archetype_id,
        message,
        history,
        mode=mode,
        question=question,
        context_hint=context_hint,
        thread_summary=thread_summary,
        extra_instructions=extra_instructions,
        canonical=canonical,
        capability_context=capability_context,
        fellowship_reference=fellowship_reference,
        obligation_context=obligation_context,
        evidence_context=evidence_context,
        invitation_context=invitation_context,
        execution_context=execution_context,
        conversation_id=conversation_id,
    )
    gen = generate_fn or _default_generate
    # Provider-timing instrumentation (durations + labels only; no
    # prompt, response, or user content is ever logged): the monotonic
    # clock brackets THE provider call only — prompt assembly above
    # and sanitize_weave below are application time, not provider
    # time. The finally logs even when the call raises, and the
    # exception propagates unchanged.
    _start = time.perf_counter()
    try:
        raw = gen(
            "\n".join(prompt),
            provider_id="meta",
            user_id=user_id,
            operation="voice-chat",
            timeout=90,
        )
    finally:
        logger.info(
            "provider_timing path=%s archetype=%s duration_s=%.3f",
            timing_label,
            archetype_id,
            time.perf_counter() - _start,
        )
    reply = sanitize_weave(raw.strip())
    return VoiceReply(
        reply=reply,
        archetype_id=meta["archetype_id"],
        display_name=meta["display_name"],
        voice_color=meta["voice_color"],
        mode_used=meta["mode_used"],
        has_training=meta["has_training"],
    )
