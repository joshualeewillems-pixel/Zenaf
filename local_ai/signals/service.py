"""
Signal service (Layer 1). Create, list, update. API uses these.
"""
from __future__ import annotations

from typing import Any

from . import models as Mod
from . import storage as St


def create_signals(items: list[Mod.SignalCreate]) -> list[dict[str, Any]]:
    """Bulk create signals. Returns list of created signal dicts (snake_case)."""
    payloads = []
    for item in items:
        payloads.append({
            "kind": item.kind,
            "title": item.title,
            "detail": item.detail,
            "source": item.source,
            "source_excerpt": item.source_excerpt,
            "source_ref": item.source_ref,
            "confidence": item.confidence,
            "linked_initiative_id": item.linked_initiative_id,
            "linked_project_id": item.linked_project_id,
            "linked_task_id": item.linked_task_id,
            "status": item.status,
        })
    return St.create_signals_bulk(payloads)


def list_signals(
    *,
    status_in: list[str] | None = None,
    status_not_in: list[str] | None = None,
    source: str | None = None,
) -> list[dict[str, Any]]:
    """List signals with optional filters."""
    return St.list_signals(status_in=status_in, status_not_in=status_not_in, source=source)


def update_signal(signal_id: str, patch: Mod.SignalUpdate) -> dict[str, Any] | None:
    """Update status and/or linked ids. Returns updated signal or None."""
    p = patch.model_dump(by_alias=False, exclude_none=True)
    return St.update_signal(signal_id, p)
