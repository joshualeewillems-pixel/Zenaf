"""Steward increment D — inspectable surface API (read-only).

Three GET endpoints over the pure read model
(``local_ai/narrative/read_model.py``):

- ``GET /steward/signals`` — grouped list, filtered, paginated.
- ``GET /steward/signals/{kind}/{signal_id}`` — per-claim drill-down.
- ``GET /steward/groups/{group_id}/members`` — bounded member pages
  for oversized groups (the list endpoint's escape hatch).
- ``GET /steward/tree-panels`` (Phase 5) — live thread state per
  seat for the Living Tree panels: active threads + latest confirmed
  change, state only, no generated prose.

Read-only by construction: no endpoint writes, transitions
delivery state, touches a clock, or moves the sweep cursor. The
route never imports the sweep, the friction pass, or any
derivation writer. Actions (accept / correct / reject / confirm /
retire / archive / split / merge / reopen) belong to increment E,
not this route. Groups are retrieval units, NOT consent units:
nothing here implies that reviewing or approving one reading
authorizes action on any other signal in its thread.

Authentication: the current user only, via ``get_current_user``
(session cookie). Unknown ids and other users' ids are
indistinguishable (both 404); there is no 403 variant and no
admin view. ``get_narrative_store`` is the injection point tests
use to substitute a tmp store (mirroring the attention route's
pattern).

Validation precedes reads (proposal §4.4): every endpoint
validates its filter/limit/cursor values BEFORE acquiring a
snapshot, so an invalid value is a 400 without a database read.
Only id-existence lookup happens after the snapshot, because
existence cannot be checked without data.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from api.routes.auth_routes import get_current_user
from local_ai.narrative.consent import steward_consent_allowed
from local_ai.narrative.read_model import (
    MEMBER_LIMIT_DEFAULT,
    MEMBER_LIMIT_MAX,
    build_signals_response,
    get_group_members,
    get_signal_detail,
    panel_thread_state,
    validate_request_params,
)
from local_ai.narrative.store import NarrativeStore

router = APIRouter(prefix="/steward", tags=["steward"])


def get_narrative_store() -> NarrativeStore:
    """Production store (default path, honoring ZENAF_DB_DIR).

    Tests monkeypatch this function to return a tmp store.
    Open-query-close per call: the route never holds a shared
    handle across requests.
    """
    return NarrativeStore()


def _build_snapshot(store: NarrativeStore, user_id: str) -> dict:
    return store.snapshot_for_read(user_id)


@router.get("/signals")
def list_signals(
    request: Request,
    current_user: dict = Depends(get_current_user),
    thread_id: str | None = Query(default=None),
    meeting_key: str | None = Query(default=None),
    seat: str | None = Query(default=None),
    scope: str | None = Query(default=None),
    kind: str | None = Query(default=None),
    delivery_status: str | None = Query(default=None),
    decline_result: str | None = Query(default=None),
    unconsulted_scope: str | None = Query(default=None),
    limit: int | None = Query(default=None),
    cursor: str | None = Query(default=None),
):
    user_id = current_user["id"]
    try:
        validate_request_params(
            kind=kind,
            delivery_status=delivery_status,
            decline_result=decline_result,
            unconsulted_scope=unconsulted_scope,
            seat=seat,
            limit=limit,
            cursor=cursor,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    store = get_narrative_store()
    try:
        snapshot = _build_snapshot(store, user_id)
        derivation_active = steward_consent_allowed(user_id)
        return build_signals_response(
            snapshot,
            user_id=user_id,
            derivation_active=derivation_active,
            thread_id=thread_id,
            meeting_key=meeting_key,
            seat=seat,
            scope=scope,
            kind=kind,
            delivery_status=delivery_status,
            decline_result=decline_result,
            unconsulted_scope=unconsulted_scope,
            limit=limit,
            cursor=cursor,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        store.close()


@router.get("/signals/{kind}/{signal_id}")
def signal_detail(
    kind: str,
    signal_id: str,
    current_user: dict = Depends(get_current_user),
):
    user_id = current_user["id"]
    try:
        validate_request_params(kind=kind)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    store = get_narrative_store()
    try:
        snapshot = _build_snapshot(store, user_id)
        return get_signal_detail(snapshot, kind=kind, signal_id=signal_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="not found") from exc
    finally:
        store.close()


@router.get("/groups/{group_id}/members")
def group_members(
    group_id: str,
    current_user: dict = Depends(get_current_user),
    kind: str | None = Query(default=None),
    delivery_status: str | None = Query(default=None),
    decline_result: str | None = Query(default=None),
    unconsulted_scope: str | None = Query(default=None),
    limit: int | None = Query(default=None),
    cursor: str | None = Query(default=None),
):
    user_id = current_user["id"]
    try:
        validate_request_params(
            kind=kind,
            delivery_status=delivery_status,
            decline_result=decline_result,
            unconsulted_scope=unconsulted_scope,
            limit=limit,
            limit_default=MEMBER_LIMIT_DEFAULT,
            limit_max=MEMBER_LIMIT_MAX,
            cursor=cursor,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    store = get_narrative_store()
    try:
        snapshot = _build_snapshot(store, user_id)
        return get_group_members(
            snapshot,
            group_id=group_id,
            kind=kind,
            delivery_status=delivery_status,
            decline_result=decline_result,
            unconsulted_scope=unconsulted_scope,
            limit=limit,
            cursor=cursor,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="not found") from exc
    finally:
        store.close()


@router.get("/tree-panels")
def tree_panels(
    current_user: dict = Depends(get_current_user),
):
    """Phase 5 tree panels: live thread state per seat, state only.

    Same owner-gated, open-query-close pattern as the other endpoints
    in this route. Seats with no active threads get an empty list, so
    the frontend renders no section there. No generated prose anywhere
    in the payload — titles, statuses, change kinds, and counts only.
    """
    user_id = current_user["id"]
    store = get_narrative_store()
    try:
        snapshot = _build_snapshot(store, user_id)
        return {"panels": panel_thread_state(snapshot)}
    finally:
        store.close()
