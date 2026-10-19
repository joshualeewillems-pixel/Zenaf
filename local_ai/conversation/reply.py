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

from dataclasses import dataclass
from typing import Any, Callable

from local_ai.agent_intake.llm_keys import generate as _default_generate
from local_ai.council.archetypes import (
    PLAIN_TO_KEY,
    WEIGHT_FLOOR,
    build_archetype_prompt_lines,
    compute_skeptic_weights,
    get_archetype,
    stock_archetype_ids,
    voice_color,
)

_MSG_MAX = 2000
_HISTORY_MAX = 20

_WEAVE_INSTRUCTION = (
    "When you genuinely echo, quote, or build directly on the user's own "
    "words or phrasing, wrap those exact words in [[u]]...[[/u]] markers. "
    "Use sparingly — only for real echoes of their language. Never wrap "
    "your own words."
)

GenerateFn = Callable[..., str]


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
) -> tuple[list[str], dict[str, Any]]:
    """Assemble the prompt for one voice turn. Returns (lines, meta).

    Raises ValueError on unknown archetype or empty message (and not question).
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
    try:
        from local_ai.council.naming import get_display_name

        custom = get_display_name(user_id, arch.id)
        if custom:
            display_name = custom
    except Exception:
        pass

    weights_override = None
    if arch.strand_weights is None:
        weights_override = compute_skeptic_weights(user_id, mode=mode)
    weights = weights_override if weights_override is not None else (arch.strand_weights or {})

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
    prompt += ["", _WEAVE_INSTRUCTION, "", "Keep replies conversational (2-5 sentences)."]
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
    )
    gen = generate_fn or _default_generate
    reply = gen(
        "\n".join(prompt),
        provider_id="meta",
        user_id=user_id,
        operation="voice-chat",
        timeout=90,
    ).strip()
    return VoiceReply(
        reply=reply,
        archetype_id=meta["archetype_id"],
        display_name=meta["display_name"],
        voice_color=meta["voice_color"],
        mode_used=meta["mode_used"],
        has_training=meta["has_training"],
    )
