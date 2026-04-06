"""
Load and resolve rows from ``ve_chat_action_coverage*.json`` for Lane A.

Keeps JSON IO and lookups out of ``direct_action_executor.py``.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterator

_REPO_ROOT = Path(__file__).resolve().parents[2]
_COVERAGE_PATH = _REPO_ROOT / "docs" / "04_REFERENCE" / "ve_chat_action_coverage.json"
_TIER1_PATH = _REPO_ROOT / "docs" / "04_REFERENCE" / "ve_chat_action_coverage_tier1.json"


@lru_cache(maxsize=1)
def load_coverage_document() -> dict[str, Any]:
    with _COVERAGE_PATH.open(encoding="utf-8") as f:
        doc = json.load(f)
    if not isinstance(doc, dict):
        return {}
    return doc


@lru_cache(maxsize=1)
def load_coverage_rows() -> tuple[dict[str, Any], ...]:
    doc = load_coverage_document()
    rows = doc.get("rows")
    if not isinstance(rows, list):
        return ()
    return tuple(r for r in rows if isinstance(r, dict))


@lru_cache(maxsize=1)
def load_tier1_coverage_rows() -> tuple[dict[str, Any], ...]:
    with _TIER1_PATH.open(encoding="utf-8") as f:
        doc = json.load(f)
    rows = doc.get("rows")
    if not isinstance(rows, list):
        return ()
    return tuple(r for r in rows if isinstance(r, dict))


def clear_coverage_caches() -> None:
    """Test hook."""
    load_coverage_document.cache_clear()
    load_coverage_rows.cache_clear()
    load_tier1_coverage_rows.cache_clear()


def iter_rows(
    *,
    tier1_only: bool = False,
    entity: str | None = None,
    surface_key: str | None = None,
    handler: str | None = None,
    lane_a_coverage: bool | None = None,
) -> Iterator[dict[str, Any]]:
    rows = load_tier1_coverage_rows() if tier1_only else load_coverage_rows()
    for r in rows:
        if entity is not None and r.get("entity") != entity:
            continue
        if surface_key is not None and r.get("surface_key") != surface_key:
            continue
        if handler is not None and r.get("handler") != handler:
            continue
        if lane_a_coverage is not None and bool(r.get("lane_a_coverage")) != lane_a_coverage:
            continue
        yield r


def find_text_append_row(entity_type: str, surface_key: str) -> dict[str, Any] | None:
    """Tier-1 row: entity + ``text_append`` handler (append-merge long text, e.g. initiative risks/deps)."""
    et = (entity_type or "").strip().lower()
    sk = (surface_key or "").strip()
    for r in load_tier1_coverage_rows():
        if r.get("handler") != "text_append":
            continue
        if r.get("entity") == et and r.get("surface_key") == sk:
            return r
    return None


def find_text_set_row(entity_type: str, surface_key: str) -> dict[str, Any] | None:
    """Tier-1 row: entity + text_set handler + exact surface_key (storage key)."""
    et = (entity_type or "").strip().lower()
    sk = (surface_key or "").strip()
    for r in load_tier1_coverage_rows():
        if r.get("handler") != "text_set":
            continue
        if r.get("entity") == et and r.get("surface_key") == sk:
            return r
    return None


def find_workflow_row(surface_key: str) -> dict[str, Any] | None:
    for r in load_tier1_coverage_rows():
        if r.get("surface_key") == surface_key:
            return r
    return None


def find_tier1_row(entity_type: str, surface_key: str) -> dict[str, Any] | None:
    et = (entity_type or "").strip().lower()
    sk = (surface_key or "").strip()
    for r in load_tier1_coverage_rows():
        if r.get("entity") == et and r.get("surface_key") == sk:
            return r
    return None


def resolve_direct_surface_action(
    *,
    parsed: dict[str, Any],
    entity_id: str | None,
    entity_type: str | None,
    context: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """
    Map a normalized parse payload + scoped entity to a single coverage row, or None.

    ``parsed`` comes from ``direct_action_parsing.parse_direct_action_intent``.
    """
    kind = parsed.get("kind")
    et = (entity_type or "").strip().lower() if entity_type else None
    eid = (entity_id or "").strip() if entity_id else None

    if kind == "text_set":
        if not eid or not et:
            return None
        sk = str(parsed.get("surface_key") or "").strip()
        if not sk:
            return None
        return find_text_set_row(et, sk)

    if kind == "text_append":
        if not eid or not et:
            return None
        sk = str(parsed.get("surface_key") or "").strip()
        if not sk:
            return None
        row = find_text_append_row(et, sk)
        if row:
            return row
        if sk == "notes" and et == "initiative":
            notes = find_tier1_row(et, "notes")
            if notes and str(notes.get("handler") or "") == "text_set":
                return notes
        return None

    if kind == "child_create_project":
        if et != "initiative" or not eid:
            return None
        return find_workflow_row("workflow:create_project")

    if kind == "child_create_tasks":
        return find_workflow_row("workflow:create_task_under_project")

    if kind == "person_assign":
        if not eid or not et:
            return None
        if et == "task":
            sk = "assignee_id"
        elif et in ("initiative", "project"):
            sk = "owner_id"
        else:
            return None
        return find_tier1_row(et, sk)

    if kind == "enum_set":
        if not eid or not et:
            return None
        sk = str(parsed.get("surface_key") or "").strip()
        if sk not in ("status", "priority"):
            return None
        if et == "initiative" and sk == "priority":
            return None
        if et == "idea" and sk != "status":
            return None
        return find_tier1_row(et, sk)

    if kind == "collection_add":
        if not eid or not et:
            return None
        sk = str(parsed.get("surface_key") or "").strip()
        if et != "initiative":
            return None
        if sk != "execution_steps":
            return None
        return find_tier1_row(et, sk)

    return None
