"""Build-room draft artifact, R1.

Clearly marked EXPERIMENTAL. This is NOT a first-class review item
(R3 wires that): it carries no verdict affordance and no execution
affordance. Its authorization text is load-bearing — the artifact
RECOMMENDS and never authorizes (spec §4 authorization boundary).
"""

from __future__ import annotations

from typing import Any

from local_ai.build_room.participants import OpenAIParticipant, Seat

AUTHORIZATION_TEXT = (
    "DRAFT EXPERIMENTAL ARTIFACT — RECOMMENDS ONLY. "
    "This artifact does not authorize execution: no file modification, "
    "no PR creation, no consequential action follows from it. "
    "Execution requires Joshua's explicit authorization, separate from "
    "any approval of the design elements discussed here."
)

CLAIMS_NOTE = (
    "Substantive claims in this artifact are model-authored and "
    "experimental, not verified metadata."
)


def build_draft_artifact(
    meeting_id: str,
    packet: Any,
    transcript: Any,
    participant: OpenAIParticipant | None,
    *,
    contribution: str | None = None,
    failure: str | None = None,
) -> dict[str, Any]:
    """Build the draft artifact dict from a finished (or failed) meeting."""
    if participant is None:
        provenance = {"participant": "GPT", "provider": "openai", "model": None,
                      "status": "absent"}
    else:
        provenance = {"participant": "GPT", "provider": "openai",
                      "model": participant.model,
                      "key_source": participant.key_source,
                      "status": "present"}
    return {
        "status": "DRAFT_EXPERIMENTAL",
        "is_review_item": False,
        "experimental_area": True,
        "authorization": AUTHORIZATION_TEXT,
        "claims_note": CLAIMS_NOTE,
        "meeting_id": meeting_id,
        "work_item": packet.work_item,
        "question": packet.question,
        "recommendation": contribution,
        "failure": failure,
        "provenance": provenance,
        "transcript_entries": len(transcript.entries),
    }


LANGUAGE_NOTE = (
    "Review surface language: this artifact's synthesis and conclusions "
    "are in English. Transcript contributions are verbatim and may "
    "include transliterable seat-to-seat shorthand."
)


def build_draft_artifact_r2(
    meeting_id: str,
    packet: Any,
    transcript: Any,
    seats: list[Seat],
    registry: Any,
    *,
    interactions: list[dict[str, Any]] | None = None,
    synthesis: dict[str, Any] | None = None,
    synthesis_failure: str | None = None,
    positions: list[dict] | None = None,
    disagreements: list[dict] | None = None,
    unresolved_objections: list[dict] | None = None,
    generation_timestamps: dict[str, dict[str, float]] | None = None,
) -> dict[str, Any]:
    """Build the R2 draft artifact dict.

    Same boundaries as R1 (DRAFT_EXPERIMENTAL, recommends-only, not a
    review item, claims note) plus the R2 structures: the mechanical
    claim registry, per-response interactions (citations + stated
    moves + mechanical addressability — NOT a genuineness score),
    attributed positions/disagreements (model-authored annotations,
    never runner facts), and the labeled synthesis. Nothing here is
    marked resolved by the room; resolution is Joshua's verdict.
    """
    provenance = []
    for seat in seats:
        if seat.participant is None:
            provenance.append({
                "participant": seat.name, "provider": seat.provider_id,
                "model": seat.model, "status": "absent",
            })
        else:
            provenance.append({
                "participant": seat.name, "provider": seat.provider_id,
                "model": seat.participant.model,
                "key_source": seat.participant.key_source,
                "status": "present",
            })
    return {
        "status": "DRAFT_EXPERIMENTAL",
        "is_review_item": False,
        "experimental_area": True,
        "authorization": AUTHORIZATION_TEXT,
        "claims_note": CLAIMS_NOTE,
        "language_note": LANGUAGE_NOTE,
        "meeting_id": meeting_id,
        "work_item": packet.work_item,
        "question": packet.question,
        "claim_registry": [c.to_dict() for c in registry.claims],
        "interactions": interactions or [],
        "positions": positions or [],
        "disagreements": disagreements or [],
        "unresolved_objections": unresolved_objections or [],
        "synthesis": synthesis,
        "synthesis_failure": synthesis_failure,
        "provenance": provenance,
        "generation_timestamps": generation_timestamps or {},
        "transcript_entries": len(transcript.entries),
    }
