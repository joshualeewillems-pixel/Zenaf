"""Minting pipeline API: journal → story → prompt pack → import/mint.

Authenticated throughout. The pipeline feeds the provenance registry
(`local_ai.provenance`); the registry remains the source of truth.

Endpoints:
  POST /pipeline/journal                        save a journal entry (+ marker nudge)
  GET  /pipeline/journal                        list the user's entries
  POST /pipeline/journal/{id}/dismiss           dismiss a story suggestion
  POST /pipeline/story                          extract a story from an entry
  GET  /pipeline/packs/plan                     graduated taste flow (ask/suggest/propose)
  POST /pipeline/packs                          generate prompt packs
  POST /pipeline/packs/{id}/regen               "give me another take"
  POST /pipeline/quote-card                     render + auto-mint a quote card
  POST /pipeline/story/key-line                 choose/edit/adopt a key line (S4)
  POST /pipeline/mint-standalone                 mint with no journal parent
  POST /pipeline/mint-standalone/{id}/anchor    answer the anchoring question
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from api.routes.auth_routes import get_current_user
from local_ai.pipeline import service as pipe
from local_ai.pipeline import packs as pack_lib
from local_ai.pipeline.store import PipelineStore
from local_ai.provenance.store import ProvenanceStore

router = APIRouter(prefix="/pipeline", tags=["pipeline"])


def _store() -> ProvenanceStore:
    return ProvenanceStore()


def _pstore() -> PipelineStore:
    return PipelineStore()


def _user_id(user: dict) -> str:
    return user["id"]


def _http(exc: Exception) -> HTTPException:
    if isinstance(exc, KeyError):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, PermissionError):
        return HTTPException(status_code=403, detail=str(exc))
    if isinstance(exc, ValueError):
        return HTTPException(status_code=422, detail=str(exc))
    if isinstance(exc, RuntimeError):
        return HTTPException(status_code=502, detail=str(exc))
    return HTTPException(status_code=500, detail="pipeline error")


# -- request models -------------------------------------------------------


class JournalBody(BaseModel):
    text: str = Field(min_length=1, max_length=20000)


class StoryBody(BaseModel):
    journal_entry_id: str


class PacksBody(BaseModel):
    story_id: str
    modalities: list[str] = Field(default_factory=list)
    answers: dict[str, str] | None = None
    confirmed: bool = False
    tweak: str | None = None


class QuoteCardBody(BaseModel):
    story_id: str
    badge: bool = True


class KeyLineChoiceBody(BaseModel):
    """Exactly one of candidate / edited_text / adopted_text (S4, Part XIII).

    candidate: one of the story's stored verified passages → certified.
    edited_text: the user's own wording → user_authored, not an entry span.
    adopted_text: a Zenaf composition the user adopts → adopted, never
    a quotation.
    """

    story_id: str
    candidate: str | None = None
    edited_text: str | None = None
    adopted_text: str | None = None


class StandaloneBody(BaseModel):
    image_base64: str = Field(description="Image bytes as base64 (data: URL ok)")
    title: str = ""


class AnchorBody(BaseModel):
    journal_entry_id: str | None = None
    micro_reflection: str | None = None


# -- journal ------------------------------------------------------------------------


@router.post("/journal")
def create_entry(body: JournalBody, user: dict = Depends(get_current_user)):
    try:
        return pipe.create_journal_entry(
            _pstore(), _store(), _user_id(user), body.text
        )
    except Exception as exc:
        raise _http(exc)


@router.get("/journal")
def list_entries(user: dict = Depends(get_current_user)):
    return {
        "entries": pipe.list_journal_entries(_pstore(), _user_id(user)),
    }


@router.post("/journal/{entry_id}/dismiss")
def dismiss(entry_id: str, user: dict = Depends(get_current_user)):
    try:
        return {
            "entry": pipe.dismiss_suggestion(_pstore(), _user_id(user), entry_id)
        }
    except Exception as exc:
        raise _http(exc)


# -- stories --------------------------------------------------------------------------


@router.post("/story")
def make_story(body: StoryBody, user: dict = Depends(get_current_user)):
    try:
        return pipe.make_story(
            _pstore(), _store(), _user_id(user), body.journal_entry_id
        )
    except Exception as exc:
        raise _http(exc)


# -- key-line selection -----------------------------------------------------------------
#
# S4 (audit Part XIII): propose → choose/edit → record. The picker UI
# is a follow-up; this endpoint is the record half, and it is what the
# frontend will call when the picker lands.


@router.post("/story/key-line")
def choose_key_line(body: KeyLineChoiceBody, user: dict = Depends(get_current_user)):
    try:
        return pipe.choose_key_line(
            _pstore(),
            _store(),
            _user_id(user),
            body.story_id,
            candidate=body.candidate,
            edited_text=body.edited_text,
            adopted_text=body.adopted_text,
        )
    except Exception as exc:
        raise _http(exc)


# -- prompt packs -----------------------------------------------------------------------


@router.get("/packs/plan")
def plan_packs(story_id: str, user: dict = Depends(get_current_user)):
    try:
        return pipe.plan_packs(_pstore(), _store(), _user_id(user), story_id)
    except Exception as exc:
        raise _http(exc)


@router.post("/packs")
def generate_packs(body: PacksBody, user: dict = Depends(get_current_user)):
    for modality in body.modalities:
        if modality not in pack_lib.MODALITIES:
            raise HTTPException(
                status_code=422,
                detail=f"unknown modality: {modality} "
                f"(choose from {', '.join(pack_lib.MODALITIES)})",
            )
    try:
        return pipe.generate_packs(
            _pstore(),
            _store(),
            _user_id(user),
            body.story_id,
            body.modalities,
            answers=body.answers,
            confirmed=body.confirmed,
            tweak=body.tweak,
        )
    except Exception as exc:
        raise _http(exc)


@router.post("/packs/{pack_id}/regen")
def regen_pack(pack_id: str, user: dict = Depends(get_current_user)):
    try:
        return pipe.regen_pack(_pstore(), _store(), _user_id(user), pack_id)
    except Exception as exc:
        raise _http(exc)


# -- quote cards --------------------------------------------------------------------------


@router.post("/quote-card")
def quote_card(body: QuoteCardBody, user: dict = Depends(get_current_user)):
    try:
        return pipe.make_quote_card(
            _pstore(), _store(), _user_id(user), body.story_id, badge=body.badge
        )
    except Exception as exc:
        raise _http(exc)


# -- standalone mint ------------------------------------------------------------------------


@router.post("/mint-standalone")
def mint_standalone(body: StandaloneBody, user: dict = Depends(get_current_user)):
    try:
        return pipe.standalone_mint(
            _store(), _user_id(user), body.image_base64, title=body.title
        )
    except Exception as exc:
        raise _http(exc)


@router.post("/mint-standalone/{artifact_id}/anchor")
def anchor(
    artifact_id: str, body: AnchorBody, user: dict = Depends(get_current_user)
):
    try:
        return pipe.anchor_standalone(
            _pstore(),
            _store(),
            _user_id(user),
            artifact_id,
            journal_entry_id=body.journal_entry_id,
            micro_reflection=body.micro_reflection,
        )
    except Exception as exc:
        raise _http(exc)
