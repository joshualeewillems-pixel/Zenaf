"""Orchestration for presence ingestion: upload -> parse -> distill -> review.

Pipeline stages (mirrored in ImportSession.status):
  uploaded -> parsed -> distilled -> reviewed
  deleted  (terminal: raw upload + events removed)

Privacy notes:
- The raw export is stored under data/presence_ingest/uploads/<session_id>/
  and can be deleted at any time via delete_session().
- delete_session() removes the raw upload AND the (redacted) events, but
  approved signals REMAIN: once the user has approved them, they are the
  user's training data, part of the doppelganger profile, and deleting the
  source export must not silently erase training history.
"""
from __future__ import annotations

import shutil
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from .adapters.registry import detect_source
from .distill import CompleteFn, DistillError, distill_events
from .schema import ImportSession
from .store import DATA_DIR, PresenceStore

UPLOAD_ROOT = DATA_DIR / "uploads"
MAX_UPLOAD_BYTES = 200 * 1024 * 1024  # 200 MB cap, enforced by the API layer too


class PresenceIngestError(RuntimeError):
    """A pipeline step failed in a way the caller should report to the user."""


def _safe_filename(name: str) -> str:
    keep = "".join(c if (c.isalnum() or c in "._-") else "_" for c in name)
    return (keep.strip("._") or "upload")[:120]


def start_import(
    file_path: Path,
    original_name: str,
    *,
    store: PresenceStore | None = None,
    upload_root: Path | None = None,
) -> ImportSession:
    """Detect source, parse (redacting at capture), and persist the session.

    Raises PresenceIngestError if the file is not a recognized export.
    """
    path = Path(file_path)
    if not path.is_file():
        raise PresenceIngestError(f"Upload not found: {path}")
    if path.stat().st_size > MAX_UPLOAD_BYTES:
        raise PresenceIngestError(
            f"Upload exceeds the {MAX_UPLOAD_BYTES // (1024 * 1024)} MB cap."
        )
    adapter = detect_source(path)
    if adapter is None:
        raise PresenceIngestError(
            "Unrecognized export format. Supported: ChatGPT conversations.json, "
            "Claude conversations.json, X tweets.js."
        )

    store = store or PresenceStore()
    upload_root = upload_root or UPLOAD_ROOT
    session_id = f"imp-{uuid4().hex[:12]}"
    session_dir = upload_root / session_id
    session_dir.mkdir(parents=True, exist_ok=True)
    stored_name = _safe_filename(original_name)
    stored_path = session_dir / stored_name
    shutil.copyfile(path, stored_path)

    session = ImportSession(
        session_id=session_id,
        source=adapter.source_id,
        file_name=original_name,
        status="uploaded",
        counts={},
        created_at=datetime.now(timezone.utc),
    )
    store.create_session(session)

    events = list(adapter.iter_events(stored_path))
    store.save_events(session_id, events)
    counts = {"events": len(events), "skipped": adapter.last_skipped}
    store.update_session(session_id, status="parsed", counts=counts)
    session.status = "parsed"
    session.counts = counts
    return session


def run_distill(
    session_id: str,
    *,
    complete_fn: CompleteFn | None = None,
    zone_hint: str = "general",
    actor: str = "user",
    store: PresenceStore | None = None,
) -> int:
    """Distill a parsed session's events into pending candidate signals.

    Returns the number of candidates. Raises PresenceIngestError if the
    session is unknown; DistillError (from distill) if the LLM is unreachable.
    """
    store = store or PresenceStore()
    session = store.get_session(session_id)
    if session is None:
        raise PresenceIngestError(f"Unknown import session: {session_id}")
    events = store.list_events(session_id)
    candidates = distill_events(
        events,
        complete_fn=complete_fn,
        zone_hint=zone_hint,
        actor=actor,
        session_id=session_id,
    )
    store.save_candidate_signals(candidates)
    counts = dict(session.counts)
    counts["candidates"] = store.count_signals(session_id, status="pending")
    store.update_session(session_id, status="distilled", counts=counts)
    return len(candidates)


def review(
    session_id: str,
    approvals: dict[str, bool],
    *,
    store: PresenceStore | None = None,
) -> dict[str, int]:
    """Apply the user's approve/reject decisions to pending candidates.

    Returns {"approved": n, "rejected": m}. Only pending signals are affected;
    already-reviewed signals are left untouched.
    """
    store = store or PresenceStore()
    session = store.get_session(session_id)
    if session is None:
        raise PresenceIngestError(f"Unknown import session: {session_id}")
    approved_ids = [sid for sid, ok in approvals.items() if ok]
    rejected_ids = [sid for sid, ok in approvals.items() if not ok]
    approved = store.review_signals(approved_ids, approve=True)
    rejected = store.review_signals(rejected_ids, approve=False)
    counts = dict(session.counts)
    counts["approved"] = store.count_signals(session_id, status="approved")
    counts["rejected"] = store.count_signals(session_id, status="rejected")
    store.update_session(session_id, status="reviewed", counts=counts)
    return {"approved": approved, "rejected": rejected}


def delete_session(
    session_id: str,
    *,
    store: PresenceStore | None = None,
    upload_root: Path | None = None,
) -> None:
    """Delete the raw upload and the session's (redacted) events.

    Approved signals are deliberately KEPT: they are the user's training data
    now, and removing the source export must not rewrite training history.
    (Signals remain append-only; see the training-signal design doc §2.)
    """
    store = store or PresenceStore()
    upload_root = upload_root or UPLOAD_ROOT
    session = store.get_session(session_id)
    if session is None:
        raise PresenceIngestError(f"Unknown import session: {session_id}")
    session_dir = upload_root / session_id
    if session_dir.is_dir():
        shutil.rmtree(session_dir, ignore_errors=True)
    store.delete_events(session_id)
    store.update_session(session_id, status="deleted")
