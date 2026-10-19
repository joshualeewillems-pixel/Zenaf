"""Per-voice chat — talk directly to one council voice.

POST /voice/chat (auth required): converse with a single archetype seat,
either as the BASE (aspirational stock) voice or the TRAINED voice (the
seat shaped by the user's approved training data). This powers the
Foundation tab's voice console: base voices show the "empty" reference,
trained voices show how each seat is coming along, and the conversation
can surface training moments for granular per-voice shaping.

Replies use the [[u]]...[[/u]] color-weave convention for user words the
voice builds on (rendered by the shared WeaveText component).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from api.routes.auth_routes import get_current_user
from local_ai.council.archetypes import (
    PLAIN_TO_KEY,
    WEIGHT_FLOOR,
    build_archetype_prompt_lines,
    compute_skeptic_weights,
    get_archetype,
    stock_archetype_ids,
    voice_color,
)

router = APIRouter(prefix="/voice", tags=["voice"])

_MSG_MAX = 2000
_HISTORY_MAX = 20

_WEAVE_INSTRUCTION = (
    "When you genuinely echo, quote, or build directly on the user's own "
    "words or phrasing, wrap those exact words in [[u]]...[[/u]] markers. "
    "Use sparingly — only for real echoes of their language. Never wrap "
    "your own words."
)


class VoiceChatTurn(BaseModel):
    role: str = Field(max_length=16)  # "user" | "voice"
    content: str = Field(max_length=4000)


class VoiceChatBody(BaseModel):
    archetype_id: str = Field(max_length=32)
    message: str = Field(default="", max_length=_MSG_MAX)
    history: list[VoiceChatTurn] = Field(default_factory=list, max_length=_HISTORY_MAX)
    mode: str = Field(default="trained", max_length=16)  # "trained" | "base"
    # "Question me" (mirrors the landing demo's tap-mode): instead of
    # responding, the voice asks the user one penetrating question from its
    # perspective. Message may be empty — the question draws on history.
    question: bool = Field(default=False)


class VoiceChatResponse(BaseModel):
    reply: str
    archetype_id: str
    display_name: str
    voice_color: str
    mode_used: str  # "trained" | "base"
    has_training: bool


def _uid(current_user: dict) -> str | None:
    return (current_user or {}).get("id") or (current_user or {}).get("user_id")


def _trained_sections(user_id: str, weights: dict[str, float]) -> tuple[list[str], bool]:
    """Render the user's trained per-strand sections for this voice's blend.

    Returns (sections, has_training). Never raises — empty training falls
    back honestly to the base voice.
    """
    try:
        from local_ai.council.naming import get_display_name  # noqa: F401
        from local_ai.personality.blend import render_user_section
        from local_ai.personality.store import PersonalityStore

        store = PersonalityStore(user_id)
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


@router.post("/chat", response_model=VoiceChatResponse)
def voice_chat(
    body: VoiceChatBody,
    current_user: dict = Depends(get_current_user),
) -> VoiceChatResponse:
    """One exchange with a single council voice (base or trained)."""
    user_id = _uid(current_user)
    if not user_id:
        raise HTTPException(status_code=401, detail="Sign in to talk to your voices.")

    arch_id = (body.archetype_id or "").strip().lower()
    arch = get_archetype(arch_id)
    if arch is None or arch_id not in stock_archetype_ids():
        raise HTTPException(status_code=422, detail=f"Unknown voice: {body.archetype_id!r}")

    message = body.message.strip()
    if not message and not body.question:
        raise HTTPException(status_code=422, detail="Message is empty.")

    mode = (body.mode or "trained").strip().lower()
    if mode not in ("trained", "base"):
        mode = "trained"

    # Display name honors the user's rename unlock; stock otherwise.
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
        weights_override = compute_skeptic_weights(user_id)
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
    if body.question:
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

    history = (body.history or [])[-10:]
    if history:
        prompt.append("")
        prompt.append("Conversation so far:")
        for turn in history:
            who = "User" if turn.role == "user" else display_name
            prompt.append(f"{who}: {turn.content[:2000]}")
    prompt.append(f"User: {message}")
    prompt.append(f"{display_name}:")

    try:
        from local_ai.agent_intake.llm_keys import generate as _generate

        reply = _generate(
            "\n".join(prompt), provider_id="meta", user_id=user_id,
            operation="voice-chat", timeout=90,
        ).strip()
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    except Exception as exc:  # noqa: BLE001 — loud failure
        raise HTTPException(status_code=502, detail=f"Voice unavailable: {exc}")

    return VoiceChatResponse(
        reply=reply,
        archetype_id=arch_id,
        display_name=display_name,
        voice_color=voice_color(arch_id),
        mode_used=mode_used,
        has_training=has_training,
    )
