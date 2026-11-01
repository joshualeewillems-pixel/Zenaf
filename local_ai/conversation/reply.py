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

import os
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
from local_ai.council.canonical.weaver import WEAVER_RECORD
from local_ai.council.jurisdictions import jurisdiction_prompt_lines
from local_ai.council.render import render_weaver_ordinary

_MSG_MAX = 2000
_HISTORY_MAX = 20

_WEAVE_INSTRUCTION = (
    "When you genuinely echo, quote, or build directly on the user's own "
    "words or phrasing, wrap those exact words in [[u]]...[[/u]] markers. "
    "Use sparingly — only for real echoes of their language. Never wrap "
    "your own words."
)

GenerateFn = Callable[..., str]

# Weaver canonical cutover — TRIAL-ONLY environment override
# (Weaver Behavioral Trial v1, authorized 2026-11-01; reverted after
# the legacy arm). Read at import: unset (or any value other than
# "legacy") keeps the merged canonical behavior ON; explicit
# "legacy" turns it OFF for ordinary Weaver turns. Fail-closed to
# canonical. Scope is unchanged: ordinary Weaver turns only
# (weave=True); meeting turns always keep the legacy assembly.
# Reverting this change restores the constant True below it.
WEAVER_CANONICAL_CUTOVER = (
    os.environ.get("ZENAF_WEAVER_CUTOVER", "canonical").strip().lower()
    != "legacy"
)


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
    weave: bool = True,
    capability_context: str | None = None,
    fellowship_reference: str | None = None,
) -> tuple[list[str], dict[str, Any]]:
    """Assemble the prompt for one voice turn. Returns (lines, meta).

    Raises ValueError on unknown archetype or empty message (and not question).

    `capability_context` is a pre-rendered continuation block from
    local_ai/council/capabilities.py (this seat's slice as background
    knowledge ONLY — no intention line, no offer instruction). It is
    supplied by the continuation call sites (conversation service,
    voice route); first meetings never pass it, because their frames
    already carry the first-meeting block via the encounter runtime.

    `weave=False` omits the [[u]] quote-weaving instruction: the
    encounter runtime (keystone meetings) runs under the
    evidence/expression separation (Joshua's ruling, 2026-10-23) —
    dialogue synthesizes in the character's own words and is never
    required to splice the user's phrases, while exact quotations
    live in the evidence layer. Chat surfaces keep the default.
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
    # every downstream section below (trained sections, weave,
    # reply guidance, question block, extra_instructions, fellowship
    # reference, thread summary, context hint, history, continuity,
    # trailer). The resolved capability guidance rides INSIDE the
    # character block (assembly order) instead of its legacy
    # downstream slot, so the downstream append below is skipped on
    # this path — same content, moved once, never duplicated.
    # Meeting turns (weave=False) and all other seats keep the exact
    # legacy assembly.
    weaver_canonical = (
        arch_id == "conductor" and WEAVER_CANONICAL_CUTOVER and weave
    )
    if weaver_canonical:
        visitor_state = {"personal_name": custom_name} if custom_name else {}
        character_block = render_weaver_ordinary(
            WEAVER_RECORD, visitor_state, resolved_capability=capability_context
        )
        preserved_lines = [ANTI_PRESUMPTION_STYLE]
        preserved_lines.extend(jurisdiction_prompt_lines(arch_id))
        preserved_lines.extend(_strand_blend_lines(weights))
    else:
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

    if weaver_canonical:
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
    if capability_context and not weaver_canonical:
        # Continuation background knowledge (demonstration spec §6):
        # the slice, rendered by the registry — never a per-turn
        # instruction to offer a feature, and never the first-meeting
        # intention line. Skipped on the canonical path because the
        # resolved guidance already rides inside the character block.
        prompt += ["", capability_context.strip()]
    if weave:
        prompt += ["", _WEAVE_INSTRUCTION]
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
        prompt += ["", extra_instructions.strip()[:8000]]
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

    turns = (history or [])[-10:]
    if turns:
        prompt.append("")
        prompt.append("Conversation so far:")
        for turn in turns:
            who = "User" if _turn_role(turn) == "user" else display_name
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
    weave: bool = True,
    capability_context: str | None = None,
    fellowship_reference: str | None = None,
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
        weave=weave,
        capability_context=capability_context,
        fellowship_reference=fellowship_reference,
    )
    gen = generate_fn or _default_generate
    reply = sanitize_weave(
        gen(
            "\n".join(prompt),
            provider_id="meta",
            user_id=user_id,
            operation="voice-chat",
            timeout=90,
        ).strip()
    )
    return VoiceReply(
        reply=reply,
        archetype_id=meta["archetype_id"],
        display_name=meta["display_name"],
        voice_color=meta["voice_color"],
        mode_used=meta["mode_used"],
        has_training=meta["has_training"],
    )
