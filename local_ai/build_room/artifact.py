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
    "Review surface language: this artifact is in English. "
    "Transcript contributions are verbatim and may "
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
    unresolved_objections: list[dict] | None = None,
    delta_report: dict[str, Any] | None = None,
    generation_timestamps: dict[str, dict[str, float]] | None = None,
    record_complete: bool = False,
    deliberation_complete: bool = False,
    ok: bool = False,
) -> dict[str, Any]:
    """Build the R2 draft artifact dict (synthesis-less).

    Same boundaries as R1 (DRAFT_EXPERIMENTAL, recommends-only, not a
    review item, claims note) plus the R2 structures: the mechanical
    claim registry, per-response interactions (citations + stated
    moves + mechanical addressability — NOT a genuineness score),
    and the mechanical unresolved-objection derivation. Nothing here
    is marked resolved by the room; resolution is Joshua's verdict.
    There is NO synthesis in this artifact, by design (2026-10-27,
    Joshua: drop synthesis entirely): synthesis fields are absent,
    not failed, and ``synthesis_removed`` marks that explicitly.
    Status fields (design §3B): ``record_complete`` (every expected
    generation accounted for), ``deliberation_complete`` (required
    phases actually completed), ``ok`` (both). Unresolved
    objections are mechanical derivations, labeled as such.
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
        "unresolved_objections": unresolved_objections or [],
        "unresolved_objections_evaluation": "mechanical",
        "delta_report": delta_report or {
            "revision_chains": [],
            "synthesis_elements_from_later_phases": [],
            "unclassified_candidates": [],
        },
        # Synthesis removal (2026-10-27, Joshua): synthesis fields
        # are ABSENT by design, not failed. This marker is what
        # distinguishes a synthesis-less artifact from a failed
        # synthesis in a historical artifact (design §3C).
        "synthesis_removed": True,
        "synthesis_removal_decision": "2026-10-27, Joshua: drop synthesis entirely",
        "record_complete": record_complete,
        "deliberation_complete": deliberation_complete,
        "ok": ok,
        "provenance": provenance,
        "generation_timestamps": generation_timestamps or {},
        "transcript_entries": len(transcript.entries),
    }
