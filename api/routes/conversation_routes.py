"""The conversation skeleton — one persistent conversation per user.

POST /conversation/turn   — one turn: persist user message, reply through the
                            shared voice builder, persist reply, touch the
                            seat's thread_state. Seat switches are just
                            archetype_id tags; history carries across seats.
GET  /conversation        — hydrate: oldest-first message history. This is
                            what replaces the client-sent `history` array.
GET  /conversation/invitations — pending invitations for one
                            conversation (Capability C S4): the "!"
                            markers a seat-sheet list or Tree badge
                            reads from. Reads never consume: tapping
                            an invitation opens it, only a sent turn
                            to the invited seat accepts it (S1).
                            (trainable moments, project proposals, mint
                            suggestions), all drafts, never filed, never
                            pushed. Cached per message watermark.
POST /conversation/meeting/*  — the keystone meetings: guided
                            first-meeting conversations on their own
                            conversation_id, driven by a stage machine
                            (local_ai/conversation/meeting.py).

All routes require auth. Nothing here writes training data.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from api.routes.auth_routes import get_current_user
from local_ai.conversation import suggestions as sugg
from local_ai.conversation.firebrand_round import ITEM_KIND, ROUND_KIND
from local_ai.conversation.round import ROUND_KIND as WEAVER_ROUND_KIND
from local_ai.conversation.meeting import MeetingError, MeetingService, MeetingStore
from local_ai.conversation.service import ConversationService
from local_ai.conversation.store import ConversationStore
from local_ai.conversation.upload_extraction import (
    chunk_index_for_offset,
    chunk_upload_text,
    extract_quoted_passages,
    resolve_quote_in_text,
    resolve_upload_source_text,
    start_upload_extraction_job,
)
from local_ai.conversation.upload_round import (
    UPLOAD_ITEM_KIND,
    UPLOAD_ROUND_KIND,
    render_upload_interpretation,
    uncertain_match_for,
    upload_coverage,
)
from local_ai.council.archetypes import get_archetype, stock_archetype_ids
from local_ai.council.naming import get_display_name
from local_ai.fellowship.events import emit_event as fellowship_emit_event
from local_ai.narrative.context import weaver_context_provider

router = APIRouter(prefix="/conversation", tags=["conversation"])

logger = logging.getLogger(__name__)

_MSG_MAX = 2000


def _store() -> ConversationStore:
    return ConversationStore()


def _agent_store(user_id: str):
    """The claim store for the Weaver skip path, owner-scoped by
    construction (the same helper shape as agent_routes._store).
    Monkeypatched in tests."""
    from local_ai.agent_intake.store import AgentStore

    return AgentStore(user_id=user_id)


def _service() -> ConversationService:
    # Fellowship Runtime P1: turns emit shared-reality events at the
    # request tail; derivation is scheduled off-path by the emitter.
    # Phase 2 steward: the Weaver's turns also carry prepared
    # steward context (consent + relevance gated inside the
    # provider). The provider builds its NarrativeStore lazily on
    # the first Weaver turn, so non-Weaver turns never touch the
    # narrative DB; any provider failure degrades to no context.
    return ConversationService(
        _store(),
        event_sink=fellowship_emit_event,
        steward_context_provider=weaver_context_provider(),
    )


def _uid(current_user: dict) -> str | None:
    return (current_user or {}).get("id") or (current_user or {}).get("user_id")


class LiveContext(BaseModel):
    sheet_type: str | None = Field(default=None, max_length=64)
    sheet_id: str | None = Field(default=None, max_length=128)
    entity_type: str | None = Field(default=None, max_length=64)
    entity_id: str | None = Field(default=None, max_length=128)
    # Weaver strand interviews (rev2 §6): one optional additive field,
    # set ONLY by the strand panel for conductor turns in strand
    # threads, never inferred, ignored for other seats and threads.
    # Validated server-side on every turn (unknown key or a thread
    # that is not the caller's mapped thread for the strand fails
    # closed with a 422).
    strand_key: str | None = Field(default=None, max_length=32)


class ConversationTurnBody(BaseModel):
    conversation_id: str = Field(default="skeleton", max_length=64)
    archetype_id: str = Field(max_length=32)
    message: str = Field(default="", max_length=_MSG_MAX)
    mode: str = Field(default="trained", max_length=16)  # "trained" | "base"
    question: bool = Field(default=False)
    context: LiveContext | None = None


class ConversationTurnResponse(BaseModel):
    reply: str
    conversation_id: str
    message_id: str
    archetype_id: str
    display_name: str
    voice_color: str
    mode_used: str
    has_training: bool
    # Firebrand lightning round (S1): the newly presented item
    # ({"kind", "proposal_id", "proposal"}), or None when this turn
    # presented nothing new. Absent from every other turn.
    round_item: dict | None = None
    # Weaver rapid fire (S1): the round state this turn recorded
    # ("item" | "checkpoint" | "closing" | "offered" | "ended"), or
    # None when this turn recorded no round state.
    round_state: str | None = None


def _check_seat(archetype_id: str) -> str:
    arch_id = (archetype_id or "").strip().lower()
    if get_archetype(arch_id) is None or arch_id not in stock_archetype_ids():
        raise HTTPException(status_code=422, detail=f"Unknown voice: {archetype_id!r}")
    return arch_id


@router.post("/turn", response_model=ConversationTurnResponse)
def conversation_turn(
    body: ConversationTurnBody,
    current_user: dict = Depends(get_current_user),
) -> ConversationTurnResponse:
    """One turn of the persistent conversation."""
    user_id = _uid(current_user)
    if not user_id:
        raise HTTPException(status_code=401, detail="Sign in to continue the conversation.")
    arch_id = _check_seat(body.archetype_id)
    conversation_id = (body.conversation_id or "skeleton").strip() or "skeleton"

    try:
        result = _service().turn(
            user_id,
            arch_id,
            body.message,
            conversation_id=conversation_id,
            mode=body.mode,
            question=body.question,
            context=(body.context.model_dump(exclude_none=True) if body.context else None),
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    except Exception as exc:  # noqa: BLE001 — loud failure
        raise HTTPException(status_code=502, detail=f"Conversation unavailable: {exc}")

    return ConversationTurnResponse(
        reply=result.reply.reply,
        conversation_id=result.conversation_id,
        message_id=result.assistant_message["id"],
        archetype_id=result.reply.archetype_id,
        display_name=result.reply.display_name,
        voice_color=result.reply.voice_color,
        mode_used=result.reply.mode_used,
        has_training=result.reply.has_training,
        round_item=result.round_item,
        round_state=result.round_state,
    )


class RoundActionBody(BaseModel):
    conversation_id: str = Field(max_length=64)
    message_id: str = Field(max_length=64)
    # Firebrand S1: the proposal this action targets. Weaver S1:
    # the claim instead. Exactly one of the two is present — the
    # skip endpoint branches on which; reserve/unreserve require
    # proposal_id. One shared skip endpoint because the path is the
    # same and a skip is a skip: park one presented item, whatever
    # its kind (brief §7.5).
    proposal_id: str | None = Field(default=None, max_length=64)
    claim_id: str | None = Field(default=None, max_length=128)


class RoundReserveBody(RoundActionBody):
    # Snooze in days, as picked on the round card: 1 (a day), 7 (a
    # week), or null (never). The duration is the user's pick (OQ7);
    # the server only bounds it.
    snooze_days: int | None = Field(default=None, ge=1, le=365)


def _round_presentation_check(
    store: ConversationStore,
    user_id: str,
    conversation_id: str,
    message_id: str,
    proposal_id: str,
) -> None:
    """The round card's presentation check: the named message must be
    the one that presented this proposal in the Firebrand round — a
    tap on any other message cannot park or reserve an item (409,
    plain copy). Owner-scoped: a foreign message reads as missing,
    never as another user's record.
    """
    msg = store.get_message(user_id, conversation_id, message_id)
    if msg is None:
        raise HTTPException(status_code=404, detail="Message not found.")
    ctx = msg.get("context") or {}
    if (
        ctx.get("round_kind") != ROUND_KIND
        or ctx.get("round_proposal_id") != proposal_id
    ):
        raise HTTPException(
            status_code=409,
            detail="That message didn't present this item — refresh to see its state.",
        )


def _round_proposal_for_action(
    store: ConversationStore,
    user_id: str,
    conversation_id: str,
    message_id: str,
    proposal_id: str,
) -> dict:
    """Shared guards for the round card's tap actions (S1).

    Presentation check first, then the standing check: the proposal
    must exist and still be pending — a tap that arrives after a
    decision elsewhere is a 409, and the card re-fetches the server
    state. Both checks are owner-scoped: a foreign message or
    proposal reads as missing, never as another user's record.
    """
    from local_ai.vision_execution import storage as ve_storage

    _round_presentation_check(store, user_id, conversation_id, message_id, proposal_id)
    proposal = ve_storage.get_task_proposal(user_id, proposal_id)
    if proposal is None:
        raise HTTPException(status_code=404, detail="Proposal not found.")
    if proposal.get("state") != "pending":
        raise HTTPException(
            status_code=409,
            detail="Already decided — refresh to see its state.",
        )
    return proposal


@router.get("/round/item-state")
def round_item_state(
    conversation_id: str = Query(max_length=64),
    message_id: str = Query(max_length=64),
    proposal_id: str = Query(max_length=64),
    current_user: dict = Depends(get_current_user),
) -> dict:
    """The round card's hydration read: the proposal plus its round
    state (parked? reserved?) for one presented item.

    The parked/reserved state lives in the round tables, not on the
    proposal record, so the bare proposal read cannot show it — a
    reload would otherwise render a parked or reserved item as a
    fresh pending card. The presentation check applies, but the
    standing check does not: a decided proposal still returns its
    state, so the card shows Created / Declined after a reload.
    """
    from local_ai.vision_execution import storage as ve_storage

    user_id = _uid(current_user)
    if not user_id:
        raise HTTPException(status_code=401, detail="Sign in to continue the conversation.")
    store = _store()
    _round_presentation_check(store, user_id, conversation_id, message_id, proposal_id)
    proposal = ve_storage.get_task_proposal(user_id, proposal_id)
    if proposal is None:
        raise HTTPException(status_code=404, detail="Proposal not found.")
    parked = proposal_id in store.list_parked_round_items(
        user_id, conversation_id, ROUND_KIND
    )
    marker = store.get_reserved_round_item(user_id, ITEM_KIND, proposal_id)
    return {
        "proposal": proposal,
        "parked": parked,
        "reserved": marker,
    }


@router.post("/round/skip")
def round_skip(
    body: RoundActionBody, current_user: dict = Depends(get_current_user)
) -> dict:
    """Park the round's current item — "I need to check" (Firebrand
    OQ5; Weaver brief §7).

    A park changes no underlying state: the proposal stays pending
    (Firebrand) or the claim stays pending (Weaver) and returns at
    the next round. The next user message advances the round (the
    tap itself sends no turn, per the tap-continuation rule). The
    body carries either proposal_id (Firebrand) or claim_id
    (Weaver); exactly one must be present.
    """
    user_id = _uid(current_user)
    if not user_id:
        raise HTTPException(status_code=401, detail="Sign in to continue the conversation.")
    store = _store()
    if body.proposal_id:
        proposal = _round_proposal_for_action(
            store, user_id, body.conversation_id, body.message_id, body.proposal_id
        )
        store.park_round_item(user_id, body.conversation_id, ROUND_KIND, body.proposal_id)
        return {"parked": True, "proposal": proposal}
    if body.claim_id:
        claim = _round_claim_for_action(
            store, _agent_store(user_id), user_id,
            body.conversation_id, body.message_id, body.claim_id,
        )
        store.park_round_item(
            user_id, body.conversation_id, WEAVER_ROUND_KIND, body.claim_id
        )
        return {"parked": True, "claim": claim}
    raise HTTPException(
        status_code=422, detail="skip needs proposal_id or claim_id."
    )


def _round_claim_for_action(
    store: ConversationStore,
    agent_store,
    user_id: str,
    conversation_id: str,
    message_id: str,
    claim_id: str,
) -> dict:
    """Shared guards for the Weaver round card's skip (brief §7.5).

    Presentation check first, then the standing check: the claim
    must have been presented in that message and still be pending
    — a tap that arrives after a decision elsewhere fails with the
    §10.3 conflict copy, and the card re-fetches the claim to show
    its actual standing. Both checks are owner-scoped: a foreign
    message or claim reads as missing, never as another user's
    record.
    """
    msg = store.get_message(user_id, conversation_id, message_id)
    if msg is None:
        raise HTTPException(status_code=404, detail="Message not found.")
    ctx = msg.get("context") or {}
    if (
        ctx.get("round_kind") != WEAVER_ROUND_KIND
        or ctx.get("round_claim_id") != claim_id
    ):
        raise HTTPException(
            status_code=409,
            detail="That message didn't present this item — refresh to see its state.",
        )
    agent_id = ctx.get("round_agent_id")
    claim = None
    if agent_id:
        for c in agent_store.get_claims(agent_id):
            if c.id == claim_id:
                claim = c
                break
    if claim is None:
        raise HTTPException(status_code=404, detail="Claim not found.")
    if claim.status != "pending":
        raise HTTPException(
            status_code=409,
            detail="This one was already decided elsewhere — in your Review, for "
            "example — so nothing was written here. It's no longer pending.",
        )
    return claim.to_dict()


@router.post("/round/reserve")
def round_reserve(
    body: RoundReserveBody, current_user: dict = Depends(get_current_user)
) -> dict:
    """Mark one item "don't remind me about this" (OQ7).

    Durable, not round-scoped: a snooze (the duration the user
    picked) or never. The round skips a reserved item until its
    snooze expires — never reserved never appears again. A tap,
    not prose: a durable suppression must never rest on a misread
    sentence.
    """
    user_id = _uid(current_user)
    if not user_id:
        raise HTTPException(status_code=401, detail="Sign in to continue the conversation.")
    if not body.proposal_id:
        raise HTTPException(
            status_code=422, detail="reserve needs proposal_id."
        )
    store = _store()
    proposal = _round_proposal_for_action(
        store, user_id, body.conversation_id, body.message_id, body.proposal_id
    )
    snooze_until = None
    if body.snooze_days is not None:
        snooze_until = (
            datetime.now(timezone.utc) + timedelta(days=body.snooze_days)
        ).isoformat()
    marker = store.reserve_round_item(
        user_id, ITEM_KIND, body.proposal_id, snooze_until=snooze_until
    )
    return {"reserved": True, "proposal": proposal, "marker": marker}


@router.post("/round/unreserve")
def round_unreserve(
    body: RoundActionBody, current_user: dict = Depends(get_current_user)
) -> dict:
    """Lift a reserved marker — the round card's Undo.

    The presentation + standing checks apply here too: only the
    message that presented the item can lift its marker, and only
    while the proposal is still pending.
    """
    user_id = _uid(current_user)
    if not user_id:
        raise HTTPException(status_code=401, detail="Sign in to continue the conversation.")
    if not body.proposal_id:
        raise HTTPException(
            status_code=422, detail="unreserve needs proposal_id."
        )
    store = _store()
    proposal = _round_proposal_for_action(
        store, user_id, body.conversation_id, body.message_id, body.proposal_id
    )
    store.unreserve_round_item(user_id, ITEM_KIND, body.proposal_id)
    return {"reserved": False, "proposal": proposal}


# -- upload rapid fire (S1) ---------------------------------------------------
#
# The upload round's own namespaced endpoints (brief §§3, 7, 8, 10,
# 12). The shared /round/* endpoints cannot serve upload: they are
# Firebrand-specific (presentation check hardcodes ROUND_KIND, the
# standing check reads VE task proposals; after Weaver's merge,
# reserve/unreserve REQUIRE proposal_id and skip branches on
# proposal_id/claim_id). Upload reuses the same shared tables and
# methods (parked ids kind "upload", reserved ids kind
# "interpretation") through these endpoints instead. Do NOT modify
# the shared endpoints for upload.


class UploadExtractBody(BaseModel):
    source_id: str = Field(max_length=128)


class UploadPromoteBody(BaseModel):
    conversation_id: str = Field(max_length=64)
    message_id: str = Field(max_length=64)


class UploadOutcomeBody(BaseModel):
    conversation_id: str = Field(max_length=64)
    message_id: str = Field(max_length=64)
    # Undertaking only: the VE kind (project | task | idea); defaults
    # to the interpretation's proposed_outcome.
    kind: str | None = Field(default=None, max_length=16)
    # Undertaking only: the parent project id from the chooser
    # (None = root).
    parent_id: str | None = Field(default=None, max_length=64)
    # Train only: the seat trained (archetype id); defaults to the
    # conversation's seat.
    seat: str | None = Field(default=None, max_length=32)
    # Artifact only: the artifact kind (required for a transformation;
    # a kept reading defaults to "kept-reading") and the artifact
    # text (defaults to the interpretation text, verbatim).
    artifact_kind: str | None = Field(default=None, max_length=32)
    artifact_text: str | None = Field(default=None, max_length=20000)


class UploadRoundActionBody(BaseModel):
    conversation_id: str = Field(max_length=64)
    message_id: str = Field(max_length=64)
    interpretation_id: str = Field(max_length=64)


class UploadRoundReserveBody(UploadRoundActionBody):
    # Snooze in days, as picked on the round card: 1 (a day), 7 (a
    # week), or null (never). The duration is the user's pick (the
    # Remind-me-later picker); the server only bounds it.
    snooze_days: int | None = Field(default=None, ge=1, le=365)
    # Archive-it (distinct from a Never snooze): reserve never AND
    # move the outcome row to 'archived'. The two are the same
    # request shape (snooze null) but different verdicts, so the
    # card names the verdict explicitly.
    archive: bool = False


def _upload_presentation_check(
    store: ConversationStore,
    user_id: str,
    conversation_id: str,
    message_id: str,
    interpretation_id: str,
) -> None:
    """The upload card's presentation check: the named message must
    be the one that presented this interpretation in the upload
    round — a tap on any other message cannot act on an item (409,
    plain copy). Owner-scoped: a foreign message reads as missing,
    never as another user's record."""
    msg = store.get_message(user_id, conversation_id, message_id)
    if msg is None:
        raise HTTPException(status_code=404, detail="Message not found.")
    ctx = msg.get("context") or {}
    if (
        ctx.get("round_kind") != UPLOAD_ROUND_KIND
        or ctx.get("round_interpretation_id") != interpretation_id
    ):
        raise HTTPException(
            status_code=409,
            detail="That message didn't present this item — refresh to see its state.",
        )


def _upload_interpretation_for_action(
    store: ConversationStore,
    user_id: str,
    conversation_id: str,
    message_id: str,
    interpretation_id: str,
) -> dict:
    """Shared guards for the upload card's QUEUE actions (skip /
    reserve / unreserve) — not the verdict actions.

    Presentation check first, then the standing check: the
    interpretation must exist and still be pending — a tap that
    arrives after a decision elsewhere is a 409, and the card
    re-fetches the server state. The verdict actions (keep / talk /
    artifact / undertaking / train) do NOT use this helper: under
    amendment A2 stacking, a ruled interpretation does not block a
    different kind's verdict — each verdict action runs its own
    per-kind guard (replay for its kind, 409 for a same-kind
    conflict). Both checks are owner-scoped.
    """
    _upload_presentation_check(
        store, user_id, conversation_id, message_id, interpretation_id
    )
    interp = store.get_upload_interpretation(user_id, interpretation_id)
    if interp is None:
        raise HTTPException(status_code=404, detail="Interpretation not found.")
    if interp.get("status") != "pending":
        raise HTTPException(
            status_code=409,
            detail="Already decided — refresh to see its state.",
        )
    return interp


#: The U-3 voice mapping (brief §7.2, amendment A2): the menu
#: choice determines which seat speaks next. Keep it / Remind me
#: later / Archive it create NO invitation and have no entry here.
#: Talk it through's entry names the seat Crane joins the OPEN
#: THREAD — the invitation brings Crane into this conversation;
#: there is no next_voice redirect to Crane (U-3 clarification),
#: so the talk branch invites but returns no next_voice.
_UPLOAD_VOICE_MAP = {
    "talk": "ambassador",  # Talk it through — Crane
    "artifact": "maverick",  # Make an artifact — Fox
    "undertaking": "champion",  # Mine for projects — Firebrand
    "train": "conductor",  # Train a model — Weaver
}


def _upload_next_voice(user_id: str, archetype_id: str) -> dict:
    """The round_item.next_voice payload: the mapped seat for the
    frontend to switch to for the next turn."""
    return {
        "archetype_id": archetype_id,
        "display_name": get_display_name(user_id, archetype_id),
    }


def _upload_invite(
    store: ConversationStore,
    user_id: str,
    conversation_id: str,
    seat: str,
    reason: str,
) -> dict:
    """Invite the mapped seat (Capability C, refresh-not-stack —
    one pending invitation per (conversation, seat))."""
    return store.create_or_refresh_invitation(
        user_id, conversation_id, seat, reason
    )


def _upload_conversation_seat(
    store: ConversationStore, user_id: str, conversation_id: str
) -> str | None:
    """The seat the conversation is open in: the latest voice
    message's archetype id, or None (a fresh conversation)."""
    for msg in reversed(store.history(user_id, conversation_id, limit=50)):
        if msg.get("role") == "voice" and msg.get("archetype_id"):
            return str(msg["archetype_id"]).strip().lower()
    return None


def _upload_first_line(text: str, cap: int = 120) -> str:
    """The VE record title: the interpretation text's first line,
    capped (brief §8.3)."""
    first = (text or "").strip().splitlines()
    line = first[0].strip() if first else ""
    return line[:cap] or (text or "").strip()[:cap]


@router.post("/upload/extract", status_code=202)
def upload_extract(
    body: UploadExtractBody, current_user: dict = Depends(get_current_user)
) -> dict:
    """Start an extraction job for one strand source (brief §3).

    Owner + resolvability validation: a foreign source reads as
    missing (404); a source with no stored text fails closed (422).
    A live (queued/running) job for the document returns 202 with
    the existing job — no second job, no duplicate extraction. The
    version rule: the latest version again when the latest job is
    'interrupted'/'failed'/'cancelled' (resume / fresh attempt);
    latest + 1 when a 'complete'/'partial' job exists
    (re-extraction); else 1. The worker runs on a daemon thread
    with its own store; the job row + call table are the record.
    """
    user_id = _uid(current_user)
    if not user_id:
        raise HTTPException(status_code=401, detail="Sign in to continue the conversation.")
    store = _store()
    source = store.get_strand_source(user_id, body.source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="Source not found.")
    if resolve_upload_source_text(store, user_id, body.source_id) is None:
        raise HTTPException(
            status_code=422,
            detail="This source has no stored text to extract from.",
        )
    latest = store.latest_upload_job(user_id, body.source_id)
    if latest is not None and latest.get("state") in ("queued", "running"):
        return {
            "job": latest,
            "detail": "An extraction is already running for this document.",
        }
    if latest is None:
        version = 1
    elif latest.get("state") in ("interrupted", "failed", "cancelled"):
        version = int(latest.get("document_version") or 1)
    else:
        version = int(latest.get("document_version") or 1) + 1
    job = store.create_upload_job(user_id, body.source_id, version)
    start_upload_extraction_job(job["job_id"], str(store.db_path))
    return {"job": job}


@router.get("/upload/jobs/{job_id}")
def upload_job(
    job_id: str, current_user: dict = Depends(get_current_user)
) -> dict:
    """One extraction job + its call rows (the durable record)."""
    user_id = _uid(current_user)
    if not user_id:
        raise HTTPException(status_code=401, detail="Sign in to continue the conversation.")
    store = _store()
    job = store.get_upload_job(user_id, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found.")
    return {"job": job, "calls": store.list_upload_job_calls(job_id)}


@router.post("/upload/jobs/{job_id}/cancel")
def upload_job_cancel(
    job_id: str, current_user: dict = Depends(get_current_user)
) -> dict:
    """Cancel a live extraction job. The worker checks the state
    between calls; completed chunks are preserved."""
    user_id = _uid(current_user)
    if not user_id:
        raise HTTPException(status_code=401, detail="Sign in to continue the conversation.")
    store = _store()
    job = store.get_upload_job(user_id, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found.")
    if job.get("state") not in ("queued", "running"):
        raise HTTPException(
            status_code=409, detail=f"Job is already {job.get('state')}."
        )
    store.set_upload_job_state(job_id, "cancelled")
    return {"job": store.get_upload_job(user_id, job_id) or job}


@router.post("/upload/promote")
def upload_promote(
    body: UploadPromoteBody, current_user: dict = Depends(get_current_user)
) -> dict:
    """Keep a spoken reading as a durable interpretation (brief §10).

    The server reads the spoken reading verbatim from the stored
    assistant message (never re-typed, never paraphrased), resolves
    its quoted passages against the stored source text (§10.3 — the
    noting §2.2/§2.3 rule: normalized for matching only, exactly
    one contiguous substring or no promotion), and writes one
    ``upload_interpretations`` row (origin 'promoted', status
    'pending'). Zero model calls, no re-extraction. A reading that
    cites no passage still files — ungrounded, with no excerpt.
    An unresolvable citation files nothing, and the user is told
    plainly (a 200 with promoted False, not an error — the tap
    succeeded, nothing was filed).
    """
    user_id = _uid(current_user)
    if not user_id:
        raise HTTPException(status_code=401, detail="Sign in to continue the conversation.")
    store = _store()
    msg = store.get_message(user_id, body.conversation_id, body.message_id)
    if msg is None:
        raise HTTPException(status_code=404, detail="Message not found.")
    if msg.get("role") != "voice":
        raise HTTPException(
            status_code=422,
            detail="Only the seat's spoken turns can be kept as readings.",
        )
    lens = store.strand_key_for_conversation(user_id, body.conversation_id)
    if not lens:
        raise HTTPException(
            status_code=422,
            detail="This conversation has no uploaded document to pin a reading to.",
        )
    # The reading, verbatim — minus the round-offer marker line, a
    # system line the seat never spoke and the visitor never sees.
    reading = "\n".join(
        ln for ln in (msg.get("body") or "").splitlines() if ln.strip() != "[[round-offer]]"
    ).strip()
    if not reading:
        raise HTTPException(
            status_code=422, detail="That message has no reading to keep."
        )
    # promotion_turn_id: the latest user message before this
    # assistant message (fallback: the assistant message itself).
    history = store.history(user_id, body.conversation_id, limit=100)
    promotion_turn_id = msg["id"]
    msg_index = next(
        (i for i, m in enumerate(history) if m.get("id") == msg["id"]), None
    )
    if msg_index is not None:
        for m in reversed(history[:msg_index]):
            if m.get("role") == "user":
                promotion_turn_id = m["id"]
                break
    quotes = extract_quoted_passages(reading)
    sources = store.list_sources_for_conversation(user_id, body.conversation_id)
    document_id: str | None = None
    stored_text: str | None = None
    resolved_spans: list[dict] = []
    if quotes:
        for source in sources:
            candidate_id = source.get("id")
            if not candidate_id:
                continue
            resolved = resolve_upload_source_text(store, user_id, candidate_id)
            if resolved is None:
                continue
            text = resolved[0]
            spans: list[dict] = []
            all_resolved = True
            for quote in quotes:
                result = resolve_quote_in_text(quote, text)
                if result.get("status") != "ok":
                    logger.info(
                        "upload promote: quote %s (conversation_id=%s, message_id=%s)",
                        result.get("status"),
                        body.conversation_id,
                        body.message_id,
                    )
                    all_resolved = False
                    break
                spans.append(result)
            if all_resolved:
                document_id, stored_text = candidate_id, text
                resolved_spans = spans
                break
        if document_id is None:
            return {
                "promoted": False,
                "detail": "I couldn't pin that reading to one passage in the document — it isn't filed.",
            }
    else:
        # Ungrounded: the newest source with stored text anchors it.
        for source in sources:
            candidate_id = source.get("id")
            if not candidate_id:
                continue
            resolved = resolve_upload_source_text(store, user_id, candidate_id)
            if resolved is not None:
                document_id, stored_text = candidate_id, resolved[0]
                break
        if document_id is None:
            return {
                "promoted": False,
                "detail": "This conversation has no uploaded document yet — add one first.",
            }
    assert document_id is not None and stored_text is not None
    job = store.latest_upload_job(user_id, document_id)
    version = int(job.get("document_version") or 1) if job is not None else 1
    # Idempotent replay: the same message promoted before returns
    # the existing row (any status), never a duplicate.
    for existing in store.list_upload_interpretations(
        user_id, document_id, lens=lens
    ):
        if (
            existing.get("origin") == "promoted"
            and existing.get("promotion_message_id") == msg["id"]
        ):
            return {
                "promoted": True,
                "interpretation": existing,
                "replayed": True,
            }
    # Span rows, found or created from the stored text (the passage
    # IS a substring of the stored text by the resolution rule, so
    # the row is exact by construction). Locations are chunk-relative
    # (the worker's convention); the span's segment is the chunk
    # holding its start.
    evidence_ids: list[dict] = []
    if resolved_spans:
        chunks, _total = chunk_upload_text(stored_text)
        for span in resolved_spans:
            chunk_index = chunk_index_for_offset(chunks, int(span["start"]))
            if chunk_index is None:
                continue
            segment_id = chunks[chunk_index]["segment_id"]
            chunk_start = sum(
                len(c["text"]) + 2 for c in chunks[:chunk_index]
            )
            location = (
                f"{segment_id}:{int(span['start']) - chunk_start}-"
                f"{int(span['end']) - chunk_start}"
            )
            row = store.save_upload_span(
                user_id,
                document_id,
                version,
                segment_id,
                str(span["span_text"]),
                "redacted",
                location,
            )
            evidence_ids.append({"span_id": row["span_id"], "role": "primary"})
    interp = store.save_upload_interpretation(
        user_id,
        document_id,
        version,
        lens,
        "strand",
        reading,
        evidence_ids=evidence_ids,
        observation_ids=[],
        origin="promoted",
        is_transformation=False,
        proposed_outcome=None,
        promotion_turn_id=promotion_turn_id,
        promotion_message_id=msg["id"],
        ungrounded=not evidence_ids,
    )
    return {"promoted": True, "interpretation": interp}


@router.post("/upload/outcomes/{outcome_id}/{action}")
def upload_outcome_action(
    outcome_id: str,
    action: str,
    body: UploadOutcomeBody,
    current_user: dict = Depends(get_current_user),
) -> dict:
    """Rule on one presented interpretation (brief §§7–9).

    The path value resolves as an outcome id when such a row
    exists, otherwise as an interpretation id — the outcome row
    only exists after the tap (and artifact/train/talk create no
    outcome row at all). The response returns the outcome (with its
    real outcome_id) so replays can use it. Replay (§8.2): the same
    outcome already created for the same action returns the
    existing record, no second write, no error — the replay guard
    runs BEFORE the standing check, so a double-tap never 409s.
    Stacking (amendment A2): cross-kind verdicts are allowed — one
    outcome per (interpretation, kind), and the 409 applies ONLY to
    a second outcome of the SAME kind. A tap on an already-ruled
    interpretation for a kind with no standing outcome proceeds.
    """
    user_id = _uid(current_user)
    if not user_id:
        raise HTTPException(status_code=401, detail="Sign in to continue the conversation.")
    action = (action or "").strip().lower()
    if action not in ("keep", "talk", "artifact", "undertaking", "train"):
        raise HTTPException(
            status_code=422, detail=f"Unknown upload outcome action: {action!r}"
        )
    store = _store()
    outcome = store.get_upload_outcome(user_id, outcome_id)
    if outcome is not None:
        interp = store.get_upload_interpretation(
            user_id, outcome["interpretation_id"]
        )
        if interp is None:
            raise HTTPException(status_code=404, detail="Interpretation not found.")
    else:
        interp = store.get_upload_interpretation(user_id, outcome_id)
        if interp is None:
            raise HTTPException(
                status_code=404, detail="Interpretation or outcome not found."
            )
        outcome = None
    interpretation_id = str(interp["interpretation_id"])
    _upload_presentation_check(
        store, user_id, body.conversation_id, body.message_id, interpretation_id
    )

    def _invite_reason(label: str) -> str:
        first = _upload_first_line(str(interp.get("text") or ""), cap=200)
        return f"{label} — the upload round's reading: {first}"

    def _fresh_interpretation() -> dict:
        return (
            store.get_upload_interpretation(user_id, interpretation_id) or interp
        )

    if action == "talk":
        # Amendment A2 (routing table): Talk it through records
        # NOTHING — no outcome row, and the interpretation stays
        # pending ("talking isn't deciding"). The reconciliation's
        # §4.2 Talk-it-through outcome (kind 'explore') is STRUCK.
        # Crane joins the OPEN THREAD (U-3 clarification): the
        # invitation brings Crane into this conversation; there is
        # no next_voice redirect to Crane's conversation. A second
        # talk tap is allowed (it records nothing to conflict with)
        # and re-invites Crane.
        seat = _UPLOAD_VOICE_MAP["talk"]
        _upload_invite(
            store, user_id, body.conversation_id, seat,
            _invite_reason("Talk it through"),
        )
        return {
            "interpretation": _fresh_interpretation(),
            "invited_seat": seat,
        }

    if action == "keep":
        kind = "keep"
        if (
            outcome is not None
            and outcome.get("kind") == kind
            and outcome.get("status") == "created"
        ):
            # Replay: the same outcome already created.
            return {
                "outcome": outcome,
                "interpretation": interp,
                "replayed": True,
            }
        # Per-kind standing check (amendment A2 stacking): a keep
        # outcome of another status blocks a new one, but a ruled
        # interpretation (ruled by a DIFFERENT kind — "Keep it,
        # then Mine for projects") does not block Keep. A 'pending'
        # keep outcome (a crash between create and set-created)
        # completes below, it is not a conflict.
        existing = store.get_upload_outcome_by_interp_kind(
            user_id, interpretation_id, kind
        )
        if existing is not None and existing.get("status") not in (
            "created",
            "pending",
        ):
            raise HTTPException(
                status_code=409,
                detail=(
                    f"Outcome is already {existing.get('status')} — "
                    "refresh to see its state."
                ),
            )
        interp = _fresh_interpretation()
        if existing is None:
            outcome = store.create_upload_outcome(
                user_id,
                str(interp["document_id"]),
                int(interp["document_version"]),
                interpretation_id,
                kind,
            )
        else:
            outcome = existing
        if outcome.get("status") == "pending":
            # Keep → the outcome IS the verdict (no VE record,
            # ve_kind/ve_id NULL).
            store.set_upload_outcome_status(
                user_id, outcome["outcome_id"], "created"
            )
            store.set_upload_interpretation_status(
                user_id, interpretation_id, "ruled"
            )
            outcome = (
                store.get_upload_outcome(user_id, outcome["outcome_id"]) or outcome
            )
        elif outcome.get("status") != "created":
            raise HTTPException(
                status_code=409,
                detail=f"Outcome is already {outcome.get('status')} — refresh to see its state.",
            )
        return {"outcome": outcome, "interpretation": _fresh_interpretation()}

    if action == "undertaking":
        from local_ai.vision_execution.storage import (
            ProposalConflict,
            UploadOutcomeStuckError,
            approve_upload_outcome,
        )

        kind = None
        if outcome is not None:
            kind = str(outcome.get("kind") or "")
        if not kind:
            kind = (
                (body.kind or interp.get("proposed_outcome") or "")
                .strip()
                .lower()
            )
        if kind not in ("project", "task", "idea"):
            raise HTTPException(
                status_code=422,
                detail="Choose a kind for the undertaking: project, task, or idea.",
            )
        if outcome is not None and outcome.get("kind") != kind:
            raise HTTPException(
                status_code=409,
                detail="That item was already decided under a different kind — refresh to see its state.",
            )
        if outcome is None:
            # Resolve the standing outcome for THIS kind (the path
            # may have been the interpretation id): a second tap for
            # the same kind must hit the replay / R1 / re-claim
            # guards below, never a duplicate create (the UNIQUE
            # (interpretation_id, kind) index). A different kind has
            # no row here — stacking creates it below.
            outcome = store.get_upload_outcome_by_interp_kind(
                user_id, interpretation_id, kind
            )
        parent_id = (body.parent_id or "").strip() or None
        if parent_id is not None:
            from local_ai.vision_execution import storage as ve_storage

            if ve_storage.get_project(parent_id, user_id) is None:
                raise HTTPException(
                    status_code=422, detail="Unknown parent project."
                )
        title = _upload_first_line(str(interp.get("text") or ""))
        detail = (interp.get("text") or "").strip()
        lens_seat = (
            _upload_conversation_seat(store, user_id, body.conversation_id)
            or "conductor"
        )
        if outcome is not None and outcome.get("status") == "created":
            # Replay (or R1 recovery): approve_upload_outcome owns
            # it — the standing check is skipped here by design.
            try:
                approved = approve_upload_outcome(
                    user_id,
                    outcome["outcome_id"],
                    kind=kind,
                    title=title,
                    detail=detail,
                    parent_id=parent_id,
                    conversation_id=body.conversation_id,
                    lens_seat=lens_seat,
                    store=store,
                )
            except (ProposalConflict, UploadOutcomeStuckError) as exc:
                raise HTTPException(status_code=409, detail=str(exc))
            seat = _UPLOAD_VOICE_MAP["undertaking"]
            _upload_invite(
                store, user_id, body.conversation_id, seat,
                _invite_reason("Mine for projects"),
            )
            return {
                "outcome": approved["outcome"],
                "record": approved["record"],
                "replayed": True,
                "interpretation": interp,
                "next_voice": _upload_next_voice(user_id, seat),
            }
        # Amendment A2 stacking: no global standing check here — a
        # ruled interpretation (ruled by a DIFFERENT kind) does not
        # block Mine for projects. The per-kind guards above (replay
        # for a 'created' outcome of this kind; 409 for a different
        # kind) are the only standing rules. The presentation check
        # already ran at the top of this handler.
        interp = _fresh_interpretation()
        if outcome is None:
            outcome = store.create_upload_outcome(
                user_id,
                str(interp["document_id"]),
                int(interp["document_version"]),
                interpretation_id,
                kind,
                parent_id=parent_id,
            )
        try:
            approved = approve_upload_outcome(
                user_id,
                outcome["outcome_id"],
                kind=kind,
                title=title,
                detail=detail,
                parent_id=parent_id,
                conversation_id=body.conversation_id,
                lens_seat=lens_seat,
                store=store,
            )
        except UploadOutcomeStuckError as exc:
            # R2 (§8.1/§8.2, amendment A4): a stuck 'creating'
            # outcome — a young one is refused ('Still creating'),
            # an old one is re-claimed by the retry tap. The
            # diagnostic names it.
            raise HTTPException(status_code=409, detail=str(exc))
        except ProposalConflict as exc:
            raise HTTPException(status_code=409, detail=str(exc))
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        seat = _UPLOAD_VOICE_MAP["undertaking"]
        _upload_invite(
            store, user_id, body.conversation_id, seat,
            _invite_reason("Mine for projects"),
        )
        return {
            "outcome": approved["outcome"],
            "record": approved["record"],
            "replayed": bool(approved.get("replayed")),
            "interpretation": _fresh_interpretation(),
            "next_voice": _upload_next_voice(user_id, seat),
        }

    if action == "artifact":
        artifact_kind = (body.artifact_kind or "").strip().lower() or None
        if artifact_kind is None:
            if interp.get("is_transformation"):
                raise HTTPException(
                    status_code=422,
                    detail="Name the artifact kind for this transformation.",
                )
            artifact_kind = "kept-reading"
        if artifact_kind not in (
            "poem",
            "satire",
            "metaphor",
            "story",
            "scene",
            "name",
            "kept-reading",
        ):
            raise HTTPException(
                status_code=422, detail=f"Unknown artifact kind: {artifact_kind!r}"
            )
        artifact_text = (body.artifact_text or "").strip() or (
            interp.get("text") or ""
        ).strip()
        if not artifact_text:
            raise HTTPException(status_code=422, detail="Artifact text is empty.")
        # Replay: the same artifact already filed for this reading.
        for existing in store.list_upload_artifacts(
            user_id, str(interp["document_id"])
        ):
            if (
                existing.get("interpretation_id") == interpretation_id
                and existing.get("artifact_kind") == artifact_kind
            ):
                seat = _UPLOAD_VOICE_MAP["artifact"]
                _upload_invite(
                    store, user_id, body.conversation_id, seat,
                    _invite_reason("Make an artifact"),
                )
                return {
                    "artifact": existing,
                    "interpretation": interp,
                    "replayed": True,
                    "next_voice": _upload_next_voice(user_id, seat),
                }
        # Amendment A2 stacking: no global standing check — a ruled
        # interpretation (ruled by a DIFFERENT action) does not block
        # Make an artifact. The replay guard above (the same artifact
        # already filed) is the only standing rule. The presentation
        # check already ran at the top of this handler.
        interp = _fresh_interpretation()
        span_ids = [
            entry.get("span_id")
            for entry in (interp.get("evidence_ids") or [])
            if isinstance(entry, dict) and entry.get("span_id")
        ]
        artifact = store.create_upload_artifact(
            user_id,
            body.conversation_id,
            str(interp["document_id"]),
            int(interp["document_version"]),
            interpretation_id,
            str(interp.get("lens") or ""),
            str(interp.get("lens_kind") or "strand"),
            artifact_kind,
            artifact_text,
            source_span_ids=span_ids,
        )
        store.set_upload_interpretation_status(
            user_id, interpretation_id, "ruled"
        )
        seat = _UPLOAD_VOICE_MAP["artifact"]
        _upload_invite(
            store, user_id, body.conversation_id, seat,
            _invite_reason("Make an artifact"),
        )
        return {
            "artifact": artifact,
            "interpretation": _fresh_interpretation(),
            "next_voice": _upload_next_voice(user_id, seat),
        }

    # action == "train"
    from local_ai.agent_intake.review_claims import ReviewClaim
    from local_ai.agent_intake.schema import (
        ConnectedAgent,
        MomentClaim,
        SortResult,
        StrandClaim,
    )

    seat = (
        (body.seat or "").strip().lower()
        or _upload_conversation_seat(store, user_id, body.conversation_id)
        or "conductor"
    )
    if get_archetype(seat) is None:
        raise HTTPException(status_code=422, detail=f"Unknown seat: {seat!r}")
    agent_id = f"upload-{seat}-{interp['document_id']}"
    claim_id = f"{agent_id}:upload_interpretation:{interpretation_id}"
    agent_store = _agent_store(user_id)
    # Replay: the same claim already filed (the deterministic id
    # upserts — re-filing never duplicates, and the standing check
    # is skipped here by design).
    for existing_claim in agent_store.get_claims(agent_id):
        if existing_claim.id == claim_id:
            next_seat = _UPLOAD_VOICE_MAP["train"]
            _upload_invite(
                store, user_id, body.conversation_id, next_seat,
                _invite_reason("Train a model"),
            )
            return {
                "claim": existing_claim.to_dict(),
                "interpretation": interp,
                "replayed": True,
                "next_voice": _upload_next_voice(user_id, next_seat),
            }
    # Amendment A2 stacking: no global standing check — a ruled
    # interpretation (ruled by a DIFFERENT action) does not block
    # Train a model. The replay guard above (the same claim already
    # filed) is the only standing rule. The presentation check
    # already ran at the top of this handler.
    interp = _fresh_interpretation()
    spans = [
        store.get_upload_span(user_id, entry.get("span_id") or "")
        for entry in (interp.get("evidence_ids") or [])
        if isinstance(entry, dict) and entry.get("span_id")
    ]
    span_texts = [str(s.get("span_text") or "") for s in spans if s]
    evidence_lines = [f'"{text}"' for text in span_texts if text]
    evidence_lines.append(f"(from the upload round, message {body.message_id})")
    lens = str(interp.get("lens") or "")
    claim = ReviewClaim(
        id=claim_id,
        claim_type="upload_interpretation",
        title=_upload_first_line(str(interp.get("text") or ""), cap=80),
        evidence="\n".join(evidence_lines),
        inference=(interp.get("text") or "").strip(),
        detail=(
            f"Upload reading ({lens} strand, document "
            f"{interp['document_id']}); proposed outcome: "
            f"{interp.get('proposed_outcome') or 'none'}."
        ),
        status="pending",
        turn_ref=body.message_id,
    )
    sort = SortResult(
        primary_strand=lens,
        claims=[
            StrandClaim(
                strand=lens,
                score=1.0,
                reasoning="Named by the upload round's reading.",
            )
        ],
        strand_weights={lens: 1.0},
        kind="undecided",
        confidence=1.0,
        needs_probing=False,
        moments=[
            MomentClaim(
                strand=lens,
                quote=span_texts[0] if span_texts else "",
                inference=(interp.get("text") or "").strip(),
            )
        ],
    )
    agent = agent_store.get(agent_id)
    if agent is None:
        agent = ConnectedAgent(
            id=agent_id,
            name=f"Upload — {seat} — {interp['document_id']}",
            source_platform="upload",
            description=(
                f"An upload reading filed as a training candidate for "
                f"{seat}'s mirror."
            ),
            instructions=None,
            examples=[],
            sort=sort,
            status="pending_review",
            created_at=datetime.now(timezone.utc).isoformat(),
            mining_state="skipped",
        )
    else:
        agent.sort = sort
        agent.status = "pending_review"
    agent_store.save(agent)
    agent_store.save_claims(agent_id, [claim])
    store.set_upload_interpretation_status(user_id, interpretation_id, "ruled")
    next_seat = _UPLOAD_VOICE_MAP["train"]
    _upload_invite(
        store, user_id, body.conversation_id, next_seat,
        _invite_reason("Train a model"),
    )
    return {
        "claim": claim.to_dict(),
        "interpretation": _fresh_interpretation(),
        "next_voice": _upload_next_voice(user_id, next_seat),
    }


@router.post("/upload/round/skip")
def upload_round_skip(
    body: UploadRoundActionBody, current_user: dict = Depends(get_current_user)
) -> dict:
    """Park the round's current item — "Not now" (brief §7.4).

    A park changes no underlying state: the interpretation stays
    pending and returns at the next round. The next user message
    advances the round (the tap itself sends no turn, per the
    tap-continuation rule)."""
    user_id = _uid(current_user)
    if not user_id:
        raise HTTPException(status_code=401, detail="Sign in to continue the conversation.")
    store = _store()
    interp = _upload_interpretation_for_action(
        store, user_id, body.conversation_id, body.message_id, body.interpretation_id
    )
    store.park_round_item(
        user_id, body.conversation_id, UPLOAD_ROUND_KIND, body.interpretation_id
    )
    return {"parked": True, "interpretation": interp}


@router.post("/upload/round/reserve")
def upload_round_reserve(
    body: UploadRoundReserveBody, current_user: dict = Depends(get_current_user)
) -> dict:
    """Mark one item "don't remind me about this" (brief §7.4).

    Durable, not round-scoped: a snooze (the duration the user
    picked) or never. The round skips a reserved item until its
    snooze expires — never reserved never appears again. A tap,
    not prose: a durable suppression must never rest on a misread
    sentence. Archive-it (archive=True) reserves never AND moves
    the outcome row to 'archived' — reserve first, then the outcome
    status, so a failure between them leaves the item
    reserved-never, which is the safe side: it never reappears.
    """
    user_id = _uid(current_user)
    if not user_id:
        raise HTTPException(status_code=401, detail="Sign in to continue the conversation.")
    store = _store()
    interp = _upload_interpretation_for_action(
        store, user_id, body.conversation_id, body.message_id, body.interpretation_id
    )
    snooze_until = None
    if not body.archive and body.snooze_days is not None:
        snooze_until = (
            datetime.now(timezone.utc) + timedelta(days=body.snooze_days)
        ).isoformat()
    marker = store.reserve_round_item(
        user_id, UPLOAD_ITEM_KIND, body.interpretation_id, snooze_until=snooze_until
    )
    result: dict = {
        "reserved": True,
        "interpretation": interp,
        "marker": marker,
        "outcome": None,
    }
    if body.archive:
        # The outcome write follows the reserve; a failure here
        # leaves the item reserved-never (the safe side) and is
        # logged loudly — the reserve is the user-visible effect.
        # Amendment A2 (routing table): Archive-it is a verdict —
        # the outcome write also flips the interpretation to
        # 'ruled', so the reading leaves the round queue.
        try:
            outcome = store.create_upload_outcome(
                user_id,
                str(interp["document_id"]),
                int(interp["document_version"]),
                body.interpretation_id,
                "keep",
            )
            if outcome.get("status") == "pending":
                store.set_upload_outcome_status(
                    user_id, outcome["outcome_id"], "archived"
                )
                store.set_upload_interpretation_status(
                    user_id, body.interpretation_id, "ruled"
                )
                outcome = (
                    store.get_upload_outcome(user_id, outcome["outcome_id"])
                    or outcome
                )
            result["outcome"] = outcome
            result["interpretation"] = store.get_upload_interpretation(
                user_id, body.interpretation_id
            ) or interp
        except Exception:
            logger.exception(
                "upload round: archive outcome write failed (conversation_id=%s)",
                body.conversation_id,
            )
    return result


@router.post("/upload/round/unreserve")
def upload_round_unreserve(
    body: UploadRoundActionBody, current_user: dict = Depends(get_current_user)
) -> dict:
    """Lift a reserved marker — the round card's Undo.

    The presentation + standing checks apply here too: only the
    message that presented the item can lift its marker, and only
    while the interpretation is still pending. (An archived
    outcome row, if one was written, stays as a historical record.)
    """
    user_id = _uid(current_user)
    if not user_id:
        raise HTTPException(status_code=401, detail="Sign in to continue the conversation.")
    store = _store()
    interp = _upload_interpretation_for_action(
        store, user_id, body.conversation_id, body.message_id, body.interpretation_id
    )
    store.unreserve_round_item(user_id, UPLOAD_ITEM_KIND, body.interpretation_id)
    return {"reserved": False, "interpretation": interp}


@router.get("/upload/item-state")
def upload_item_state(
    conversation_id: str = Query(max_length=64),
    message_id: str = Query(max_length=64),
    interpretation_id: str = Query(max_length=64),
    current_user: dict = Depends(get_current_user),
) -> dict:
    """The upload card's hydration read: the interpretation (fully
    rendered, as the turn presented it) plus its round state
    (parked? reserved? outcome?) for one presented item.

    The presentation check applies, but the standing check does
    not: a decided interpretation still returns its state, so the
    card shows Created / Ruled after a reload. The uncertain-match
    marker is read from the row's ``uncertain_match`` column
    (amendment A3), falling back to a queue-time derivation when
    the column is NULL (e.g. the prior was ruled after this row
    was written)."""
    user_id = _uid(current_user)
    if not user_id:
        raise HTTPException(status_code=401, detail="Sign in to continue the conversation.")
    store = _store()
    _upload_presentation_check(
        store, user_id, conversation_id, message_id, interpretation_id
    )
    interp = store.get_upload_interpretation(user_id, interpretation_id)
    if interp is None:
        raise HTTPException(status_code=404, detail="Interpretation not found.")
    interp = dict(interp)
    interp["uncertain_match"] = uncertain_match_for(store, user_id, interp)
    coverage = upload_coverage(
        store, user_id, str(interp.get("document_id") or "")
    )
    try:
        from local_ai.vision_execution.storage import list_projects

        projects = list_projects(user_id)[:10]
    except Exception:
        logger.exception("upload round: parentage options failed")
        projects = []
    rendering = render_upload_interpretation(
        store,
        user_id,
        interp,
        coverage=coverage,
        parentage_options=[
            {"id": p.get("id"), "title": p.get("title")}
            for p in (projects or [])
            if p.get("id")
        ],
    )
    outcomes = store.list_upload_outcomes(
        user_id, interpretation_id=interpretation_id
    )
    # The standing outcome: a decided one ('created' / 'archived')
    # if any, else the most recent attempt.
    outcome = None
    for candidate in outcomes:
        if candidate.get("status") in ("created", "archived"):
            outcome = candidate
            break
    if outcome is None and outcomes:
        outcome = outcomes[-1]
    parked = interpretation_id in store.list_parked_round_items(
        user_id, conversation_id, UPLOAD_ROUND_KIND
    )
    marker = store.get_reserved_round_item(
        user_id, UPLOAD_ITEM_KIND, interpretation_id
    )
    return {
        "item": {
            "kind": UPLOAD_ITEM_KIND,
            "interpretation_id": interpretation_id,
            "document_id": interp.get("document_id"),
            "document_version": interp.get("document_version"),
            "lens": interp.get("lens"),
            "rendering": rendering,
        },
        "interpretation": interp,
        "outcome": outcome,
        "parked": parked,
        "reserved": marker,
    }


@router.get("/upload/diagnostics/stuck-outcomes")
def upload_stuck_outcomes(
    current_user: dict = Depends(get_current_user),
) -> dict:
    """Read-only: outcomes stuck mid-creation ('creating') with
    their age, the latest job state for the document, and whether a
    carrier row exists (R1 vs R2, brief §8.2, amendment A4). A
    'creating' outcome WITH a carrier row completes on the next
    approve attempt — the retry tap heals it (R1, reconciliation
    §6.3 R3). One WITHOUT is stuck: the retry tap re-claims it
    only when it is older than one hour (R2, step 1b); a younger
    one is refused ('Still creating — check back shortly')."""
    from local_ai.vision_execution import storage as ve_storage

    user_id = _uid(current_user)
    if not user_id:
        raise HTTPException(status_code=401, detail="Sign in to continue the conversation.")
    store = _store()
    now = datetime.now(timezone.utc)
    outcomes = []
    for outcome in store.list_upload_outcomes(user_id, status="creating"):
        created = None
        try:
            created = datetime.fromisoformat(
                str(outcome.get("created_at") or "").replace("Z", "+00:00")
            )
        except ValueError:
            created = None
        job = store.latest_upload_job(user_id, outcome.get("document_id") or "")
        outcomes.append(
            {
                "outcome_id": outcome.get("outcome_id"),
                "document_id": outcome.get("document_id"),
                "interpretation_id": outcome.get("interpretation_id"),
                "status": outcome.get("status"),
                "age_s": int((now - created).total_seconds())
                if created is not None
                else None,
                "job_state": job.get("state") if job else None,
                "carrier_exists": ve_storage.get_upload_outcome_creation(
                    user_id, outcome.get("outcome_id") or ""
                )
                is not None,
            }
        )
    return {"outcomes": outcomes}


@router.get("/list")
def list_conversations(
    limit: int = Query(default=20, ge=1, le=100),
    seat: str | None = Query(default=None, max_length=64),
    current_user: dict = Depends(get_current_user),
) -> dict:
    """List the caller's talk conversations, newest message activity first.

    Discovery only: the ``seats`` array in each entry is derived from
    message rows (seats that have already spoken in the conversation)
    so the client can resume a talk. It is NOT a participation or
    authorization record — no invite, join, or membership state is
    implied, and no participant table exists. Every aggregate and
    preview subquery carries the caller's user_id predicate, so
    another user's rows can never match.

    When ``seat`` is given, only conversations that seat has spoken
    in are returned, via an EXISTS membership predicate applied
    before the limit (see ConversationStore.list_conversations).
    An absent or empty seat returns today's unfiltered list.
    """
    user_id = _uid(current_user)
    if not user_id:
        raise HTTPException(status_code=401, detail="Sign in to continue the conversation.")
    return {"conversations": _store().list_conversations(user_id, limit=limit, seat=seat)}


@router.get("")
def get_conversation(
    conversation_id: str = Query(default="skeleton", max_length=64),
    limit: int = Query(default=50, ge=1, le=200),
    before: str | None = Query(default=None, max_length=64),
    current_user: dict = Depends(get_current_user),
) -> dict:
    """Hydrate the ongoing conversation (oldest first).

    ``before`` is a stable paging cursor: the id of the oldest message
    the client already shows. When present, the response holds only
    messages strictly older than that message's (created_at, id) pair,
    so messages appended after the snapshot can never shift, duplicate,
    or skip rows in earlier pages. An unknown cursor — including one
    from another user or conversation — returns an empty page.
    ``total`` is the live message count for the conversation.
    """
    user_id = _uid(current_user)
    if not user_id:
        raise HTTPException(status_code=401, detail="Sign in to continue the conversation.")
    cid = (conversation_id or "skeleton").strip() or "skeleton"
    svc = _service()
    if before:
        messages = svc.history_before(user_id, cid, before_id=before, limit=limit)
    else:
        messages = svc.history(user_id, cid, limit=limit)
    total = svc.store.count_messages(user_id, cid)
    return {"conversation_id": cid, "messages": messages, "total": total}


# ---------------------------------------------------------------------------
# Capability C S4 — invitation read surface.
# ---------------------------------------------------------------------------

#: Verdict Q5: the reason is the inviting selection's reading, never
#: presented as fact. Every item carries this attribution explicitly
#: so no client can render the reason as an established claim about
#: the conversation.
INVITATION_REASON_ATTRIBUTION = (
    "The inviting selection's reading of the exchange — an "
    "interpretation, not an established fact."
)


def _invitation_api_item(inv: dict) -> dict:
    """Read-surface shape for one invitation (Capability C S4).

    The caller's user_id is not echoed (the endpoint is strictly
    per-user already); the stored evidence travels verbatim, and the
    reason travels with its attribution attached. Pure shaping — no
    store reads, no status changes.
    """
    return {
        "id": inv.get("id"),
        "conversation_id": inv.get("conversation_id"),
        "seat": inv.get("seat"),
        "reason": inv.get("reason"),
        "reason_attribution": INVITATION_REASON_ATTRIBUTION,
        "evidence": inv.get("evidence") or {},
        "status": inv.get("status"),
        "created_at": inv.get("created_at"),
        "expires_at": inv.get("expires_at"),
    }


@router.get("/invitations")
def list_invitations(
    conversation_id: str = Query(default="skeleton", max_length=64),
    current_user: dict = Depends(get_current_user),
) -> dict:
    """Pending invitations for one conversation (Capability C S4).

    READ-ONLY: listing never changes invitation status. Tapping an
    invitation opens the seat's sheet (a client action, not a state
    transition); only a sent turn to the invited seat accepts it
    (S1 accept-on-turn). A cleared conversation yields nothing: clear
    expires its pending rows, and the pending filter excludes expired
    rows even before any sweep. Strictly per-user: another user's
    rows, and foreign conversation ids, yield nothing.
    """
    user_id = _uid(current_user)
    if not user_id:
        raise HTTPException(status_code=401, detail="Sign in to continue the conversation.")
    cid = (conversation_id or "skeleton").strip() or "skeleton"
    pending = _store().list_pending_invitations(user_id, cid)
    return {
        "conversation_id": cid,
        "invitations": [_invitation_api_item(inv) for inv in pending],
    }


# ---------------------------------------------------------------------------
# Weaver strand interviews (rev2, as accepted).
#
# One ordinary Weaver (conductor) Talk thread per strand, opened from
# the Tree's strand roots. Conversation-first: resolve opens the thread
# immediately with a pattern-copy orientation — NO model call happens
# on open (T1b). The first generated Weaver question arrives via the
# standard POST /conversation/turn path, with strand_key carried on
# LiveContext and validated server-side there.
#
# Strand keys are the design keys (heart, hands, logic, voice, ear,
# compass, eye). The server never trusts a client-supplied strand_key:
# unknown keys and threads that are not the caller's mapped thread for
# the strand fail closed with a 422. No first-meeting gate: strand
# threads never touch meeting state (rev2 §6, OQ5).
# ---------------------------------------------------------------------------


def _ingest_store():
    """Presence-ingest store (file-source sessions). Lazily imported
    so this module never depends on the ingest pipeline at import
    time; monkeypatchable in tests."""
    from local_ai.presence_ingest.store import PresenceStore

    return PresenceStore()


def _check_strand(strand_key: str) -> str:
    """Validate a design strand key (fail closed, 422 on unknown)."""
    from local_ai.strand_interviews.keys import validate_strand_key

    try:
        return validate_strand_key(strand_key)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


def _strand_source_api_item(source: dict) -> dict:
    """Read-surface shape for one linked strand source. Paste excerpts
    travel redacted (they were redacted at capture); file sources carry
    no excerpt here — their redacted events are read at turn time."""
    excerpt = str(source.get("excerpt_redacted") or "")
    return {
        "id": source.get("id"),
        "strand_key": source.get("strand_key"),
        "conversation_id": source.get("conversation_id"),
        "kind": source.get("kind"),
        "ref": source.get("ref"),
        "label": source.get("label"),
        "excerpt": excerpt[:500] if excerpt else "",
        "created_at": source.get("created_at"),
    }


def _strand_resolve_payload(user_id: str, strand_key: str) -> dict:
    """Resolve payload for one strand: mapping + orientation + boundaries
    + sources. Storage only — no model call, no generation."""
    from local_ai.strand_interviews.keys import STRAND_DEFINITIONS
    from local_ai.strand_interviews.orientation import orientation_for

    store = _store()
    resolved = store.resolve_strand_thread(user_id, strand_key)
    definition = STRAND_DEFINITIONS[strand_key]
    return {
        "strand_key": strand_key,
        "strand_name": definition["agent_name"],
        "definition": definition["definition"],
        "conversation_id": resolved["conversation_id"],
        "is_fresh": bool(resolved["is_fresh"]),
        "orientation": orientation_for(
            strand_key, is_fresh=bool(resolved["is_fresh"])
        ),
        "boundaries": store.list_topic_boundaries(user_id, strand_key),
        "sources": [
            _strand_source_api_item(s)
            for s in store.list_strand_sources(user_id, strand_key)
        ],
    }


@router.get("/strand/{strand_key}")
def resolve_strand(strand_key: str, current_user: dict = Depends(get_current_user)) -> dict:
    """Resolve-or-create the caller's strand thread (rev2 T1/T1b).

    Returns the mapped conversation_id, the pattern-copy orientation
    (fresh vs returning), active topic boundaries, and linked sources.
    Performs ZERO model calls: opening a strand thread never
    generates. The first generated Weaver question comes from the
    standard turn endpoint once the user sends a message.
    """
    user_id = _uid(current_user)
    if not user_id:
        raise HTTPException(status_code=401, detail="Sign in to continue the conversation.")
    key = _check_strand(strand_key)
    return _strand_resolve_payload(user_id, key)


class StrandBoundaryBody(BaseModel):
    topic: str = Field(max_length=120)


@router.post("/strand/{strand_key}/boundaries")
def add_strand_boundary(
    strand_key: str,
    body: StrandBoundaryBody,
    current_user: dict = Depends(get_current_user),
) -> dict:
    """Record an explicit topic boundary ("never ask me about this").

    Only the user's explicit boundary-setting words create a boundary
    (rev2 C2); this endpoint is the explicit user action for it. The
    turn path also recognizes explicit boundary words in strand-thread
    messages. Ordinary declines are never recorded here. Idempotent by
    normalized topic.
    """
    user_id = _uid(current_user)
    if not user_id:
        raise HTTPException(status_code=401, detail="Sign in to continue the conversation.")
    key = _check_strand(strand_key)
    try:
        return _store().add_topic_boundary(user_id, key, body.topic)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.delete("/strand/{strand_key}/boundaries/{boundary_id}")
def delete_strand_boundary(
    strand_key: str,
    boundary_id: str,
    current_user: dict = Depends(get_current_user),
) -> dict:
    """Reopen a bounded topic: questions on it may be asked again (C2)."""
    user_id = _uid(current_user)
    if not user_id:
        raise HTTPException(status_code=401, detail="Sign in to continue the conversation.")
    _check_strand(strand_key)
    deleted = _store().delete_topic_boundary(user_id, boundary_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Unknown topic boundary.")
    return {"deleted": True}


class StrandSourceBody(BaseModel):
    kind: str = Field(max_length=16)
    text: str | None = Field(default=None, max_length=20000)
    ingest_session_id: str | None = Field(default=None, max_length=128)
    label: str | None = Field(default=None, max_length=200)


@router.post("/strand/{strand_key}/sources")
def add_strand_source(
    strand_key: str,
    body: StrandSourceBody,
    current_user: dict = Depends(get_current_user),
) -> dict:
    """Link a source to a strand thread (rev2 §7, P2).

    Paste: text is redacted at capture (emails, phones, SSNs, long
    digit runs) and the redacted excerpt is stored, capped at 2000
    chars. File: the ingest session id must name an EXISTING session
    (unknown ids fail closed); the session's redacted events are read
    at turn time, never duplicated here. The source is always linked
    to the caller's OWN mapped thread for the strand — the client
    supplies no conversation id. Share links are paste-fallback in
    this slice (rev2 OQ2): the panel offers paste as the guaranteed
    path; server-side share-link fetching exists in the intake
    pipeline but strand-targeted share-link import is out of scope.
    """
    user_id = _uid(current_user)
    if not user_id:
        raise HTTPException(status_code=401, detail="Sign in to continue the conversation.")
    key = _check_strand(strand_key)
    store = _store()
    resolved = store.resolve_strand_thread(user_id, key)
    kind = (body.kind or "").strip().lower()
    try:
        if kind == "paste":
            from local_ai.presence_ingest.redact import redact_text

            text = (body.text or "").strip()
            if not text:
                raise HTTPException(status_code=422, detail="Pasted text is empty.")
            # U-2: the full redacted text lives COMPRESSED on the
            # source row (paste_text_blob); the excerpt stays capped
            # at 2000 chars, unchanged.
            redacted = redact_text(text)
            excerpt = redacted[:2000]
            source = store.add_strand_source(
                user_id,
                key,
                resolved["conversation_id"],
                "paste",
                "paste",
                label=(body.label or "").strip() or "Pasted text",
                excerpt_redacted=excerpt,
                paste_full_text=redacted,
            )
        elif kind == "file":
            session_id = (body.ingest_session_id or "").strip()
            if not session_id:
                raise HTTPException(status_code=422, detail="Ingest session id is empty.")
            session = _ingest_store().get_session(session_id)
            if session is None:
                raise HTTPException(status_code=404, detail="Unknown import session.")
            source = store.add_strand_source(
                user_id,
                key,
                resolved["conversation_id"],
                "file",
                session_id,
                label=(body.label or "").strip() or str(session.file_name or ""),
            )
        else:
            raise HTTPException(
                status_code=422, detail=f"Unknown strand source kind: {body.kind!r}"
            )
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return _strand_source_api_item(source)


@router.get("/strand/{strand_key}/sources")
def list_strand_sources(
    strand_key: str, current_user: dict = Depends(get_current_user)
) -> dict:
    """Linked sources for one strand (per-strand scoping: a Hands
    source is never evidence in a Heart conversation)."""
    user_id = _uid(current_user)
    if not user_id:
        raise HTTPException(status_code=401, detail="Sign in to continue the conversation.")
    key = _check_strand(strand_key)
    store = _store()
    return {
        "strand_key": key,
        "sources": [
            _strand_source_api_item(s)
            for s in store.list_strand_sources(user_id, key)
        ],
    }


# ---------------------------------------------------------------------------
# Keystone meetings — guided first-meeting conversations (see
# local_ai/conversation/meeting.py). The transcript lives in the same
# conversation store under its own conversation_id; these endpoints drive
# the stage machine. MeetingError (a design-rule refusal) maps to 409.
# ---------------------------------------------------------------------------


def _meeting_service() -> MeetingService:
    return MeetingService(ConversationStore(), MeetingStore())


class MeetingStartBody(BaseModel):
    archetype_id: str = Field(max_length=32)
    keystone_index: int = Field(default=1, ge=1, le=4)


class MeetingTurnBody(BaseModel):
    archetype_id: str = Field(max_length=32)
    keystone_index: int = Field(default=1, ge=1, le=4)
    message: str = Field(default="", max_length=_MSG_MAX)


class MeetingPauseBody(BaseModel):
    archetype_id: str = Field(max_length=32)
    keystone_index: int = Field(default=1, ge=1, le=4)


class MeetingRestartBody(BaseModel):
    archetype_id: str = Field(max_length=32)
    keystone_index: int = Field(default=1, ge=1, le=4)


class MeetingCompleteBody(BaseModel):
    archetype_id: str = Field(max_length=32)
    keystone_index: int = Field(default=1, ge=1, le=4)


def _meeting_call(fn) -> dict:
    try:
        return fn()
    except MeetingError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    except Exception as exc:  # noqa: BLE001 — loud failure
        raise HTTPException(status_code=502, detail=f"Meeting unavailable: {exc}")


@router.post("/meeting/start")
def meeting_start(body: MeetingStartBody, current_user: dict = Depends(get_current_user)) -> dict:
    """Begin or resume a keystone meeting; returns the full meeting state
    including the transcript."""
    user_id = _uid(current_user)
    if not user_id:
        raise HTTPException(status_code=401, detail="Sign in to begin the meeting.")
    arch_id = _check_seat(body.archetype_id)
    return _meeting_call(lambda: _meeting_service().start(user_id, arch_id, body.keystone_index))


@router.post("/meeting/turn")
def meeting_turn(body: MeetingTurnBody, current_user: dict = Depends(get_current_user)) -> dict:
    """One user turn inside the active meeting."""
    user_id = _uid(current_user)
    if not user_id:
        raise HTTPException(status_code=401, detail="Sign in to continue the meeting.")
    arch_id = _check_seat(body.archetype_id)
    return _meeting_call(
        lambda: _meeting_service().turn(user_id, arch_id, body.message, body.keystone_index)
    )


@router.post("/meeting/pause")
def meeting_pause(body: MeetingPauseBody, current_user: dict = Depends(get_current_user)) -> dict:
    """Set the meeting aside; it resumes at the same beat later."""
    user_id = _uid(current_user)
    if not user_id:
        raise HTTPException(status_code=401, detail="Sign in to pause the meeting.")
    arch_id = _check_seat(body.archetype_id)
    return _meeting_call(lambda: _meeting_service().pause(user_id, arch_id, body.keystone_index))


@router.post("/meeting/restart")
def meeting_restart(body: MeetingRestartBody, current_user: dict = Depends(get_current_user)) -> dict:
    """Meet again: archive a completed meeting's full transcript, verified
    complete, and reset it to not-started (its keystone task returns to
    its seeded status), so the conversation can be run fresh. Refuses —
    409 — when there is no completed meeting to restart."""
    user_id = _uid(current_user)
    if not user_id:
        raise HTTPException(status_code=401, detail="Sign in to meet again.")
    arch_id = _check_seat(body.archetype_id)
    return _meeting_call(lambda: _meeting_service().restart(user_id, arch_id, body.keystone_index))


@router.post("/meeting/complete")
def meeting_complete(body: MeetingCompleteBody, current_user: dict = Depends(get_current_user)) -> dict:
    """Complete an in-progress meeting at the visitor's word, so it
    reaches its close (and Meet again becomes available) even when the
    runtime's own close verdict never fired. Returns the completed
    state, including the character's closing words. Refuses — 409 —
    when there is no meeting in progress to complete."""
    user_id = _uid(current_user)
    if not user_id:
        raise HTTPException(status_code=401, detail="Sign in to complete the meeting.")
    arch_id = _check_seat(body.archetype_id)
    return _meeting_call(lambda: _meeting_service().complete(user_id, arch_id, body.keystone_index))


@router.get("/meeting")
def meeting_state(
    archetype_id: str = Query(max_length=32),
    keystone_index: int = Query(default=1, ge=1, le=4),
    current_user: dict = Depends(get_current_user),
) -> dict:
    """Current meeting state + transcript for hydration/resume."""
    user_id = _uid(current_user)
    if not user_id:
        raise HTTPException(status_code=401, detail="Sign in to see the meeting.")
    arch_id = _check_seat(archetype_id)
    return _meeting_call(lambda: _meeting_service().state(user_id, arch_id, keystone_index))


@router.get("/suggestions")
def get_suggestions(
    conversation_id: str = Query(default="skeleton", max_length=64),
    current_user: dict = Depends(get_current_user),
) -> dict:
    """The suggestion engine's three kinds, all drafts. Cached per message
    watermark — a repeat GET with no new messages returns the cached run."""
    user_id = _uid(current_user)
    if not user_id:
        raise HTTPException(status_code=401, detail="Sign in to continue the conversation.")
    cid = (conversation_id or "skeleton").strip() or "skeleton"
    service = _service()
    store = service.store

    # Permissions Slice 1 (B-S2): the thread summaries folded into
    # suggestion minting below are steward-derived material, and a
    # cached run carries their citations (thread_note / thread ids) —
    # both are consumptions of steward_derivation. The check runs on
    # every request, so a revocation takes effect at the next
    # request, cached runs included; already-served suggestions are
    # not recalled. Governed by steward_derivation ALONE (O-S1-5):
    # this is same-conversation consumption of the user's own thread
    # state, not cross-branch coordination, so no coordination flag
    # is consulted here.
    from local_ai.permissions.consumption import consumption_allowed

    steward_ok = consumption_allowed(user_id, "steward_derivation")

    latest_id = store.latest_message_id(user_id, cid)
    if latest_id and steward_ok:
        cached = store.get_suggestion_run(user_id, cid)
        if cached and cached["up_to_message_id"] == latest_id:
            return {
                "conversation_id": cid,
                "cached": True,
                **sugg.asdict_suggestion_payload(cached["suggestions"]),
            }

    turns = service.history(user_id, cid, limit=30)
    live_context = (turns[-1].get("context") or {}) if turns else {}
    seat_names: dict[str, str] = {}
    try:
        from local_ai.council.naming import get_display_name

        for t in turns:
            arch = t.get("archetype_id")
            if arch and arch not in seat_names:
                seat_names[arch] = get_display_name(user_id, arch)
    except Exception:
        pass

    # Phase 5: mint items cite live thread ids from the read model.
    # Best-effort and same-user only — any failure leaves thread
    # state out, which is exactly the pre-Phase 5 behavior. Threads
    # are the user's own state surfaced in their own conversation;
    # this is not cross-branch coordination, so no coordination flag
    # gates it (the route itself is already current-user-only). The
    # steward_derivation consumption check above does gate it
    # (Slice 1, B-S2): when derivation is off the summaries are not
    # built at all, and minting takes its existing no-threads path.
    thread_summaries = None
    if steward_ok:
        try:
            from api.routes.steward_routes import get_narrative_store
            from local_ai.narrative.read_model import active_thread_summaries

            _narrative_store = get_narrative_store()
            try:
                thread_summaries = active_thread_summaries(
                    _narrative_store.snapshot_for_read(user_id)
                )
            finally:
                _narrative_store.close()
        except Exception:
            thread_summaries = None

    payload = sugg.generate_suggestions(
        turns, live_context, generate_fn=None, seat_names=seat_names,
        user_id=user_id, threads=thread_summaries,
    )
    payload = sugg.asdict_suggestion_payload(payload)
    if latest_id:
        store.save_suggestion_run(user_id, cid, latest_id, payload)
    return {"conversation_id": cid, "cached": False, **payload}
