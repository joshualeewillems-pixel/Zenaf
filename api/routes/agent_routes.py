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


def _render_store():
    from local_ai.agent_intake.render_jobs import RenderJobStore

    return RenderJobStore()


@router.post("/connect/share-link", status_code=201)
def connect_via_share_link(body: ShareLinkBody):
    """Connect from a ChatGPT/Claude shared conversation URL.

    If the page renders server-side, connects immediately. If it needs
    JavaScript, queues a render job for a registered browser and returns
    {"status": "pending_render", "job_id"} — the pipeline resumes
    automatically when a renderer completes the job.
    """
    try:
        agent, job = _pipeline().connect_via_share_link(
            url=body.url,
            name=body.name,
            store=_store(),
            render_store=_render_store(),
        )
    except AgentIntakeError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    if job is not None:
        return {
            "status": "pending_render",
            "job_id": job.id,
            "message": (
                "This page needs JavaScript rendering. A registered browser "
                "(desktop extension or iOS Shortcut) will pick it up; the "
                "agent will appear in your review queue when rendering completes."
            ),
        }
    assert agent is not None
    return {"status": "connected", **agent.to_dict()}


# ---------------------------------------------------------------------------
# Render jobs — for registered browsers (desktop extension, iOS Shortcut).
# ---------------------------------------------------------------------------


@router.get("/render-jobs/next")
def render_job_next(worker_id: str = ""):
    """A registered renderer polls here to claim its next job.

    Returns {"job": {...} | None}. Claiming is atomic — one job per worker.
    """
    worker_id = (worker_id or "").strip() or "anonymous"
    job = _render_store().next_pending(worker_id)
    return {"job": job.to_dict() if job else None}


@router.get("/render-jobs/{job_id}")
def render_job_status(job_id: str):
    """Check a render job's status (for UI polling)."""
    job = _render_store().get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="unknown render job")
    d = job.to_dict()
    d["pending_count"] = _render_store().pending_count()
    return d


class RenderCompleteBody(BaseModel):
    transcript: str
    title: str | None = None
    name: str | None = None  # optional agent name override

    @field_validator("transcript")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        v = (v or "").strip()
        if not v:
            raise ValueError("transcript is required")
        return v


@router.post("/render-jobs/{job_id}/complete", status_code=201)
def render_job_complete(job_id: str, body: RenderCompleteBody):
    """A renderer submits the extracted transcript; the intake pipeline resumes.

    Returns the connected agent (with sort + mined projects) in one call.
    """
    from local_ai.agent_intake import project_miner

    rs = _render_store()
    job = rs.complete(job_id, body.transcript, body.title)
    if job is None:
        raise HTTPException(status_code=404, detail="unknown render job")
    try:
        agent = _pipeline().resume_from_render(
            job_id, name=(body.name or "").strip() or None, store=_store(), render_store=rs
        )
    except AgentIntakeError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    # Mine projects/tasks from the transcript (best-effort, same as share-text).
    mined: dict = {"engine": "none", "initiatives": [], "projects": [], "standalone_tasks": [], "ideas": []}
    try:
        from dataclasses import asdict

        result = project_miner.mine_projects(body.transcript)
        mined = {
            "engine": result.engine,
            "initiatives": [asdict(i) for i in result.initiatives],
            "projects": [asdict(p) for p in result.projects],
            "standalone_tasks": [asdict(t) for t in result.standalone_tasks],
            "ideas": [asdict(i) for i in result.ideas],
        }
    except Exception:
        pass
    return {"agent": agent.to_dict(), "mined": mined}


@router.post("/render-jobs/{job_id}/fail", status_code=200)
def render_job_fail(job_id: str, body: dict | None = None):
    """A renderer reports it could not extract the page."""
    error = str((body or {}).get("error", "renderer failed"))[:500]
    job = _render_store().fail(job_id, error)
    if job is None:
        raise HTTPException(status_code=404, detail="unknown render job")
    return job.to_dict()


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


class ShareTextBody(BaseModel):
    """Bookmarklet-extracted share-page text."""

    url: str
    transcript: str
    title: str | None = None
    name: str | None = None

    @field_validator("url", "transcript")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        v = (v or "").strip()
        if not v:
            raise ValueError("url and transcript are required")
        return v


@router.post("/connect/share-text", status_code=201)
def connect_share_text(body: ShareTextBody):
    """Connect an agent from bookmarklet-extracted share-page text.

    The Zenaf bookmarklet runs inside the rendered page in the user's own
    browser, extracts the conversation, and POSTs it here — no copy/paste.
    Runs the standard intake pipeline (redact → sort → review queue) and
    returns the pending agent plus mined project/task proposals.
    """
    from local_ai.agent_intake import project_miner

    try:
        agent = _pipeline().connect_via_extracted_text(
            url=body.url,
            transcript=body.transcript,
            title=(body.title or "").strip() or None,
            name=(body.name or "").strip() or None,
            store=_store(),
        )
    except AgentIntakeError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    # Mine projects/tasks from the same transcript (best-effort).
    mined: dict = {"engine": "none", "initiatives": [], "projects": [], "standalone_tasks": [], "ideas": []}
    try:
        from dataclasses import asdict

        result = project_miner.mine_projects(body.transcript)
        mined = {
            "engine": result.engine,
            "initiatives": [asdict(i) for i in result.initiatives],
            "projects": [asdict(p) for p in result.projects],
            "standalone_tasks": [asdict(t) for t in result.standalone_tasks],
            "ideas": [asdict(i) for i in result.ideas],
        }
    except Exception:
        pass
    return {"agent": agent.to_dict(), "mined": mined}


class IntakeChatBody(BaseModel):
    """One message to the Muse intake guide."""

    message: str
    history: list[dict] = []


@router.post("/intake/chat", status_code=200)
def intake_chat(body: IntakeChatBody):
    """Chat with Muse to connect a conversation.

    Paste conversation text (or drop a share link); Muse routes it through
    the intake pipeline and replies conversationally. Anything else gets a
    plain Muse reply as the intake guide.
    """
    from local_ai.agent_intake import intake_chat as ichat

    return ichat.handle_message(body.message, body.history)


class MineBody(BaseModel):
    """Mine a transcript for proposed projects and tasks."""

    transcript: str

    @field_validator("transcript")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        v = (v or "").strip()
        if not v:
            raise ValueError("transcript is required")
        return v


@router.post("/mine-projects", status_code=200)
def mine_projects(body: MineBody):
    """Read a transcript like a chief of staff: propose projects and tasks.

    Returns proposed projects (with nested tasks) and standalone tasks, each
    with source quotes. Nothing is created — the user reviews and confirms
    via POST /agents/mined-projects/confirm, which creates real Vision
    Execution entities. Uses the Anthropic engine when configured,
    rule-based fallback otherwise.
    """
    from local_ai.agent_intake import project_miner
    from dataclasses import asdict

    result = project_miner.mine_projects(body.transcript)
    return {
        "engine": result.engine,
        "initiatives": [asdict(i) for i in result.initiatives],
        "projects": [asdict(p) for p in result.projects],
        "standalone_tasks": [asdict(t) for t in result.standalone_tasks],
        "ideas": [asdict(i) for i in result.ideas],
    }


class ConfirmMinedBody(BaseModel):
    """User-confirmed subset of mined proposals to create as VE entities."""

    initiatives: list[dict] = []
    projects: list[dict] = []
    standalone_tasks: list[dict] = []
    ideas: list[dict] = []
    selected_titles: list[str] | None = None  # None = create all
    user_id: str = ""


@router.post("/mined-projects/confirm", status_code=201)
def confirm_mined_projects(body: ConfirmMinedBody):
    """Create Vision Execution entities from confirmed mined proposals.

    Respects the VE hierarchy (initiatives → projects → tasks, plus ideas).
    Plugs into the existing VE service layer — no parallel structures.
    """
    from local_ai.agent_intake import project_miner

    if not body.user_id.strip():
        raise HTTPException(status_code=422, detail="user_id is required")

    def _task(d: dict) -> project_miner.ProposedTask:
        return project_miner.ProposedTask(
            title=str(d.get("title", "")),
            detail=str(d.get("detail", "")),
            source_quote=str(d.get("source_quote", "")),
        )

    result = project_miner.MiningResult(
        initiatives=[
            project_miner.ProposedInitiative(
                title=str(i.get("title", "")),
                brief=str(i.get("brief", "")),
                source_quote=str(i.get("source_quote", "")),
                project_titles=[str(t) for t in (i.get("project_titles") or [])],
            )
            for i in body.initiatives
            if i.get("title")
        ],
        projects=[
            project_miner.ProposedProject(
                title=str(p.get("title", "")),
                goal=str(p.get("goal", "")),
                status_hint=str(p.get("status_hint", "")),
                source_quote=str(p.get("source_quote", "")),
                initiative_title=(str(p.get("initiative_title", "")).strip() or None),
                tasks=[_task(t) for t in (p.get("tasks") or []) if t.get("title")],
            )
            for p in body.projects
            if p.get("title")
        ],
        standalone_tasks=[_task(t) for t in body.standalone_tasks if t.get("title")],
        ideas=[
            project_miner.ProposedIdea(
                title=str(i.get("title", "")),
                detail=str(i.get("detail", "")),
                source_quote=str(i.get("source_quote", "")),
            )
            for i in body.ideas
            if i.get("title")
        ],
        engine="api",
    )
    selected = set(body.selected_titles) if body.selected_titles is not None else None
    try:
        return project_miner.create_confirmed(result, body.user_id.strip(), selected)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)[:300])


@router.get("/bookmarklet/install", include_in_schema=False)
def bookmarklet_install():
    """Serve the bookmarklet install page (HTML)."""
    from fastapi.responses import HTMLResponse
    from pathlib import Path

    page = Path(__file__).resolve().parent.parent.parent / "local_ai" / "agent_intake" / "install_page.html"
    return HTMLResponse(content=page.read_text(encoding="utf-8"))
