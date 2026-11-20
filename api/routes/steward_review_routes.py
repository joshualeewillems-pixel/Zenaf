"""Steward review verdict surface (Phase 1, addendum §4.1).

A SEPARATE router from increment D's read-only ``steward_routes``:
that route's read-only-by-construction contract stays intact, and
verdicts live here. Endpoints:

- ``GET /steward/review`` — pending steward proposals as review
  items, plus the proposal-precision metric from the store.
- ``POST /steward/review/{kind}/{row_id}/accept|reject|unresolve``
  — apply one verdict through ``local_ai/narrative/review.py``.
- ``POST /steward/review/{kind}/{row_id}/explore`` — the
  Explore-with-Aria bridge (Gate B): the user carries a pending
  progression reading, fitting, or correspondence into a strand
  thread as a strand source. No verdict, no state change on the
  proposal — exploration is a user act, not an establishment.

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
from pydantic import BaseModel

from api.routes.auth_routes import get_current_user
from local_ai.conversation.store import ConversationStore
from local_ai.narrative import review as steward_review
from local_ai.narrative.lenses import get_lens
from local_ai.narrative.store import NarrativeStore

router = APIRouter(prefix="/steward/review", tags=["steward"])


def get_narrative_store() -> NarrativeStore:
    """Production store (default path, honoring ZENAF_DB_DIR).

    Tests monkeypatch this function to return a tmp store.
    Open-query-close per call: the route never holds a shared
    handle across requests.
    """
    return NarrativeStore()


def get_conversation_store() -> ConversationStore:
    """Production conversation store (the Explore-with-Aria bridge).

    Tests monkeypatch this function to return a tmp store, exactly
    like ``get_narrative_store``.
    """
    return ConversationStore()


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


# -- Explore with Aria (Gate B recognition bridge) ---------------------------
#
# The one conversational bridge the recognition slice adds: the
# USER carries a steward proposal (progression reading, fitting,
# or correspondence) into a strand thread of their choosing, as a
# strand source, where Aria (the Weaver, conductor of the strand
# threads) can explore it with them. The act is the user's — the
# route is authenticated as them, the source is user-carried — and
# it changes no state on the proposal itself: exploration never
# establishes, endorses, or retires anything. Verdicts stay in the
# verdict endpoints above.

_EXPLORE_KINDS = ("reading", "fitting", "correspondence")
_SUMMARY_CAP = 2000


class ExploreBody(BaseModel):
    strand_key: str


def _proposal_summary(item: steward_review.ReviewItem) -> str:
    """The proposal's evidence-backed summary, as carried text."""
    payload = item.payload or {}
    if item.item_kind == "reading":
        reading = payload.get("reading") or {}
        if reading.get("kind") == "progression_candidate":
            steps = "; ".join(
                str(step.get("observation") or "")
                for step in reading.get("steps") or []
            )
            text = (
                "Steward proposal — a possible progression: "
                f"{reading.get('development_claim') or ''} "
                f"Steps: {steps}"
            )
        else:
            bits = []
            for key in ("tensions", "milestones", "open_questions"):
                values = reading.get(key) or []
                if values:
                    bits.append(f"{key}: {'; '.join(str(v) for v in values)}")
            text = "Steward proposal — a reading: " + " | ".join(bits)
    elif item.item_kind == "fitting":
        lens = get_lens(str(payload.get("lens_id") or ""))
        if lens is not None:
            text = (
                f"Steward proposal — narrative frame: {lens.name}. "
                f"{lens.source_note} Cautions: "
                + "; ".join(lens.cautions)
            )
        else:
            text = "Steward proposal — a narrative frame."
    elif item.item_kind == "correspondence":
        text = (
            "Steward proposal — a correspondence: "
            f"{payload.get('structural_tension') or ''} "
            f"Relationship: {payload.get('proposed_relationship') or ''} "
            f"Limitations: {payload.get('limitations') or ''}"
        )
    else:  # pragma: no cover - guarded by _EXPLORE_KINDS
        text = "Steward proposal."
    return text[:_SUMMARY_CAP]


@router.post("/{kind}/{row_id}/explore", status_code=200)
def explore_review_item(
    kind: str,
    row_id: str,
    body: ExploreBody,
    current_user: dict = Depends(get_current_user),
) -> dict:
    """Carry one proposal into a strand thread as a source (user act)."""
    if kind not in _EXPLORE_KINDS:
        raise HTTPException(
            status_code=400, detail=f"kind {kind!r} cannot be explored"
        )
    user_id = current_user["id"]
    store = get_narrative_store()
    conversation_store = get_conversation_store()
    try:
        item = next(
            (
                candidate
                for candidate in steward_review.pending_review_items(
                    store, user_id
                )
                if candidate.item_kind == kind
                and candidate.item_id == f"{kind}:{row_id}"
            ),
            None,
        )
        if item is None:
            # Unknown ids and other users' ids are indistinguishable.
            raise HTTPException(status_code=404, detail="unknown review item")
        summary = _proposal_summary(item)
        try:
            mapping = conversation_store.resolve_strand_thread(
                user_id, body.strand_key
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        source = conversation_store.add_strand_source(
            user_id,
            body.strand_key,
            mapping["conversation_id"],
            kind="paste",
            ref=f"steward:{kind}:{row_id}",
            label=f"Steward proposal ({kind}) — {item.title}"[:200],
            excerpt_redacted=summary,
            paste_full_text=summary,
        )
        return {
            "item_id": item.item_id,
            "strand_key": body.strand_key,
            "source": source,
        }
    finally:
        store.close()
        conversation_store.close()
