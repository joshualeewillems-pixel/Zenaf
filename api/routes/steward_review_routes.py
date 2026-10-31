"""Steward review verdict surface (Phase 1, addendum §4.1).

A SEPARATE router from increment D's read-only ``steward_routes``:
that route's read-only-by-construction contract stays intact, and
verdicts live here. Endpoints:

- ``GET /steward/review`` — pending steward proposals as review
  items, plus the proposal-precision metric from the store.
- ``POST /steward/review/{kind}/{row_id}/accept|reject|unresolve``
  — apply one verdict through ``local_ai/narrative/review.py``.

Authentication mirrors ``steward_routes``: the current user only,
via ``get_current_user``. Unknown ids and other users' ids are
indistinguishable (both 404); there is no 403 variant and no admin
view. ``get_narrative_store`` is the injection point tests use to
substitute a tmp store.

No thread HTTP endpoints are added: review items carry their
thread context inline, so verdicts need no thread read endpoints
in Phase 1 (those belong to Phase 5's tree expression, if at all).

No foreground generation happens on any path here: verdicts are
store transitions + an append-only log row.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from api.routes.auth_routes import get_current_user
from local_ai.narrative import review as steward_review
from local_ai.narrative.store import NarrativeStore

router = APIRouter(prefix="/steward/review", tags=["steward"])


def get_narrative_store() -> NarrativeStore:
    """Production store (default path, honoring ZENAF_DB_DIR).

    Tests monkeypatch this function to return a tmp store.
    Open-query-close per call: the route never holds a shared
    handle across requests.
    """
    return NarrativeStore()


def _item_to_dict(item: steward_review.ReviewItem) -> dict:
    return {
        "item_id": item.item_id,
        "item_kind": item.item_kind,
        "thread_id": item.thread_id,
        "surface": item.surface,
        "status": item.status,
        "title": item.title,
        "payload": item.payload,
    }


def _apply(
    store: NarrativeStore, user_id: str, kind: str, row_id: str, verdict: str
) -> dict:
    try:
        item = steward_review.apply_verdict(
            store, user_id, f"{kind}:{row_id}", verdict
        )
    except ValueError as exc:
        message = str(exc)
        if message.startswith("no pending review item"):
            # Unknown ids and other users' ids are indistinguishable:
            # identical 404, no id in the detail.
            raise HTTPException(
                status_code=404, detail="unknown review item"
            ) from exc
        raise HTTPException(status_code=400, detail=message) from exc
    return _item_to_dict(item)


@router.get("")
def list_review_items(
    current_user: dict = Depends(get_current_user),
) -> dict:
    """Pending steward proposals + proposal precision, current user only."""
    user_id = current_user["id"]
    store = get_narrative_store()
    try:
        items = steward_review.pending_review_items(store, user_id)
        return {
            "items": [_item_to_dict(item) for item in items],
            "precision": store.proposal_precision(user_id),
        }
    finally:
        store.close()


@router.post("/{kind}/{row_id}/accept", status_code=200)
def accept_review_item(
    kind: str,
    row_id: str,
    current_user: dict = Depends(get_current_user),
) -> dict:
    """Accept one steward proposal — confirms it as standing state."""
    store = get_narrative_store()
    try:
        return _apply(store, current_user["id"], kind, row_id, "accepted")
    finally:
        store.close()


@router.post("/{kind}/{row_id}/reject", status_code=200)
def reject_review_item(
    kind: str,
    row_id: str,
    current_user: dict = Depends(get_current_user),
) -> dict:
    """Reject one steward proposal — terminal, durable, logged."""
    store = get_narrative_store()
    try:
        return _apply(store, current_user["id"], kind, row_id, "rejected")
    finally:
        store.close()


@router.post("/{kind}/{row_id}/unresolve", status_code=200)
def unresolve_review_item(
    kind: str,
    row_id: str,
    current_user: dict = Depends(get_current_user),
) -> dict:
    """Leave one steward proposal explicitly undecided — recorded, not skipped."""
    store = get_narrative_store()
    try:
        return _apply(store, current_user["id"], kind, row_id, "unresolved")
    finally:
        store.close()
