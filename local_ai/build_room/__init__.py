"""Build-Council Room: R1 single-model engine + R2 multi-participant engine.

R1 scope: one participant (GPT via the openai provider module),
one work item in, a persisted verbatim transcript out, plus an
inspectable DRAFT artifact in a clearly marked experimental area.

R2 scope (approved design, 2026-10-26; synthesis removed 2026-10-27):
five participants, convene -> independent openings -> one response
round -> optional revision, with a mechanical claim registry,
attributed positions/disagreements, and preserved disagreement.
No role labels anywhere, not even labeled provisional.

Load-bearing boundaries (spec §4/§5):
- The artifact RECOMMENDS. It never authorizes execution. This package
  has no execution path: no file modification outside its store dir,
  no PR creation, no subprocess, no network calls except provider
  generations.
- Key values are never read into outputs, logged, or transmitted
  anywhere except the provider call itself. Presence checks return a
  boolean + source label only.
"""

from __future__ import annotations

from local_ai.build_room.artifact import build_draft_artifact, build_draft_artifact_r2
from local_ai.build_room.meeting import (
    Budget,
    Claim,
    ClaimRegistry,
    EvidencePacket,
    MeetingResult,
    Transcript,
    TranscriptEntry,
    replay_derived_r2_transcript,
    replay_r2_transcript,
    run_multi_model_meeting,
    run_single_model_meeting,
)
from local_ai.build_room.participants import (
    SEAT_SPECS,
    OpenAIParticipant,
    Seat,
    SeatParticipant,
    check_openai_key_present,
    resolve_openai_participant,
    resolve_seat_participants,
    resolve_seat_participant,
)

__all__ = [
    "Budget",
    "Claim",
    "ClaimRegistry",
    "EvidencePacket",
    "MeetingResult",
    "OpenAIParticipant",
    "SEAT_SPECS",
    "Seat",
    "SeatParticipant",
    "Transcript",
    "TranscriptEntry",
    "build_draft_artifact",
    "build_draft_artifact_r2",
    "check_openai_key_present",
    "replay_derived_r2_transcript",
    "replay_r2_transcript",
    "resolve_openai_participant",
    "resolve_seat_participants",
    "resolve_seat_participant",
    "run_multi_model_meeting",
    "run_single_model_meeting",
]
