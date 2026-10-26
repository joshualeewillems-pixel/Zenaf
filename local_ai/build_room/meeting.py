"""Build-room meeting runner, R1: single-model meeting.

One work item in, persisted verbatim transcript out, plus a draft
artifact (see artifact.py). The transcript is append-only: convene,
contribution, pass, failure, and absence entries are all recorded
verbatim with attribution. Nothing is paraphrase-laundered.

Budget enforcement (spec §5): one contribution max for R1, a per-call
timeout, and a prompt-size cap. Breach means a recorded failure entry
and no generation — never a silent overrun.
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from local_ai.build_room.artifact import build_draft_artifact
from local_ai.build_room.participants import (
    OpenAIParticipant,
    resolve_openai_participant,
)
from local_ai.llm.execution_principal import ExecutionPrincipal


@dataclass(frozen=True)
class EvidencePacket:
    """Shared, immutable meeting evidence (spec §4 convene).

    Frozen on purpose: later evidence is appended as new transcript
    entries, never by mutating this packet.
    """

    work_item: str
    question: str
    excerpts: tuple[str, ...] = ()
    constraints: tuple[str, ...] = ()
    source_refs: tuple[str, ...] = ()
    context: tuple[str, ...] = ()

    def render_prompt(self) -> str:
        parts = [f"Work item:\n{self.work_item}", f"Question:\n{self.question}"]
        if self.excerpts:
            parts.append("Excerpts:\n" + "\n---\n".join(self.excerpts))
        if self.constraints:
            parts.append("Constraints:\n" + "\n".join(f"- {c}" for c in self.constraints))
        if self.source_refs:
            parts.append("Source references:\n" + "\n".join(f"- {r}" for r in self.source_refs))
        if self.context:
            parts.append("Architectural context:\n" + "\n---\n".join(self.context))
        parts.append(
            "Respond as a single deliberation contribution, keeping these "
            "distinct:\n"
            "- Observed: only statements directly supported by the supplied "
            "evidence above.\n"
            "- Inferred: conclusions reached by reasoning from identified "
            "evidence above.\n"
            "- Proposed: a suggested intervention.\n"
            "- Speculative: an exploratory possibility.\n"
            "- Contested: an unresolved objection, not merely uncertainty.\n"
            "If no observations are warranted, omit the Observed category "
            "rather than filling it."
        )
        return "\n\n".join(parts)


@dataclass(frozen=True)
class Budget:
    max_contributions: int = 1
    timeout_seconds: int = 120
    max_prompt_chars: int = 20000


@dataclass
class TranscriptEntry:
    kind: str  # convene | contribution | failure | absence | note
    participant: str
    text: str
    ts: float = field(default_factory=time.time)


@dataclass
class Transcript:
    entries: list[TranscriptEntry] = field(default_factory=list)

    def append(self, kind: str, participant: str, text: str) -> TranscriptEntry:
        entry = TranscriptEntry(kind=kind, participant=participant, text=text)
        self.entries.append(entry)
        return entry

    def to_dict(self) -> dict[str, Any]:
        return {"entries": [asdict(e) for e in self.entries]}


@dataclass
class MeetingResult:
    meeting_id: str
    transcript: Transcript
    artifact: dict[str, Any]
    ok: bool
    transcript_path: Path
    artifact_path: Path


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _log_usage(store_dir: Path, **fields: Any) -> None:
    line = json.dumps({"ts": time.time(), **fields}, sort_keys=True)
    with (store_dir / "usage.jsonl").open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def run_single_model_meeting(
    packet: EvidencePacket,
    *,
    store_dir: Path | str,
    budget: Budget | None = None,
    principal: ExecutionPrincipal | None = None,
    participant: OpenAIParticipant | None = None,
) -> MeetingResult:
    """Run one R1 meeting. Never raises for participant/generation failure:
    failures are recorded in the transcript and reflected in ``ok``."""
    budget = budget or Budget()
    store = Path(store_dir)
    store.mkdir(parents=True, exist_ok=True)
    meeting_id = uuid.uuid4().hex[:12]
    transcript = Transcript()
    transcript.append("convene", "Reynard (convener)",
                      f"Work item: {packet.work_item}\nQuestion: {packet.question}")

    if participant is None:
        participant, absence_note = resolve_openai_participant(principal)
        if participant is None:
            transcript.append("absence", "GPT", absence_note)
            artifact = build_draft_artifact(meeting_id, packet, transcript, None)
            t_path = store / f"meeting_{meeting_id}.transcript.json"
            a_path = store / f"meeting_{meeting_id}.draft_artifact.json"
            _write_json(t_path, {"meeting_id": meeting_id, **transcript.to_dict()})
            _write_json(a_path, artifact)
            _log_usage(store, meeting_id=meeting_id, participant="GPT",
                       provider="openai", key_source="none",
                       operation="build_room_r1_meeting", outcome="absent")
            return MeetingResult(meeting_id, transcript, artifact, False, t_path, a_path)

    prompt = packet.render_prompt()
    contribution: str | None = None
    failure: str | None = None
    if budget.max_contributions < 1:
        failure = "budget_exceeded: max_contributions is 0; no generation attempted"
    elif len(prompt) > budget.max_prompt_chars:
        failure = (
            f"budget_exceeded: prompt of {len(prompt)} chars exceeds "
            f"max_prompt_chars={budget.max_prompt_chars}; no generation attempted"
        )
    else:
        try:
            contribution = participant.generate(prompt, timeout=budget.timeout_seconds)
        except Exception as exc:  # recorded, not raised
            failure = f"{type(exc).__name__}: {str(exc)[:200]}"

    if failure is not None:
        transcript.append("failure", "GPT", failure)
        outcome = "failed"
    else:
        transcript.append("contribution", "GPT", contribution or "")
        outcome = "generated"

    artifact = build_draft_artifact(meeting_id, packet, transcript, participant,
                                    contribution=contribution, failure=failure)
    t_path = store / f"meeting_{meeting_id}.transcript.json"
    a_path = store / f"meeting_{meeting_id}.draft_artifact.json"
    _write_json(t_path, {"meeting_id": meeting_id, **transcript.to_dict()})
    _write_json(a_path, artifact)
    _log_usage(store, meeting_id=meeting_id, participant="GPT",
               provider="openai", key_source=participant.key_source,
               operation="build_room_r1_meeting", outcome=outcome)
    return MeetingResult(meeting_id, transcript, artifact, failure is None, t_path, a_path)
