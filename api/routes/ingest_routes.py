"""Presence ingestion API: upload exports -> distill -> review candidates.

Pipeline: POST /ingest/upload -> POST /ingest/sessions/{sid}/distill ->
GET /ingest/sessions/{sid}/candidates -> POST /ingest/sessions/{sid}/review.

Privacy: no endpoint ever returns raw unredacted text. Stored events are
already redacted at capture; candidates expose redacted summaries only.
Uploads are capped at 200 MB.
"""
from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel, Field, field_validator

from local_ai.identity import LicenseRequired, ScopeDenied
from local_ai.presence_ingest.schema import (
    ContributionClaim,
    ImportSession,
    TrainingSignal,
)

router = APIRouter(prefix="/ingest", tags=["ingest"])

MAX_UPLOAD_BYTES = 200 * 1024 * 1024


class ReviewBody(BaseModel):
    approvals: dict[str, bool] = {}
    contexts: dict[str, dict] = Field(
        default_factory=dict,
        description=(
            "Per-signal decision-context corrections (signal_id -> envelope "
            "dict). Applied to pending signals before the approve/reject "
            "decision, so approval means 'this signal and its context are "
            "correct'. Approved/rejected rows are never touched."
        ),
    )


class ContributionClaimBody(BaseModel):
    """Define the user's part in a collaborative work."""

    work_title: str = ""
    role: str
    parts: str = ""
    extent: dict = {}
    collaborators: list[str] = []
    note: str = ""
    event_ids: list[str] = []

    @field_validator("role")
    @classmethod
    def _role_not_blank(cls, v: str) -> str:
        v = (v or "").strip()
        if not v:
            raise ValueError("role is required")
        return v


def _service():
    from local_ai.presence_ingest import service

    return service


def _store():
    from local_ai.presence_ingest.store import PresenceStore

    return PresenceStore()


@router.get("/sources")
def list_ingest_sources():
    """Adapter catalog: which export formats are supported."""
    from local_ai.presence_ingest.adapters.registry import list_sources

    return {"sources": list_sources()}


@router.post("/upload", response_model=ImportSession)
async def upload_export(file: UploadFile = File(...)):
    """Upload an export file; detect source, parse, and redact at capture.

    Returns the import session summary (no raw content).
    """
    from local_ai.presence_ingest.service import PresenceIngestError

    filename = file.filename or "upload"
    tmp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            delete=False, suffix=Path(filename).suffix
        ) as tmp:
            tmp_path = Path(tmp.name)
            size = 0
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                size += len(chunk)
                if size > MAX_UPLOAD_BYTES:
                    raise HTTPException(
                        status_code=413, detail="Upload exceeds the 200 MB cap."
                    )
                tmp.write(chunk)
        try:
            session = _service().start_import(tmp_path, filename)
        except LicenseRequired:
            raise HTTPException(
                status_code=409,
                detail="Issue an identity license first: POST /identity/license/issue",
            )
        except PresenceIngestError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        return session
    finally:
        if tmp_path is not None and tmp_path.exists():
            tmp_path.unlink(missing_ok=True)


@router.get("/sessions", response_model=list[ImportSession])
def list_ingest_sessions():
    """List import sessions (summaries only, no raw content)."""
    return _store().list_sessions()


@router.get("/sessions/{session_id}", response_model=ImportSession)
def get_ingest_session(session_id: str):
    """Session detail with pipeline counts."""
    session = _store().get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Unknown import session.")
    return session


@router.post("/sessions/{session_id}/distill")
def distill_session(session_id: str):
    """Run LLM distillation on a parsed session -> pending candidates."""
    from local_ai.presence_ingest.distill import DistillError
    from local_ai.presence_ingest.service import PresenceIngestError

    try:
        count = _service().run_distill(session_id)
    except LicenseRequired:
        raise HTTPException(
            status_code=409,
            detail="Issue an identity license first: POST /identity/license/issue",
        )
    except ScopeDenied as exc:
        raise HTTPException(
            status_code=403,
            detail=f"{exc} Grant it via POST /identity/scopes.",
        )
    except PresenceIngestError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except DistillError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    return {"session_id": session_id, "candidates": count}


@router.get("/sessions/{session_id}/candidates", response_model=list[TrainingSignal])
def list_candidates(session_id: str):
    """Pending candidate signals awaiting user review (redacted)."""
    store = _store()
    if store.get_session(session_id) is None:
        raise HTTPException(status_code=404, detail="Unknown import session.")
    return store.list_candidates(session_id)


@router.post("/sessions/{session_id}/review")
def review_candidates(session_id: str, body: ReviewBody):
    """Apply approve/reject decisions (with optional context corrections).

    Only pending signals are affected. Context corrections are applied
    first, so approving a signal means its context is correct too.
    """
    from local_ai.presence_ingest.service import PresenceIngestError

    try:
        result = _service().review(session_id, body.approvals, contexts=body.contexts)
    except PresenceIngestError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return {"session_id": session_id, **result}


@router.delete("/sessions/{session_id}")
def delete_ingest_session(session_id: str):
    """Delete the raw upload and the session's events.

    Approved signals persist — they are the user's training data now.
    """
    from local_ai.presence_ingest.service import PresenceIngestError

    try:
        _service().delete_session(session_id)
    except PresenceIngestError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return {"session_id": session_id, "deleted": True}


@router.post(
    "/sessions/{session_id}/contributions",
    response_model=ContributionClaim,
    status_code=201,
)
def define_contribution_claim(session_id: str, body: ContributionClaimBody):
    """Claim the user's part in a collaborative work ("I played guitar").

    Opt-in per item; scopes distillation to the contribution and keeps the
    identity license honest (contributions, not whole works).
    """
    from local_ai.presence_ingest.service import PresenceIngestError

    try:
        return _service().define_contribution(
            session_id,
            role=body.role,
            work_title=body.work_title,
            parts=body.parts,
            extent=body.extent,
            collaborators=body.collaborators,
            note=body.note,
            event_ids=body.event_ids,
        )
    except LicenseRequired:
        raise HTTPException(
            status_code=409,
            detail="Issue an identity license first: POST /identity/license/issue",
        )
    except PresenceIngestError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.get(
    "/sessions/{session_id}/contributions",
    response_model=list[ContributionClaim],
)
def list_contribution_claims(session_id: str):
    """List a session's contribution claims."""
    store = _store()
    if store.get_session(session_id) is None:
        raise HTTPException(status_code=404, detail="Unknown import session.")
    return store.list_claims(session_id)


@router.delete("/contributions/{claim_id}")
def delete_contribution_claim(claim_id: str):
    """Remove a contribution claim (claims are user assertions, freely
    removable — unlike append-only signals)."""
    from local_ai.presence_ingest.service import PresenceIngestError

    try:
        _service().remove_contribution(claim_id)
    except PresenceIngestError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return {"claim_id": claim_id, "deleted": True}
