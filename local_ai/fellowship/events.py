"""Runtime event vocabulary + emitters (Fellowship Runtime P1).

An *event* is the pipeline's first step (doctrine §2): something
happened in the shared reality the seven seats inhabit — a conversation
turn, a claim verdict, a task completion, a meeting completion, a
decision record. Events are emitted at the existing chokepoints where
those things already happen; this module adds no new user-visible
behavior and collects no new data — it names what the system already
does so a character can, later and off the reply path, interpret it
(derivation.py).

Transport: events ride the append-only activity log
(local_ai/activity.py) — one JSONL line per event, ``source`` =
``"fellowship"``, the detail field carrying a JSON payload (summary +
verbatim evidence where the event has any). Per activity.py's own
rule, this log is a causal timeline, not a store: canonical entities
(conversations, claims, tasks, decisions) stay in their own stores and
the event only references them (entity_type / entity_id). The
observation store (observations.py) holds the derived interpretations;
an observation's ``event_ref`` is the activity event id returned here.

Two-speed law (Joshua's ruling, 2026-10-23): emitting an event is
cheap and synchronous (a file append, the same cost class as the
activity logging the emitters' neighbors already do). Derivation —
the slow path — is *scheduled*, never run inline: it happens on a
background thread through the pipeline derivation.py installs, and
only when a pipeline is installed (the app installs one at assembly;
unit tests and embedding tools that never install one simply record
events). A failure anywhere in the scheduling path is logged and
swallowed: an event can never break the operation that produced it.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any

from local_ai import activity as _activity

logger = logging.getLogger(__name__)

#: ``ActivityEvent.source`` for fellowship runtime events.
FELLOWSHIP_ACTIVITY_SOURCE = "fellowship"

# -- the vocabulary -----------------------------------------------------------
#: A user turn in the persistent conversation (ConversationService.turn).
CONVERSATION_TURN = "conversation_turn"
#: A review verdict on a claim (accept / correct / explain / reject /
#: unresolve), emitted from the single verdict chokepoint
#: (agent_intake.pipeline.log_claim_feedback).
CLAIM_DECIDED = "claim_decided"
#: A vision-execution task transitioned to a done status
#: (vision_execution.storage.update_task, beside the existing
#: TASK_COMPLETED activity record).
TASK_COMPLETED = "task_completed"
#: A keystone meeting completed (MeetingService._do_reveal — the single
#: completion chokepoint every meeting path funnels through).
MEETING_COMPLETED = "meeting_completed"
#: A vision-execution decision record was appended
#: (vision_execution.storage.create_decision). The event *adopts* the
#: existing append-only DecisionCreate record as its source — the
#: event references the decision by id and never duplicates it.
DECISION_RECORDED = "decision_recorded"

EVENT_KINDS: tuple[str, ...] = (
    CONVERSATION_TURN,
    CLAIM_DECIDED,
    TASK_COMPLETED,
    MEETING_COMPLETED,
    DECISION_RECORDED,
)


@dataclass(frozen=True)
class FellowshipEvent:
    """One thing that happened in the shared reality.

    ``evidence_text`` is verbatim words from the record (the user's
    own message, a claim's anchored evidence, the user's read-back
    answer) — never a paraphrase. It may be empty for events whose
    record carries no user words (e.g. a task completion); in that
    case an observation's evidence is the entity reference instead.
    ``summary`` is a factual one-liner for prompt context and the
    pre-filter — context, not evidence.
    """

    id: str
    kind: str
    user_id: str
    entity_type: str
    entity_id: str
    evidence_text: str = ""
    summary: str = ""
    payload: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""


def emit_event(
    *,
    kind: str,
    user_id: str,
    entity_type: str,
    entity_id: str,
    evidence_text: str = "",
    summary: str = "",
    payload: dict[str, Any] | None = None,
    schedule: bool = True,
) -> FellowshipEvent:
    """Record an event on the activity log and schedule its derivation.

    Returns the event (its ``id`` is the activity event id observations
    reference). Never raises for log/scheduling failures — those are
    logged and swallowed — but raises ValueError for an unknown kind:
    a misspelled event kind is a programming error, not a runtime
    condition, and should fail loudly in development and tests.
    """
    if kind not in EVENT_KINDS:
        raise ValueError(f"unknown fellowship event kind: {kind!r}")
    payload = dict(payload or {})
    detail = json.dumps(
        {
            "summary": summary,
            "evidence": evidence_text,
            "payload": payload,
        },
        ensure_ascii=False,
    )
    event_id = _activity.log_activity_simple(
        type=kind,
        entity_type=entity_type,
        entity_id=entity_id,
        actor=user_id or "system",
        source=FELLOWSHIP_ACTIVITY_SOURCE,
        detail=detail,
    )
    event = FellowshipEvent(
        id=event_id,
        kind=kind,
        user_id=user_id,
        entity_type=entity_type,
        entity_id=entity_id,
        evidence_text=evidence_text,
        summary=summary,
        payload=payload,
    )
    if schedule:
        _schedule_derivation(event)
    return event


def _schedule_derivation(event: FellowshipEvent) -> None:
    """Hand the event to the derivation pipeline, if one is installed.

    Fully guarded: derivation is a slow-path nicety; the operation that
    produced the event must never feel it fail.
    """
    try:
        from local_ai.fellowship import derivation

        pipeline = derivation.get_pipeline()
        if pipeline is not None:
            pipeline.schedule(event)
    except Exception:
        logger.exception("fellowship: derivation scheduling failed for %s", event.id)
