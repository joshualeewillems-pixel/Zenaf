"""Multi-strand entity weighting endpoints.

People, projects, tasks, assets, and jobs carry 7-strand weight vectors —
never a single category.

PUT /entities/{entity_type}/{entity_id}/strands — record weights explicitly.
GET /entities/{entity_type}/{entity_id}/strands — read current weights
    (weights=null means never weighed — unknown is honest, never zero).
DELETE /entities/{entity_type}/{entity_id}/strands — clear a weighting.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from api.routes.auth_routes import get_current_user
from local_ai import entity_strands
from local_ai.entity_strands import ENTITY_TYPES, SOURCES

router = APIRouter(prefix="/entities", tags=["entity-strands"])


class SetWeightsBody(BaseModel):
    """Explicit strand weights for an entity."""

    weights: dict[str, float] = Field(
        description="Strand name -> weight. Keys: Voice, Logic, Eye, Ear, Hands, Heart, Compass. Must sum to 1.0."
    )
    source: str = Field(
        default="user_stated",
        description=f"One of {list(SOURCES)}. Defaults to user_stated.",
    )


class WeightingResponse(BaseModel):
    entity_id: str
    entity_type: str
    weights: dict[str, float] | None
    source: str | None
    updated_at: str
    dominant: list[tuple[str, float]] = []


def _uid(current_user: dict) -> str:
    return current_user["id"]


def _check_type(entity_type: str) -> None:
    if entity_type not in ENTITY_TYPES:
        raise HTTPException(
            status_code=404,
            detail=f"unknown entity type {entity_type!r} — expected one of {list(ENTITY_TYPES)}",
        )


@router.put("/{entity_type}/{entity_id}/strands", response_model=WeightingResponse)
def put_entity_strands(
    entity_type: str,
    entity_id: str,
    body: SetWeightsBody,
    current_user: dict = Depends(get_current_user),
):
    """Record a strand weight vector for an entity (replaces any existing)."""
    _check_type(entity_type)
    if body.source not in SOURCES:
        raise HTTPException(
            status_code=400,
            detail=f"unknown source {body.source!r} — expected one of {list(SOURCES)}",
        )
    try:
        weighting = entity_strands.set_entity_strands(
            _uid(current_user), entity_type, entity_id, body.weights, body.source
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    out = weighting.to_dict()
    out["dominant"] = weighting.dominant()
    return out


@router.get("/{entity_type}/{entity_id}/strands", response_model=WeightingResponse)
def get_entity_strands(
    entity_type: str,
    entity_id: str,
    current_user: dict = Depends(get_current_user),
):
    """Read the recorded strand weights for an entity.

    ``weights`` is null when the entity was never weighed — unknown is
    honest, never zero.
    """
    _check_type(entity_type)
    weighting = entity_strands.get_entity_strands(_uid(current_user), entity_type, entity_id)
    out = weighting.to_dict()
    out["dominant"] = weighting.dominant()
    return out


@router.delete("/{entity_type}/{entity_id}/strands")
def delete_entity_strands(
    entity_type: str,
    entity_id: str,
    current_user: dict = Depends(get_current_user),
):
    """Clear a recorded strand weighting."""
    _check_type(entity_type)
    deleted = entity_strands.clear_entity_strands(_uid(current_user), entity_type, entity_id)
    return {"entity_id": entity_id, "entity_type": entity_type, "cleared": deleted}
