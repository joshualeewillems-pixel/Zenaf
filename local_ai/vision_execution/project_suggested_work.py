"""
Project Suggested work (AI) — coordination hints, not execution steps or tasks.

Returns a short JSON list of observations; no DB writes.
"""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any

from local_ai.llm.adapter import LLMRequest
from local_ai.llm.execution_principal import principal_for_vision_execution_user
from local_ai.llm.resolver import get_llm_adapter_for_principal
from local_ai.vision_execution.idea_evaluate import _extract_json_object

logger = logging.getLogger(__name__)

ALLOWED_KINDS = frozenset(
    {
        "missing_ownership",
        "uncovered_work",
        "coordination_gap",
        "unclear_scope",
    }
)

PROMPT = """You are a project coordination assistant. Given a project snapshot (brief, owner, tasks, assignees, dependencies), respond with coordination insights only.

You MUST NOT output execution steps, task titles to create, or ordered checklists. Do not tell the user to "create a task" or list micro-steps.

Instead output 3 to 8 short observations across these categories:
- missing_ownership: work or areas with no clear owner or assignee
- uncovered_work: scope or outcomes implied by the brief but not reflected in tasks
- coordination_gap: handoffs, dependencies, sequencing, or communication risks
- unclear_scope: vague brief, missing success criteria, or follow-through ambiguity

Respond with exactly one JSON object and nothing else. No markdown, no code fences, no preamble.
Valid JSON only. Required shape:
{{
  "suggestions": [
    {{ "kind": "missing_ownership", "text": "One concise sentence." }},
    {{ "kind": "coordination_gap", "text": "One concise sentence." }}
  ]
}}

Rules:
- "kind" must be one of: missing_ownership, uncovered_work, coordination_gap, unclear_scope
- "text" is a single short sentence (max ~200 characters)
- 3 to 8 items total; prioritize the most important gaps
- If the project looks healthy, return fewer items or one item noting "brief looks aligned" with kind unclear_scope or coordination_gap only if honest

--- Project snapshot ---
{snapshot}

JSON:"""

RETRY = "\n\nRemember: only one JSON object with key suggestions (array of objects with kind and text). No steps or tasks to create."


def _person_name(persons_by_id: dict[str, str], pid: str | None) -> str:
    if not pid:
        return "(none)"
    return persons_by_id.get(pid, pid)


def _build_snapshot(
    project: dict[str, Any],
    tasks: list[dict[str, Any]],
    persons_by_id: dict[str, str],
) -> str:
    lines: list[str] = []
    title = str(project.get("title") or "").strip() or "(untitled)"
    brief = str(project.get("brief") or "").strip()
    status = str(project.get("status") or "").strip()
    owner = _person_name(persons_by_id, project.get("owner_id"))
    sup = project.get("supporting_owner_ids")
    sup_names = []
    if isinstance(sup, list):
        for x in sup:
            if isinstance(x, str) and x:
                sup_names.append(_person_name(persons_by_id, x))
    lines.append(f"Title: {title}")
    lines.append(f"Status: {status}")
    lines.append(f"Owner: {owner}")
    if sup_names:
        lines.append(f"Supporting owners: {', '.join(sup_names)}")
    lines.append(f"Brief:\n{brief or '(empty)'}")
    lines.append("")
    lines.append(f"Tasks ({len(tasks)}):")
    if not tasks:
        lines.append("  (none)")
    else:
        tid_set = {str(t.get("id")) for t in tasks if t.get("id")}
        for t in tasks[:40]:
            tid = str(t.get("id") or "")
            tit = str(t.get("title") or "(untitled)").strip()
            st = str(t.get("status") or "").strip()
            asg = _person_name(persons_by_id, t.get("assignee_id"))
            deps = t.get("dependency_ids")
            dep_note = ""
            if isinstance(deps, list) and deps:
                resolved = []
                for d in deps[:8]:
                    ds = str(d)
                    if ds in tid_set:
                        other = next((x for x in tasks if str(x.get("id")) == ds), None)
                        if other:
                            resolved.append(str(other.get("title") or ds)[:40])
                        else:
                            resolved.append(ds[:12])
                    else:
                        resolved.append(ds[:12])
                dep_note = f" | depends_on: {', '.join(resolved)}"
            crit = str(t.get("completion_criteria") or "").strip()
            crit_note = f" | criteria: {crit[:80]}…" if len(crit) > 80 else (f" | criteria: {crit}" if crit else "")
            lines.append(f"  - [{st}] {tit} | assignee: {asg}{dep_note}{crit_note}")
        if len(tasks) > 40:
            lines.append(f"  ... and {len(tasks) - 40} more tasks omitted")
    return "\n".join(lines)


def _normalize_suggestions(raw: Any) -> list[dict[str, str]] | None:
    if not isinstance(raw, list):
        return None
    out: list[dict[str, str]] = []
    for item in raw[:12]:
        if not isinstance(item, dict):
            continue
        kind = str(item.get("kind") or "").strip()
        if kind not in ALLOWED_KINDS:
            kind = "coordination_gap"
        text = str(item.get("text") or "").strip()
        if not text or len(text) > 400:
            continue
        out.append({"id": str(uuid.uuid4()), "kind": kind, "text": text})
    if len(out) < 1:
        return None
    return out[:8]


def generate_project_suggested_work(
    *,
    project: dict[str, Any],
    tasks: list[dict[str, Any]],
    persons_by_id: dict[str, str],
    user_id: str,
) -> dict[str, Any]:
    snapshot = _build_snapshot(project, tasks, persons_by_id)
    try:
        adapter = get_llm_adapter_for_principal(principal_for_vision_execution_user(user_id))
    except Exception as e:
        return {"error": f"LLM unavailable: {e}"}

    prompt = PROMPT.format(snapshot=snapshot[:14000])

    def _call(p: str) -> dict[str, Any] | None:
        try:
            raw = adapter.generate_text(
                LLMRequest(
                    task="vision_project_suggested_work",
                    prompt=p,
                    timeout=120,
                    metadata={"project_id": str(project.get("id") or ""), "tasks": len(tasks)},
                )
            )
        except Exception as e:
            logger.warning("project_suggested_work LLM error: %s", e)
            return None
        if not raw or not isinstance(raw, str):
            return None
        js = _extract_json_object(raw.strip())
        if not js:
            return None
        try:
            data = json.loads(js)
        except json.JSONDecodeError:
            return None
        if not isinstance(data, dict):
            return None
        sug = _normalize_suggestions(data.get("suggestions"))
        if not sug:
            return None
        return {"suggestions": sug}

    first = _call(prompt)
    if first is not None:
        return first
    second = _call(prompt + RETRY)
    if second is not None:
        return second
    return {"error": "Could not generate suggestions — try again or check LLM settings."}
