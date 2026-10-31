"""Per-response feedback — v1: inert records only.

POST /feedback — one record per explicit widget submit. The frontend sends
nothing until the user submits, so an untouched widget stores nothing.
GET  /feedback — list the user's records, newest first, optionally for one
                 thread. This read path is the whole v1 surfacing: the
                 records exist as data for a future review-queue tie-in.

Deliberately NOT in v1: review-queue analysis or discussion, any training
consequence, preference/profile writes, review-gate changes, mandatory
interaction, or any inference from slider values alone. Nothing here writes
training data, and nothing here changes what a seat says or what is
approved.

All routes require auth. Rows are strictly per-user.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from api.routes.auth_routes import get_current_user
from local_ai.council.archetypes import get_archetype, stock_archetype_ids
from local_ai.feedback.store import FeedbackStore

router = APIRouter(prefix="/feedback", tags=["feedback"])

# The design doc's six proposed presets, adopted as the v1 set. The server
# rejects any check outside this set so a record's checks always mean one
# of these user-visible options.
FEEDBACK_PRESETS = [
    "Sounds like me",
    "Sounds like the seat",
    "Helpful",
    "Missed the mark",
    "Tone feels off",
    "Want more of this",
]

_NOTE_MAX = 2000


def _store() -> FeedbackStore:
    return FeedbackStore()


def _uid(current_user: dict) -> str | None:
    return (current_user or {}).get("id") or (current_user or {}).get("user_id")


def _check_seat(seat: str) -> str:
    seat_id = (seat or "").strip().lower()
    if get_archetype(seat_id) is None or seat_id not in stock_archetype_ids():
        raise HTTPException(status_code=422, detail=f"Unknown voice: {seat!r}")
    return seat_id


class FeedbackBody(BaseModel):
    response_ref: str = Field(min_length=1, max_length=256)
    conversation_id: str = Field(default="local", max_length=64)
    seat: str = Field(max_length=32)
    slider: int = Field(ge=1, le=7)
    checks: list[str] = Field(default_factory=list)
    note: str = Field(default="", max_length=_NOTE_MAX)


@router.post("")
def submit_feedback(
    body: FeedbackBody,
    current_user: dict = Depends(get_current_user),
) -> dict:
    """Store exactly one feedback record for one explicit widget submit."""
    user_id = _uid(current_user)
    if not user_id:
        raise HTTPException(status_code=401, detail="Sign in to leave feedback.")
    seat_id = _check_seat(body.seat)
    response_ref = body.response_ref.strip()
    if not response_ref:
        raise HTTPException(status_code=422, detail="response_ref is empty.")
    for check in body.checks:
        if check not in FEEDBACK_PRESETS:
            raise HTTPException(status_code=422, detail=f"Unknown feedback option: {check!r}")
    return _store().add_feedback(
        user_id,
        response_ref,
        (body.conversation_id or "local").strip() or "local",
        seat_id,
        body.slider,
        list(body.checks),
        body.note,
    )


@router.get("")
def list_feedback(
    conversation_id: str | None = Query(default=None, max_length=64),
    limit: int = Query(default=50, ge=1, le=200),
    current_user: dict = Depends(get_current_user),
) -> dict:
    """The user's feedback records, newest first."""
    user_id = _uid(current_user)
    if not user_id:
        raise HTTPException(status_code=401, detail="Sign in to see feedback.")
    cid = (conversation_id or "").strip() or None
    return {"records": _store().list_feedback(user_id, cid, limit=limit)}
