"""Connect pipeline for Agent Intake & Sorting.

connect_agent(): redact at capture -> sort -> store as pending_review.
confirm_agent(): the review gate — accept, correct (corrections become
ideals-guidance training signals for the v2 sorter), or archive.

Nothing trains until the user reviews and approves it.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from local_ai.presence_ingest.redact import redact_text
from local_ai.strands import strand_keys

from .schema import KINDS, ConnectedAgent, SortResult
from .share_link import SharedConversation, detect_source, fetch_shared_conversation
from .sorter_llm import sort_primary
from .store import AgentStore

DEFAULT_CORRECTIONS_LOG = Path.home() / ".zenaf" / "agent_intake_corrections.jsonl"


def _store_user_id(store) -> str | None:
    return getattr(store, "user_id", None)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class AgentIntakeError(Exception):
    """Unknown agent id, invalid correction, etc."""


def connect_agent(
    name: str,
    platform: str,
    description: str,
    instructions: str | None = None,
    examples: list[str] | None = None,
    store: AgentStore | None = None,
) -> ConnectedAgent:
    """Connect an external agent: redact at capture, sort, queue for review."""
    name = (name or "").strip()
    if not name:
        raise AgentIntakeError("name is required")
    description = (description or "").strip()
    if not description:
        raise AgentIntakeError("description is required")

    # Redact at capture — only redacted text is stored or sorted.
    redacted_name = redact_text(name)
    redacted_description = redact_text(description)
    redacted_instructions = redact_text(instructions) if instructions else None
    redacted_examples = [redact_text(e) for e in (examples or []) if e]

    result, _engine = sort_primary(
        redacted_name,
        redacted_description,
        redacted_instructions,
        redacted_examples,
        user_id=_store_user_id(store),
    )

    agent = ConnectedAgent(
        id=uuid.uuid4().hex,
        name=redacted_name,
        source_platform=(platform or "manual").strip().lower() or "manual",
        description=redacted_description,
        instructions=redacted_instructions,
        examples=redacted_examples,
        sort=result,
        status="pending_review",
        created_at=_now_iso(),
    )
    (store or AgentStore()).save(agent)
    return agent


def connect_via_extracted_text(
    url: str,
    transcript: str,
    title: str | None = None,
    name: str | None = None,
    store: AgentStore | None = None,
) -> ConnectedAgent:
    """Connect an agent from bookmarklet-extracted share-page text.

    The bookmarklet runs inside the rendered page (user's own browser),
    extracts the conversation, and POSTs it here. Same pipeline as
    connect_via_share_link, but the JS-rendering step happened client-side.
    """
    url = (url or "").strip()
    transcript = (transcript or "").strip()
    if not transcript:
        raise AgentIntakeError("transcript text is required")
    src = detect_source(url)
    source = src.key if src else "share"
    description = (
        f"Shared {source} conversation"
        + (f": {title}" if title else "")
        + f" ({len(transcript)} chars extracted via bookmarklet)."
    )
    # Split transcript into per-message examples (best-effort on speaker labels).
    examples = _split_transcript(transcript)
    return connect_agent(
        name=name or title or f"{source} shared chat",
        platform=f"{source}_share",
        description=description,
        examples=examples,
        store=store,
    )


def _split_transcript(transcript: str) -> list[str]:
    """Best-effort split of bookmarklet text into per-message examples."""
    import re

    parts = re.split(r"\n(?=(?:USER|ASSISTANT|HUMAN|AI)\s*:)", transcript, flags=re.I)
    chunks = [p.strip() for p in parts if p.strip()]
    # Cap: keep it to ~20 messages of reasonable length.
    return [c[:2000] for c in chunks[:20]] if len(chunks) > 1 else [transcript[:8000]]


def connect_via_share_link(
    url: str,
    name: str | None = None,
    store: AgentStore | None = None,
    render_store: "RenderJobStore | None" = None,
) -> tuple[ConnectedAgent | None, "RenderJob | None"]:
    """Connect an agent from a shared conversation URL.

    Accepts a ChatGPT/Claude (/etc.) share link, fetches and parses it, then
    runs the standard connect pipeline with the transcript as examples.
    Raises AgentIntakeError for unsupported URLs.

    When the page needs JavaScript rendering, this no longer errors out —
    it creates a render job for a registered browser and returns
    (None, job). The caller resumes via `resume_from_render` when the job
    completes.
    """
    from .render_jobs import RenderJob, RenderJobStore

    url = (url or "").strip()
    src = detect_source(url)
    if src is None:
        raise AgentIntakeError(f"Unsupported share URL: {url[:80]}")
    conv = fetch_shared_conversation(url)
    if conv.needs_browser:
        rs = render_store or RenderJobStore()
        job = rs.create(url, user_id=_store_user_id(store))
        return None, job
    examples = conv.as_examples()
    description = (
        f"Shared {conv.source} conversation"
        + (f": {conv.title}" if conv.title else "")
        + f" ({len(conv.messages)} messages)."
    )
    agent = connect_agent(
        name=name or conv.title or f"{conv.source} shared chat",
        platform=f"{conv.source}_share",
        description=description,
        examples=examples,
        store=store,
    )
    return agent, None


def resume_from_render(
    job_id: str,
    name: str | None = None,
    store: AgentStore | None = None,
    render_store: "RenderJobStore | None" = None,
) -> ConnectedAgent:
    """Resume the intake pipeline after a render job completes.

    Takes the extracted transcript from the completed job and runs the
    standard pipeline via connect_via_extracted_text.
    """
    from .render_jobs import RenderJobStore

    rs = render_store or RenderJobStore()
    job = rs.get(job_id)
    if job is None:
        raise AgentIntakeError(f"unknown render job: {job_id}")
    if job.status != "completed" or not job.transcript:
        raise AgentIntakeError(f"render job {job_id} is {job.status}, not completed")
    return connect_via_extracted_text(
        url=job.url,
        transcript=job.transcript,
        title=job.title,
        name=name,
        store=store,
    )


def _validate_corrections(corrections: dict[str, Any]) -> dict[str, Any]:
    """Keep only known correction fields; validate their values."""
    cleaned: dict[str, Any] = {}
    if "primary_strand" in corrections:
        strand = str(corrections["primary_strand"]).strip().lower()
        if strand not in strand_keys():
            raise AgentIntakeError(f"unknown strand: {corrections['primary_strand']!r}")
        cleaned["primary_strand"] = strand
    if "kind" in corrections:
        kind = str(corrections["kind"]).strip().lower()
        if kind not in KINDS:
            raise AgentIntakeError(f"unknown kind: {corrections['kind']!r}")
        cleaned["kind"] = kind
    return cleaned


def _append_correction_log(
    agent_id: str,
    original: dict[str, Any],
    corrections: dict[str, Any],
    log_path: Path | None,
) -> None:
    """Append the correction as an ideals-guidance signal (JSONL)."""
    path = Path(log_path) if log_path else DEFAULT_CORRECTIONS_LOG
    path.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "agent_id": agent_id,
        "ts": _now_iso(),
        "original": original,
        "correction": corrections,
    }
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


def confirm_agent(
    agent_id: str,
    accepted: bool,
    corrections: dict[str, Any] | None = None,
    store: AgentStore | None = None,
    corrections_log: Path | str | None = None,
) -> ConnectedAgent:
    """Review-gate decision for a connected agent.

    - accepted=True, no corrections: status -> active.
    - corrections given: apply corrected primary_strand/kind, status ->
      active, and log the correction as an ideals-guidance training signal.
    - accepted=False, no corrections: status -> archived (kept as audit).
    """
    store = store or AgentStore()
    agent = store.get(agent_id)
    if agent is None:
        raise AgentIntakeError(f"unknown agent: {agent_id}")

    cleaned = _validate_corrections(corrections or {})

    if cleaned:
        # Re-sort result with the user's corrected placement. Claims stay as
        # the sorter made them — the correction is recorded separately.
        original = agent.sort
        original_primary = original.primary_strand if original else None
        original_kind = original.kind if original else None
        agent.sort = SortResult(
            primary_strand=cleaned.get(
                "primary_strand",
                original.primary_strand if original else "",
            ),
            claims=original.claims if original else [],
            kind=cleaned.get("kind", original.kind if original else "undecided"),  # type: ignore[arg-type]
            kind_reasoning=(
                f"user corrected to '{cleaned['kind']}'"
                if "kind" in cleaned
                else (original.kind_reasoning if original else "")
            ),
            linked_projects=original.linked_projects if original else [],
            confidence=original.confidence if original else 0.0,
            needs_probing=False,
        )
        _append_correction_log(
            agent.id,
            {"primary_strand": original_primary, "kind": original_kind},
            cleaned,
            Path(corrections_log) if corrections_log else None,
        )
        agent.status = "active"
    elif accepted:
        agent.status = "active"
    else:
        agent.status = "archived"

    store.save(agent)
    return agent
