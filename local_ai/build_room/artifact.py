"""Build-room draft artifact, R1.

Clearly marked EXPERIMENTAL. This is NOT a first-class review item
(R3 wires that): it carries no verdict affordance and no execution
affordance. Its authorization text is load-bearing — the artifact
RECOMMENDS and never authorizes (spec §4 authorization boundary).
"""

from __future__ import annotations

from typing import Any

from local_ai.build_room.participants import OpenAIParticipant

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
