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
from .schema import ContributionClaim, ImportSession
from .store import DATA_DIR, PresenceStore

# One-way dependency: presence_ingest -> identity. identity only imports
# presence_ingest lazily inside functions, so this module-level import is safe.
from local_ai.identity import LicenseRequired
from local_ai.identity import service as identity_service

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

    Requires an active identity license: imports are re-anchored under the
    owner's license at capture, and the license_id is stamped into the
    session's and every event's provenance. Raises LicenseRequired if none
    exists, PresenceIngestError if the file is not a recognized export.
    """
    lic = identity_service.get_license()
    if lic is None or lic.status != "active":
        raise LicenseRequired()
    license_id = lic.license_id

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
        provenance={"license_id": license_id, "reanchored": True},
    )
    store.create_session(session)

    events = list(adapter.iter_events(stored_path))
    for e in events:
        e.provenance["license_id"] = license_id
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

    Requires the train:self consent scope (default-deny). Returns the number
    of candidates. Raises PresenceIngestError if the session is unknown;
    ScopeDenied if the scope is not granted; DistillError (from distill) if
    the LLM is unreachable.
    """
    from local_ai.identity.scopes import require_scope

    require_scope("train:self")

    store = store or PresenceStore()
    session = store.get_session(session_id)
    if session is None:
        raise PresenceIngestError(f"Unknown import session: {session_id}")
    events = store.list_events(session_id)
    claims = store.list_claims(session_id)
    candidates = distill_events(
        events,
        complete_fn=complete_fn,
        zone_hint=zone_hint,
        actor=actor,
        session_id=session_id,
        claims=claims,
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
    contexts: dict[str, dict] | None = None,
) -> dict[str, int]:
    """Apply the user's approve/reject decisions to pending candidates.

    `contexts` optionally carries per-signal decision-envelope corrections
    (signal_id -> envelope dict). Corrections are applied to pending signals
    BEFORE the approve/reject decision, so approval keeps meaning "this
    signal and its context are correct". Approved/rejected rows are never
    touched by corrections.

    Returns {"approved": n, "rejected": m, "contexts_updated": k}. Only
    pending signals are affected; already-reviewed signals are left
    untouched.
    """
    store = store or PresenceStore()
    session = store.get_session(session_id)
    if session is None:
        raise PresenceIngestError(f"Unknown import session: {session_id}")
    contexts_updated = 0
    for sid, envelope in (contexts or {}).items():
        if isinstance(envelope, dict) and store.update_signal_context(sid, envelope):
            contexts_updated += 1
    approved_ids = [sid for sid, ok in approvals.items() if ok]
    rejected_ids = [sid for sid, ok in approvals.items() if not ok]
    approved = store.review_signals(approved_ids, approve=True)
    rejected = store.review_signals(rejected_ids, approve=False)
    counts = dict(session.counts)
    counts["approved"] = store.count_signals(session_id, status="approved")
    counts["rejected"] = store.count_signals(session_id, status="rejected")
    store.update_session(session_id, status="reviewed", counts=counts)
    return {"approved": approved, "rejected": rejected, "contexts_updated": contexts_updated}


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


# -- contribution claims -----------------------------------------------


def define_contribution(
    session_id: str,
    *,
    role: str,
    work_title: str = "",
    parts: str = "",
    extent: dict | None = None,
    collaborators: list[str] | None = None,
    note: str = "",
    event_ids: list[str] | None = None,
    store: PresenceStore | None = None,
) -> ContributionClaim:
    """Record the user's part in a collaborative work ("I played guitar").

    Claims are opt-in per item and scope distillation: signals distilled
    from covered events learn from the user's contribution only, and the
    claim keeps the identity license honest (it covers contributions, never
    whole works). Requires an active identity license, like imports.

    Raises PresenceIngestError for an unknown session, empty role, or
    event_ids outside the session; LicenseRequired when no license exists.
    """
    role = (role or "").strip()
    if not role:
        raise PresenceIngestError("A contribution claim requires a role.")
    store = store or PresenceStore()
    session = store.get_session(session_id)
    if session is None:
        raise PresenceIngestError(f"Unknown import session: {session_id}")

    lic = identity_service.get_license()
    if lic is None or lic.status != "active":
        raise LicenseRequired()

    event_ids = list(event_ids or [])
    if event_ids:
        known = {e.event_id for e in store.list_events(session_id)}
        unknown = [eid for eid in event_ids if eid not in known]
        if unknown:
            raise PresenceIngestError(
                f"event_ids not in session {session_id}: {unknown[:5]}"
            )

    claim = ContributionClaim(
        claim_id=f"claim-{uuid4().hex[:12]}",
        session_id=session_id,
        event_ids=event_ids,
        work_title=work_title.strip(),
        role=role,
        parts=parts.strip(),
        extent=dict(extent or {}),
        collaborators=[c.strip() for c in (collaborators or []) if c.strip()],
        note=note.strip(),
        attestations=[],
        license_id=lic.license_id,
        created_at=datetime.now(timezone.utc),
    )
    return store.save_claim(claim)


def remove_contribution(
    claim_id: str,
    *,
    store: PresenceStore | None = None,
) -> bool:
    """Delete a contribution claim. Claims are user assertions — freely
    removable, unlike append-only signals. Returns True if deleted."""
    store = store or PresenceStore()
    if store.get_claim(claim_id) is None:
        raise PresenceIngestError(f"Unknown contribution claim: {claim_id}")
    return store.delete_claim(claim_id)
