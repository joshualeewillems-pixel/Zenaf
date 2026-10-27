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
    positions_evaluation: str | None = None,
    disagreements_evaluation: str | None = None,
    recommendations: list[dict] | None = None,
    limitations: list[dict] | None = None,
    recommendations_evaluation: str | None = None,
    limitations_evaluation: str | None = None,
    rejected_entries: list[dict] | None = None,
    unresolved_objections: list[dict] | None = None,
    delta_report: dict[str, Any] | None = None,
    generation_timestamps: dict[str, dict[str, float]] | None = None,
    synthesis_coverage: dict[str, Any] | None = None,
    synthesis_coverage_accepted: bool = False,
    synthesis_generation: dict[str, Any] | None = None,
    synthesis_generation_cost: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the R2 draft artifact dict.

    Same boundaries as R1 (DRAFT_EXPERIMENTAL, recommends-only, not a
    review item, claims note) plus the R2 structures: the mechanical
    claim registry, per-response interactions (citations + stated
    moves + mechanical addressability — NOT a genuineness score),
    attributed positions/disagreements (model-authored annotations,
    never runner facts), and the labeled synthesis. Nothing here is
    marked resolved by the room; resolution is Joshua's verdict.
    Per-field evaluation status (C7): when synthesis did not run,
    positions and disagreements are None with ``not_evaluated`` —
    never an empty list masquerading as a finding. Unresolved
    objections are mechanical pre-synthesis derivations, labeled as
    such, never synthesis results.
    Legibility B adds the synthesis contract fields: recommendations
    and limitations with their own evaluation fields (same
    vocabulary: synthesized_complete / synthesized_partial /
    synthesized_empty / unparseable / not_evaluated, plus the legacy
    evaluated_* values for section-parsed output), and rejected_entries — contract
    entries excluded during per-entry salvage, each with field,
    index, and reason. Structured synthesis fields are the
    synthesizer's interpretation, never mechanical evidence, and
    never override registry mechanics.
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
    synthesis_ran = synthesis is not None and synthesis.get("status") == "complete"
    if not synthesis_ran:
        positions_out = None
        disagreements_out = None
        positions_evaluation_out = "not_evaluated"
        disagreements_evaluation_out = "not_evaluated"
        recommendations_out = None
        limitations_out = None
        recommendations_evaluation_out = "not_evaluated"
        limitations_evaluation_out = "not_evaluated"
    else:
        positions_out = positions if positions is not None else []
        disagreements_out = disagreements if disagreements is not None else []
        positions_evaluation_out = positions_evaluation or (
            "evaluated_with_results" if positions_out else "evaluated_empty")
        disagreements_evaluation_out = disagreements_evaluation or (
            "evaluated_with_results" if disagreements_out else "evaluated_empty")
        recommendations_out = recommendations if recommendations is not None else []
        limitations_out = limitations if limitations is not None else []
        recommendations_evaluation_out = recommendations_evaluation or (
            "evaluated_with_results" if recommendations_out else "evaluated_empty")
        limitations_evaluation_out = limitations_evaluation or (
            "evaluated_with_results" if limitations_out else "evaluated_empty")
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
        "positions": positions_out,
        "positions_evaluation": positions_evaluation_out,
        "disagreements": disagreements_out,
        "disagreements_evaluation": disagreements_evaluation_out,
        "recommendations": recommendations_out,
        "recommendations_evaluation": recommendations_evaluation_out,
        "limitations": limitations_out,
        "limitations_evaluation": limitations_evaluation_out,
        "rejected_entries": rejected_entries or [],
        "unresolved_objections": unresolved_objections or [],
        "unresolved_objections_evaluation": "mechanical_pre_synthesis",
        "delta_report": delta_report or {
            "revision_chains": [],
            "synthesis_elements_from_later_phases": [],
            "unclassified_candidates": [],
        },
        "synthesis": synthesis,
        "synthesis_failure": synthesis_failure,
        # Coverage assurance (design §C/§E/§F): the coverage verdict
        # is a VERDICT field, never injected synthesis content. It
        # stays on the artifact even when synthesis failed (None
        # verdict + accepted False), so a coverage failure is
        # visible on the meeting artifact itself — the Phase C
        # prerequisite — not only in the harness response.
        "synthesis_coverage": synthesis_coverage,
        "synthesis_coverage_accepted": synthesis_coverage_accepted,
        "synthesis_generation": synthesis_generation,
        "synthesis_generation_cost": synthesis_generation_cost,
        "provenance": provenance,
        "generation_timestamps": generation_timestamps or {},
        "transcript_entries": len(transcript.entries),
    }
