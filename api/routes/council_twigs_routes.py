"""Specialization twigs — proposals, approval, and listing.

GET  /council/twigs                 — list the user's twigs (proposed + approved)
POST /council/twigs/detect          — run cluster detection, create proposals
POST /council/twigs/{twig_id}/approve — approve a proposed twig
DELETE /council/twigs/{twig_id}     — remove a twig

Twigs are never auto-activated: detection only creates proposals, and only
approved twigs participate in council weaving.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from api.routes.auth_routes import get_current_user
from local_ai.council.twigs import TwigRecord, TwigStore, detect_and_propose

router = APIRouter(prefix="/council/twigs", tags=["council-twigs"])


class TwigOut(BaseModel):
    twig_id: str
    parent_id: str
    domain: str
    domain_label: str
    display_name: str
    strand_weights: dict[str, float]
    prompt_frame: str
    status: str
    signal_count: int


class DetectResponse(BaseModel):
    proposed: list[TwigOut] = Field(default_factory=list)
    message: str = ""


def _user_id(current_user: dict) -> str:
    uid = (current_user or {}).get("id") or (current_user or {}).get("user_id")
    if not uid:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return str(uid)


def _to_out(twig: TwigRecord) -> TwigOut:
    return TwigOut(
        twig_id=twig.twig_id,
        parent_id=twig.parent_id,
        domain=twig.domain,
        domain_label=twig.domain_label,
        display_name=twig.display_name,
        strand_weights={k: round(v, 4) for k, v in twig.strand_weights.items()},
        prompt_frame=twig.prompt_frame,
        status=twig.status,
        signal_count=twig.signal_count,
    )


@router.get("", response_model=list[TwigOut])
def list_twigs(current_user: dict = Depends(get_current_user)):
    """List the user's twigs, proposals first."""
    store = TwigStore()
    try:
        twigs = store.list(_user_id(current_user))
    finally:
        store.close()
    twigs.sort(key=lambda t: (t.status != "proposed", t.created_at))
    return [_to_out(t) for t in twigs]


@router.post("/detect", response_model=DetectResponse)
def detect_twigs(current_user: dict = Depends(get_current_user)):
    """Run cluster detection; create proposals for new qualifying domains.

    Existing twigs (any status) are never re-proposed.
    """
    uid = _user_id(current_user)
    store = TwigStore()
    try:
        proposed = detect_and_propose(uid, store=store)
    finally:
        store.close()
    if not proposed:
        return DetectResponse(
            proposed=[],
            message=(
                "No new domain clusters found. Clusters need 20+ approved "
                "signals in one zone with a strand pattern distinct from the "
                "stock archetypes."
            ),
        )
    return DetectResponse(
        proposed=[_to_out(t) for t in proposed],
        message=f"{len(proposed)} new twig proposal(s) ready for your review.",
    )


@router.post("/{twig_id}/approve", response_model=TwigOut)
def approve_twig(twig_id: str, current_user: dict = Depends(get_current_user)):
    """Approve a proposed twig — it now participates in council weaving."""
    uid = _user_id(current_user)
    store = TwigStore()
    try:
        twig = store.get(uid, twig_id)
        if twig is None:
            raise HTTPException(status_code=404, detail="Twig not found.")
        if twig.status != "approved":
            store.set_status(uid, twig_id, "approved")
            twig.status = "approved"
        return _to_out(twig)
    finally:
        store.close()


@router.delete("/{twig_id}")
def delete_twig(twig_id: str, current_user: dict = Depends(get_current_user)):
    """Remove a twig (proposal or approved)."""
    uid = _user_id(current_user)
    store = TwigStore()
    try:
        if not store.delete(uid, twig_id):
            raise HTTPException(status_code=404, detail="Twig not found.")
    finally:
        store.close()
    return {"deleted": twig_id}
