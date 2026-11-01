"""Per-voice chat — talk directly to one council voice.

POST /voice/chat (auth required): converse with a single archetype seat,
either as the BASE (aspirational stock) voice or the TRAINED voice (the
seat shaped by the user's approved training data). This powers the
Foundation tab's voice console: base voices show the "empty" reference,
trained voices show how each seat is coming along, and the conversation
can surface training moments for granular per-voice shaping.

The reply is built by the shared builder in local_ai/conversation/reply.py —
the same builder POST /conversation/turn uses. Passing `conversation_id`
joins the persistent skeleton: the server loads history from the store
(instead of the client-sent `history` array) and persists both turns.

Replies use the [[u]]...[[/u]] color-weave convention for user words the
voice builds on (rendered by the shared WeaveText component).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from api.routes.auth_routes import get_current_user
from local_ai.conversation.reply import generate_voice_reply
from local_ai.conversation.store import ConversationStore
from local_ai.council import capabilities as CAP
from local_ai.council.archetypes import get_archetype, stock_archetype_ids
from local_ai.narrative.context import weaver_context_provider

router = APIRouter(prefix="/voice", tags=["voice"])

_MSG_MAX = 2000
_HISTORY_MAX = 20


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
    # Join the persistent conversation skeleton: when present, the server
    # loads the last turns from the store (the client-sent `history` array
    # is ignored) and persists both turns of this exchange.
    conversation_id: str | None = Field(default=None, max_length=64)


class VoiceChatResponse(BaseModel):
    reply: str
    archetype_id: str
    display_name: str
    voice_color: str
    mode_used: str  # "trained" | "base"
    has_training: bool


def _uid(current_user: dict) -> str | None:
    return (current_user or {}).get("id") or (current_user or {}).get("user_id")


def _conversation_store() -> ConversationStore:
    return ConversationStore()


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

    store: ConversationStore | None = None
    conversation_id: str | None = None
    history: list[VoiceChatTurn] = []
    thread_summary: str | None = None
    if body.conversation_id:
        # Skeleton mode: server-side history is the source of truth.
        conversation_id = (body.conversation_id or "skeleton").strip() or "skeleton"
        store = _conversation_store()
        store.ensure_conversation(user_id, conversation_id)
        for m in store.history(user_id, conversation_id, limit=10):
            history.append(
                VoiceChatTurn(role=m["role"], content=m["body"])
            )
        thread_summary = (
            store.get_thread_state(user_id, conversation_id, arch_id)["summary"] or None
        )
    else:
        history = (body.history or [])[-10:]

    try:
        # Phase 2 steward (Weaver only, same provider seam as
        # POST /conversation/turn): prepared steward context
        # travels as extra_instructions inside the existing prompt
        # budget — no new generation. Every other seat's call is
        # unchanged, and any provider failure degrades to no
        # context, never a failed turn.
        steward_block = None
        if arch_id == "conductor":
            try:
                steward_block = weaver_context_provider()(
                    user_id, message, history
                )
            except Exception:
                steward_block = None
        voice_reply = generate_voice_reply(
            user_id,
            arch_id,
            message,
            history,
            mode=body.mode,
            question=body.question,
            thread_summary=thread_summary,
            extra_instructions=steward_block,
            # Continuation background knowledge (demonstration spec
            # §6): this seat's slice, resolved from the visitor's
            # actual state — no intention line, no offer instruction.
            capability_context=CAP.continuation_block(
                arch_id, CAP.resolve_visitor_state(user_id)),
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    except Exception as exc:  # noqa: BLE001 — loud failure
        raise HTTPException(status_code=502, detail=f"Voice unavailable: {exc}")

    if store is not None and conversation_id is not None:
        mode_used = voice_reply.mode_used
        store.append_message(
            user_id, conversation_id, arch_id, "user", message, mode=body.mode
        )
        store.append_message(
            user_id, conversation_id, arch_id, "voice", voice_reply.reply, mode=mode_used
        )
        # Touch the seat's thread (counter only; rolling summaries refresh on
        # the /conversation/turn path to keep /voice/chat latency unchanged).
        try:
            store.update_thread_state(user_id, conversation_id, arch_id, increment=1)
        except Exception:
            pass

    return VoiceChatResponse(
        reply=voice_reply.reply,
        archetype_id=voice_reply.archetype_id,
        display_name=voice_reply.display_name,
        voice_color=voice_reply.voice_color,
        mode_used=voice_reply.mode_used,
        has_training=voice_reply.has_training,
    )
