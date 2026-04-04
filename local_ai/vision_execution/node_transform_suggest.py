"""
Bounded VE node transforms: single JSON response (no SSE). For short user asks like
“turn this into a task” — not the council streaming path.

Canonical payload spine: ``judgment_trunk`` (SubjectRef + JudgmentTrunk from ``judgment_substrate``).
Legacy keys ``intent``, ``suggested_action``, ``proposed_node``, ``reason``, ``confidence`` are
mirrors derived from the trunk for stable API/frontend formatting (``formatNodeTransformAgentContent``).
"""

from __future__ import annotations

import json
import logging
from typing import Any, Mapping

from local_ai.judgment_substrate import (
    JudgmentMechanism,
    JudgmentObservation,
    JudgmentTrunk,
    JudgmentVerdict,
    SubjectRef,
)
from local_ai.vision_execution.entity_judgment_primitives import clamp01
from local_ai.vision_execution.idea_evaluate import _extract_json_object

logger = logging.getLogger(__name__)

INTENTS = frozenset({"idea_to_task", "idea_to_project", "project_to_tasks", "make_more_concrete"})
SOURCE_TYPES = frozenset({"idea", "initiative", "project", "task"})
PROPOSED_TYPES = frozenset({"idea", "initiative", "project", "task"})

_VERDICT_KIND = "ve_node_transform_proposal"

TRANSFORM_PROMPT = """You refine or reshape ONE workspace entity based on a short user request. Suggest only — human creates/updates records.

Transform intent: {intent}
Source entity type: {node_type}
Source entity id: {node_id}
Title: {title}
Summary / context: {summary}
User message: {user_message}

Core profile (optional strategic alignment):
{profile_block}

Respond with exactly one JSON object (no markdown). Use the canonical judgment verdict block:

{{
  "intent": "{intent}",
  "verdict": {{
    "transform_operation": "create_child_task | create_project | split_tasks | refine_in_place",
    "proposed_entity": {{
      "type": "task | project | idea | initiative",
      "title": "concise actionable title",
      "summary": "1–3 sentences"
    }},
    "reason": "why this shape fits the intent and source",
    "confidence": 0.0
  }}
}}

Rules:
- Align proposed_entity.type with intent (e.g. idea_to_task → type task).
- For project_to_tasks, proposed_entity is the first / anchor task; mention other tasks briefly in summary or reason.
- For make_more_concrete, keep same coarse type unless a child task is clearly better; transform_operation may be refine_in_place or create_child_task.
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


def _normalize_proposed_entity(pn_raw: Any) -> dict[str, str]:
    ptype = "task"
    ptitle = ""
    psum = ""
    if isinstance(pn_raw, dict):
        ptype = str(pn_raw.get("type") or "task").strip().lower()
        if ptype not in PROPOSED_TYPES:
            ptype = "task"
        ptitle = str(pn_raw.get("title") or "")[:500]
        psum = str(pn_raw.get("summary") or "")[:2000]
    return {"type": ptype, "title": ptitle, "summary": psum}


def _extract_proposal_from_llm(data: dict[str, Any], intent: str) -> dict[str, Any]:
    """Map LLM JSON (verdict block or legacy flat keys) to normalized proposal fields."""
    it = str(data.get("intent") or intent).strip().lower()
    if it not in INTENTS:
        it = intent
    verdict = data.get("verdict")
    if isinstance(verdict, dict):
        op = str(verdict.get("transform_operation") or verdict.get("suggested_action") or "create_child_task")[:120]
        pn_raw = verdict.get("proposed_entity") or verdict.get("proposed_node")
        reason = str(verdict.get("reason") or data.get("reason") or "")[:1200]
        conf = verdict.get("confidence", data.get("confidence"))
    else:
        op = str(data.get("suggested_action") or data.get("transform_operation") or "create_child_task")[:120]
        pn_raw = data.get("proposed_node") or data.get("proposed_entity")
        reason = str(data.get("reason") or "")[:1200]
        conf = data.get("confidence")
    pe = _normalize_proposed_entity(pn_raw)
    return {
        "intent": it,
        "transform_operation": op,
        "proposed_entity": pe,
        "reason": reason,
        "confidence": clamp01(conf, default_when_invalid=0.55),
    }


def _build_trunk_from_proposal(
    proposal: dict[str, Any],
    *,
    node_type: str,
    node_id: str,
    title: str,
    summary: str,
    user_message: str,
) -> JudgmentTrunk:
    subj_title = (title or "").strip() or None
    subj_summary = (summary or "").strip()[:2000] or None
    subject = SubjectRef(
        entity_type=node_type,
        entity_id=node_id,
        title=subj_title,
        summary=subj_summary,
        extra={},
    )
    pe = proposal["proposed_entity"]
    payload: dict[str, Any] = {
        "transform_operation": proposal["transform_operation"],
        "proposed_entity": dict(pe),
        "reason": proposal["reason"],
        "confidence": proposal["confidence"],
    }
    return JudgmentTrunk(
        subject=subject,
        observation=JudgmentObservation(
            pointer=None,
            context={
                "user_message": (user_message or "")[:2000],
                "transform_intent": proposal["intent"],
            },
        ),
        verdict=JudgmentVerdict(kind=_VERDICT_KIND, payload=payload),
        mechanism=JudgmentMechanism(mode="llm"),
        effect="proposal",
        state="proposed",
    )


def _legacy_fields_from_trunk(trunk: JudgmentTrunk) -> dict[str, Any]:
    """Stable API keys consumed by frontend ``NodeTransformResponse`` / formatting."""
    ctx = trunk.observation.context if trunk.observation else {}
    pl = (trunk.verdict.payload if trunk.verdict else {}) or {}
    pe = pl.get("proposed_entity")
    if not isinstance(pe, dict):
        pe = {}
    it = str(ctx.get("transform_intent") or "make_more_concrete").strip().lower()
    if it not in INTENTS:
        it = "make_more_concrete"
    return {
        "intent": it,
        "suggested_action": str(pl.get("transform_operation") or "create_child_task")[:120],
        "proposed_node": {
            "type": str(pe.get("type") or "task"),
            "title": str(pe.get("title") or ""),
            "summary": str(pe.get("summary") or ""),
        },
        "reason": str(pl.get("reason") or "")[:1200],
        "confidence": float(pl.get("confidence") if pl.get("confidence") is not None else 0.55),
    }


def _finalize_trunk_response(
    trunk: JudgmentTrunk,
    exec_meta: Mapping[str, Any] | None,
    *,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    out: dict[str, Any] = {
        "judgment_trunk": trunk.model_dump(mode="json"),
        **_legacy_fields_from_trunk(trunk),
    }
    if extra:
        out.update(extra)
    mu = (exec_meta or {}).get("model_used")
    pu = (exec_meta or {}).get("provider_used")
    if mu is not None:
        out["model_used"] = mu
    if pu is not None:
        out["provider_used"] = pu
    return out


def _heuristic_proposal(intent: str, title: str, summary: str) -> dict[str, Any]:
    base_title = (title or "Untitled").strip()[:200]
    if intent == "idea_to_task":
        ptype = "task"
        ptitle = f"Next step: {base_title}"[:500]
        psum = "Concrete task derived from the source idea; refine owner and dates in Vision Execution."
        op = "create_child_task"
    elif intent == "idea_to_project":
        ptype = "project"
        ptitle = f"Project: {base_title}"[:500]
        psum = "Scoped project container; link back to the originating idea in VE."
        op = "create_project"
    elif intent == "project_to_tasks":
        ptype = "task"
        ptitle = f"First milestone: {base_title}"[:500]
        psum = "Anchor task for breaking work down; add sibling tasks in VE."
        op = "create_child_task"
    else:
        ptype = "task"
        ptitle = base_title[:500] or "Refined scope"
        psum = summary[:800] or "Tighter, more actionable wording — edit in place or spawn a child task."
        op = "create_child_task" if ptype == "task" else "create_project"
    return {
        "intent": intent,
        "transform_operation": op,
        "proposed_entity": {"type": ptype, "title": ptitle, "summary": psum},
        "reason": "Heuristic fallback (model unavailable). Verify in Vision Execution.",
        "confidence": 0.42,
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

    def _heuristic_response(err: str | None = None) -> dict[str, Any]:
        prop = _heuristic_proposal(intent, title, summary)
        trunk = _build_trunk_from_proposal(
            prop,
            node_type=node_type,
            node_id=node_id,
            title=title,
            summary=summary,
            user_message=user_message,
        )
        extra: dict[str, Any] = {"_fallback": True}
        if err:
            extra["error"] = err[:300]
        return _finalize_trunk_response(trunk, exec_meta, extra=extra)

    try:
        raw = provider.generate(prompt, timeout=55)
    except Exception as e:
        logger.warning("[node-transform] generate failed: %s", e)
        return _heuristic_response(str(e))

    if not raw or not isinstance(raw, str):
        return _heuristic_response()

    data = _parse_llm_json(raw)
    if not isinstance(data, dict):
        return _heuristic_response()

    try:
        proposal = _extract_proposal_from_llm(data, intent)
        trunk = _build_trunk_from_proposal(
            proposal,
            node_type=node_type,
            node_id=node_id,
            title=title,
            summary=summary,
            user_message=user_message,
        )
    except Exception:
        return _heuristic_response()

    return _finalize_trunk_response(trunk, exec_meta)

