"""Build-Council Room, R1: single-model meeting engine.

R1 scope only: one participant (GPT via the openai provider module),
one work item in, a persisted verbatim transcript out, plus an
inspectable DRAFT artifact in a clearly marked experimental area.

Load-bearing boundaries (spec §4/§5):
- The artifact RECOMMENDS. It never authorizes execution. This package
  has no execution path: no file modification outside its store dir,
  no PR creation, no subprocess, no network calls except the single
  provider generation.
- Key values are never read into outputs, logged, or transmitted
  anywhere except the provider call itself. Presence checks return a
  boolean + source label only.
"""

from __future__ import annotations

from local_ai.build_room.artifact import build_draft_artifact
from local_ai.build_room.meeting import (
    Budget,
    EvidencePacket,
    MeetingResult,
    Transcript,
    TranscriptEntry,
    run_single_model_meeting,
)
from local_ai.build_room.participants import (
    OpenAIParticipant,
    check_openai_key_present,
    resolve_openai_participant,
)

__all__ = [
    "Budget",
    "EvidencePacket",
    "MeetingResult",
    "OpenAIParticipant",
    "Transcript",
    "TranscriptEntry",
    "build_draft_artifact",
    "check_openai_key_present",
    "resolve_openai_participant",
    "run_single_model_meeting",
]
