"""Pydantic schemas for the presence-ingestion pipeline.

Privacy contract: PresenceEvent.text is ALWAYS already redacted at capture
(see redact.py). Raw user content never enters the event store.

TrainingSignal follows the unified §2 envelope from
docs/02_ACTIVE_DESIGN/TRAINING_SIGNAL_DESIGN.md, with two additions required
by the ingestion pipeline:
  - status: pending | approved | rejected (the review gate — nothing enters
    the profile without the user's explicit approval)
  - session_id: which import produced this signal
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field

SignalLayer = Literal["decision", "behavior", "guidance"]
SignalValence = Literal["endorsed", "rejected", "corrected", "observed"]
SignalStatus = Literal["pending", "approved", "rejected"]
SessionStatus = Literal["uploaded", "parsed", "distilled", "reviewed", "deleted"]


class PresenceEvent(BaseModel):
    """One redacted unit of a user's digital presence (a message, a post)."""

    event_id: str
    source: str  # e.g. "chatgpt", "claude", "x"
    ts: datetime | None = None
    actor: str  # "user" | "assistant" | ...
    kind: str  # "message" | "post" | ...
    text: str  # ALREADY redacted at capture — never raw
    context: dict[str, Any] = Field(default_factory=dict)
    provenance: dict[str, Any] = Field(default_factory=dict)


class TrainingSignal(BaseModel):
    """Unified training-signal envelope (§2 of the training-signal design doc)."""

    signal_id: str
    ts_ms: int
    layer: SignalLayer
    zone: str
    actor: str  # owner user id; renters' signals stay with renters

    summary: str  # human-readable, redacted
    context_ref: dict[str, Any] = Field(default_factory=dict)
    payload_redacted: str = ""  # layer-specific detail, PII-stripped

    valence: SignalValence
    correction_diff: str | None = None

    provenance: dict[str, Any] = Field(default_factory=dict)
    supersedes: str | None = None

    # Presence-ingest additions:
    status: SignalStatus = "pending"
    session_id: str = ""


class ImportSession(BaseModel):
    """Tracks one uploaded export through the pipeline stages."""

    session_id: str
    source: str
    file_name: str
    status: SessionStatus = "uploaded"
    counts: dict[str, int] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    # Identity license this import was re-anchored under (set at import).
    provenance: dict[str, Any] = Field(default_factory=dict)


class ContributionClaim(BaseModel):
    """The user's asserted part in a collaborative work.

    "I played guitar in this song." Imported material is often collaborative;
    a claim scopes distillation to the user's contribution (the rest of the
    work becomes context, not training data) and keeps the identity license
    honest — it covers the user's contributions, never whole works.

    Claims are user assertions, not audit records: freely editable and
    deletable by the user. `attestations` is reserved for future multi-party
    confirmation (collaborators on Zenaf confirming each other's parts) and
    is always empty for now.
    """

    claim_id: str
    session_id: str
    event_ids: list[str] = Field(
        default_factory=list,
        description="Specific events this claim covers; empty = session-level.",
    )
    work_title: str = ""  # e.g. "Midnight Run (song)"
    role: str  # required, e.g. "guitar"
    parts: str = ""  # free text: "lead guitar, verses; not the solo"
    extent: dict[str, Any] = Field(
        default_factory=dict,
        description='Optional structured scope, e.g. {"sections": [...]}.',
    )
    collaborators: list[str] = Field(default_factory=list)
    note: str = ""
    attestations: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Reserved for future multi-party confirmation.",
    )
    license_id: str = ""
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
