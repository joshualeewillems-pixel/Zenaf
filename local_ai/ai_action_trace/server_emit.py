"""
Emit AiActionTrace-shaped records from the API process when no client trace runs.

- Logs one JSON line at INFO on logger ``atria.server_ai_action`` (prefix SERVER_AI_ACTION_TRACE).
- Appends a compact row to ``activity.log`` via ``log_activity_simple`` for durable lineage.

Align fields with ``frontend/src/ai-actions/types.ts`` (AiActionTrace).

Log JSON may include non-TS extensions for ops: ``schema``, ``origin``, and ``user_id`` (signed-in
account id when provided). Consumers that require strict AiActionTrace should strip those keys or
use a tolerant parser.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from local_ai.activity import (
    COORDINATION_ACTIVITY_SOURCE_SERVER_EXECUTION,
    ActivityType,
    log_activity_simple,
)

_logger = logging.getLogger("atria.server_ai_action")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _meta_from_ve_result(result: Any) -> tuple[str | None, str | None]:
    if not isinstance(result, dict):
        return None, None
    mu = result.get("model_used")
    pu = result.get("provider_used")
    return (
        str(mu).strip() if mu is not None and str(mu).strip() else None,
        str(pu).strip() if pu is not None and str(pu).strip() else None,
    )


def enrich_meeting_debug_llm_meta(
    out: dict[str, Any],
    *,
    routing_context: dict[str, Any] | None,
    user_id: str | None,
    mode: str,
) -> None:
    """
    Ensure model_used / provider_used exist for server traces when the extract helper omits them.
    Re-applies the same execution seam as the extract path (scoped context manager) to read routing meta.
    If still missing and the response is not execution-blocked, set explicit 'unknown' (LLM attempted or allowed).

    Future: prefer capturing model_used / provider_used from the original execution path that invoked
    the LLM, instead of re-entering seam resolution here—so trace metadata cannot drift if seam
    logic, cost, or matching with the real run changes.
    """
    if not isinstance(out, dict):
        return
    has_mu = bool(out.get("model_used") and str(out.get("model_used") or "").strip())
    has_pu = bool(out.get("provider_used") and str(out.get("provider_used") or "").strip())
    if has_mu and has_pu:
        return

    from local_ai.vision_execution.meeting_extraction_execution import meeting_execution_seam

    try:
        with meeting_execution_seam(routing_context, mode=mode, user_id=user_id) as meta:
            if isinstance(meta, dict):
                mu = meta.get("model_used")
                pu = meta.get("provider_used")
                if mu is not None and str(mu).strip() and not has_mu:
                    out["model_used"] = str(mu).strip()
                if pu is not None and str(pu).strip() and not has_pu:
                    out["provider_used"] = str(pu).strip()
    except Exception:
        pass

    if bool(out.get("execution_blocked")):
        return
    if not (out.get("model_used") and str(out.get("model_used") or "").strip()):
        out.setdefault("model_used", "unknown")
    if not (out.get("provider_used") and str(out.get("provider_used") or "").strip()):
        out.setdefault("provider_used", "unknown")


def emit_server_ai_action_trace(
    *,
    user_id: str | None,
    surface: str,
    action_kind: str,
    action_intent: str,
    subject_type: str,
    subject_id: str,
    field_key: str | None,
    input_snapshot: str,
    model_used: str | None,
    provider_used: str | None,
    prompt_version: str | None,
    output_summary: str,
    user_outcome: str = "none",
    persist_activity: bool = True,
    trace_id: str | None = None,
) -> str:
    trace_id = (trace_id or "").strip() or str(uuid.uuid4())
    payload: dict[str, Any] = {
        "schema": "atria_ai_action_trace_v1",
        "origin": "server",
        "trace_id": trace_id,
        "surface": surface,
        "action_kind": action_kind,
        "action_intent": action_intent,
        "subject_type": (subject_type or "")[:128],
        "subject_id": (subject_id or "")[:512],
        "field_key": field_key,
        "input_snapshot": (input_snapshot or "")[:8000],
        "model_used": model_used,
        "provider_used": provider_used,
        "prompt_version": prompt_version,
        "output": (output_summary or "")[:12000],
        "user_outcome": user_outcome,
        "created_at": _now_iso(),
    }
    if user_id:
        payload["user_id"] = str(user_id).strip()[:128]

    line = json.dumps(payload, ensure_ascii=False, default=str)
    _logger.info("SERVER_AI_ACTION_TRACE %s", line)

    if persist_activity:
        try:
            act_detail = json.dumps(
                {"trace_id": trace_id, "action_intent": action_intent, "surface": surface},
                ensure_ascii=False,
            )
            if len(act_detail) > 1900:
                act_detail = act_detail[:1900]
            log_activity_simple(
                type=ActivityType.SERVER_AI_ACTION_TRACE.value,
                entity_type=(subject_type or "unknown")[:64],
                entity_id=(subject_id or "unknown")[:256],
                actor=str(user_id).strip() if user_id else "system",
                source=COORDINATION_ACTIVITY_SOURCE_SERVER_EXECUTION,
                detail=act_detail,
            )
        except Exception:
            pass
    return trace_id


def trace_core_profile_llm_route(
    *,
    user_id: str,
    profile_id: str,
    action_intent: str,
    result: Any,
    turns_n: int,
    notes_len: int,
) -> None:
    model_used, provider_used = _meta_from_ve_result(result)
    if isinstance(result, dict):
        if action_intent == "core_profile_reconcile":
            proposed = result.get("proposed")
            out_obj: dict[str, Any] = {
                "has_proposed": proposed is not None,
                "execution_blocked": bool(result.get("execution_blocked")),
            }
            if result.get("exception"):
                out_obj["route_exception"] = True
            err = result.get("error")
            if err is not None:
                out_obj["error"] = str(err)[:400]
        elif action_intent == "core_profile_conversation":
            reply = result.get("reply")
            out_obj = {
                "reply_char_len": len(str(reply or "")),
                "execution_blocked": bool(result.get("execution_blocked")),
                "learning_record_id": result.get("learning_record_id"),
            }
            if result.get("exception"):
                out_obj["route_exception"] = True
            err = result.get("error")
            if err is not None:
                out_obj["error"] = str(err)[:400]
        else:
            out_obj = {"keys": list(result.keys())[:20]}
        out = json.dumps(out_obj, ensure_ascii=False, default=str)
    else:
        out = json.dumps({"type": type(result).__name__}, ensure_ascii=False)

    # Match frontend/src/vision-execution/coreProfileTrace.ts (emitCoreProfile*Trace).
    if action_intent == "core_profile_conversation":
        action_kind = "suggestion_batch"
        prompt_version = "core_profile_conversation_v1"
    else:
        action_kind = "structured_evaluation"
        prompt_version = "core_profile_reconcile_v1"

    emit_server_ai_action_trace(
        user_id=user_id,
        surface="core_profile",
        action_kind=action_kind,
        action_intent=action_intent,
        subject_type="core_profile",
        subject_id=profile_id,
        field_key=None,
        input_snapshot=f"profile_id={profile_id}\nconversation_turns_n={turns_n}\nraw_notes_len={notes_len}",
        model_used=model_used,
        provider_used=provider_used,
        prompt_version=prompt_version,
        output_summary=out[:12000],
    )


def trace_meeting_debug_extract_route(
    *,
    user_id: str | None,
    action_intent: str,
    result: Any,
    input_snapshot: str,
) -> None:
    trace_id = str(uuid.uuid4())
    subject_id = f"debug:{trace_id}"
    model_used, provider_used = _meta_from_ve_result(result)
    if isinstance(result, dict):
        if action_intent == "meeting_extract_segment_summary":
            out_obj = {
                "topic_len": len(str(result.get("topic") or "")),
                "brief_summary_len": len(str(result.get("briefSummary") or result.get("brief_summary") or "")),
                "candidate_tasks_n": len(result.get("candidateTasks") or result.get("candidate_tasks") or []),
                "error": (str(result.get("error"))[:300] if result.get("error") else None),
            }
        elif action_intent == "meeting_extract_meeting_segments":
            summaries = result.get("segment_summaries") or []
            out_obj = {
                "segment_summaries_n": len(summaries) if isinstance(summaries, list) else 0,
                "execution_blocked": bool(result.get("execution_blocked")),
                "error": (str(result.get("error"))[:300] if result.get("error") else None),
            }
        elif action_intent == "meeting_extract_meeting_synthesis":
            out_obj = {
                "ideas_n": len(result.get("ideas") or []),
                "initiatives_n": len(result.get("initiatives") or []),
                "tasks_n": len(result.get("tasks") or []),
                "projects_n": len(result.get("projects") or []),
                "execution_blocked": bool(result.get("execution_blocked")),
                "error": (str(result.get("error"))[:300] if result.get("error") else None),
            }
        else:
            out_obj = {"keys": list(result.keys())[:24]}
        out = json.dumps(out_obj, ensure_ascii=False, default=str)
    else:
        out = json.dumps({"type": type(result).__name__}, ensure_ascii=False)

    emit_server_ai_action_trace(
        user_id=user_id,
        surface="meeting_extraction",
        action_kind="suggestion_batch",
        action_intent=action_intent,
        subject_type="meeting_capture_debug",
        subject_id=subject_id[:512],
        field_key=None,
        input_snapshot=input_snapshot[:8000],
        model_used=model_used,
        provider_used=provider_used,
        prompt_version=f"server_{action_intent}_v1",
        output_summary=out[:12000],
        trace_id=trace_id,
    )
