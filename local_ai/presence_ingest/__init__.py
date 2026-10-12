"""Presence ingestion: "bring your history".

Import a user's existing digital presence (AI chat exports, social archives,
...) and distill it into candidate TrainingSignals for the doppelganger —
with redaction at capture and an explicit user approval gate before anything
enters the training profile.

Pipeline: upload -> detect source -> parse (redacted PresenceEvents) ->
distill (candidate TrainingSignals, status=pending) -> review (approve/reject).

Raw exports stay on the local machine only. Nothing here ever calls an
external API; distillation uses the local Ollama instance.
"""
from __future__ import annotations
