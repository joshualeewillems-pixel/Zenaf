"""
Structured elicitation for scoped Vision Execution records: one honest gap at a time.

Used by Zenaf trunk instructions — does not persist; guides the model to notice blanks
instead of implying saves that did not happen.
"""
from __future__ import annotations

import json
from typing import Any, TypedDict

from local_ai.vision_execution import storage as ve_storage
from local_ai.vision_execution.direct_action_executor import _resolve_scoped_ve_entity

_MISSING_FIELD_KEYS = frozenset(
    {
        "ve_gap_mode",
        "ve_gap_primary",
        "ve_gap_inventory",
    }
)


class MissingFieldPrompt(TypedDict, total=False):
    field_key: str
    label: str
    reason: str
    question: str


def _blank(v: Any) -> bool:
    return not str(v if v is not None else "").strip()


def _assets_empty(v: Any) -> bool:
    if v is None:
        return True
    if isinstance(v, list):
        return len(v) == 0
    if isinstance(v, str):
        s = v.strip()
        if not s or s == "[]":
            return True
        try:
            p = json.loads(s)
            return not (isinstance(p, list) and len(p) > 0)
        except Exception:
            return False
    return False


def _initiative_seat_gap(row: dict[str, Any]) -> MissingFieldPrompt | None:
    seats = row.get("seats")
    seat_list = seats if isinstance(seats, list) else []
    if not seat_list:
        return {
            "field_key": "seats",
            "label": "Required seats / roles",
            "reason": "No roles are defined yet, so ownership of workstreams is unclear.",
            "question": "This initiative has no required seats or roles yet. Which roles do you need, and who might fill them?",
        }
    unassigned = sum(1 for s in seat_list if isinstance(s, dict) and _blank(s.get("assigned_person_id")))
    if len(seat_list) > 0 and unassigned == len(seat_list):
        return {
            "field_key": "seats",
            "label": "Seat assignees",
            "reason": "Seats exist but nobody is assigned yet.",
            "question": f"This initiative has {len(seat_list)} seat row(s), but none have an assignee yet. Who should fill each role?",
        }
    return None


def next_missing_field_prompt(
    entity_type: str,
    row: dict[str, Any],
    *,
    execution_step_count: int | None = None,
    task_count: int | None = None,
) -> MissingFieldPrompt | None:
    """Single highest-priority gap for the entity shape (initiative → project → task → idea)."""
    et = (entity_type or "").strip().lower()
    if et == "initiative":
        if _blank(row.get("owner_id")):
            return {
                "field_key": "owner_id",
                "label": "Owner",
                "reason": "An owner anchors decisions and follow-through.",
                "question": "This initiative has no owner yet. Who should own it?",
            }
        if _blank(row.get("brief")):
            return {
                "field_key": "brief",
                "label": "Brief",
                "reason": "A short brief keeps everyone aligned on intent.",
                "question": "The brief is still empty. In one or two sentences, what is this initiative for?",
            }
        if _blank(row.get("source_idea_id")):
            return {
                "field_key": "source_idea_id",
                "label": "Source idea",
                "reason": "Linking the originating idea preserves traceability.",
                "question": "No source idea is linked yet. Which idea should this roll up from (if any)?",
            }
        n = execution_step_count if execution_step_count is not None else -1
        if n == 0:
            return {
                "field_key": "execution_steps",
                "label": "Execution steps",
                "reason": "Checklist steps turn intent into concrete next actions.",
                "question": "There are no execution steps yet. What is the first step someone should take?",
            }
        if _blank(row.get("risks")):
            return {
                "field_key": "risks",
                "label": "Risks",
                "reason": "Surfacing risks early avoids late surprises.",
                "question": "No risks are captured yet. What is the main thing that could derail this initiative?",
            }
        if _blank(row.get("kill_criteria")):
            return {
                "field_key": "kill_criteria",
                "label": "Kill criteria",
                "reason": "Clear stop rules protect capacity and focus.",
                "question": "Kill criteria are empty. Under what conditions should this initiative stop or pause?",
            }
        sg = _initiative_seat_gap(row)
        if sg:
            return sg
        if _assets_empty(row.get("required_assets")):
            return {
                "field_key": "required_assets",
                "label": "Required assets",
                "reason": "Assets clarify dependencies on tools, budget, or materials.",
                "question": "No required assets are listed yet. What do you need (tools, budget, access) to execute?",
            }
        return None

    if et == "project":
        if _blank(row.get("owner_id")):
            return {
                "field_key": "owner_id",
                "label": "Owner",
                "reason": "A project owner drives delivery.",
                "question": "This project has no owner yet. Who should own it?",
            }
        if _blank(row.get("brief")):
            return {
                "field_key": "brief",
                "label": "Brief",
                "reason": "A brief scopes outcomes and expectations.",
                "question": "The project brief is empty. What outcome are you aiming for?",
            }
        if _blank(row.get("status")):
            return {
                "field_key": "status",
                "label": "Status",
                "reason": "Status signals where the project sits in the pipeline.",
                "question": "Status is not set. What status fits this project right now?",
            }
        sup = row.get("supporting_owner_ids")
        if isinstance(sup, list) and len(sup) == 0:
            return {
                "field_key": "supporting_owner_ids",
                "label": "Supporting owners",
                "reason": "Supporting owners share load across workstreams.",
                "question": "There are no supporting owners yet. Who else should be involved as a co-owner or helper?",
            }
        if _blank(row.get("start_date")) and _blank(row.get("end_date")) and (
            row.get("estimated_weekly_hours") is None or row.get("estimated_weekly_hours") == ""
        ):
            return {
                "field_key": "schedule",
                "label": "Schedule / effort",
                "reason": "Time bounds or weekly hours make capacity trade-offs visible.",
                "question": "Start date, end date, and weekly hours are unset. What timeline or weekly effort should we assume?",
            }
        tc = task_count if task_count is not None else -1
        if tc == 0:
            return {
                "field_key": "tasks",
                "label": "Tasks",
                "reason": "Tasks break delivery into trackable units.",
                "question": "This project has no tasks yet. What is the first task you want to track?",
            }
        return None

    if et == "task":
        if _blank(row.get("assignee_id")):
            return {
                "field_key": "assignee_id",
                "label": "Assignee",
                "reason": "An assignee makes accountability explicit.",
                "question": "This task has no assignee yet. Who should be responsible?",
            }
        if _blank(row.get("status")):
            return {
                "field_key": "status",
                "label": "Status",
                "reason": "Status shows whether work has started or stalled.",
                "question": "Status is not set. What status should this task be in?",
            }
        if _blank(row.get("due_date")):
            return {
                "field_key": "due_date",
                "label": "Due date",
                "reason": "A due date helps sequence work against other commitments.",
                "question": "No due date is set. When should this be done?",
            }
        if _blank(row.get("completion_criteria")):
            return {
                "field_key": "completion_criteria",
                "label": "Completion criteria",
                "reason": "Criteria prevent “done” arguments later.",
                "question": "Completion criteria are empty. How will you know this task is finished?",
            }
        dep = row.get("dependency_ids")
        if isinstance(dep, list) and len(dep) == 0:
            return {
                "field_key": "dependency_ids",
                "label": "Dependencies",
                "reason": "Dependencies surface blockers and ordering.",
                "question": "No dependencies are listed. Is anything blocking this task, or can it start now?",
            }
        return None

    if et == "idea":
        if _blank(row.get("description")):
            return {
                "field_key": "description",
                "label": "Expanded description",
                "reason": "A fuller description separates a spark from something evaluable.",
                "question": "The description is still thin. What would you add so someone else could evaluate this idea?",
            }
        if _blank(row.get("summary")):
            return {
                "field_key": "summary",
                "label": "Summary / intent",
                "reason": "A one-line summary orients readers quickly.",
                "question": "There is no short summary yet. In one line, what is this idea?",
            }
        if _blank(row.get("desired_outcome")):
            return {
                "field_key": "desired_outcome",
                "label": "What success looks like",
                "reason": "Success criteria shape evaluate vs. promote decisions.",
                "question": "What success looks like is not written down yet. What outcome would make this idea worth promoting?",
            }
        st = str(row.get("status") or "").strip().casefold()
        if st in ("", "captured"):
            return {
                "field_key": "status",
                "label": "Evaluate / promote",
                "reason": "Early-stage ideas benefit from an explicit evaluate-or-promote decision.",
                "question": "This idea is still in a captured stage. Do you want to evaluate it further, promote it toward execution, or park it?",
            }
        return None

    return None


def top_missing_field_prompts(
    entity_type: str,
    row: dict[str, Any],
    *,
    execution_step_count: int | None = None,
    task_count: int | None = None,
    limit: int = 4,
) -> list[MissingFieldPrompt]:
    """Walk priority ladder repeatedly for inventory-style answers (2–4 gaps)."""
    out: list[MissingFieldPrompt] = []
    if limit <= 0:
        return out
    shadow: dict[str, Any] = dict(row)
    esc: int | None = execution_step_count
    tc: int | None = task_count

    for _ in range(limit):
        hit = next_missing_field_prompt(entity_type, shadow, execution_step_count=esc, task_count=tc)
        if not hit:
            break
        out.append(hit)
        fk = hit.get("field_key") or ""
        if fk == "owner_id":
            shadow["owner_id"] = "filled"
        elif fk == "brief":
            shadow["brief"] = "filled"
        elif fk == "source_idea_id":
            shadow["source_idea_id"] = "filled"
        elif fk == "execution_steps":
            esc = 1
        elif fk == "risks":
            shadow["risks"] = "filled"
        elif fk == "kill_criteria":
            shadow["kill_criteria"] = "filled"
        elif fk == "seats":
            shadow["seats"] = [{"role": "x", "assigned_person_id": "p"}]
        elif fk == "required_assets":
            shadow["required_assets"] = ["x"]
        elif fk == "status":
            shadow["status"] = "Active"
        elif fk == "supporting_owner_ids":
            shadow["supporting_owner_ids"] = ["x"]
        elif fk == "schedule":
            shadow["start_date"] = "x"
        elif fk == "tasks":
            tc = 1
        elif fk == "assignee_id":
            shadow["assignee_id"] = "filled"
        elif fk == "due_date":
            shadow["due_date"] = "2099-01-01"
        elif fk == "completion_criteria":
            shadow["completion_criteria"] = "filled"
        elif fk == "dependency_ids":
            shadow["dependency_ids"] = ["x"]
        elif fk == "description":
            shadow["description"] = "filled"
        elif fk == "summary":
            shadow["summary"] = "filled"
        elif fk == "desired_outcome":
            shadow["desired_outcome"] = "filled"
        else:
            break
    return out


def _load_scoped_row(
    entity_type: str, entity_id: str, user_id: str
) -> tuple[dict[str, Any] | None, int | None, int | None]:
    et = entity_type.strip().lower()
    esc: int | None = None
    tc: int | None = None
    if et == "initiative":
        row = ve_storage.get_initiative(entity_id, user_id)
        if row:
            esc = len(ve_storage.list_execution_steps(ve_storage.EXECUTION_STEPS_SCOPE_INITIATIVE, entity_id, user_id))
        return row, esc, None
    if et == "project":
        row = ve_storage.get_project(entity_id, user_id)
        if row:
            tc = len(ve_storage.list_tasks(user_id=user_id, project_id=entity_id))
        return row, None, tc
    if et == "task":
        return ve_storage.get_task(entity_id, user_id), None, None
    if et == "idea":
        return ve_storage.get_idea(entity_id, user_id), None, None
    return None, None, None


def _decline_aligned_prompt(
    last_intent: dict[str, Any] | None,
    entity_type: str,
    row: dict[str, Any],
    *,
    execution_step_count: int | None,
    task_count: int | None,
) -> MissingFieldPrompt | None:
    if not last_intent or not isinstance(last_intent, dict):
        return None
    kind = str(last_intent.get("kind") or "").strip()
    et = entity_type.strip().lower()
    if kind == "person_assign":
        if et == "initiative" and _blank(row.get("owner_id")):
            return {
                "field_key": "owner_id",
                "label": "Owner",
                "reason": "Lane A could not assign an owner on this turn.",
                "question": "I could not apply an owner change directly yet. This initiative still has no owner — who should own it?",
            }
        if et == "project" and _blank(row.get("owner_id")):
            return {
                "field_key": "owner_id",
                "label": "Owner",
                "reason": "Lane A could not assign a project owner on this turn.",
                "question": "I could not apply an owner change directly yet. This project still has no owner — who should own it?",
            }
        if et == "task" and _blank(row.get("assignee_id")):
            return {
                "field_key": "assignee_id",
                "label": "Assignee",
                "reason": "Lane A could not assign on this turn.",
                "question": "I could not apply an assignee change directly yet. This task still has no assignee — who should take it?",
            }
    if kind == "enum_set":
        sk = str(last_intent.get("surface_key") or "").strip().lower()
        if sk == "status":
            return {
                "field_key": "status",
                "label": "Status",
                "reason": "Status change did not persist in Lane A.",
                "question": "I did not persist a status change on this turn. What status should this record be in?",
            }
        if sk == "priority":
            return {
                "field_key": "priority",
                "label": "Priority",
                "reason": "Priority change did not persist in Lane A.",
                "question": "I did not persist a priority change on this turn. How urgent is this (e.g. low / medium / high)?",
            }
    if kind == "collection_add":
        return {
            "field_key": "collection_add",
            "label": "Structured list",
            "reason": "Append to risks/steps/deps did not complete in Lane A.",
            "question": "I did not add that to the structured list in-app on this turn. What exact text should we capture as a proposed addition?",
        }
    return next_missing_field_prompt(
        entity_type, row, execution_step_count=execution_step_count, task_count=task_count
    )


def _clear_ve_gap_keys(cp: dict[str, Any]) -> None:
    for k in _MISSING_FIELD_KEYS:
        cp.pop(k, None)


def attach_ve_gap_to_preflight(
    council_preflight_dict: dict[str, Any] | None,
    *,
    conversation_subject_dict: dict[str, Any] | None,
    user_id: str | None,
    question_kind: str,
) -> None:
    """
    Mutates ``council_preflight_dict`` in place with ``ve_gap_*`` keys for trunk consumption.

    Skips when there is no authenticated user id or no resolvable scoped entity.
    """
    if not user_id or not isinstance(council_preflight_dict, dict):
        return
    ctx: dict[str, Any] = {"council_preflight": council_preflight_dict}
    if isinstance(conversation_subject_dict, dict):
        ctx["conversation_subject"] = conversation_subject_dict
    if council_preflight_dict.get("is_scoped_digression"):
        ctx["is_scoped_digression"] = True

    eid, et = _resolve_scoped_ve_entity(ctx)
    if not eid or not et:
        _clear_ve_gap_keys(council_preflight_dict)
        return

    row, esc, tc = _load_scoped_row(et, eid, user_id)
    if not row:
        _clear_ve_gap_keys(council_preflight_dict)
        return

    _clear_ve_gap_keys(council_preflight_dict)
    cp = council_preflight_dict

    mut_parsed = bool(cp.get("lane_a_mutation_intent_parsed"))
    declined = bool(cp.get("lane_a_direct_action_declined"))
    lane_err = bool(cp.get("lane_a_direct_action_error"))
    last_intent = cp.get("lane_a_last_intent") if isinstance(cp.get("lane_a_last_intent"), dict) else None

    if question_kind == "missing_fields":
        inv = top_missing_field_prompts(et, row, execution_step_count=esc, task_count=tc, limit=4)
        if not inv:
            return
        cp["ve_gap_mode"] = "inventory"
        cp["ve_gap_inventory"] = [dict(x) for x in inv]
        cp["ve_gap_primary"] = dict(inv[0])
        return

    if mut_parsed and (declined or lane_err):
        primary = _decline_aligned_prompt(last_intent, et, row, execution_step_count=esc, task_count=tc)
        if not primary:
            return
        cp["ve_gap_mode"] = "decline_pivot"
        cp["ve_gap_primary"] = dict(primary)
        return

    _idle_elicitation_kinds = frozenset(
        {
            "next_step",
            "reflective_inquiry",
            "conversation_continuity",
            "option_generation",
        }
    )
    if not mut_parsed and question_kind in _idle_elicitation_kinds:
        primary = next_missing_field_prompt(et, row, execution_step_count=esc, task_count=tc)
        if not primary:
            return
        cp["ve_gap_mode"] = "idle_close"
        cp["ve_gap_primary"] = dict(primary)
