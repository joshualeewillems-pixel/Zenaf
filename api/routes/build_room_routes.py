"""Build-Council Room runner (R1 invocation surface).

One endpoint: POST /build-room/meetings runs a single-model (R1)
meeting for the signed-in OWNER account and returns its transcript
plus the draft artifact.

Owner-gating is load-bearing: a meeting spends the owner's OpenAI
credit, so the endpoint requires the bootstrapped owner account —
never anonymous, never public, never another user. The participant
resolves under the CALLER's account principal (not the system
principal), because that is where the saved key lives.

Boundaries (spec section 4/5, R1 semantics preserved):
- No key values in responses or logs. The artifact carries a key
  SOURCE label only; the participant object is never serialized.
- R1 budget/timeout enforcement applies; failures are recorded in
  the transcript and reflected in ``ok`` — never raised as crashes.
- No execution path: the artifact RECOMMENDS only. Nothing this
  endpoint returns authorizes file changes or PRs.
- This module does not change R1 semantics; it only invokes it.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, field_validator

from api.routes.auth_routes import get_current_user
from local_ai.build_room.meeting import (
    EvidencePacket,
    run_single_model_meeting,
)
from local_ai.llm.execution_principal import authenticated_account_principal
from local_ai.vision_execution import storage as St

router = APIRouter(prefix="/build-room", tags=["build-room"])


def get_build_room_store_dir() -> Path:
    """Production store dir (injection point tests monkeypatch).

    Under the app data dir, which on staging is the persistent
    volume (``/app/data``): transcripts and draft artifacts survive
    redeploys.
    """
    return Path(__file__).resolve().parent.parent.parent / "data" / "build_room"


def get_current_owner_user(current_user: dict = Depends(get_current_user)) -> dict:
    """Owner-only gate. Fail closed: unknown owner row denies."""
    owner_id = St.get_owner_user_id()
    if owner_id is None or current_user.get("id") != owner_id:
        raise HTTPException(
            status_code=403, detail="Build-room meetings are owner-only"
        )
    return current_user


class RunMeetingBody(BaseModel):
    """Work item + question for one R1 meeting."""

    work_item: str
    question: str
    excerpts: list[str] = []
    constraints: list[str] = []
    source_refs: list[str] = []

    @field_validator("work_item", "question")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        v = (v or "").strip()
        if not v:
            raise ValueError("work_item and question are required")
        return v


@router.post("/meetings")
def run_meeting(
    body: RunMeetingBody, current_user: dict = Depends(get_current_owner_user)
):
    """Run one R1 meeting for the caller and return its record.

    The caller id is authoritative (never trust a client-supplied
    user id): the participant resolves under the caller's own
    account principal, so the spend follows the caller.
    """
    uid = current_user["id"]
    principal = authenticated_account_principal(uid)
    packet = EvidencePacket(
        work_item=body.work_item,
        question=body.question,
        excerpts=tuple(body.excerpts),
        constraints=tuple(body.constraints),
        source_refs=tuple(body.source_refs),
    )
    result = run_single_model_meeting(
        packet, store_dir=get_build_room_store_dir(), principal=principal
    )
    return {
        "meeting_id": result.meeting_id,
        "ok": result.ok,
        "transcript": result.transcript.to_dict(),
        "artifact": result.artifact,
    }
