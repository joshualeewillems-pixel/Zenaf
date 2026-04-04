"""
Canonical Signal model (Layer 1). Single source of truth for attention/risk/opportunity/blocker/info.
"""
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


SIGNAL_KIND = Literal["attention", "risk", "opportunity", "blocker", "info"]
SIGNAL_STATUS = Literal["new", "acknowledged", "linked", "resolved", "dismissed"]
CONFIDENCE = Literal["high", "medium", "low"]


class Signal(BaseModel):
    id: str
    kind: SIGNAL_KIND
    title: str
    detail: str | None = None
    source: str
    source_excerpt: str | None = Field(None, alias="sourceExcerpt")
    source_ref: dict[str, str] | None = Field(
        default=None,
        description="E.g. {'type': 'meeting', 'id': 'meeting-123'}",
        alias="sourceRef",
    )
    confidence: CONFIDENCE | None = None
    linked_initiative_id: str | None = Field(None, alias="linkedInitiativeId")
    linked_project_id: str | None = Field(None, alias="linkedProjectId")
    linked_task_id: str | None = Field(None, alias="linkedTaskId")
    linked_asset_ids: list[str] = Field(default_factory=list, alias="linkedAssetIds")
    status: SIGNAL_STATUS = "new"
    created_at: datetime
    updated_at: datetime

    model_config = {"populate_by_name": True}


class SignalCreate(BaseModel):
    """Payload for creating a signal (no id, created_at, updated_at)."""

    kind: SIGNAL_KIND
    title: str
    detail: str | None = None
    source: str
    source_excerpt: str | None = Field(None, alias="sourceExcerpt")
    source_ref: dict[str, str] | None = Field(None, alias="sourceRef")
    confidence: CONFIDENCE | None = None
    linked_initiative_id: str | None = Field(None, alias="linkedInitiativeId")
    linked_project_id: str | None = Field(None, alias="linkedProjectId")
    linked_task_id: str | None = Field(None, alias="linkedTaskId")
    linked_asset_ids: list[str] = Field(default_factory=list, alias="linkedAssetIds")
    status: SIGNAL_STATUS = "new"

    model_config = {"populate_by_name": True}


class SignalUpdate(BaseModel):
    """Partial update for PATCH (status, linked ids)."""

    status: SIGNAL_STATUS | None = None
    linked_initiative_id: str | None = Field(None, alias="linkedInitiativeId")
    linked_project_id: str | None = Field(None, alias="linkedProjectId")
    linked_task_id: str | None = Field(None, alias="linkedTaskId")
    linked_asset_ids: list[str] | None = Field(None, alias="linkedAssetIds")

    model_config = {"populate_by_name": True}
