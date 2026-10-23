"""Council jurisdiction registry — read-only exposure.

GET /council/jurisdictions — every seat's jurisdiction record.
GET /council/jurisdictions/{archetype_id} — one seat's record
(404 for unknown ids).

The records are canonical character data (local_ai/council/
jurisdictions.py): focus, periphery, conflicts, register. Static and
user-independent — the same for every user — so session auth is enough,
same as the council archetype naming routes. Nothing here writes;
jurisdictions change by code review, not by request.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from api.routes.auth_routes import get_current_user
from local_ai.council.jurisdictions import (
    SEAT_JURISDICTIONS,
    get_jurisdiction,
    jurisdiction_as_dict,
    jurisdiction_ids,
)

router = APIRouter(prefix="/council/jurisdictions", tags=["council-jurisdictions"])


@router.get("")
def list_jurisdictions(current_user: dict = Depends(get_current_user)):
    """Every seat's jurisdiction record, in canonical seat order."""
    return {
        "jurisdictions": [
            jurisdiction_as_dict(SEAT_JURISDICTIONS[seat_id])
            for seat_id in jurisdiction_ids()
        ]
    }


@router.get("/{archetype_id}")
def get_jurisdiction_record(
    archetype_id: str,
    current_user: dict = Depends(get_current_user),
):
    """One seat's jurisdiction record. 404 for unknown archetype ids."""
    record = get_jurisdiction(archetype_id)
    if record is None:
        raise HTTPException(
            status_code=404, detail=f"unknown archetype {archetype_id!r}"
        )
    return jurisdiction_as_dict(record)
