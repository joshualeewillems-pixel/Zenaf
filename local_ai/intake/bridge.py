"""
Thin bridge from Intake (staging) to Vision Execution (durable core).

When an intake item is graduated into a task, we create the task and record a
minimal lifecycle linkage in a Vision Execution Decision and in task notes.
No dedicated lifecycle table; no workflow engine.
"""
from __future__ import annotations

from typing import Any

# Prefix for provenance line in task notes; parseable for lifecycle queries.
LIFECYCLE_NOTES_PREFIX = "[Atria lifecycle]"


def _append_lifecycle_provenance(notes: str, intake_item_id: str, judgment_id: str | None) -> str:
    """Append a single parseable line to task notes: intake_item_id and optional judgment_id."""
    parts = [f"intake_item_id={intake_item_id}"]
    if judgment_id and (judgment_id or "").strip():
        parts.append(f"judgment_id={judgment_id.strip()}")
    line = f"\n{LIFECYCLE_NOTES_PREFIX} " + " ".join(parts)
    return (notes or "").strip() + line


def create_task_from_intake_item(
    intake_item_id: str,
    project_id: str,
    title: str,
    *,
    summary: str | None = None,
    notes: str | None = None,
    source_judgment_id: str | None = None,
) -> dict[str, Any]:
    """
    Create a Vision Execution task from an intake item and record minimal lifecycle linkage.

    - Creates the task with title, description (summary), notes (with provenance line).
    - Creates a Vision Execution Decision with entity_type=task, entity_id=task_id,
      decision_type=intake_graduate_task, final_values_snapshot={ intake_item_id, judgment_id, task_id }.

    Returns: { "task": <task dict>, "decision_id": <str> }.
    Raises: ValueError if intake item not found or project_id invalid.
    """
    from local_ai.intake.queue_store import get_item
    from local_ai.vision_execution import storage as ve_storage
    from local_ai.vision_execution import models as M
    from local_ai.vision_execution.recognition import DECISION_TYPE_INTAKE_GRADUATE_TASK

    item = get_item(intake_item_id)
    if item is None:
        raise ValueError(f"Intake item not found: {intake_item_id}")

    title_clean = (title or "").strip() or (item.get("subject") or "")[:200] or "Task from intake"
    description_clean = (summary or "").strip() or (item.get("summary") or "")[:2000]
    notes_with_provenance = _append_lifecycle_provenance(notes or "", intake_item_id, source_judgment_id)

    task_data = M.TaskCreate(
        project_id=project_id,
        parent_task_id=None,
        title=title_clean,
        description=description_clean,
        notes=notes_with_provenance,
        status="Todo",
    )
    task = ve_storage.create_task(task_data)
    task_id = task.get("id")
    if not task_id:
        raise ValueError("Vision Execution create_task did not return task id")

    snapshot: dict[str, Any] = {
        "intake_item_id": intake_item_id,
        "task_id": task_id,
    }
    if source_judgment_id and (source_judgment_id or "").strip():
        snapshot["judgment_id"] = source_judgment_id.strip()

    decision_data = M.DecisionCreate(
        user_id=None,
        entity_type="task",
        entity_id=task_id,
        decision_type=DECISION_TYPE_INTAKE_GRADUATE_TASK,
        ai_proposal_snapshot=None,
        final_values_snapshot={
            **snapshot,
            "recognition_kind": "signal_to_action",
        },
    )
    decision = ve_storage.create_decision(decision_data)
    decision_id = decision.get("id") or ""

    return {"task": task, "decision_id": decision_id}
