"""Agent Intake & Sorting API ("The Sorting").

Pipeline: POST /agents/connect -> GET /agents/pending ->
POST /agents/{id}/confirm.

Privacy: no endpoint ever returns raw unredacted text. Descriptions,
instructions, and examples are redacted at capture; only redacted text is
stored or returned.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, field_validator

from api.routes.auth_routes import get_current_user
from local_ai.agent_intake.pipeline import AgentIntakeError

router = APIRouter(prefix="/agents", tags=["agents"])

logger = logging.getLogger(__name__)


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


def _store(user_id: str | None):
    from local_ai.agent_intake.store import AgentStore

    return AgentStore(user_id=user_id)


def _uid(current_user: dict) -> str:
    return current_user["id"]


def _require_train_self(user_id: str) -> None:
    """Intake needs the user's explicit train:self consent (default-deny)."""
    from local_ai.identity import ScopeDenied
    from local_ai.identity.scopes import require_scope

    try:
        require_scope("train:self", user_id=user_id)
    except ScopeDenied:
        raise HTTPException(
            status_code=403,
            detail="Intake needs your 'train:self' consent scope. Grant it in Settings → Identity.",
        )


def _pipeline():
    from local_ai.agent_intake import pipeline

    return pipeline


@router.post("/connect", status_code=201)
def connect_agent(body: ConnectBody, current_user: dict = Depends(get_current_user)):
    """Connect an external agent: redact at capture, sort, queue for review.

    Returns the agent with its SortResult and status "pending_review".
    """
    uid = _uid(current_user)
    _require_train_self(uid)
    try:
        agent = _pipeline().connect_agent(
            name=body.name,
            platform=body.platform,
            description=body.description,
            instructions=body.instructions,
            examples=body.examples,
            store=_store(uid),
        )
    except AgentIntakeError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return agent.to_dict()


def _render_store():
    from local_ai.agent_intake.render_jobs import RenderJobStore

    return RenderJobStore()


@router.post("/connect/share-link", status_code=201)
def connect_via_share_link(body: ShareLinkBody, current_user: dict = Depends(get_current_user)):
    """Connect from a ChatGPT/Claude shared conversation URL.

    If the page renders server-side, connects immediately. If it needs
    JavaScript, queues a render job for a registered browser and returns
    {"status": "pending_render", "job_id"} — the pipeline resumes
    automatically when a renderer completes the job.
    """
    try:
        uid = _uid(current_user)
        _require_train_self(uid)
        agent, job = _pipeline().connect_via_share_link(
            url=body.url,
            name=body.name,
            store=_store(uid),
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


def _require_worker_key(request: Request):
    """Shared-secret auth for the render-job worker endpoints.

    Single-worker design: the only real worker is the scheduled reader on
    this VM. The secret lives in the ZENAF_RENDER_WORKER_KEY env var (a Fly
    secret on staging). Unset -> fail closed with 503, never open.

    Scope is honest, not fine-grained: any key holder can claim, complete,
    or fail any pending job. That's acceptable for one trusted worker and
    no multi-tenant renderer fleet.
    """
    import hmac
    import os

    expected = os.environ.get("ZENAF_RENDER_WORKER_KEY", "")
    if not expected:
        raise HTTPException(
            status_code=503,
            detail="render worker not configured (ZENAF_RENDER_WORKER_KEY unset)",
        )
    provided = request.headers.get("X-Worker-Key", "")
    if not hmac.compare_digest(provided, expected):
        raise HTTPException(status_code=403, detail="invalid worker key")
    return True


@router.get("/render-jobs/next")
def render_job_next(
    request: Request,
    worker_id: str = "",
    _worker: bool = Depends(_require_worker_key),
):
    """A registered renderer polls here to claim its next job.

    Returns {"job": {...} | None}. Claiming is atomic — one job per worker.
    """
    worker_id = (worker_id or "").strip() or "anonymous"
    job = _render_store().next_pending(worker_id)
    return {"job": job.to_dict() if job else None}


@router.get("/render-jobs/{job_id}")
def render_job_status(job_id: str, current_user: dict = Depends(get_current_user)):
    """Check a render job's status (for UI polling). Owner only."""
    uid = _uid(current_user)
    job = _render_store().get(job_id, user_id=uid)
    if job is None:
        raise HTTPException(status_code=404, detail="unknown render job")
    d = job.to_dict()
    d["pending_count"] = _render_store().pending_count(user_id=uid)
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
def render_job_complete(
    job_id: str,
    body: RenderCompleteBody,
    request: Request,
    _worker: bool = Depends(_require_worker_key),
):
    """A renderer submits the extracted transcript; the intake pipeline resumes.

    Returns the connected agent (with sort + mined projects) in one call.

    Idempotent: a repeat POST for an already-completed job replays the stored
    result (agent + mined payload) instead of re-running the pipeline — the
    old behavior created a duplicate agent on every retry.
    """
    import json

    from local_ai.agent_intake import project_miner

    rs = _render_store()
    existing = rs.get(job_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="unknown render job")
    owner = existing.user_id or ""

    if existing.status == "completed":
        if not existing.result_agent_id:
            raise HTTPException(
                status_code=409,
                detail="job already completed (legacy row); cannot recover agent",
            )
        agent = _store(owner or None).get(existing.result_agent_id)
        if agent is None:
            raise HTTPException(
                status_code=409,
                detail="job already completed but its agent is gone",
            )
        try:
            mined = json.loads(existing.result_mined or "")
        except (TypeError, ValueError):
            mined = None
        if not isinstance(mined, dict):
            mined = {"engine": "none", "initiatives": [], "projects": [],
                     "standalone_tasks": [], "ideas": []}
        return {"agent": agent.to_dict(), "mined": mined, "replayed": True}

    job = rs.complete(job_id, body.transcript, body.title, user_id=owner or None)
    if job is None:
        raise HTTPException(status_code=404, detail="unknown render job")
    try:
        agent = _pipeline().resume_from_render(
            job_id, name=(body.name or "").strip() or None, store=_store(owner or None), render_store=rs
        )
    except AgentIntakeError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    # Mine projects/tasks from the transcript (best-effort, same as share-text).
    mined: dict = {"engine": "none", "initiatives": [], "projects": [], "standalone_tasks": [], "ideas": []}
    try:
        from dataclasses import asdict

        result = project_miner.mine_projects(body.transcript, user_id=owner or None)
        mined = {
            "engine": result.engine,
            "initiatives": [asdict(i) for i in result.initiatives],
            "projects": [asdict(p) for p in result.projects],
            "standalone_tasks": [asdict(t) for t in result.standalone_tasks],
            "ideas": [asdict(i) for i in result.ideas],
        }
    except Exception:
        pass
    rs.set_result(job_id, agent.id, json.dumps(mined))
    return {"agent": agent.to_dict(), "mined": mined}


@router.post("/render-jobs/{job_id}/fail", status_code=200)
def render_job_fail(
    job_id: str,
    request: Request,
    body: dict | None = None,
    _worker: bool = Depends(_require_worker_key),
):
    """A renderer reports it could not extract the page.

    A completed job can never be failed (409). Re-failing an already-failed
    job is idempotent — returns the job unchanged.
    """
    error = str((body or {}).get("error", "renderer failed"))[:500]
    rs = _render_store()
    existing = rs.get(job_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="unknown render job")
    if existing.status == "completed":
        raise HTTPException(status_code=409, detail="job already completed; cannot fail it")
    if existing.status == "failed":
        return existing.to_dict()
    job = rs.fail(job_id, error, user_id=existing.user_id or None)
    if job is None:
        raise HTTPException(status_code=404, detail="unknown render job")
    return job.to_dict()


@router.get("/pending")
def list_pending_agents(current_user: dict = Depends(get_current_user)):
    """Review queue: agents awaiting accept/correct."""
    return [a.to_dict() for a in _store(_uid(current_user)).list_pending()]


@router.get("")
def list_agents(current_user: dict = Depends(get_current_user)):
    """All connected agents."""
    return [a.to_dict() for a in _store(_uid(current_user)).list_all()]


class ConfirmMinedBody(BaseModel):
    """User-confirmed subset of mined proposals to create as VE entities."""

    initiatives: list[dict] = []
    projects: list[dict] = []
    standalone_tasks: list[dict] = []
    ideas: list[dict] = []
    selected_titles: list[str] | None = None  # None = create all
    user_id: str = ""
    agent_id: str | None = None  # when set, resolve items from the agent's stored mined_payload server-side


@router.post("/mined-projects/confirm", status_code=201)
def confirm_mined_projects(body: ConfirmMinedBody, current_user: dict = Depends(get_current_user)):
    """Create Vision Execution entities from confirmed mined proposals.

    Respects the VE hierarchy (initiatives → projects → tasks, plus ideas).
    Plugs into the existing VE service layer — no parallel structures.

    When agent_id is set, items are resolved from the agent's stored
    mined_payload server-side (robust against client title mismatches or
    stale payloads). Direct arrays remain supported for backward compat.
    Returns 422 if nothing resolves — a silent 201 with zero entities
    created is a bug, not a success.
    """
    from local_ai.agent_intake import project_miner
    from local_ai.vision_execution import graduation as _graduation

    uid = _uid(current_user)  # authoritative: never trust the client-supplied user_id

    initiatives = list(body.initiatives)
    projects = list(body.projects)
    standalone_tasks = list(body.standalone_tasks)
    ideas = list(body.ideas)

    # Server-side resolution: if the client sent empty arrays but named an
    # agent, pull the proposals from the agent's stored mined_payload and
    # match by title. This is the robust path — the server controls both
    # the payload and the claim titles.
    if body.agent_id and not (initiatives or projects or standalone_tasks or ideas):
        store = _store(uid)
        agent = store.get(body.agent_id)
        if agent is None:
            raise HTTPException(status_code=404, detail=f"unknown agent: {body.agent_id}")
        payload = agent.mined_payload or {}
        wanted = set(body.selected_titles) if body.selected_titles is not None else None

        def _pick(items: list[dict]) -> list[dict]:
            out = []
            for d in items or []:
                t = str(d.get("title", "") or "")
                if t and (wanted is None or t in wanted):
                    out.append(d)
            return out

        initiatives = _pick(payload.get("initiatives"))
        projects = _pick(payload.get("projects"))
        standalone_tasks = _pick(payload.get("standalone_tasks"))
        ideas = _pick(payload.get("ideas"))

    if not (initiatives or projects or standalone_tasks or ideas):
        raise HTTPException(
            status_code=422,
            detail="Nothing to create — no proposals matched. Try mining again.",
        )

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
            for i in initiatives
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
            for p in projects
            if p.get("title")
        ],
        standalone_tasks=[_task(t) for t in standalone_tasks if t.get("title")],
        ideas=[
            project_miner.ProposedIdea(
                title=str(i.get("title", "")),
                detail=str(i.get("detail", "")),
                source_quote=str(i.get("source_quote", "")),
                desired_outcome=str(i.get("desired_outcome", "")),
                suggested_level=(str(i.get("suggested_level", "")).strip().lower() or None),
                target_level=(str(i.get("target_level", "")).strip().lower() or None),
                checklist=i.get("checklist") if isinstance(i.get("checklist"), list) else None,
            )
            for i in ideas
            if i.get("title")
        ],
        engine="api",
    )
    selected = set(body.selected_titles) if body.selected_titles is not None else None
    try:
        return project_miner.create_confirmed(result, uid, selected)
    except _graduation.IdeaNotReadyError as exc:
        raise HTTPException(
            status_code=422,
            detail={"message": str(exc), "missing": exc.missing, "idea": exc.idea_title},
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)[:300])
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)[:300])




@router.post("/{agent_id}/confirm")
def confirm_agent(agent_id: str, body: ConfirmBody, current_user: dict = Depends(get_current_user)):
    """Accept the sort, correct it, or archive the agent.

    Corrections ("no, this is a People talent") are logged as
    ideals-guidance training signals for the v2 sorter.

    Alternatives the user never verdict stay "pending" until now: filing
    marks them "unresolved" — an explicit left-open, never a silent
    approval of an interpretation the user didn't confirm.
    """
    try:
        uid = _uid(current_user)
        store = _store(uid)
        agent = store.get(agent_id)
        if agent is None:
            raise AgentIntakeError(f"unknown agent: {agent_id}")
        for c in store.get_claims(agent_id):
            if c.claim_type == "alternative" and c.status == "pending":
                store.update_claim(c.id, "unresolved")
        agent = _pipeline().confirm_agent(
            agent_id,
            accepted=body.accepted,
            corrections=body.corrections or None,
            store=store,
            user_id=uid,
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
def connect_share_text(body: ShareTextBody, current_user: dict = Depends(get_current_user)):
    """Connect an agent from bookmarklet-extracted share-page text.

    The Zenaf bookmarklet runs inside the rendered page in the user's own
    browser, extracts the conversation, and POSTs it here — no copy/paste.
    Runs the standard intake pipeline (redact → sort → review queue) and
    returns the pending agent plus mined project/task proposals.
    """
    from local_ai.agent_intake import project_miner

    try:
        uid = _uid(current_user)
        _require_train_self(uid)
        agent = _pipeline().connect_via_extracted_text(
            url=body.url,
            transcript=body.transcript,
            title=(body.title or "").strip() or None,
            name=(body.name or "").strip() or None,
            store=_store(uid),
        )
    except AgentIntakeError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    # Mine projects/tasks from the same transcript (best-effort).
    mined: dict = {"engine": "none", "initiatives": [], "projects": [], "standalone_tasks": [], "ideas": []}
    try:
        from dataclasses import asdict

        result = project_miner.mine_projects(body.transcript, user_id=owner or None)
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


class ReviewChatBody(BaseModel):
    """One message to the Zenaf review bot."""

    message: str
    history: list[dict] = []
    pending_proposal: dict | None = None
    is_confirmation: bool = False
    quick_file_indices: list[int] | None = None


@router.post("/intake/chat", status_code=200)
def intake_chat(body: IntakeChatBody, current_user: dict = Depends(get_current_user)):
    """Chat with Muse to connect a conversation.

    Paste conversation text (or drop a share link); Muse routes it through
    the intake pipeline and replies conversationally. Anything else gets a
    plain Muse reply as the intake guide.
    """
    from local_ai.agent_intake import intake_chat as ichat

    uid = _uid(current_user)
    _require_train_self(uid)
    return ichat.handle_message(body.message, body.history, user_id=uid)


@router.post("/{agent_id}/review-chat", status_code=200)
def review_chat(agent_id: str, body: ReviewChatBody, current_user: dict = Depends(get_current_user)):
    """Chat with Zenaf about an imported conversation.

    Zenaf has read the full transcript and the flagged training moments.
    It's humble, curious, and helps the user discover what should be trained.
    When the user confirms a placement, a TrainingSignal is created.
    """
    from local_ai.agent_intake import review_chat as rchat

    uid = _uid(current_user)
    store = _store(uid)
    agent = store.get(agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail=f"unknown agent: {agent_id}")
    
    # Backfill LLM moments if the agent was sorted before the feature
    if agent.sort and not getattr(agent.sort, 'moments', None):
        try:
            from local_ai.agent_intake import sorter_llm
            result, _engine = sorter_llm.sort_primary(
                agent.name,
                agent.description,
                agent.instructions,
                agent.examples,
                user_id=uid,
            )
            agent.sort = result
            store.save(agent)
        except Exception:
            pass  # fallback to no-moments mode
    
    result = rchat.handle_message(
        agent, 
        body.message, 
        body.history, 
        user_id=uid,
        pending_proposal=body.pending_proposal,
        is_confirmation=body.is_confirmation,
        quick_file_indices=body.quick_file_indices,
    )
    return result


@router.post("/{agent_id}/mining-chat", status_code=200)
def mining_chat(agent_id: str, body: ReviewChatBody, current_user: dict = Depends(get_current_user)):
    """Chat with Zenaf to pull practical items from a conversation.

    Initiatives, projects, tasks, assets, and people — proposed one by one
    in conversation. When the user confirms, the real entity is created.
    """
    from local_ai.agent_intake import mining_chat as mchat

    uid = _uid(current_user)
    store = _store(uid)
    agent = store.get(agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail=f"unknown agent: {agent_id}")

    result = mchat.handle_message(
        agent,
        body.message,
        body.history,
        user_id=uid,
        pending_proposal=body.pending_proposal,
        is_confirmation=body.is_confirmation,
    )
    return result


class MineBody(BaseModel):
    """Mine a transcript for proposed projects and tasks."""

    transcript: str
    agent_id: str | None = None  # when set, mined claims are stored for review

    @field_validator("transcript")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        v = (v or "").strip()
        if not v:
            raise ValueError("transcript is required")
        return v


@router.post("/mine-projects", status_code=200)
def mine_projects(body: MineBody, current_user: dict = Depends(get_current_user)):
    """Read a transcript like a chief of staff: propose projects and tasks.

    Returns proposed projects (with nested tasks) and standalone tasks, each
    with source quotes. Nothing is created — the user reviews and confirms
    via POST /agents/mined-projects/confirm, which creates real Vision
    Execution entities. Uses the Anthropic engine when configured,
    rule-based fallback otherwise.

    When body.agent_id is set, the mined proposals are also stored as review
    claims so each can be accepted/corrected/explained individually.
    """
    from local_ai.agent_intake import project_miner
    from local_ai.agent_intake import review_claims
    from dataclasses import asdict

    uid = _uid(current_user)
    _require_train_self(uid)
    result = project_miner.mine_projects(body.transcript, user_id=uid)
    mined = {
        "engine": result.engine,
        "initiatives": [asdict(i) for i in result.initiatives],
        "projects": [asdict(p) for p in result.projects],
        "standalone_tasks": [asdict(t) for t in result.standalone_tasks],
        "ideas": [asdict(i) for i in result.ideas],
    }
    if body.agent_id:
        store = _store(uid)
        agent = store.get(body.agent_id)
        if agent is None:
            raise HTTPException(status_code=404, detail=f"unknown agent: {body.agent_id}")
        claims = review_claims.build_mined_claims(result, agent.id)
        store.save_claims(agent.id, claims)
        # Persist the mining stage and payload on the agent: the staged
        # review gate reads mining_state, and the payload lets the client
        # create accepted claims as entities after a reload.
        store.set_mining_state(agent.id, "mined", payload=mined)
    return mined


@router.post("/{agent_id}/skip-mining", status_code=200)
def skip_mining(agent_id: str, current_user: dict = Depends(get_current_user)):
    """The user explicitly skips project mining for this agent.

    Records mining_state="skipped" so the staged review gate can finalize
    the agent without mining. Mining can still be run later — POST
    /agents/mine-projects with agent_id overwrites the skip.
    """
    store = _store(_uid(current_user))
    agent = store.get(agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail=f"unknown agent: {agent_id}")
    store.set_mining_state(agent.id, "skipped")
    agent.mining_state = "skipped"
    return agent.to_dict()


class ClaimNoteBody(BaseModel):
    """User's correction or explanation for a single claim."""

    note: str = ""

    @field_validator("note")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        v = (v or "").strip()
        if not v:
            raise ValueError("note is required")
        return v


def _get_claim(store, agent_id: str, claim_id: str):
    """Fetch an agent and one of its claims, or raise 404."""
    from local_ai.agent_intake import review_claims

    agent = store.get(agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail=f"unknown agent: {agent_id}")
    for c in store.get_claims(agent_id):
        if c.id == claim_id:
            return agent, c
    # Claim not built yet — build strand/kind claims on demand.
    claims = review_claims.build_strand_claims(agent)
    kind_claim = review_claims.build_kind_claim(agent)
    if kind_claim:
        claims.append(kind_claim)
    for c in claims:
        if c.id == claim_id:
            store.save_claims(agent.id, claims)
            return agent, c
    raise HTTPException(status_code=404, detail=f"unknown claim: {claim_id}")


# NOTE: claim review verdicts are written to the canonical TrainingSignal
# store by local_ai.agent_intake.pipeline.log_claim_feedback (kind=
# "claim_feedback"). The old _claim_to_signal lived here; it moved there
# in the signals consolidation.


@router.post("/backfill-moments")
def backfill_moments(current_user: dict = Depends(get_current_user)):
    """TEMPORARY: Re-run LLM sorter to generate moments for existing agents.

    For agents sorted before the LLM moment feature, re-runs the sorter
    to populate SortResult.moments, then clears cached claims so they
    rebuild with the new LLM-based inferences.
    """
    from local_ai.agent_intake import sorter_llm
    from local_ai.agent_intake.store import AgentStore

    store = _store(_uid(current_user))
    agents = store.list_all()
    results = []
    for agent in agents:
        # Skip if already has moments
        if agent.sort and getattr(agent.sort, 'moments', None):
            results.append({"id": agent.id, "name": agent.name, "status": "skipped (has moments)"})
            continue
        try:
            # Re-run LLM sorter
            result, _engine = sorter_llm.sort_primary(
                agent.name,
                agent.description,
                agent.instructions,
                agent.examples,
                user_id=_uid(current_user),
            )
            agent.sort = result
            store.save(agent)
            # Clear cached strand claims so they rebuild with LLM moments.
            # Mined claims are untouched.
            store.delete_claim_types(agent.id, ("strand", "alternative", "kind"))
            results.append({
                "id": agent.id,
                "name": agent.name,
                "status": "ok",
                "moments": len(result.moments),
            })
        except Exception as e:
            results.append({"id": agent.id, "name": agent.name, "status": f"error: {e}"})
    return {"results": results}


@router.get("/{agent_id}/claims")
def list_claims(agent_id: str, current_user: dict = Depends(get_current_user)):
    """Per-inference review cards for an agent.

    Each claim carries verbatim evidence, a plain-language inference, and a
    pending/accepted/corrected/explained status. Strand cards are moment-level
    (one per qualifying transcript moment per strand, capped); kind and
    strand claims are built on demand from the stored transcript. Mined
    claims appear after POST /agents/mine-projects with agent_id.
    """
    from local_ai.agent_intake import review_claims
    from local_ai.agent_intake.store import AgentStore

    store = _store(_uid(current_user))
    agent = store.get(agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail=f"unknown agent: {agent_id}")
    claims = store.get_claims(agent_id)
    if not claims:
        # Fallback: check unscoped store (render jobs may have saved under
        # a different user scope). If found there, use those claims.
        try:
            unscoped = AgentStore(user_id=None)
            unscoped_claims = unscoped.get_claims(agent_id)
            if unscoped_claims:
                claims = unscoped_claims
                # Migrate to user's scope for future requests
                store.save_claims(agent.id, claims)
        except Exception:
            pass
    # Rebuild if cached claims use the old lazy inference wording.
    # The new wording explains the behavior, not just keywords.
    needs_rebuild = False
    if claims:
        for c in claims:
            inf = getattr(c, 'inference', '') or ''
            if inf.startswith('This passage routes to') or inf.startswith('This passage was routed to'):
                needs_rebuild = True
                break
    # Backfill LLM moments for agents sorted before the feature.
    # If the agent has no moments, re-run the sorter to generate them.
    if agent.sort and not getattr(agent.sort, 'moments', None):
        try:
            from local_ai.agent_intake import sorter_llm
            result, _engine = sorter_llm.sort_primary(
                agent.name,
                agent.description,
                agent.instructions,
                agent.examples,
                user_id=_uid(current_user),
            )
            agent.sort = result
            store.save(agent)
            # Clear old claims so they rebuild with LLM moments
            store.delete_claim_types(agent.id, ("strand", "alternative", "kind"))
            needs_rebuild = True
        except Exception:
            # If LLM fails, fall back to rule-based (existing behavior)
            pass
    if not claims or needs_rebuild:
        claims = review_claims.build_strand_claims(agent)
        kind_claim = review_claims.build_kind_claim(agent)
        if kind_claim:
            claims.append(kind_claim)
        if claims:
            store.save_claims(agent.id, claims)
    return [c.to_dict() for c in claims]


@router.post("/{agent_id}/claims/{claim_id}/accept", status_code=200)
def accept_claim(agent_id: str, claim_id: str, current_user: dict = Depends(get_current_user)):
    """Accept one inference — confirms it as training signal."""
    from local_ai.agent_intake import pipeline as _pipeline_mod

    uid = _uid(current_user)
    store = _store(uid)
    agent, claim = _get_claim(store, agent_id, claim_id)
    store.update_claim(claim.id, "accepted")
    try:
        _pipeline_mod.log_claim_feedback(
            agent.id, claim.id, claim.claim_type, "accepted",
            evidence=claim.evidence, inference=claim.inference,
            claim_title=claim.title, user_id=uid,
        )
    except Exception:
        logger.exception("claim feedback signal write failed")
    claim.status = "accepted"
    return claim.to_dict()


@router.post("/{agent_id}/claims/{claim_id}/correct", status_code=200)
def correct_claim(agent_id: str, claim_id: str, body: ClaimNoteBody, current_user: dict = Depends(get_current_user)):
    """Correct one inference — the correction is ideals-guidance training signal."""
    from local_ai.agent_intake import pipeline as _pipeline_mod

    uid = _uid(current_user)
    store = _store(uid)
    agent, claim = _get_claim(store, agent_id, claim_id)
    store.update_claim(claim.id, "corrected", body.note)
    try:
        _pipeline_mod.log_claim_feedback(
            agent.id, claim.id, claim.claim_type, "corrected", note=body.note,
            evidence=claim.evidence, inference=claim.inference,
            claim_title=claim.title, user_id=uid,
        )
    except Exception:
        logger.exception("claim feedback signal write failed")
    claim.status = "corrected"
    claim.user_note = body.note
    return claim.to_dict()


@router.post("/{agent_id}/claims/{claim_id}/explain", status_code=200)
def explain_claim(agent_id: str, claim_id: str, body: ClaimNoteBody, current_user: dict = Depends(get_current_user)):
    """Explain *why* — the user's reasoning is stored as ideals-guidance signal."""
    from local_ai.agent_intake import pipeline as _pipeline_mod

    uid = _uid(current_user)
    store = _store(uid)
    agent, claim = _get_claim(store, agent_id, claim_id)
    store.update_claim(claim.id, "explained", body.note)
    try:
        _pipeline_mod.log_claim_feedback(
            agent.id, claim.id, claim.claim_type, "explained", note=body.note,
            evidence=claim.evidence, inference=claim.inference,
            claim_title=claim.title, user_id=uid,
        )
    except Exception:
        logger.exception("claim feedback signal write failed")
    claim.status = "explained"
    claim.user_note = body.note
    return claim.to_dict()


@router.post("/{agent_id}/claims/{claim_id}/reject", status_code=200)
def reject_claim(agent_id: str, claim_id: str, current_user: dict = Depends(get_current_user)):
    """Reject one inference — the system got it wrong.

    Logged as negative training signal: a rejected inference teaches the
    miner what not to claim.
    """
    from local_ai.agent_intake import pipeline as _pipeline_mod

    uid = _uid(current_user)
    store = _store(uid)
    agent, claim = _get_claim(store, agent_id, claim_id)
    store.update_claim(claim.id, "rejected")
    try:
        _pipeline_mod.log_claim_feedback(
            agent.id, claim.id, claim.claim_type, "rejected",
            evidence=claim.evidence, inference=claim.inference,
            claim_title=claim.title, user_id=uid,
        )
    except Exception:
        logger.exception("claim feedback signal write failed")
    claim.status = "rejected"
    return claim.to_dict()


@router.post("/{agent_id}/claims/{claim_id}/unresolve", status_code=200)
def unresolve_claim(agent_id: str, claim_id: str, current_user: dict = Depends(get_current_user)):
    """Leave one inference unresolved — an explicit "not deciding", first-class.

    Not everything needs a verdict. Unresolved is recorded (not a silent
    skip) but carries no positive or negative training weight.
    """
    from local_ai.agent_intake import pipeline as _pipeline_mod

    uid = _uid(current_user)
    store = _store(uid)
    agent, claim = _get_claim(store, agent_id, claim_id)
    store.update_claim(claim.id, "unresolved")
    try:
        _pipeline_mod.log_claim_feedback(
            agent.id, claim.id, claim.claim_type, "unresolved",
            evidence=claim.evidence, inference=claim.inference,
            claim_title=claim.title, user_id=uid,
        )
    except Exception:
        logger.exception("claim feedback signal write failed")
    claim.status = "unresolved"
    return claim.to_dict()


# Claim types rebuilt by insight regeneration. Mined project claims
# (initiative/project/task/idea) belong to the project-mining step and are
# left untouched.
_REGENERATED_CLAIM_TYPES = (
    "strand", "kind",
    "value_inference", "decision_pattern", "stance", "preference",
    "alternative", "recurrence",
)


@router.post("/{agent_id}/claims/regenerate", status_code=200)
def regenerate_claims(agent_id: str, current_user: dict = Depends(get_current_user)):
    """Re-read the conversation for atomic insights.

    Rebuilds strand/kind/insight claims from the stored transcript without
    re-ingesting. Existing resolutions are preserved by claim ID; mined
    project claims are untouched. Powers the "Re-read for insights" button.
    """
    from local_ai.agent_intake import insight_miner, review_claims

    uid = _uid(current_user)
    _require_train_self(uid)
    store = _store(uid)
    agent = store.get(agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail=f"unknown agent: {agent_id}")

    # Preserve the user's existing verdicts by stable claim ID.
    existing = {c.id: c for c in store.get_claims(agent_id)}

    claims = review_claims.build_strand_claims(agent)
    kind_claim = review_claims.build_kind_claim(agent)
    if kind_claim:
        claims.append(kind_claim)
    insights, engine = insight_miner.mine_insights(agent.examples, user_id=uid)
    claims.extend(review_claims.build_insight_claims(insights, agent.id))

    # Recurrence pass: what the person keeps coming back to across turns
    # (pattern-scope claims, grounded in quotes from distinct turns).
    from local_ai.agent_intake import recurrence

    patterns, _recurrence_engine = recurrence.mine_recurrences(agent.examples, user_id=uid)
    claims.extend(review_claims.build_recurrence_claims(patterns, agent.id))

    for c in claims:
        old = existing.get(c.id)
        if old is not None and old.status != "pending":
            c.status = old.status
            c.user_note = old.user_note

    # Remove stale regenerated-type rows (a re-read may yield fewer
    # insights), then save the fresh set. Mined claims survive.
    store.delete_claim_types(agent_id, _REGENERATED_CLAIM_TYPES)
    if claims:
        store.save_claims(agent.id, claims)
    return {"claims": [c.to_dict() for c in claims], "engine": engine}


@router.get("/bookmarklet/install", include_in_schema=False)
def bookmarklet_install():
    """Serve the bookmarklet install page (HTML)."""
    from fastapi.responses import HTMLResponse
    from pathlib import Path

    page = Path(__file__).resolve().parent.parent.parent / "local_ai" / "agent_intake" / "install_page.html"
    return HTMLResponse(content=page.read_text(encoding="utf-8"))
