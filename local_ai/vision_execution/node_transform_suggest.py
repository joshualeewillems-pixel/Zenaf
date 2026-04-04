"""
Bounded VE node transforms: single JSON response (no SSE). For short user asks like
“turn this into a task” — not the council streaming path.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Mapping

from local_ai.vision_execution.entity_judgment_primitives import clamp01
from local_ai.vision_execution.idea_evaluate import _extract_json_object

logger = logging.getLogger(__name__)

INTENTS = frozenset({"idea_to_task", "idea_to_project", "project_to_tasks", "make_more_concrete"})
SOURCE_TYPES = frozenset({"idea", "initiative", "project", "task"})
PROPOSED_TYPES = frozenset({"idea", "initiative", "project", "task"})

TRANSFORM_PROMPT = """You refine or reshape ONE workspace entity based on a short user request. Suggest only — human creates/updates records.

Transform intent: {intent}
Source entity type: {node_type}
Source entity id: {node_id}
Title: {title}
Summary / context: {summary}
User message: {user_message}

Core profile (optional strategic alignment):
{profile_block}

Respond with exactly one JSON object (no markdown):
{{
  "intent": "{intent}",
  "suggested_action": "create_child_task | create_project | split_tasks | refine_in_place",
  "proposed_node": {{
    "type": "task | project | idea | initiative",
    "title": "concise actionable title",
    "summary": "1–3 sentences"
  }},
  "reason": "why this shape fits the intent and source",
  "confidence": 0.0
}}

Rules:
- Align proposed_node.type with intent (e.g. idea_to_task → type task).
- For project_to_tasks, proposed_node is the first / anchor task; mention other tasks briefly in summary or reason.
- For make_more_concrete, keep same coarse type unless a child task is clearly better; suggested_action may be refine_in_place or create_child_task.
- confidence: conservative 0–1.

JSON:"""


def _resolve_node_texts(
    node_type: str,
    node_id: str,
    user_id: str | None,
    title_in: str,
    summary_in: str,
) -> tuple[str, str]:
    title = (title_in or "").strip()
    summary = (summary_in or "").strip()
    tid = (node_id or "").strip()
    t = (node_type or "").strip().lower()
    if not tid or not user_id:
        return title, summary
    from local_ai.vision_execution import service as S

    try:
        if t == "idea":
            row = S.get_idea(tid, user_id)
            if row:
                title = title or str(row.get("title") or "").strip()
                summary = summary or str(row.get("summary") or row.get("description") or "").strip()[:2000]
        elif t == "initiative":
            row = S.get_initiative(tid, user_id)
            if row:
                title = title or str(row.get("title") or "").strip()
                summary = summary or str(row.get("brief") or row.get("notes") or "").strip()[:2000]
        elif t == "project":
            row = S.get_project(tid, user_id)
            if row:
                title = title or str(row.get("title") or "").strip()
                summary = summary or str(row.get("brief") or row.get("notes") or "").strip()[:2000]
        elif t == "task":
            row = S.get_task(tid, user_id)
            if row:
                title = title or str(row.get("title") or "").strip()
                summary = summary or str(row.get("description") or row.get("notes") or "").strip()[:2000]
    except Exception as e:
        logger.warning("[node-transform] resolve texts: %s", e)
    return title, summary


def _parse_llm_json(raw: str) -> dict[str, Any] | None:
    js = _extract_json_object(raw)
    if not js:
        return None
    try:
        return json.loads(js)
    except json.JSONDecodeError:
        return None


def _normalize_output(data: dict[str, Any], intent: str) -> dict[str, Any]:
    it = str(data.get("intent") or intent).strip().lower()
    if it not in INTENTS:
        it = intent
    pn = data.get("proposed_node")
    ptype = "task"
    ptitle = ""
    psum = ""
    if isinstance(pn, dict):
        ptype = str(pn.get("type") or "task").strip().lower()
        if ptype not in PROPOSED_TYPES:
            ptype = "task"
        ptitle = str(pn.get("title") or "")[:500]
        psum = str(pn.get("summary") or "")[:2000]
    return {
        "intent": it,
        "suggested_action": str(data.get("suggested_action") or "create_child_task")[:120],
        "proposed_node": {"type": ptype, "title": ptitle, "summary": psum},
        "reason": str(data.get("reason") or "")[:1200],
        "confidence": clamp01(data.get("confidence"), default_when_invalid=0.55),
    }


def _heuristic(intent: str, title: str, summary: str) -> dict[str, Any]:
    base_title = (title or "Untitled").strip()[:200]
    blob = f"{base_title} {summary}".strip()
    if intent == "idea_to_task":
        ptype = "task"
        ptitle = f"Next step: {base_title}"[:500]
        psum = "Concrete task derived from the source idea; refine owner and dates in Vision Execution."
    elif intent == "idea_to_project":
        ptype = "project"
        ptitle = f"Project: {base_title}"[:500]
        psum = "Scoped project container; link back to the originating idea in VE."
    elif intent == "project_to_tasks":
        ptype = "task"
        ptitle = f"First milestone: {base_title}"[:500]
        psum = "Anchor task for breaking work down; add sibling tasks in VE."
    else:
        ptype = "task"
        ptitle = base_title[:500] or "Refined scope"
        psum = summary[:800] or "Tighter, more actionable wording — edit in place or spawn a child task."
    return {
        "intent": intent,
        "suggested_action": "create_child_task" if ptype == "task" else "create_project",
        "proposed_node": {"type": ptype, "title": ptitle, "summary": psum},
        "reason": "Heuristic fallback (model unavailable). Verify in Vision Execution.",
        "confidence": 0.42,
        "_fallback": True,
    }


def suggest_node_transform(
    body: Mapping[str, Any],
    *,
    user_id: str | None,
    use_execution_seam: bool,
    exec_meta: Mapping[str, Any] | None = None,
    active_profile: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Body keys: intent, node_id/nodeId, node_type/nodeType, title, summary, user_message/userMessage,
    optional client hints. Loads title/summary from storage when missing.
    """
    intent = str(body.get("intent") or body.get("transform_intent") or "").strip().lower()
    if intent not in INTENTS:
        return {"error": "invalid_intent", "message": f"intent must be one of {sorted(INTENTS)}"}
    node_id = str(body.get("node_id") or body.get("nodeId") or "").strip()
    node_type = str(body.get("node_type") or body.get("nodeType") or "").strip().lower()
    if not node_id or node_type not in SOURCE_TYPES:
        return {"error": "invalid_node", "message": "node_id and node_type (idea|initiative|project|task) are required"}
    title_in = str(body.get("title") or "")
    summary_in = str(body.get("summary") or body.get("brief") or "")
    user_message = str(body.get("user_message") or body.get("userMessage") or "").strip()[:2000]

    title, summary = _resolve_node_texts(node_type, node_id, user_id, title_in, summary_in)
    if not title:
        title = "(untitled)"

    from local_ai.vision_execution.candidate_placement_suggest import (
        format_profile_block_for_prompt,
        profile_has_output_metadata,
    )

    if active_profile and profile_has_output_metadata(active_profile):
        profile_block = format_profile_block_for_prompt(active_profile) or "(name only)"
    else:
        profile_block = "(none)"

    from local_ai.llm.execution_principal import execution_principal_from_legacy_user_id, principal_for_vision_execution_user
    from local_ai.vision_execution.llm_seam import ve_eval_provider_shim

    principal = principal_for_vision_execution_user(user_id) if user_id else execution_principal_from_legacy_user_id(None)
    provider = ve_eval_provider_shim(principal, use_execution_seam=use_execution_seam)

    prompt = TRANSFORM_PROMPT.format(
        intent=intent,
        node_type=node_type,
        node_id=node_id,
        title=title[:500],
        summary=summary[:2000] or "(none)",
        user_message=user_message or "(see intent only)",
        profile_block=profile_block[:3500],
    )

    try:
        raw = provider.generate(prompt, timeout=55)
    except Exception as e:
        logger.warning("[node-transform] generate failed: %s", e)
        out = _heuristic(intent, title, summary)
        out["error"] = str(e)[:300]
        return out

    if not raw or not isinstance(raw, str):
        return _heuristic(intent, title, summary)

    data = _parse_llm_json(raw)
    if not isinstance(data, dict):
        return _heuristic(intent, title, summary)

    try:
        normalized = _normalize_output(data, intent)
    except Exception:
        return _heuristic(intent, title, summary)

    mu = (exec_meta or {}).get("model_used")
    pu = (exec_meta or {}).get("provider_used")
    if mu is not None:
        normalized["model_used"] = mu
    if pu is not None:
        normalized["provider_used"] = pu
    return normalized
