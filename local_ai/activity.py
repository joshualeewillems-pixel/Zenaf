"""
Layer 1: Universal ActivityEvent primitive.

Lightweight, append-only activity/event log for important system events.
This is NOT full event sourcing; it simply creates a causal timeline that
other modules (signals, radar, tasks) can reference.

Architecture: Views must not become models. Activity records events about
canonical entities (meeting, signal, task, etc.); it is not the storage for those entities.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# JSONL ``ActivityEvent.source`` for coordination checkpoints (distinct from judgment ``evidence_source`` strings).
COORDINATION_ACTIVITY_SOURCE_SERVER_EXECUTION = "server-execution"
COORDINATION_ACTIVITY_SOURCE_CLIENT_TRACE = "zenaf-client-trace"


class ActivityType(str, Enum):
    """Event type: what happened. Use .value when logging."""

    MEETING_PROCESSED = "meeting_processed"
    SIGNAL_CREATED = "signal_created"
    SIGNAL_ACKNOWLEDGED = "signal_acknowledged"
    SIGNAL_LINKED = "signal_linked"
    SIGNAL_RESOLVED = "signal_resolved"
    SIGNAL_DISMISSED = "signal_dismissed"
    TASK_CREATED = "task_created"
    TASK_COMPLETED = "task_completed"
    TASK_UPDATED = "task_updated"
    TASK_DELETED = "task_deleted"
    INITIATIVE_CREATED = "initiative_created"
    INITIATIVE_UPDATED = "initiative_updated"
    INITIATIVE_DELETED = "initiative_deleted"
    PROJECT_CREATED = "project_created"
    PROJECT_UPDATED = "project_updated"
    PROJECT_DELETED = "project_deleted"
    IDEA_CREATED = "idea_created"
    IDEA_UPDATED = "idea_updated"
    IDEA_DELETED = "idea_deleted"
    # Coordination layer (execution checkpoints; pointers for execution_flow_reading judgments)
    EXECUTION_STEP_MATERIALIZED = "execution_step_materialized"
    AI_SUGGESTION_APPLIED = "ai_suggestion_applied"
    VE_EVALUATE_APPLIED = "ve_evaluate_applied"
    AI_ACTION_USER_TRACE = "ai_action_user_trace"
    # Server-emitted AiActionTrace lineage (routes with no client pushAiActionTrace)
    SERVER_AI_ACTION_TRACE = "server_ai_action_trace"


class ActivityEntityType(str, Enum):
    """Entity type: what the event refers to. Use .value when logging."""

    MEETING = "meeting"
    SIGNAL = "signal"
    TASK = "task"
    PROJECT = "project"
    INITIATIVE = "initiative"
    IDEA = "idea"


@dataclass
class ActivityEvent:
    id: str
    type: str  # ActivityType.value
    entity_type: str  # ActivityEntityType.value
    entity_id: str
    related_entity_id: str | None
    actor: str | None  # "system" or user id/email/name when available
    source: str  # e.g. "meeting-extraction", "inbox-triage", "doc-parse"
    detail: str | None
    created_at: str


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id() -> str:
    try:
        from local_ai.vision_execution import models as M
        return M.new_id()
    except Exception:
        return f"act-{datetime.now(timezone.utc).timestamp()}"


def new_id() -> str:
    """Generate a new unique id (e.g. for a processed meeting). Use when you need to refer back later."""
    return _new_id()


def _activity_log_path() -> Path:
    root = Path(__file__).resolve().parent.parent
    return root / "activity.log"


def log_activity(event: ActivityEvent) -> None:
    """Append an ActivityEvent to the JSONL log."""
    path = _activity_log_path()
    line = json.dumps(asdict(event), ensure_ascii=False)
    try:
        with path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception as e:
        logger.warning("Failed to write activity event %s: %s", event.id, e)


def log_activity_simple(
    *,
    type: str,
    entity_type: str,
    entity_id: str,
    related_entity_id: str | None = None,
    actor: str | None = "system",
    source: str,
    detail: str | None = None,
) -> str:
    """Convenience wrapper to create and log an ActivityEvent. Prefer ActivityType/ActivityEntityType .value for type/entity_type. Returns event id."""
    ev = ActivityEvent(
        id=_new_id(),
        type=type,
        entity_type=entity_type,
        entity_id=entity_id,
        related_entity_id=related_entity_id,
        actor=actor,
        source=source,
        detail=detail,
        created_at=_now_iso(),
    )
    log_activity(ev)
    return ev.id


def get_recent_activity(limit: int = 100) -> list[ActivityEvent]:
    """Read activity.log and return parsed events in reverse chronological order (newest first)."""
    path = _activity_log_path()
    if not path.exists():
        return []
    events: list[ActivityEvent] = []
    try:
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    d = json.loads(line)
                    events.append(
                        ActivityEvent(
                            id=d.get("id", ""),
                            type=d.get("type", ""),
                            entity_type=d.get("entity_type", ""),
                            entity_id=d.get("entity_id", ""),
                            related_entity_id=d.get("related_entity_id"),
                            actor=d.get("actor"),
                            source=d.get("source", ""),
                            detail=d.get("detail"),
                            created_at=d.get("created_at", ""),
                        )
                    )
                except (json.JSONDecodeError, TypeError):
                    continue
    except OSError as e:
        logger.warning("Failed to read activity log: %s", e)
        return []
    # Reverse so newest first
    events.reverse()
    return events[:limit]


