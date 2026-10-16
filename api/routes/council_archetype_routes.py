"""Council archetype naming unlocks.

GET /council/archetypes/status — per-archetype training depth, rename
unlock state, and custom-archetype milestone progress.
PUT /council/archetypes/{id}/name — rename a seat. 404 for unknown ids,
403 when the rename milestone is not yet unlocked (with signals_to_unlock),
422 for invalid names.

Renaming is a display preference, not training: session auth is enough
(no train:self scope), same as the council-mode setting.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from api.routes.auth_routes import get_current_user
from local_ai.council.archetypes import get_archetype
from local_ai.council.naming import rename_status

router = APIRouter(prefix="/council/archetypes", tags=["council-archetypes"])


class RenameBody(BaseModel):
    """New display name for a council archetype seat."""

    display_name: str = Field(min_length=1, max_length=60)


def _uid(current_user: dict) -> str | None:
    return (current_user or {}).get("id") or (current_user or {}).get("user_id")


@router.get("/status")
def get_archetype_status(current_user: dict = Depends(get_current_user)):
    """Naming unlock status for every council archetype.

    For each archetype: id, display_name (custom if renamed), depth
    (depth points from approved signals), rename_unlocked, and
    signals_to_unlock (depth points still needed, 0 when unlocked).
    Also reports the all-rename and custom-archetype milestones.
    """
    return rename_status(_uid(current_user))


@router.put("/{archetype_id}/name")
def rename_archetype(
    archetype_id: str,
    body: RenameBody,
    current_user: dict = Depends(get_current_user),
):
    """Rename a council archetype seat (after its unlock milestone).

    Joshua's principle: naming is intimate — the seat's training depth
    must reach 25 depth points before it can be renamed. Returns 403 with
    signals_to_unlock when the milestone is not yet met.
    """
    arch = get_archetype(archetype_id)
    if arch is None:
        raise HTTPException(
            status_code=404, detail=f"unknown archetype {archetype_id!r}"
        )
    uid = _uid(current_user)
    status = rename_status(uid)
    entry = next((a for a in status["archetypes"] if a["id"] == arch.id), None)
    if entry is None or not entry["rename_unlocked"]:
        raise HTTPException(
            status_code=403,
            detail={
                "message": (
                    f"{arch.display_name} cannot be renamed yet — "
                    "naming unlocks after 25 depth points of training shape it."
                ),
                "signals_to_unlock": (entry or {}).get("signals_to_unlock", 25),
            },
        )
    from local_ai.personality.store import PersonalityStore

    store = PersonalityStore(user_id=uid)
    try:
        try:
            name = store.set_archetype_name(arch.id, body.display_name)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
    finally:
        store.close()
    return {"id": arch.id, "display_name": name}
