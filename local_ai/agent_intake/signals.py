"""Canonical-signal writers for agent-intake review outcomes.

Before the signals consolidation, review corrections were appended to a
JSONL sidecar (~/.zenaf/agent_intake_corrections.jsonl), bypassing the
canonical TrainingSignal store — and per-claim verdicts were written to
*both* the sidecar and the store. Everything here writes TrainingSignals
to the canonical store; the sidecar is dead (see
local_ai/presence_ingest/migrate.py for the one-time import).
"""
from __future__ import annotations

import json
import time
from typing import Any

from local_ai.presence_ingest.schema import TrainingSignal
from local_ai.presence_ingest.store import PresenceStore

#: Valence/layer per claim-feedback action. "unresolved" is recorded but
#: carries no positive or negative training weight (valence "observed").
_CLAIM_ACTION_MAP: dict[str, tuple[str, str]] = {
    "accepted": ("endorsed", "behavior"),
    "rejected": ("rejected", "behavior"),
    "corrected": ("corrected", "guidance"),
    "explained": ("corrected", "guidance"),
    "unresolved": ("observed", "guidance"),
}


def _strand_from_claim(claim_id: str, claim_type: str, claim_title: str) -> str:
    """Best-effort strand key for a strand claim, else ''."""
    if claim_type == "strand":
        parts = claim_id.split(":")
        if len(parts) >= 3 and parts[1] == "strand":
            return parts[2]
        if claim_title:
            from local_ai.agent_intake.review_claims import _STRAND_NAME

            title_lower = claim_title.lower().replace(" strand", "")
            for key, name in _STRAND_NAME.items():
                if name.lower() == title_lower:
                    return key
    return ""


def placement_correction_signal(
    *,
    agent_id: str,
    user_id: str,
    original: dict[str, Any],
    correction: dict[str, Any],
    ts_ms: int | None = None,
) -> TrainingSignal:
    """Build the canonical signal for a user-corrected sort placement.

    Preserves everything the JSONL sidecar captured: the agent, the
    original placement, and the corrected fields.
    """
    now_ms = ts_ms if ts_ms is not None else int(time.time() * 1000)
    parts = []
    for field in ("primary_strand", "kind"):
        old, new = original.get(field), correction.get(field)
        if field in correction and old != new:
            parts.append(f"{field} {old!r} -> {new!r}")
    summary = "Corrected sort placement" + (
        f": {'; '.join(parts)}" if parts else ""
    )
    return TrainingSignal(
        signal_id=f"intake:{agent_id}:placement:{now_ms}",
        ts_ms=now_ms,
        layer="guidance",
        zone=str(correction.get("primary_strand") or "self"),
        actor=user_id,
        summary=summary,
        context_ref={},
        payload_redacted="",
        valence="corrected",
        correction_diff=json.dumps(
            {"original": original, "correction": correction}
        ),
        kind="placement_correction",
        provenance={"source": "agent_intake", "agent_id": agent_id},
        supersedes=None,
        # The user's own correction is explicit approval.
        status="approved",
        session_id="",
    )


def claim_feedback_signal(
    *,
    agent_id: str,
    claim_id: str,
    claim_type: str,
    claim_title: str = "",
    action: str,
    user_id: str,
    evidence: str = "",
    inference: str = "",
    note: str = "",
) -> TrainingSignal:
    """Build the canonical signal for one reviewed intake claim.

    Supersedes the old _claim_to_signal in api/routes/agent_routes.py;
    claim_type is now preserved in provenance (it wasn't before).
    """
    valence, layer = _CLAIM_ACTION_MAP.get(action, ("observed", "guidance"))
    strand = _strand_from_claim(claim_id, claim_type, claim_title)
    return TrainingSignal(
        signal_id=f"intake:{claim_id}:{action}",
        ts_ms=int(time.time() * 1000),
        layer=layer,  # type: ignore[typeddict-item]
        zone=strand or "self",
        actor=user_id,
        summary=inference or claim_title,
        context_ref={},
        payload_redacted=evidence or "",
        valence=valence,  # type: ignore[typeddict-item]
        correction_diff=note if note else None,
        kind="claim_feedback",
        provenance={
            "source": "agent_intake",
            "agent_id": agent_id,
            "claim_id": claim_id,
            "claim_type": claim_type,
            "action": action,
        },
        supersedes=None,
        status="approved",
        session_id="",
    )


def save_intake_signal(
    signal: TrainingSignal, store: PresenceStore | None = None
) -> TrainingSignal:
    """Persist one intake signal to the canonical store."""
    (store or PresenceStore()).save_candidate_signals([signal])
    return signal
