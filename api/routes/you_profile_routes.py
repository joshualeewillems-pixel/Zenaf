"""Per-seat "You" profile API — the Zenaf/You switch + QC surface data.

Authenticated throughout; a user only ever sees their own echo.

Endpoints:
  GET /you-profile/{archetype_id}   composed profile: canonical seat data,
                                    the You record + its `revealed` flag
                                    (the character-card presentation stays
                                    unrevealed until keystone 4), derived
                                    recognition status (rentability lives
                                    there), and the QC "what's being
                                    fashioned" view (depth, approved signals
                                    with anchors, persona version, snapshot
                                    references) — all visible from day one
  PUT /you-profile/{archetype_id}   set the echo's identity fields
                                    (personal_name, avatar_ref,
                                    current_snapshot_id). NOT gated: the
                                    switch, the QC surface, and this record
                                    are open from day one; keystone 4 gates
                                    only the card reveal and rentability.

All heavy data is composed at read time from its ground-truth store
(depth, TrainingSignal store, PersonalityStore, vision_execution tasks);
the only persisted writes land in the YouProfileStore.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from api.routes.auth_routes import get_current_user
from local_ai.council.archetypes import stock_archetype_ids
from local_ai.you_profile.service import YouProfileService
from local_ai.you_profile.store import UNSET

router = APIRouter(prefix="/you-profile", tags=["you-profile"])


def _svc() -> YouProfileService:
    return YouProfileService()


def _uid(user: dict) -> str:
    uid = (user or {}).get("id") or (user or {}).get("user_id")
    if not uid:
        raise HTTPException(status_code=401, detail="Sign in to see your echo.")
    return uid


def _check_archetype(archetype_id: str) -> str:
    arch_id = (archetype_id or "").strip().lower()
    if arch_id not in stock_archetype_ids():
        raise HTTPException(status_code=404, detail=f"Unknown seat: {archetype_id!r}")
    return arch_id


def _http(exc: Exception) -> HTTPException:
    if isinstance(exc, PermissionError):
        return HTTPException(status_code=409, detail=str(exc))
    if isinstance(exc, ValueError):
        return HTTPException(status_code=422, detail=str(exc))
    return HTTPException(status_code=500, detail="you-profile error")


class YouProfileUpdate(BaseModel):
    """Partial update — only fields present in the body are touched.

    Explicit null clears a field (e.g. unpin a snapshot).
    """

    personal_name: str | None = Field(default=None, max_length=120)
    avatar_ref: str | None = Field(default=None, max_length=2000)
    current_snapshot_id: str | None = Field(default=None, max_length=128)


@router.get("/{archetype_id}")
def get_you_profile(archetype_id: str, user: dict = Depends(get_current_user)):
    try:
        return _svc().get_profile(_uid(user), _check_archetype(archetype_id))
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001 — loud, mapped failure
        raise _http(exc)


@router.put("/{archetype_id}")
def update_you_profile(
    archetype_id: str,
    body: YouProfileUpdate,
    user: dict = Depends(get_current_user),
):
    fields_set = body.model_fields_set
    try:
        record = _svc().update_profile(
            _uid(user),
            _check_archetype(archetype_id),
            personal_name=body.personal_name if "personal_name" in fields_set else UNSET,
            avatar_ref=body.avatar_ref if "avatar_ref" in fields_set else UNSET,
            current_snapshot_id=(
                body.current_snapshot_id
                if "current_snapshot_id" in fields_set
                else UNSET
            ),
        )
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001 — loud, mapped failure
        raise _http(exc)
    return {"ok": True, "record": record}
