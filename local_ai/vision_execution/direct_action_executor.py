"""
Direct Vision Execution (Lane A): narrow imperative mutations against scoped VE context.

Orchestration only: resolve entity → parse intent → coverage row → handler.
Parsing lives in ``direct_action_parsing``; registry in ``action_coverage``; I/O in ``direct_action_handlers``.
"""
from __future__ import annotations

from typing import Any, Literal

from local_ai.integration_commit import user_affirms_precision_commit
from local_ai.vision_execution.action_coverage import resolve_direct_surface_action
from local_ai.vision_execution.pending_ve_elicitation import try_resolve_pending_ve_elicitation
from local_ai.vision_execution.direct_action_handlers import execute_direct_surface_action
from local_ai.vision_execution.direct_action_parsing import parse_direct_action_intent
from local_ai.vision_execution.ve_integration_schema import normalize_trunk_token_to_storage_key

Status = Literal["handled", "declined", "error"]

_LANE_A_GUARD_KEYS = frozenset(
    {
        "lane_a_direct_action_evaluated",
        "lane_a_mutation_intent_parsed",
        "lane_a_direct_action_declined",
        "lane_a_direct_action_handled",
        "lane_a_direct_action_error",
        "lane_a_last_intent",
    }
)


def _reset_lane_a_guard(context: dict[str, Any] | None) -> None:
    if not isinstance(context, dict):
        return
    cp = context.get("council_preflight")
    if not isinstance(cp, dict):
        return
    for k in _LANE_A_GUARD_KEYS:
        cp.pop(k, None)


def _apply_lane_a_guard(
    context: dict[str, Any] | None,
    intent: dict[str, Any] | None,
    status: str,
) -> None:
    """
    Council reads ``council_preflight`` to avoid success hallucinations when Lane A parsed a mutation
    but did not persist (declined).
    """
    if not isinstance(context, dict):
        return
    cp = context.get("council_preflight")
    if not isinstance(cp, dict):
        return
    cp["lane_a_direct_action_evaluated"] = True
    if intent is not None:
        cp["lane_a_mutation_intent_parsed"] = True
        ik = str(intent.get("kind") or "").strip()
        if ik:
            slim: dict[str, Any] = {"kind": ik}
            sk = intent.get("surface_key")
            if sk is not None and str(sk).strip():
                slim["surface_key"] = str(sk).strip()
            cp["lane_a_last_intent"] = slim
    if intent is not None and status == "declined":
        cp["lane_a_direct_action_declined"] = True
    elif status == "handled":
        cp["lane_a_direct_action_handled"] = True
    elif status == "error":
        cp["lane_a_direct_action_error"] = True


def _result(
    status: Status,
    message: str = "",
    *,
    refresh_hint: str | None = None,
    created_entities: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "kind": "direct_ve_action",
        "status": status,
        "message": message,
        "refresh_hint": refresh_hint,
        "created_entities": created_entities or [],
    }


_VALID_VE_ENTITY_TYPES = frozenset({"idea", "initiative", "project", "task"})


def _normalize_ve_scope(entity_id: Any, entity_type: Any) -> tuple[str | None, str | None]:
    if entity_id is None or entity_type is None:
        return None, None
    eid = str(entity_id).strip()
    et = str(entity_type).strip().lower()
    if not eid or not et or et not in _VALID_VE_ENTITY_TYPES:
        return None, None
    return eid, et


def _scope_from_ve_focus_dict(vf: Any) -> tuple[str | None, str | None]:
    if not isinstance(vf, dict):
        return None, None
    return _normalize_ve_scope(vf.get("entity_id"), vf.get("entity_type"))


def _scope_from_ve_selected_entity(obj: Any) -> tuple[str | None, str | None]:
    if not isinstance(obj, dict):
        return None, None
    return _normalize_ve_scope(obj.get("entity_id"), obj.get("entity_type"))


def _scope_from_ve_selection_dict(sel: Any) -> tuple[str | None, str | None]:
    """Mirror frontend ``deriveVeSelectionFromDetailState`` ids (VisionExecutionView)."""
    if not isinstance(sel, dict):
        return None, None
    for key, et in (
        ("ideaId", "idea"),
        ("initiativeId", "initiative"),
        ("projectId", "project"),
        ("taskId", "task"),
    ):
        raw = sel.get(key)
        if raw is None:
            continue
        eid = str(raw).strip()
        if eid:
            return eid, et
    return None, None


def _scope_from_conversation_subject(cs: Any) -> tuple[str | None, str | None]:
    if not isinstance(cs, dict):
        return None, None
    return _normalize_ve_scope(cs.get("entity_id"), cs.get("entity_type"))


def _resolve_scoped_ve_entity(context: dict[str, Any] | None) -> tuple[str | None, str | None]:
    """
    Lane A mutation scope. Priority:

    1. Scoped council sub-thread (explicit digression entity in preflight).
    2. Panel-selected VE entity (``ve_selected_entity`` from client — open row / list selection).
    3. Raw ``ve_selection`` ids (fallback if structured payload omitted).
    4. Field / graph ``ve_focus`` (last resort when selection not sent).
    5. ``conversation_subject`` (thread continuity — must not override an open VE row).
    """
    if not isinstance(context, dict):
        return None, None
    cp = context.get("council_preflight")
    cp_d: dict[str, Any] = cp if isinstance(cp, dict) else {}

    if context.get("is_scoped_digression"):
        hit = _scope_from_ve_focus_dict(cp_d.get("ve_focus"))
        if hit[0] and hit[1]:
            return hit

    hit = _scope_from_ve_selected_entity(cp_d.get("ve_selected_entity"))
    if hit[0] and hit[1]:
        return hit

    hit = _scope_from_ve_selection_dict(cp_d.get("ve_selection"))
    if hit[0] and hit[1]:
        return hit

    hit = _scope_from_ve_focus_dict(cp_d.get("ve_focus"))
    if hit[0] and hit[1]:
        return hit

    hit = _scope_from_conversation_subject(context.get("conversation_subject"))
    if hit[0] and hit[1]:
        return hit

    return None, None


def resolve_direct_surface_action_public(
    *,
    question: str,
    context: dict[str, Any] | None,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None, str | None, str | None]:
    """
    Debug / test helper: return (intent, row, entity_id, entity_type) after normalization.

    Not used by the hot path; ``evaluate_direct_ve_action`` inlines the same steps.
    """
    eid, et = _resolve_scoped_ve_entity(context)
    intent = parse_direct_action_intent(question, entity_type=et)
    if not intent:
        return None, None, None, None
    if intent.get("kind") == "text_set":
        if not eid or not et:
            return intent, None, eid, et
        sk = normalize_trunk_token_to_storage_key(et, intent["surface_key"]) or intent["surface_key"]
        intent = {"kind": "text_set", "surface_key": sk, "value": intent["value"]}
    if intent.get("kind") == "text_append":
        if not eid or not et:
            return intent, None, eid, et
        sk0 = str(intent.get("surface_key") or "").strip()
        sk = normalize_trunk_token_to_storage_key(et, sk0) or sk0
        intent = {"kind": "text_append", "surface_key": sk, "value": intent["value"]}
    row = resolve_direct_surface_action(parsed=intent, entity_id=eid, entity_type=et, context=context)
    return intent, row, eid, et


def evaluate_direct_ve_action(
    *,
    question: str,
    context: dict[str, Any] | None,
    user_id: str | None,
) -> dict[str, Any]:
    q = (question or "").strip()
    uid = (user_id or "").strip()
    if not q or not uid:
        return _result("declined")

    _reset_lane_a_guard(context)

    if isinstance(context, dict):
        _pend_res = try_resolve_pending_ve_elicitation(q, context, uid)
        if _pend_res is not None:
            return _pend_res

    if user_affirms_precision_commit(q) and len(q) <= 64:
        return _result("declined")

    eid, et = _resolve_scoped_ve_entity(context)
    intent = parse_direct_action_intent(q, entity_type=et)
    if not intent:
        return _result("declined")

    if intent.get("kind") == "text_set":
        if not eid or not et:
            _apply_lane_a_guard(context, intent, "declined")
            return _result("declined")
        sk = normalize_trunk_token_to_storage_key(et, intent["surface_key"]) or intent["surface_key"]
        intent = {"kind": "text_set", "surface_key": sk, "value": intent["value"]}

    if intent.get("kind") == "text_append":
        if not eid or not et:
            _apply_lane_a_guard(context, intent, "declined")
            return _result("declined")
        sk0 = str(intent.get("surface_key") or "").strip()
        sk = normalize_trunk_token_to_storage_key(et, sk0) or sk0
        intent = {"kind": "text_append", "surface_key": sk, "value": intent["value"]}

    row = resolve_direct_surface_action(parsed=intent, entity_id=eid, entity_type=et, context=context)
    if not row:
        _apply_lane_a_guard(context, intent, "declined")
        return _result("declined")

    out = execute_direct_surface_action(
        row,
        intent,
        context=context,
        user_id=uid,
        entity_id=eid,
        entity_type=et,
    )
    _apply_lane_a_guard(context, intent, str(out.get("status") or "declined"))
    return out


def should_skip_council_for_direct_result(result: dict[str, Any] | None) -> bool:
    return isinstance(result, dict) and result.get("kind") == "direct_ve_action" and result.get(
        "status"
    ) in ("handled", "error")
