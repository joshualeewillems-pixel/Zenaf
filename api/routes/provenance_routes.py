"""Minting & provenance API: the butterfly-effect ledger.

Authenticated throughout — engagement actors are recorded only inside the
authenticated ecosystem (spec §8). All money/pricing is out of scope;
this is the registry, the derivation DAG, engagement events, reach scores,
import fingerprinting, and creatorship disputes.

Endpoints:
  POST /provenance/register            register an image artifact (unlisted)
  POST /provenance/{id}/mint           the mint act: unlisted -> private
  POST /provenance/{id}/publish        explicit public
  POST /provenance/derive              register a child with parent link(s)
  POST /provenance/links/approve       parent creator approves a pending derivation
  POST /provenance/events              log an engagement event
  GET  /provenance/artifacts/{id}      artifact detail (visibility-gated)
  GET  /provenance/artifacts/{id}/lineage   tree + downstream timeline
  GET  /provenance/ledger              per-user ledger + perspective_reach
  POST /provenance/recompute           batch recompute of cached reach
  POST /provenance/ingest              fingerprint at ingestion (exact/near/none)
  POST /provenance/ingest/{id}/confirm-link   confirm a near-match derivation
  POST /provenance/disputes            challenge a creatorship claim
  POST /provenance/disputes/{id}/resolve   admin resolution
  GET  /provenance/disputes            list disputes (admin)
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from api.routes.auth_routes import get_current_admin_user, get_current_user
from local_ai.provenance import service as prov
from local_ai.provenance.store import ProvenanceStore

router = APIRouter(prefix="/provenance", tags=["provenance"])


def _store() -> ProvenanceStore:
    return ProvenanceStore()


def _user_id(user: dict) -> str:
    return user["id"]


def _http(exc: Exception) -> HTTPException:
    if isinstance(exc, KeyError):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, PermissionError):
        return HTTPException(status_code=403, detail=str(exc))
    if isinstance(exc, ValueError):
        return HTTPException(status_code=422, detail=str(exc))
    return HTTPException(status_code=500, detail="provenance error")


# -- request models -------------------------------------------------------


class RegisterBody(BaseModel):
    image_base64: str = Field(description="Image bytes as base64 (data: URL ok)")
    title: str = ""
    description: str = ""
    archetype_cast: list[str] = Field(default_factory=list)
    source_hash: str | None = None
    remix_policy: str = "open"


class DeriveBody(BaseModel):
    parent_ids: list[str]
    image_base64: str | None = None
    title: str = ""
    description: str = ""
    archetype_cast: list[str] = Field(default_factory=list)


class ApproveBody(BaseModel):
    parent_id: str
    child_id: str


class EventBody(BaseModel):
    artifact_id: str
    type: str
    context: dict[str, Any] = Field(default_factory=dict)


class IngestBody(BaseModel):
    image_base64: str
    title: str = ""
    description: str = ""
    claim_creator: bool = False


class ConfirmLinkBody(BaseModel):
    parent_id: str


class DisputeBody(BaseModel):
    artifact_id: str
    evidence: str = ""


class ResolveBody(BaseModel):
    outcome: str = Field(description="verified | rejected | disputed")
    resolution_note: str = ""


# -- registration / minting -------------------------------------------------


@router.post("/register")
def register(body: RegisterBody, user: dict = Depends(get_current_user)):
    try:
        return prov.register_artifact(
            _store(),
            image_base64=body.image_base64,
            creator_user_id=_user_id(user),
            title=body.title,
            description=body.description,
            archetype_cast=body.archetype_cast,
            source_hash=body.source_hash,
            remix_policy=body.remix_policy,
        )
    except Exception as exc:
        raise _http(exc)


@router.post("/{artifact_id}/mint")
def mint(artifact_id: str, user: dict = Depends(get_current_user)):
    try:
        return prov.mint_artifact(_store(), artifact_id, _user_id(user))
    except Exception as exc:
        raise _http(exc)


@router.post("/{artifact_id}/publish")
def publish(artifact_id: str, user: dict = Depends(get_current_user)):
    try:
        return prov.publish_artifact(_store(), artifact_id, _user_id(user))
    except Exception as exc:
        raise _http(exc)


# -- derivation ---------------------------------------------------------------------


@router.post("/derive")
def derive(body: DeriveBody, user: dict = Depends(get_current_user)):
    try:
        return prov.derive_artifact(
            _store(),
            parent_ids=body.parent_ids,
            image_base64=body.image_base64,
            actor_user_id=_user_id(user),
            title=body.title,
            description=body.description,
            archetype_cast=body.archetype_cast,
        )
    except Exception as exc:
        raise _http(exc)


@router.post("/links/approve")
def approve_link(body: ApproveBody, user: dict = Depends(get_current_user)):
    try:
        return prov.approve_derivation(
            _store(), parent_id=body.parent_id, child_id=body.child_id,
            user_id=_user_id(user),
        )
    except Exception as exc:
        raise _http(exc)


# -- events ---------------------------------------------------------------------------


@router.post("/events")
def log_event(body: EventBody, user: dict = Depends(get_current_user)):
    try:
        return prov.log_event(
            _store(), artifact_id=body.artifact_id, type=body.type,
            actor_user_id=_user_id(user), context=body.context,
        )
    except Exception as exc:
        raise _http(exc)


# -- reads ------------------------------------------------------------------------------


@router.get("/artifacts/{artifact_id}")
def get_artifact(artifact_id: str, user: dict = Depends(get_current_user)):
    store = _store()
    artifact = store.get_artifact(artifact_id)
    if artifact is None:
        raise HTTPException(status_code=404, detail="unknown artifact")
    if not prov.can_view(artifact, _user_id(user)):
        raise HTTPException(status_code=403, detail="artifact is private")
    return artifact


@router.get("/artifacts/{artifact_id}/lineage")
def get_lineage(artifact_id: str, user: dict = Depends(get_current_user)):
    try:
        return prov.get_lineage(_store(), artifact_id, _user_id(user))
    except Exception as exc:
        raise _http(exc)


@router.get("/ledger")
def get_ledger(user: dict = Depends(get_current_user)):
    return prov.get_ledger(_store(), _user_id(user))


@router.post("/recompute")
def recompute(user: dict = Depends(get_current_user)):
    return {"recomputed": prov.recompute_all(_store())}


# -- ingest -------------------------------------------------------------------------------


@router.post("/ingest")
def ingest(body: IngestBody, user: dict = Depends(get_current_user)):
    """Fingerprint at ingestion. Outcome is one of:
    exact (dedup — existing artifact returned), near (registered as imported
    + suggested_parent for confirmation), none (registered as imported)."""
    try:
        return prov.identify_upload(
            _store(),
            image_base64=body.image_base64,
            user_id=_user_id(user),
            title=body.title,
            description=body.description,
            claim_creator=body.claim_creator,
        )
    except Exception as exc:
        raise _http(exc)


@router.post("/ingest/{artifact_id}/confirm-link")
def confirm_link(
    artifact_id: str, body: ConfirmLinkBody, user: dict = Depends(get_current_user)
):
    try:
        return prov.confirm_derivation_link(
            _store(), child_id=artifact_id, parent_id=body.parent_id,
            user_id=_user_id(user),
        )
    except Exception as exc:
        raise _http(exc)


# -- disputes ---------------------------------------------------------------------------------


@router.post("/disputes")
def file_dispute(body: DisputeBody, user: dict = Depends(get_current_user)):
    try:
        return prov.file_dispute(
            _store(), artifact_id=body.artifact_id,
            challenger_user_id=_user_id(user), evidence=body.evidence,
        )
    except Exception as exc:
        raise _http(exc)


@router.post("/disputes/{dispute_id}/resolve")
def resolve_dispute(
    dispute_id: str, body: ResolveBody, user: dict = Depends(get_current_admin_user)
):
    try:
        return prov.resolve_dispute(
            _store(), dispute_id=dispute_id, outcome=body.outcome,
            resolution_note=body.resolution_note,
        )
    except Exception as exc:
        raise _http(exc)


@router.get("/disputes")
def list_disputes(status: str | None = None, user: dict = Depends(get_current_admin_user)):
    return {"disputes": _store().list_disputes(status=status)}
