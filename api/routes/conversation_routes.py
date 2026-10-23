"""The conversation skeleton — one persistent conversation per user.

POST /conversation/turn   — one turn: persist user message, reply through the
                            shared voice builder, persist reply, touch the
                            seat's thread_state. Seat switches are just
                            archetype_id tags; history carries across seats.
GET  /conversation        — hydrate: oldest-first message history. This is
                            what replaces the client-sent `history` array.
GET  /conversation/suggestions — the suggestion engine's three kinds
                            (trainable moments, project proposals, mint
                            suggestions), all drafts, never filed, never
                            pushed. Cached per message watermark.
POST /conversation/meeting/*  — the keystone meetings: guided
                            first-meeting conversations on their own
                            conversation_id, driven by a stage machine
                            (local_ai/conversation/meeting.py).

All routes require auth. Nothing here writes training data.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from api.routes.auth_routes import get_current_user
from local_ai.conversation import suggestions as sugg
from local_ai.conversation.meeting import MeetingError, MeetingService, MeetingStore
from local_ai.conversation.service import ConversationService
from local_ai.conversation.store import ConversationStore
from local_ai.council.archetypes import get_archetype, stock_archetype_ids

router = APIRouter(prefix="/conversation", tags=["conversation"])

_MSG_MAX = 2000


def _store() -> ConversationStore:
    return ConversationStore()


def _service() -> ConversationService:
    return ConversationService(_store())


def _uid(current_user: dict) -> str | None:
    return (current_user or {}).get("id") or (current_user or {}).get("user_id")


class LiveContext(BaseModel):
    sheet_type: str | None = Field(default=None, max_length=64)
    sheet_id: str | None = Field(default=None, max_length=128)
    entity_type: str | None = Field(default=None, max_length=64)
    entity_id: str | None = Field(default=None, max_length=128)


class ConversationTurnBody(BaseModel):
    conversation_id: str = Field(default="skeleton", max_length=64)
    archetype_id: str = Field(max_length=32)
    message: str = Field(default="", max_length=_MSG_MAX)
    mode: str = Field(default="trained", max_length=16)  # "trained" | "base"
    question: bool = Field(default=False)
    context: LiveContext | None = None


class ConversationTurnResponse(BaseModel):
    reply: str
    conversation_id: str
    message_id: str
    archetype_id: str
    display_name: str
    voice_color: str
    mode_used: str
    has_training: bool


def _check_seat(archetype_id: str) -> str:
    arch_id = (archetype_id or "").strip().lower()
    if get_archetype(arch_id) is None or arch_id not in stock_archetype_ids():
        raise HTTPException(status_code=422, detail=f"Unknown voice: {archetype_id!r}")
    return arch_id


@router.post("/turn", response_model=ConversationTurnResponse)
def conversation_turn(
    body: ConversationTurnBody,
    current_user: dict = Depends(get_current_user),
) -> ConversationTurnResponse:
    """One turn of the persistent conversation."""
    user_id = _uid(current_user)
    if not user_id:
        raise HTTPException(status_code=401, detail="Sign in to continue the conversation.")
    arch_id = _check_seat(body.archetype_id)
    conversation_id = (body.conversation_id or "skeleton").strip() or "skeleton"

    try:
        result = _service().turn(
            user_id,
            arch_id,
            body.message,
            conversation_id=conversation_id,
            mode=body.mode,
            question=body.question,
            context=(body.context.model_dump(exclude_none=True) if body.context else None),
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    except Exception as exc:  # noqa: BLE001 — loud failure
        raise HTTPException(status_code=502, detail=f"Conversation unavailable: {exc}")

    return ConversationTurnResponse(
        reply=result.reply.reply,
        conversation_id=result.conversation_id,
        message_id=result.assistant_message["id"],
        archetype_id=result.reply.archetype_id,
        display_name=result.reply.display_name,
        voice_color=result.reply.voice_color,
        mode_used=result.reply.mode_used,
        has_training=result.reply.has_training,
    )


@router.get("")
def get_conversation(
    conversation_id: str = Query(default="skeleton", max_length=64),
    limit: int = Query(default=50, ge=1, le=200),
    current_user: dict = Depends(get_current_user),
) -> dict:
    """Hydrate the ongoing conversation (oldest first)."""
    user_id = _uid(current_user)
    if not user_id:
        raise HTTPException(status_code=401, detail="Sign in to continue the conversation.")
    cid = (conversation_id or "skeleton").strip() or "skeleton"
    messages = _service().history(user_id, cid, limit=limit)
    return {"conversation_id": cid, "messages": messages}


# ---------------------------------------------------------------------------
# Keystone meetings — guided first-meeting conversations (see
# local_ai/conversation/meeting.py). The transcript lives in the same
# conversation store under its own conversation_id; these endpoints drive
# the stage machine. MeetingError (a design-rule refusal) maps to 409.
# ---------------------------------------------------------------------------


def _meeting_service() -> MeetingService:
    return MeetingService(ConversationStore(), MeetingStore())


class MeetingStartBody(BaseModel):
    archetype_id: str = Field(max_length=32)
    keystone_index: int = Field(default=1, ge=1, le=4)


class MeetingTurnBody(BaseModel):
    archetype_id: str = Field(max_length=32)
    keystone_index: int = Field(default=1, ge=1, le=4)
    message: str = Field(default="", max_length=_MSG_MAX)


class MeetingPauseBody(BaseModel):
    archetype_id: str = Field(max_length=32)
    keystone_index: int = Field(default=1, ge=1, le=4)


def _meeting_call(fn) -> dict:
    try:
        return fn()
    except MeetingError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    except Exception as exc:  # noqa: BLE001 — loud failure
        raise HTTPException(status_code=502, detail=f"Meeting unavailable: {exc}")


@router.post("/meeting/start")
def meeting_start(body: MeetingStartBody, current_user: dict = Depends(get_current_user)) -> dict:
    """Begin or resume a keystone meeting; returns the full meeting state
    including the transcript."""
    user_id = _uid(current_user)
    if not user_id:
        raise HTTPException(status_code=401, detail="Sign in to begin the meeting.")
    arch_id = _check_seat(body.archetype_id)
    return _meeting_call(lambda: _meeting_service().start(user_id, arch_id, body.keystone_index))


@router.post("/meeting/turn")
def meeting_turn(body: MeetingTurnBody, current_user: dict = Depends(get_current_user)) -> dict:
    """One user turn inside the active meeting."""
    user_id = _uid(current_user)
    if not user_id:
        raise HTTPException(status_code=401, detail="Sign in to continue the meeting.")
    arch_id = _check_seat(body.archetype_id)
    return _meeting_call(
        lambda: _meeting_service().turn(user_id, arch_id, body.message, body.keystone_index)
    )


@router.post("/meeting/pause")
def meeting_pause(body: MeetingPauseBody, current_user: dict = Depends(get_current_user)) -> dict:
    """Set the meeting aside; it resumes at the same beat later."""
    user_id = _uid(current_user)
    if not user_id:
        raise HTTPException(status_code=401, detail="Sign in to pause the meeting.")
    arch_id = _check_seat(body.archetype_id)
    return _meeting_call(lambda: _meeting_service().pause(user_id, arch_id, body.keystone_index))


@router.get("/meeting")
def meeting_state(
    archetype_id: str = Query(max_length=32),
    keystone_index: int = Query(default=1, ge=1, le=4),
    current_user: dict = Depends(get_current_user),
) -> dict:
    """Current meeting state + transcript for hydration/resume."""
    user_id = _uid(current_user)
    if not user_id:
        raise HTTPException(status_code=401, detail="Sign in to see the meeting.")
    arch_id = _check_seat(archetype_id)
    return _meeting_call(lambda: _meeting_service().state(user_id, arch_id, keystone_index))


@router.get("/suggestions")
def get_suggestions(
    conversation_id: str = Query(default="skeleton", max_length=64),
    current_user: dict = Depends(get_current_user),
) -> dict:
    """The suggestion engine's three kinds, all drafts. Cached per message
    watermark — a repeat GET with no new messages returns the cached run."""
    user_id = _uid(current_user)
    if not user_id:
        raise HTTPException(status_code=401, detail="Sign in to continue the conversation.")
    cid = (conversation_id or "skeleton").strip() or "skeleton"
    service = _service()
    store = service.store

    latest_id = store.latest_message_id(user_id, cid)
    if latest_id:
        cached = store.get_suggestion_run(user_id, cid)
        if cached and cached["up_to_message_id"] == latest_id:
            return {
                "conversation_id": cid,
                "cached": True,
                **sugg.asdict_suggestion_payload(cached["suggestions"]),
            }

    turns = service.history(user_id, cid, limit=30)
    live_context = (turns[-1].get("context") or {}) if turns else {}
    seat_names: dict[str, str] = {}
    try:
        from local_ai.council.naming import get_display_name

        for t in turns:
            arch = t.get("archetype_id")
            if arch and arch not in seat_names:
                seat_names[arch] = get_display_name(user_id, arch)
    except Exception:
        pass

    payload = sugg.generate_suggestions(
        turns, live_context, generate_fn=None, seat_names=seat_names, user_id=user_id
    )
    payload = sugg.asdict_suggestion_payload(payload)
    if latest_id:
        store.save_suggestion_run(user_id, cid, latest_id, payload)
    return {"conversation_id": cid, "cached": False, **payload}
