"""Agent Intake & Sorting API ("The Sorting").

Pipeline: POST /agents/connect -> GET /agents/pending ->
POST /agents/{id}/confirm.

Privacy: no endpoint ever returns raw unredacted text. Descriptions,
instructions, and examples are redacted at capture; only redacted text is
stored or returned.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, field_validator

from local_ai.agent_intake.pipeline import AgentIntakeError

router = APIRouter(prefix="/agents", tags=["agents"])


class ConnectBody(BaseModel):
    """Describe an external agent to connect (lowest-friction intake)."""

    name: str
    platform: str = "manual"
    description: str
    instructions: str | None = None
    examples: list[str] = []

    @field_validator("name", "description")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        v = (v or "").strip()
        if not v:
            raise ValueError("name and description are required")
        return v


class ShareLinkBody(BaseModel):
    """Connect via a shared conversation URL (ChatGPT/Claude share link)."""

    url: str
    name: str | None = None

    @field_validator("url")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        v = (v or "").strip()
        if not v:
            raise ValueError("url is required")
        return v


class ConfirmBody(BaseModel):
    """Review-gate decision: accept as sorted, or correct the placement."""

    accepted: bool = True
    corrections: dict = {}


def _store():
    from local_ai.agent_intake.store import AgentStore

    return AgentStore()


def _pipeline():
    from local_ai.agent_intake import pipeline

    return pipeline


@router.post("/connect", status_code=201)
def connect_agent(body: ConnectBody):
    """Connect an external agent: redact at capture, sort, queue for review.

    Returns the agent with its SortResult and status "pending_review".
    """
    try:
        agent = _pipeline().connect_agent(
            name=body.name,
            platform=body.platform,
            description=body.description,
            instructions=body.instructions,
            examples=body.examples,
            store=_store(),
        )
    except AgentIntakeError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return agent.to_dict()


@router.post("/connect/share-link", status_code=201)
def connect_via_share_link(body: ShareLinkBody):
    """Connect from a ChatGPT/Claude shared conversation URL.

    Accepts the link, fetches and parses the transcript, then runs the
    standard connect pipeline. 422 if the URL is unsupported or the page
    needs JavaScript rendering (caller should paste the text instead).
    """
    try:
        agent = _pipeline().connect_via_share_link(
            url=body.url,
            name=body.name,
            store=_store(),
        )
    except AgentIntakeError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return agent.to_dict()


@router.get("/pending")
def list_pending_agents():
    """Review queue: agents awaiting accept/correct."""
    return [a.to_dict() for a in _store().list_pending()]


@router.get("")
def list_agents():
    """All connected agents."""
    return [a.to_dict() for a in _store().list_all()]


@router.post("/{agent_id}/confirm")
def confirm_agent(agent_id: str, body: ConfirmBody):
    """Accept the sort, correct it, or archive the agent.

    Corrections ("no, this is a People talent") are logged as
    ideals-guidance training signals for the v2 sorter.
    """
    try:
        agent = _pipeline().confirm_agent(
            agent_id,
            accepted=body.accepted,
            corrections=body.corrections or None,
            store=_store(),
        )
    except AgentIntakeError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return agent.to_dict()
