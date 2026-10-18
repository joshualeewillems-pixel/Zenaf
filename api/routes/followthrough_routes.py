"""Follow-through engine API — watchers, nudges, commitments, growth states.

Authenticated throughout. ``GET /followthrough/nudges`` is the feed the future
today-aggregate consumes; its response schema is the stable integration
contract — keep it backward compatible.

Endpoints:
  GET    /followthrough/nudges                        ranked live nudges
  POST   /followthrough/nudges/{id}/ack                acknowledge a nudge
  POST   /followthrough/nudges/{id}/snooze            snooze a nudge {until}
  POST   /followthrough/commitments                   capture a commitment
  GET    /followthrough/commitments                    list commitments
  PATCH  /followthrough/commitments/{id}/link          link to a task {task_id}
  PATCH  /followthrough/commitments/{id}               set status {status}
  GET    /followthrough/entities/{type}/{id}/growth    read growth state
  PATCH  /followthrough/entities/{type}/{id}/growth    set growth state {state}
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from api.routes.auth_routes import get_current_user
from local_ai.followthrough.service import FollowthroughService
from local_ai.followthrough.store import FollowthroughStore

router = APIRouter(prefix="/followthrough", tags=["followthrough"])


def _svc() -> FollowthroughService:
    return FollowthroughService(FollowthroughStore())


def _uid(user: dict) -> str:
    return user["id"]


def _http(exc: Exception) -> HTTPException:
    if isinstance(exc, KeyError):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, PermissionError):
        return HTTPException(status_code=403, detail=str(exc))
    if isinstance(exc, ValueError):
        return HTTPException(status_code=422, detail=str(exc))
    return HTTPException(status_code=500, detail="follow-through error")


# -- request models -----------------------------------------------------------


class SnoozeBody(BaseModel):
    until: str = Field(..., description="ISO timestamp; must be in the future")


class CommitmentBody(BaseModel):
    text: str
    source_quote: str | None = None


class LinkBody(BaseModel):
    task_id: str


class CommitmentStatusBody(BaseModel):
    status: str = Field(..., description="open | done | dismissed")


class GrowthBody(BaseModel):
    state: str | None = Field(
        None, description="seed | sprout | sapling | bloom | fruit, or null to clear"
    )


# -- nudges -------------------------------------------------------------------


@router.get("/nudges")
def get_nudges(user: dict = Depends(get_current_user)):
    try:
        return {"nudges": _svc().compute_nudges(_uid(user))}
    except Exception as exc:  # noqa: BLE001 — thin translation layer
        raise _http(exc)


@router.post("/nudges/{nudge_id}/ack")
def ack_nudge(nudge_id: str, user: dict = Depends(get_current_user)):
    try:
        return _svc().ack_nudge(_uid(user), nudge_id)
    except Exception as exc:  # noqa: BLE001
        raise _http(exc)


@router.post("/nudges/{nudge_id}/snooze")
def snooze_nudge(
    nudge_id: str, body: SnoozeBody, user: dict = Depends(get_current_user)
):
    try:
        return _svc().snooze_nudge(_uid(user), nudge_id, body.until)
    except Exception as exc:  # noqa: BLE001
        raise _http(exc)


# -- commitments ---------------------------------------------------------------


@router.post("/commitments")
def create_commitment(body: CommitmentBody, user: dict = Depends(get_current_user)):
    try:
        return _svc().create_commitment(_uid(user), body.text, body.source_quote)
    except Exception as exc:  # noqa: BLE001
        raise _http(exc)


@router.get("/commitments")
def list_commitments(
    status: str | None = None, user: dict = Depends(get_current_user)
):
    try:
        if status and status not in ("open", "done", "dismissed"):
            raise ValueError(f"unknown status {status!r}")
        return {"commitments": _svc().list_commitments(_uid(user), status)}
    except Exception as exc:  # noqa: BLE001
        raise _http(exc)


@router.patch("/commitments/{commitment_id}/link")
def link_commitment(
    commitment_id: str, body: LinkBody, user: dict = Depends(get_current_user)
):
    try:
        return _svc().link_commitment(_uid(user), commitment_id, body.task_id)
    except Exception as exc:  # noqa: BLE001
        raise _http(exc)


@router.patch("/commitments/{commitment_id}")
def set_commitment_status(
    commitment_id: str,
    body: CommitmentStatusBody,
    user: dict = Depends(get_current_user),
):
    try:
        return _svc().set_commitment_status(_uid(user), commitment_id, body.status)
    except Exception as exc:  # noqa: BLE001
        raise _http(exc)


# -- growth states --------------------------------------------------------------


@router.get("/entities/{entity_type}/{entity_id}/growth")
def get_growth(
    entity_type: str, entity_id: str, user: dict = Depends(get_current_user)
):
    try:
        return _svc().get_growth_state(_uid(user), entity_type, entity_id)
    except Exception as exc:  # noqa: BLE001
        raise _http(exc)


@router.patch("/entities/{entity_type}/{entity_id}/growth")
def set_growth(
    entity_type: str,
    entity_id: str,
    body: GrowthBody,
    user: dict = Depends(get_current_user),
):
    try:
        return _svc().set_growth_state(_uid(user), entity_type, entity_id, body.state)
    except Exception as exc:  # noqa: BLE001
        raise _http(exc)
