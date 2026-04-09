"""
In-memory queue for intake items. Raw content is never stored; only structured items.
Supports status (new/reviewed/done), notes, assigned_to for operational use.
For production, replace with a proper DB or task queue.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .pipeline import IntakeItem

# Order of ids (newest last); item dicts by id for updates
_order: list[str] = []
_items: dict[str, dict[str, Any]] = {}


def add_item(item: "IntakeItem") -> None:
    d = item.to_dict()
    _items[item.id] = d
    _order.append(item.id)
    try:
        from . import mirror
        sanitized = getattr(item, "sanitized_body", None) or ""
        mirror.upsert_item(d, sanitized_body_text=sanitized if sanitized else None)
        mirror.upsert_judgment_chain_for_entity(item.id)
    except Exception:
        pass  # do not fail add_item if mirror is unavailable


def get_queue(
    limit: int = 100,
    *,
    lane: str | None = None,
    status: str | None = None,
    search: str | None = None,
    sort: str = "created_desc",
    include_archived: bool = False,
) -> list[dict[str, Any]]:
    """
    Return queue items with optional filters and sort.
    lane: filter by lane id; status: filter by status; search: substring in subject + summary (case-insensitive).
    sort: created_desc (newest first) or created_asc (oldest first).
    include_archived: if False (default), exclude items with archived=True (internal hide in Zenaf only).
    """
    ids = list(_order)
    items = [_items[i] for i in ids if i in _items]

    if not include_archived:
        items = [d for d in items if not d.get("archived")]

    if lane is not None and lane.strip():
        lane_val = lane.strip().lower()
        items = [d for d in items if (d.get("lane") or "").lower() == lane_val]
    if status is not None and status.strip():
        status_val = status.strip().lower()
        items = [d for d in items if (d.get("status") or "").lower() == status_val]
    if search is not None and search.strip():
        q = search.strip().lower()
        items = [
            d
            for d in items
            if q in (d.get("subject") or "").lower() or q in (d.get("summary") or "").lower()
        ]

    # Sort by created_at
    def _created_key(d: dict[str, Any]) -> str:
        return (d.get("created_at") or "") or ""

    items.sort(key=_created_key, reverse=(sort != "created_asc"))

    return items[: max(1, min(500, limit))]


def get_item(item_id: str) -> dict[str, Any] | None:
    return _items.get(item_id)


def get_by_external_id(external_id: str) -> dict[str, Any] | None:
    """Return the first queue item with this external_id, or None. Used for duplicate prevention."""
    if not external_id:
        return None
    for iid in _order:
        if _items.get(iid, {}).get("external_id") == external_id:
            return _items[iid]
    return None


def update_item(
    item_id: str,
    *,
    status: str | None = None,
    notes: str | None = None,
    assigned_to: str | None = None,
    lane_override: str | None = None,
    correction_note: str | None = None,
    archived: bool | None = None,
) -> dict[str, Any] | None:
    """
    Update status, notes, assigned_to, or archived. If lane_override and correction_note are provided,
    record a correction in the judgment layer and set lane_override and judgment_id on the item.
    archived=True hides the item from default queue list (internal Zenaf only; no mailbox change).
    """
    if item_id not in _items:
        return None
    d = _items[item_id]
    if status is not None:
        d["status"] = status
    if archived is not None:
        d["archived"] = bool(archived)
    if notes is not None:
        d["notes"] = notes
    if assigned_to is not None:
        d["assigned_to"] = assigned_to
    if lane_override is not None:
        d["lane_override"] = lane_override
    # Only create a correction record when setting a non-empty lane override (not when clearing)
    if (
        lane_override is not None
        and (lane_override or "").strip()
        and correction_note is not None
        and (correction_note or "").strip()
    ):
        from local_ai.judgment import create_correction_record
        prev_judgment_id = (d.get("judgment_id") or "").strip()
        if prev_judgment_id:
            new_record = create_correction_record(
                entity_id=item_id,
                supersedes_judgment_id=prev_judgment_id,
                proposed_action_override={"lane": lane_override.strip()},
                correction_note=correction_note.strip(),
            )
            d["judgment_id"] = new_record.id
    try:
        from . import mirror
        mirror.upsert_item(d)
        mirror.upsert_judgment_chain_for_entity(item_id)
    except Exception:
        pass
    return d


def clear_queue() -> None:
    _order.clear()
    _items.clear()


def replace_with_items(items: list[dict[str, Any]]) -> None:
    """
    Replace in-memory queue with the given items (e.g. from persistent mirror).
    Each dict must have 'id'; order of list is preserved for _order.
    """
    _order.clear()
    _items.clear()
    for d in items:
        iid = d.get("id")
        if iid:
            _items[iid] = d
            _order.append(iid)
