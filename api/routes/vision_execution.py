"""
Vision → Execution Engine API. Separate from /run and file sorter.
Prefix: /vision-execution. All CRUD via local_ai.vision_execution.service.
Signals (Layer 1) via local_ai.signals.
"""
import json
import logging
from typing import Any, Callable, TypeVar

from fastapi import APIRouter, Body, HTTPException, Query, Depends
from fastapi.responses import Response

logger = logging.getLogger(__name__)

from local_ai.vision_execution import models as M
from local_ai.vision_execution import service as S
from local_ai.vision_execution import storage as VEStorage
from local_ai.signals import service as SigS
from local_ai.signals.models import SignalCreate, SignalUpdate
from api.routes.auth_routes import get_current_user
from local_ai.ai_action_trace.server_emit import (
    enrich_meeting_debug_llm_meta,
    emit_server_ai_action_trace,
    trace_core_profile_llm_route,
    trace_meeting_debug_extract_route,
)

router = APIRouter(prefix="/vision-execution", tags=["vision-execution"])

_R = TypeVar("_R")
_PERMISSION_BEHAVIORAL_TRACKING = "behavioral_tracking"
_PERMISSION_PERSONALIZATION = "personalization"
_PERMISSION_PROFILE_LEARNING = "profile_learning"
_PERMISSION_ANALYTICS = "analytics_product_improvement"
_PERMISSION_ASPIRATION_STORE = "aspiration_store_explicit"
_PERMISSION_ASPIRATION_INFER = "aspiration_infer_suggestions"
_PERMISSION_ASPIRATION_USE = "aspiration_use_in_guidance"


def _require_user_permission(current_user: dict, permission_key: str, *, detail: str) -> None:
    from local_ai.vision_execution.storage import user_permission_enabled

    if not user_permission_enabled(current_user["id"], permission_key):
        raise HTTPException(status_code=403, detail=detail)


def _extract_routing_context(body: dict | None) -> dict | None:
    if not isinstance(body, dict):
        return None
    rc = body.get("routing_context")
    if not isinstance(rc, dict):
        rc = body.get("routingContext")
    return rc if isinstance(rc, dict) else None


def _log_core_profile_path_param(*, route: str, user_id: str, profile_id: str) -> None:
    """``profile_id`` in URL path — resource identity (not optional override). Log at DEBUG to avoid noise."""
    logger.debug(
        "core_profile.profile_id_usage classification=necessary_resource_path route=%s user_id=%s profile_id=%s",
        route,
        user_id,
        profile_id,
    )


def _merge_client_correlation_id(body: dict | None, result: Any) -> None:
    """Echo optional client_correlation_id / clientCorrelationId for bulk suggest correlation (max 200 chars)."""
    if not isinstance(body, dict) or not isinstance(result, dict):
        return
    cid = body.get("client_correlation_id")
    if cid is None:
        cid = body.get("clientCorrelationId")
    if cid is None:
        return
    s = str(cid).strip()
    if s:
        result["client_correlation_id"] = s[:200]


def _normalize_ve_candidate_inputs(body: dict) -> tuple[dict[str, Any], dict[str, Any], str | None]:
    """Shared candidate + workspace mirror for placement and presort routes."""
    candidate = body.get("candidate") if isinstance(body.get("candidate"), dict) else {}
    existing = body.get("existing_entities")
    if not isinstance(existing, dict):
        existing = body.get("existingEntities")
    if not isinstance(existing, dict):
        existing = {}
    ctx = body.get("context")
    context_str = ctx.strip() if isinstance(ctx, str) else None
    return candidate, existing, context_str


def _resolve_active_placement_profile(
    body: dict | None, user_id: str, *, route: str | None = None
) -> dict[str, Any] | None:
    """Server-loaded core profile by id wins; else optional client ``active_profile`` if it carries metadata."""
    if not isinstance(body, dict):
        return None
    pid = body.get("profile_id") or body.get("profileId")
    if pid is not None and str(pid).strip():
        pid_s = str(pid).strip()
        row = S.get_core_profile(pid_s, user_id)
        if isinstance(row, dict):
            if route:
                logger.info(
                    "core_profile.profile_id_usage classification=placement_body_override route=%s user_id=%s profile_id=%s",
                    route,
                    user_id,
                    pid_s,
                )
            return row
    ap = body.get("active_profile") or body.get("activeProfile")
    if isinstance(ap, dict):
        from local_ai.vision_execution.candidate_placement_suggest import profile_has_output_metadata

        if profile_has_output_metadata(ap):
            return ap
    uid = (user_id or "").strip()
    if uid:
        canonical = S.canonical_core_profile_for_user(uid)
        if isinstance(canonical, dict):
            if route:
                logger.info(
                    "core_profile.profile_id_usage classification=canonical_fallback route=%s user_id=%s",
                    route,
                    uid,
                )
            return canonical
    return None


def _run_ve_llm_with_routing(
    *,
    mode: str,
    body: dict | None,
    compute: Callable[[bool, dict[str, Any]], _R],
    user_id: str | None = None,
) -> _R:
    """
    When ``body.routing_context`` is present, apply the same seam as ``POST /run``
    (supported providers: ollama, openai only). Pass ``use_execution_seam`` and ``exec_meta``
    into ``compute`` so evaluate paths can branch on ``provider_used`` / ``action_intent``.
    """
    from local_ai.execution_policy.run_context import end_execution_routing
    from local_ai.execution_policy.seam_routing import apply_seam_routing
    from local_ai.llm.execution_principal import execution_principal_from_legacy_user_id, principal_for_vision_execution_user

    rc = _extract_routing_context(body)
    ve_principal = (
        principal_for_vision_execution_user(user_id)
        if user_id
        else execution_principal_from_legacy_user_id(None)
    )
    teardown, meta = apply_seam_routing(
        mode=mode,
        routing_context=rc,
        principal=ve_principal,
    )
    use_seam = rc is not None
    try:
        if meta.get("execution_blocked"):
            err: dict[str, Any] = {
                "error": meta.get("error_detail", "Execution blocked"),
                "execution_blocked": True,
                "model_used": meta.get("model_used"),
                "provider_used": meta.get("provider_used"),
            }
            pbr = meta.get("privacy_block_reason")
            if pbr:
                err["privacy_block_reason"] = pbr
            return err  # type: ignore[return-value]
        result = compute(use_seam, meta)
        if use_seam and isinstance(result, dict):
            # Truthful routing metadata for support/debug on both success and LLM/validation errors.
            mu = meta.get("model_used")
            pu = meta.get("provider_used")
            if mu is not None:
                result.setdefault("model_used", mu)
            if pu is not None:
                result.setdefault("provider_used", pu)
        return result
    finally:
        end_execution_routing(teardown)


def _emit_ve_server_trace(
    *,
    user_id: str,
    action_intent: str,
    subject_type: str,
    subject_id: str,
    field_key: str | None,
    input_snapshot: str,
    result: Any,
    action_kind: str = "structured_evaluation",
    prompt_version: str | None = None,
) -> None:
    """One server AiActionTrace line + activity row for Vision Execution LLM routes (non–core-profile)."""
    if isinstance(result, dict):
        mu = result.get("model_used")
        pu = result.get("provider_used")
        model_used = str(mu).strip() if mu is not None and str(mu).strip() else None
        provider_used = str(pu).strip() if pu is not None and str(pu).strip() else None
        err = result.get("error")
        out_obj: dict[str, Any] = {
            "execution_blocked": bool(result.get("execution_blocked")),
            "keys": list(result.keys())[:24],
        }
        if err is not None:
            out_obj["error"] = str(err)[:400]
        out = json.dumps(out_obj, ensure_ascii=False, default=str)
    else:
        model_used = None
        provider_used = None
        out = json.dumps({"type": type(result).__name__}, ensure_ascii=False)

    pv = prompt_version or f"ve_{action_intent}_v1"
    try:
        emit_server_ai_action_trace(
            user_id=user_id,
            surface="vision_execution",
            action_kind=action_kind,
            action_intent=action_intent,
            subject_type=subject_type,
            subject_id=subject_id,
            field_key=field_key,
            input_snapshot=input_snapshot[:8000],
            model_used=model_used,
            provider_used=provider_used,
            prompt_version=pv,
            output_summary=out[:12000],
        )
    except Exception:
        logger.warning("server_ai_trace %s emission failed", action_intent, exc_info=True)


# --- Council workspace (server-owned perspective agents when signed in) ---
@router.get("/council-workspace/perspectives")
def get_council_workspace_perspectives(current_user: dict = Depends(get_current_user)):
    row = VEStorage.get_user_council_workspace(current_user["id"])
    if row is None:
        return {"row_exists": False, "perspectives": [], "updated_at": None}
    try:
        data = json.loads(row["perspectives_json"] or "[]")
    except json.JSONDecodeError:
        data = []
    if not isinstance(data, list):
        data = []
    return {"row_exists": True, "perspectives": data, "updated_at": row["updated_at"]}


@router.put("/council-workspace/perspectives")
def put_council_workspace_perspectives(
    body: M.CouncilWorkspacePerspectivesPut,
    current_user: dict = Depends(get_current_user),
):
    try:
        out = VEStorage.upsert_user_council_workspace(current_user["id"], body.perspectives)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {"ok": True, "updated_at": out["updated_at"]}


# --- Core profiles ---
@router.get("/core-profiles")
def list_core_profiles(current_user: dict = Depends(get_current_user)):
    rows = S.list_core_profiles(current_user["id"])
    canon = S.canonical_core_profile_for_user(current_user["id"])
    cid = canon.get("id") if isinstance(canon, dict) else None
    out: list[dict[str, Any]] = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        d = dict(r)
        d["is_canonical"] = bool(cid and r.get("id") == cid)
        out.append(d)
    return out


@router.get("/core-profiles/{profile_id}")
def get_core_profile(profile_id: str, current_user: dict = Depends(get_current_user)):
    out = S.get_core_profile(profile_id, current_user["id"])
    if out is None:
        raise HTTPException(status_code=404, detail="Core profile not found")
    _log_core_profile_path_param(
        route="GET /vision-execution/core-profiles/{profile_id}",
        user_id=current_user["id"],
        profile_id=profile_id,
    )
    canon = S.canonical_core_profile_for_user(current_user["id"])
    cid = canon.get("id") if isinstance(canon, dict) else None
    d = dict(out)
    d["is_canonical"] = bool(cid and out.get("id") == cid)
    return d


@router.get("/node-vitality")
def list_node_vitality(
    current_user: dict = Depends(get_current_user),
    entity_type: str | None = Query(None, description="Optional filter by VE entity type (e.g. idea, project)."),
):
    from local_ai.vision_execution.storage import list_node_vitality_for_user

    rows = list_node_vitality_for_user(current_user["id"], entity_type=entity_type, limit=500)
    vitality: list[dict[str, Any]] = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        vitality.append(
            {
                "entity_type": r.get("entity_type"),
                "entity_id": r.get("entity_id"),
                "water": float(r.get("water") or 0.0),
                "soil": float(r.get("soil") or 0.0),
                "fruit": float(r.get("fruit") or 0.0),
                "staleness_days": float(r.get("staleness_days") or 0.0),
                "last_assessed_at": r.get("last_assessed_at"),
                "rules_version": str(r.get("rules_version") or "v1"),
            }
        )
    return {"vitality": vitality}


@router.post("/core-profiles")
def create_core_profile(body: M.CoreProfileCreate, current_user: dict = Depends(get_current_user)):
    return S.create_core_profile(body, current_user["id"])


@router.patch("/core-profiles/{profile_id}")
def update_core_profile(profile_id: str, body: M.CoreProfileUpdate, current_user: dict = Depends(get_current_user)):
    out = S.update_core_profile(profile_id, body, current_user["id"])
    if out is None:
        raise HTTPException(status_code=404, detail="Core profile not found")
    _log_core_profile_path_param(
        route="PATCH /vision-execution/core-profiles/{profile_id}",
        user_id=current_user["id"],
        profile_id=profile_id,
    )
    return out


@router.patch("/core-profiles/{profile_id}/set-primary")
def set_core_profile_primary_route(profile_id: str, current_user: dict = Depends(get_current_user)):
    """Mark one core profile as canonical for this user; clears is_primary on others."""
    out = S.set_core_profile_primary(profile_id, current_user["id"])
    if out is None:
        raise HTTPException(status_code=404, detail="Core profile not found")
    _log_core_profile_path_param(
        route="PATCH /vision-execution/core-profiles/{profile_id}/set-primary",
        user_id=current_user["id"],
        profile_id=profile_id,
    )
    return out


@router.post("/core-profiles/{profile_id}/reconcile")
def reconcile_core_profile(profile_id: str, body: dict = Body(...), current_user: dict = Depends(get_current_user)):
    """Propose updated structured profile from raw_notes + conversation. Returns { proposed } or { error }. Does not persist."""
    if S.get_core_profile(profile_id, current_user["id"]) is None:
        raise HTTPException(status_code=404, detail="Core profile not found")
    _log_core_profile_path_param(
        route="POST /vision-execution/core-profiles/{profile_id}/reconcile",
        user_id=current_user["id"],
        profile_id=profile_id,
    )
    from local_ai.vision_execution.core_profile_reconcile import reconcile

    conversation_turns = body.get("conversation_turns")
    if not isinstance(conversation_turns, list):
        conversation_turns = []
    current_structured = body.get("current_structured")
    if not isinstance(current_structured, dict):
        current_structured = {}
    rc = _extract_routing_context(body)

    enriched_notes = body.get("raw_notes") or ""

    council_evidence_block = ""
    if body.get("include_recent_council_evidence", False):
        try:
            from local_ai.vision_execution.storage import list_recent_council_stream_runs

            recent_runs = list_recent_council_stream_runs(
                user_id=current_user["id"],
                limit=5,
            )
            if recent_runs:
                lines = ["\n\n--- RECENT COUNCIL CONTEXT (supplemental, treat as tertiary evidence) ---"]
                for run in recent_runs:
                    artifact = run.get("artifact", {})
                    question = artifact.get("question", "")
                    synthesis = artifact.get("synthesis_text", "")
                    created = run.get("created_at", "")
                    subject = artifact.get("subject") or {}
                    subject_line = ""
                    if subject.get("entity_type") and subject.get("entity_id"):
                        subject_line = f" (re: {subject['entity_type']} {subject.get('title') or subject['entity_id']})"
                    if question or synthesis:
                        lines.append(f"\n[{created[:10]}{subject_line}]")
                    if question:
                        lines.append(f"Q: {question[:300]}")
                    if synthesis:
                        lines.append(f"Council: {synthesis[:600]}")
                council_evidence_block = "\n".join(lines)
        except Exception:
            logger.warning(
                "Failed to load council evidence for reconcile",
                exc_info=True,
            )

    if council_evidence_block:
        enriched_notes = enriched_notes + council_evidence_block

    def _compute(use_seam: bool, exec_meta: dict[str, Any]):
        return reconcile(
            raw_notes=enriched_notes,
            conversation_turns=conversation_turns,
            current_structured=current_structured,
            routing_context=rc,
            use_execution_seam=use_seam,
            exec_meta=exec_meta,
            profile_id=profile_id,
            user_id=current_user["id"],
        )

    result: Any = None
    route_exc: Exception | None = None
    try:
        result = _run_ve_llm_with_routing(
            mode="core_profile_reconcile", body=body, compute=_compute, user_id=current_user["id"]
        )
    except Exception as e:
        route_exc = e
        result = {"error": str(e)[:800], "exception": True}
    try:
        trace_core_profile_llm_route(
            user_id=current_user["id"],
            profile_id=profile_id,
            action_intent="core_profile_reconcile",
            result=result,
            turns_n=len(conversation_turns),
            notes_len=len(str(enriched_notes or "")),
        )
    except Exception:
        logger.warning("server_ai_trace reconcile emission failed", exc_info=True)
    if route_exc is not None:
        raise route_exc
    return result


@router.post("/core-profiles/{profile_id}/conversation")
def core_profile_conversation(profile_id: str, body: dict = Body(...), current_user: dict = Depends(get_current_user)):
    """Minimal exploratory assistant for Core Profile conversation. Returns one assistant reply; no persistence."""
    if S.get_core_profile(profile_id, current_user["id"]) is None:
        raise HTTPException(status_code=404, detail="Core profile not found")
    _log_core_profile_path_param(
        route="POST /vision-execution/core-profiles/{profile_id}/conversation",
        user_id=current_user["id"],
        profile_id=profile_id,
    )
    from local_ai.vision_execution.core_profile_conversation import converse

    raw_notes = body.get("raw_notes") or ""
    conversation_turns = body.get("conversation_turns")
    if not isinstance(conversation_turns, list):
        conversation_turns = []
    current_structured = body.get("current_structured")
    if not isinstance(current_structured, dict):
        current_structured = {}
    rc = _extract_routing_context(body)

    def _compute(use_seam: bool, exec_meta: dict[str, Any]):
        return converse(
            raw_notes=raw_notes,
            conversation_turns=conversation_turns,
            current_structured=current_structured,
            routing_context=rc,
            use_execution_seam=use_seam,
            exec_meta=exec_meta,
            user_id=current_user["id"],
        )

    result: Any = None
    route_exc: Exception | None = None
    try:
        result = _run_ve_llm_with_routing(
            mode="core_profile_conversation", body=body, compute=_compute, user_id=current_user["id"]
        )
    except Exception as e:
        route_exc = e
        result = {"error": str(e)[:800], "exception": True}
    try:
        trace_core_profile_llm_route(
            user_id=current_user["id"],
            profile_id=profile_id,
            action_intent="core_profile_conversation",
            result=result,
            turns_n=len(conversation_turns),
            notes_len=len(str(raw_notes or "")),
        )
    except Exception:
        logger.warning("server_ai_trace conversation emission failed", exc_info=True)
    if route_exc is not None:
        raise route_exc
    return result


@router.post("/learning-records/user-outcome")
def post_learning_record_user_outcome(body: dict = Body(...), current_user: dict = Depends(get_current_user)):
    """
    Attach ``user_outcome`` to an in-memory ``LearningRecord`` (general/structured tiers).

    Correlate via ``learning_record_id`` returned from e.g. Core Profile conversation when
    ``routing_context`` + execution seam are active.
    """
    _require_user_permission(
        current_user,
        _PERMISSION_ANALYTICS,
        detail="Permission required: optional analytics / product improvement signals.",
    )
    from local_ai.delegation.learning_capture import update_learning_record_user_outcome

    rid = body.get("learning_record_id")
    if not isinstance(rid, str) or not rid.strip():
        raise HTTPException(status_code=400, detail="learning_record_id is required")
    outcome = body.get("user_outcome")
    if not isinstance(outcome, str) or not outcome.strip():
        raise HTTPException(status_code=400, detail="user_outcome is required")
    diff = body.get("outcome_diff_summary")
    diff_s = diff.strip() if isinstance(diff, str) else None
    pm = body.get("privacy_mode")
    pm_s = pm.strip() if isinstance(pm, str) and pm.strip() else None
    ok = update_learning_record_user_outcome(
        rid.strip(),
        outcome.strip(),
        outcome_diff_summary=diff_s,
        privacy_mode=pm_s,
    )
    if not ok:
        raise HTTPException(status_code=404, detail="learning_record_id not found or invalid user_outcome")
    return {"ok": True}


@router.post("/resonance-ratings")
def post_resonance_rating(body: dict = Body(...), current_user: dict = Depends(get_current_user)):
    _require_user_permission(
        current_user,
        _PERMISSION_BEHAVIORAL_TRACKING,
        detail="Permission required: behavioral tracking.",
    )
    from local_ai.vision_execution.storage import append_resonance_rating

    et = body.get("entity_type")
    eid = body.get("entity_id")
    score = body.get("score")
    response_id = body.get("response_id")
    seat_id = body.get("seat_id")
    context_kind = body.get("context_kind")
    subject_perspective_id = body.get("subject_perspective_id")

    if not isinstance(et, str) or not et.strip():
        raise HTTPException(status_code=400, detail="entity_type is required")
    if not isinstance(eid, str) or not eid.strip():
        raise HTTPException(status_code=400, detail="entity_id is required")
    if not isinstance(response_id, str) or not response_id.strip():
        raise HTTPException(status_code=400, detail="response_id is required")
    if not isinstance(context_kind, str) or not context_kind.strip():
        raise HTTPException(status_code=400, detail="context_kind is required")
    try:
        sc = float(score)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="score must be a number between 0 and 1")
    seat_s = seat_id.strip() if isinstance(seat_id, str) and seat_id.strip() else None
    subj = (
        subject_perspective_id.strip()
        if isinstance(subject_perspective_id, str) and subject_perspective_id.strip()
        else None
    )
    try:
        jid = append_resonance_rating(
            user_id=current_user["id"],
            entity_type=et.strip(),
            entity_id=eid.strip(),
            score=sc,
            response_id=response_id.strip(),
            seat_id=seat_s,
            context_kind=context_kind.strip(),
            subject_perspective_id=subj,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {"id": jid}


@router.get("/resonance-patterns")
def get_resonance_patterns(
    current_user: dict = Depends(get_current_user),
    context_kind: str | None = Query(None),
    seat_id: str | None = Query(None),
    limit: int = Query(100, ge=1, le=500),
):
    _require_user_permission(
        current_user,
        _PERMISSION_PERSONALIZATION,
        detail="Permission required: personalization / adaptive responses.",
    )
    from local_ai.vision_execution.storage import get_resonance_pattern

    return get_resonance_pattern(
        current_user["id"],
        context_kind=context_kind,
        seat_id=seat_id,
        limit=limit,
    )


_LEARNING_EXPORT_DISABLED_DETAIL = (
    "Learning export/inspect is disabled. Set environment variable ZENAF_LEARNING_EXPORT_ENABLED=1 "
    "(or true/yes/on) to enable read-only buffer export for operators."
)


@router.get("/learning-records/stats")
def learning_records_stats(current_user: dict = Depends(get_current_user)):
    """Aggregate counts over the in-memory buffer (no row bodies). Gated by ``ZENAF_LEARNING_EXPORT_ENABLED``."""
    _ = current_user
    from local_ai.delegation import learning_capture as LC

    if not LC.learning_export_enabled():
        raise HTTPException(status_code=403, detail=_LEARNING_EXPORT_DISABLED_DETAIL)
    return LC.learning_buffer_aggregate_stats()


@router.get("/learning-records/inspect")
def learning_records_inspect(
    current_user: dict = Depends(get_current_user),
    offset: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    order: str = Query("asc", pattern="^(asc|desc)$"),
):
    """Paginated JSON page of stored records (already redacted at capture time)."""
    _ = current_user
    from local_ai.delegation import learning_capture as LC

    if not LC.learning_export_enabled():
        raise HTTPException(status_code=403, detail=_LEARNING_EXPORT_DISABLED_DETAIL)
    return LC.inspect_learning_buffer(offset=offset, limit=limit, order=order)  # type: ignore[arg-type]


@router.get("/learning-records/export")
def learning_records_export(
    current_user: dict = Depends(get_current_user),
    export_format: str = Query("jsonl", alias="format", pattern="^(json|jsonl)$"),
    offset: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    order: str = Query("asc", pattern="^(asc|desc)$"),
):
    """
    Download a slice of the buffer as **JSON Lines** (default) or a single JSON document
    (same fields as ``/inspect``). Requires auth + ``ZENAF_LEARNING_EXPORT_ENABLED``.
    """
    _ = current_user
    from local_ai.delegation import learning_capture as LC

    if not LC.learning_export_enabled():
        raise HTTPException(status_code=403, detail=_LEARNING_EXPORT_DISABLED_DETAIL)
    if export_format == "jsonl":
        body, _total = LC.export_learning_records_jsonl(offset=offset, limit=limit, order=order)  # type: ignore[arg-type]
        return Response(
            content=body.encode("utf-8"),
            media_type="application/x-ndjson; charset=utf-8",
            headers={"Content-Disposition": 'attachment; filename="zenaf_learning_export.jsonl"'},
        )
    return LC.inspect_learning_buffer(offset=offset, limit=limit, order=order)  # type: ignore[arg-type]


# --- Ideas ---
@router.get("/ideas")
def list_ideas(current_user: dict = Depends(get_current_user)):
    return S.list_ideas(current_user["id"])


@router.get("/ideas/{idea_id}")
def get_idea(idea_id: str, current_user: dict = Depends(get_current_user)):
    out = S.get_idea(idea_id, current_user["id"])
    if out is None:
        raise HTTPException(status_code=404, detail="Idea not found")
    return out


@router.post("/ideas")
def create_idea(body: M.IdeaCreate, current_user: dict = Depends(get_current_user)):
    try:
        return S.create_idea(body, current_user["id"])
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.patch("/ideas/{idea_id}")
def update_idea(idea_id: str, body: M.IdeaUpdate, current_user: dict = Depends(get_current_user)):
    try:
        out = S.update_idea(idea_id, body, current_user["id"])
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if out is None:
        raise HTTPException(status_code=404, detail="Idea not found")
    return out


@router.delete("/ideas/{idea_id}")
def delete_idea(idea_id: str, current_user: dict = Depends(get_current_user)):
    if not S.delete_idea(idea_id, current_user["id"]):
        raise HTTPException(status_code=404, detail="Idea not found")
    return {"ok": True}


@router.post("/ideas/{idea_id}/evaluate")
def evaluate_idea(idea_id: str, body: dict | None = Body(None), current_user: dict = Depends(get_current_user)):
    """Propose AI-suggested values for this idea (MVP contract). Body may include relaxed: true for partial/less-strict evaluation. Returns proposal only; no write."""
    logger.info("[idea-eval] ROUTE ENTERED idea_id=%s", idea_id)
    relaxed = isinstance(body, dict) and body.get("relaxed") is True
    logger.info("[idea-eval] route hit idea_id=%s relaxed=%s body=%s", idea_id, relaxed, body)
    idea = S.get_idea(idea_id, current_user["id"])
    if idea is None:
        raise HTTPException(status_code=404, detail="Idea not found")
    title = idea.get("title") or ""
    has_summary = bool((idea.get("summary") or "").strip())
    has_description = bool((idea.get("description") or "").strip())
    brief = (idea.get("summary") or "").strip() or (idea.get("description") or "").strip()
    logger.info("[idea-eval] loaded idea title=%r has_summary=%s has_description=%s brief_len=%s", title, has_summary, has_description, len(brief))
    from local_ai.vision_execution.idea_evaluate import evaluate_idea as _eval_idea
    core_summary = None
    p = S.canonical_core_profile_for_user(current_user["id"])
    if p:
        from local_ai.vision_execution.core_profile_context import build_core_profile_summary

        core_summary = build_core_profile_summary(p)

    rc = _extract_routing_context(body)

    def _compute(use_seam: bool, exec_meta: dict[str, Any]):
        return _eval_idea(
            title=title,
            brief=brief,
            core_profile_summary=core_summary,
            relaxed=relaxed,
            user_id=current_user["id"],
            use_execution_seam=use_seam,
            routing_context=rc,
            exec_meta=exec_meta,
        )

    result = _run_ve_llm_with_routing(
        mode="idea_evaluate", body=body, compute=_compute, user_id=current_user["id"]
    )
    _emit_ve_server_trace(
        user_id=current_user["id"],
        action_intent="idea_evaluate",
        subject_type="idea",
        subject_id=idea_id,
        field_key=None,
        input_snapshot=f"idea_id={idea_id}\nrelaxed={relaxed}\nbrief_len={len(brief)}",
        result=result,
    )
    if "error" in result:
        logger.info("[idea-eval] route returning error: %s", result.get("error", "")[:200])
    else:
        logger.info("[idea-eval] route returning success contract keys=%s", list(result.keys()))
    return result


# --- Initiatives ---
@router.get("/initiatives")
def list_initiatives(current_user: dict = Depends(get_current_user)):
    return S.list_initiatives(current_user["id"])


@router.get("/initiatives/{initiative_id}")
def get_initiative(initiative_id: str, current_user: dict = Depends(get_current_user)):
    out = S.get_initiative(initiative_id, current_user["id"])
    if out is None:
        raise HTTPException(status_code=404, detail="Initiative not found")
    return out


@router.post("/initiatives")
def create_initiative(body: M.InitiativeCreate, current_user: dict = Depends(get_current_user)):
    try:
        return S.create_initiative(body, current_user["id"])
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.patch("/initiatives/{initiative_id}")
def update_initiative(initiative_id: str, body: M.InitiativeUpdate, current_user: dict = Depends(get_current_user)):
    try:
        out = S.update_initiative(initiative_id, body, current_user["id"])
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if out is None:
        raise HTTPException(status_code=404, detail="Initiative not found")
    return out


@router.post("/initiatives/{initiative_id}/evaluate")
def evaluate_initiative(
    initiative_id: str,
    body: dict | None = Body(None),
    current_user: dict = Depends(get_current_user),
):
    """Propose AI-suggested values for this initiative. Returns proposal only; no write. User must Apply to save."""
    init = S.get_initiative(initiative_id, current_user["id"])
    if init is None:
        raise HTTPException(status_code=404, detail="Initiative not found")
    from local_ai.vision_execution.initiative_evaluate import evaluate_initiative as _eval
    core_summary = None
    p = S.canonical_core_profile_for_user(current_user["id"])
    if p:
        from local_ai.vision_execution.core_profile_context import build_core_profile_summary

        core_summary = build_core_profile_summary(p)

    rc = _extract_routing_context(body)

    def _compute(use_seam: bool, exec_meta: dict[str, Any]):
        return _eval(
            title=init.get("title") or "",
            brief=init.get("brief") or "",
            core_profile_summary=core_summary,
            user_id=current_user["id"],
            use_execution_seam=use_seam,
            routing_payload=rc if use_seam else None,
            exec_meta=exec_meta,
            initiative_id=initiative_id,
        )

    result = _run_ve_llm_with_routing(
        mode="initiative_evaluate", body=body, compute=_compute, user_id=current_user["id"]
    )
    _emit_ve_server_trace(
        user_id=current_user["id"],
        action_intent="initiative_evaluate",
        subject_type="initiative",
        subject_id=initiative_id,
        field_key=None,
        input_snapshot=f"initiative_id={initiative_id}\nbrief_len={len(str(init.get('brief') or ''))}",
        result=result,
    )
    return result


def _http_from_execution_value_error(e: ValueError) -> HTTPException:
    msg = str(e)
    if msg == "EXECUTION_STEPS_EXIST":
        return HTTPException(
            status_code=409,
            detail=(
                "Execution steps already exist for this scope. "
                "Pass replace=true on materialize to replace all steps, or add steps individually."
            ),
        )
    return HTTPException(status_code=400, detail=msg)


@router.get("/initiatives/{initiative_id}/execution-steps")
def list_initiative_execution_steps(initiative_id: str, current_user: dict = Depends(get_current_user)):
    if S.get_initiative(initiative_id, current_user["id"]) is None:
        raise HTTPException(status_code=404, detail="Initiative not found")
    return S.list_execution_steps_for_initiative(initiative_id, current_user["id"])


@router.post("/initiatives/{initiative_id}/execution-steps")
def create_initiative_execution_step(
    initiative_id: str, body: M.ExecutionStepCreate, current_user: dict = Depends(get_current_user)
):
    if S.get_initiative(initiative_id, current_user["id"]) is None:
        raise HTTPException(status_code=404, detail="Initiative not found")
    try:
        return S.create_execution_step_for_initiative(initiative_id, body, current_user["id"])
    except ValueError as e:
        raise _http_from_execution_value_error(e) from e


@router.post("/initiatives/{initiative_id}/execution-steps/materialize")
def materialize_initiative_execution_steps(
    initiative_id: str, body: M.ExecutionStepMaterializeBody, current_user: dict = Depends(get_current_user)
):
    if S.get_initiative(initiative_id, current_user["id"]) is None:
        raise HTTPException(status_code=404, detail="Initiative not found")
    try:
        return S.materialize_execution_steps_for_initiative(initiative_id, body, current_user["id"])
    except ValueError as e:
        raise _http_from_execution_value_error(e) from e


@router.post("/initiatives/{initiative_id}/execution-steps/reorder")
def reorder_initiative_execution_steps(
    initiative_id: str, body: M.ExecutionStepReorderBody, current_user: dict = Depends(get_current_user)
):
    if S.get_initiative(initiative_id, current_user["id"]) is None:
        raise HTTPException(status_code=404, detail="Initiative not found")
    try:
        return S.reorder_execution_steps_for_initiative(initiative_id, body, current_user["id"])
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.get("/projects/{project_id}/execution-steps")
def list_project_execution_steps(project_id: str, current_user: dict = Depends(get_current_user)):
    if S.get_project(project_id, current_user["id"]) is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return S.list_execution_steps_for_project(project_id, current_user["id"])


@router.post("/projects/{project_id}/execution-steps")
def create_project_execution_step(
    project_id: str, body: M.ExecutionStepCreate, current_user: dict = Depends(get_current_user)
):
    if S.get_project(project_id, current_user["id"]) is None:
        raise HTTPException(status_code=404, detail="Project not found")
    try:
        return S.create_execution_step_for_project(project_id, body, current_user["id"])
    except ValueError as e:
        raise _http_from_execution_value_error(e) from e


@router.post("/projects/{project_id}/execution-steps/materialize")
def materialize_project_execution_steps(
    project_id: str, body: M.ExecutionStepMaterializeBody, current_user: dict = Depends(get_current_user)
):
    if S.get_project(project_id, current_user["id"]) is None:
        raise HTTPException(status_code=404, detail="Project not found")
    try:
        return S.materialize_execution_steps_for_project(project_id, body, current_user["id"])
    except ValueError as e:
        raise _http_from_execution_value_error(e) from e


@router.post("/projects/{project_id}/execution-steps/reorder")
def reorder_project_execution_steps(
    project_id: str, body: M.ExecutionStepReorderBody, current_user: dict = Depends(get_current_user)
):
    if S.get_project(project_id, current_user["id"]) is None:
        raise HTTPException(status_code=404, detail="Project not found")
    try:
        return S.reorder_execution_steps_for_project(project_id, body, current_user["id"])
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.patch("/execution-steps/{step_id}")
def patch_execution_step(step_id: str, body: M.ExecutionStepUpdate, current_user: dict = Depends(get_current_user)):
    try:
        out = S.update_execution_step(step_id, body, current_user["id"])
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    if out is None:
        raise HTTPException(status_code=404, detail="Execution step not found")
    return out


@router.delete("/execution-steps/{step_id}")
def delete_execution_step_route(step_id: str, current_user: dict = Depends(get_current_user)):
    if not S.delete_execution_step(step_id, current_user["id"]):
        raise HTTPException(status_code=404, detail="Execution step not found")
    return {"ok": True}


@router.delete("/initiatives/{initiative_id}")
def delete_initiative(initiative_id: str, current_user: dict = Depends(get_current_user)):
    if not S.delete_initiative(initiative_id, current_user["id"]):
        raise HTTPException(status_code=404, detail="Initiative not found")
    return {"ok": True}


# --- Decisions (append-only; for personality learning / decision analysis) ---
@router.post("/decisions")
def create_decision(body: M.DecisionCreate, current_user: dict = Depends(get_current_user)):
    """Record a user decision when profile-learning permission is enabled."""
    _require_user_permission(
        current_user,
        _PERMISSION_PROFILE_LEARNING,
        detail="Permission required: profile learning from usage.",
    )
    payload = body.model_copy(update={"user_id": current_user["id"]})
    return S.create_decision(payload)


@router.get("/decisions")
def list_decisions(
    entity_type: str | None = None,
    entity_id: str | None = None,
    limit: int = 500,
    current_user: dict = Depends(get_current_user),
):
    """List decision records, optionally filtered by entity. For analysis/export."""
    _require_user_permission(
        current_user,
        _PERMISSION_PROFILE_LEARNING,
        detail="Permission required: profile learning from usage.",
    )
    return S.list_decisions(entity_type=entity_type, entity_id=entity_id, limit=limit)


@router.post("/coordination/client-checkpoint")
def coordination_client_checkpoint(
    body: M.CoordinationClientCheckpointCreate, current_user: dict = Depends(get_current_user)
):
    """Log a client-originated coordination checkpoint (``zenaf-client-trace`` activity). Returns ``activity_event_id``."""
    try:
        aid = S.log_coordination_client_checkpoint(current_user["id"], body)
    except ValueError as e:
        msg = str(e)
        if "not found" in msg or "not owned" in msg:
            raise HTTPException(status_code=404, detail=msg) from e
        raise HTTPException(status_code=400, detail=msg) from e
    return {"activity_event_id": aid}


@router.get("/coordination/execution-flow-readings")
def coordination_execution_flow_readings(
    entity_type: str,
    entity_id: str,
    limit: int = 20,
    current_user: dict = Depends(get_current_user),
):
    """Bounded summaries of ``execution_flow_reading`` judgments for an owned entity."""
    try:
        readings = S.list_coordination_execution_flow_readings(
            current_user["id"], entity_type, entity_id, limit=limit
        )
    except ValueError as e:
        msg = str(e)
        if "not found" in msg or "not owned" in msg:
            raise HTTPException(status_code=404, detail=msg) from e
        raise HTTPException(status_code=400, detail=msg) from e
    return {"readings": readings}


# --- Signals (Layer 1 canonical entity; Radar is a view over these) ---
@router.post("/signals")
def create_signals(body: list[SignalCreate]):
    """Bulk create signals (e.g. from meeting extraction, inbox triage)."""
    return SigS.create_signals(body)


@router.get("/signals")
def list_signals(
    status: str | None = Query(None, description="Comma-separated: only these statuses (e.g. new,acknowledged,linked)"),
    status_not: str | None = Query(None, description="Comma-separated: exclude these (e.g. resolved,dismissed)"),
    source: str | None = Query(None, description="Filter by source"),
):
    """List signals with optional filters. Radar uses status_not=resolved,dismissed."""
    status_in = status.split(",") if status else None
    status_not_in = status_not.split(",") if status_not else None
    return SigS.list_signals(status_in=status_in, status_not_in=status_not_in, source=source)


@router.patch("/signals/{signal_id}")
def patch_signal(signal_id: str, body: SignalUpdate):
    """Update signal status and/or linked initiative/project/task."""
    out = SigS.update_signal(signal_id, body)
    if out is None:
        raise HTTPException(status_code=404, detail="Signal not found")
    return out


# --- Radar (orientation + signals view) ---
@router.get("/radar")
def get_radar(current_user: dict = Depends(get_current_user)):
    """Strategic radar: what needs attention (act_now, blocked, overcapacity, unanchored, high_value_stalled, kill_candidates, signals)."""
    return S.get_radar(current_user["id"])


@router.post("/radar/items")
def create_radar_item(body: M.RadarFeedCreate):
    """Deprecated: prefer POST /signals. Add a radar feed item (e.g. meeting-extraction signal)."""
    return S.create_radar_item(body)


# --- Projects ---
@router.get("/projects")
def list_projects(current_user: dict = Depends(get_current_user)):
    return S.list_projects(current_user["id"])


@router.get("/projects/{project_id}")
def get_project(project_id: str, current_user: dict = Depends(get_current_user)):
    out = S.get_project(project_id, current_user["id"])
    if out is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return out


@router.post("/projects/{project_id}/suggested-work")
def project_suggested_work(project_id: str, current_user: dict = Depends(get_current_user)):
    """AI coordination hints (not tasks / not persisted). Returns { suggestions: [{id, kind, text}] } or { error }."""
    uid = current_user["id"]
    proj = S.get_project(project_id, uid)
    if proj is None:
        raise HTTPException(status_code=404, detail="Project not found")
    tasks = S.list_tasks(uid, project_id)
    persons = S.list_persons()
    persons_by_id = {str(p["id"]): str(p.get("name") or p["id"]) for p in persons if p.get("id")}
    from local_ai.vision_execution.project_suggested_work import generate_project_suggested_work

    result = generate_project_suggested_work(
        project=proj,
        tasks=list(tasks) if isinstance(tasks, list) else [],
        persons_by_id=persons_by_id,
        user_id=uid,
    )
    _emit_ve_server_trace(
        user_id=uid,
        action_intent="project_suggested_work",
        subject_type="project",
        subject_id=project_id,
        field_key=None,
        input_snapshot=f"project_id={project_id}\ntasks_n={len(tasks) if isinstance(tasks, list) else 0}",
        result=result,
        action_kind="suggestion_batch",
    )
    return result


@router.post("/projects")
def create_project(body: M.ProjectCreate, current_user: dict = Depends(get_current_user)):
    try:
        return S.create_project(body, current_user["id"])
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.patch("/projects/{project_id}")
def update_project(project_id: str, body: M.ProjectUpdate, current_user: dict = Depends(get_current_user)):
    try:
        out = S.update_project(project_id, body, current_user["id"])
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if out is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return out


@router.delete("/projects/{project_id}")
def delete_project(project_id: str, current_user: dict = Depends(get_current_user)):
    if not S.delete_project(project_id, current_user["id"]):
        raise HTTPException(status_code=404, detail="Project not found")
    return {"ok": True}


# --- Tasks ---
@router.get("/tasks")
def list_tasks(project_id: str | None = None, current_user: dict = Depends(get_current_user)):
    return S.list_tasks(current_user["id"], project_id)


@router.get("/tasks/{task_id}")
def get_task(task_id: str, current_user: dict = Depends(get_current_user)):
    out = S.get_task(task_id, current_user["id"])
    if out is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return out


@router.post("/tasks")
def create_task(body: M.TaskCreate, current_user: dict = Depends(get_current_user)):
    try:
        return S.create_task(body, current_user["id"])
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.patch("/tasks/{task_id}")
def update_task(task_id: str, body: M.TaskUpdate, current_user: dict = Depends(get_current_user)):
    try:
        out = S.update_task(task_id, body, current_user["id"])
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if out is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return out


@router.delete("/tasks/{task_id}")
def delete_task(task_id: str, current_user: dict = Depends(get_current_user)):
    if not S.delete_task(task_id, current_user["id"]):
        raise HTTPException(status_code=404, detail="Task not found")
    return {"ok": True}


# --- Persons ---
@router.get("/persons")
def list_persons():
    return S.list_persons()


@router.get("/persons/{person_id}")
def get_person(person_id: str):
    out = S.get_person(person_id)
    if out is None:
        raise HTTPException(status_code=404, detail="Person not found")
    return out


@router.post("/persons")
def create_person(body: M.PersonCreate):
    return S.create_person(body)


@router.patch("/persons/{person_id}")
def update_person(person_id: str, body: M.PersonUpdate):
    out = S.update_person(person_id, body)
    if out is None:
        raise HTTPException(status_code=404, detail="Person not found")
    return out


@router.delete("/persons/{person_id}")
def delete_person(person_id: str):
    if not S.delete_person(person_id):
        raise HTTPException(status_code=404, detail="Person not found")
    return {"ok": True}


# --- Capacity ---
@router.get("/capacity-profiles")
def list_capacity_profiles(current_user: dict = Depends(get_current_user)):
    return S.list_capacity_profiles(current_user["id"])


@router.get("/capacity-profiles/{person_id}")
def get_capacity_profile(person_id: str, current_user: dict = Depends(get_current_user)):
    out = S.get_capacity_profile(person_id, current_user["id"])
    if out is None:
        raise HTTPException(status_code=404, detail="Capacity profile not found")
    return out


@router.put("/capacity-profiles")
def upsert_capacity_profile(body: M.CapacityProfileUpsert):
    return S.upsert_capacity_profile(body)


# --- Assets ---
@router.get("/assets")
def list_assets():
    return S.list_assets()


@router.get("/assets/{asset_id}")
def get_asset(asset_id: str):
    out = S.get_asset(asset_id)
    if out is None:
        raise HTTPException(status_code=404, detail="Asset not found")
    return out


@router.post("/assets")
def create_asset(body: M.AssetCreate):
    return S.create_asset(body)


@router.patch("/assets/{asset_id}")
def update_asset(asset_id: str, body: M.AssetUpdate):
    out = S.update_asset(asset_id, body)
    if out is None:
        raise HTTPException(status_code=404, detail="Asset not found")
    return out


@router.delete("/assets/{asset_id}")
def delete_asset(asset_id: str):
    if not S.delete_asset(asset_id):
        raise HTTPException(status_code=404, detail="Asset not found")
    return {"ok": True}


# --- Content briefs ---
@router.get("/content-briefs")
def list_content_briefs(current_user: dict = Depends(get_current_user)):
    return S.list_content_briefs(current_user["id"])


@router.get("/content-briefs/{brief_id}")
def get_content_brief(brief_id: str, current_user: dict = Depends(get_current_user)):
    out = S.get_content_brief(brief_id, current_user["id"])
    if out is None:
        raise HTTPException(status_code=404, detail="Content brief not found")
    return out


@router.post("/content-briefs")
def create_content_brief(body: dict = Body(...), current_user: dict = Depends(get_current_user)):
    return S.create_content_brief(body, current_user["id"])


@router.patch("/content-briefs/{brief_id}")
def update_content_brief(brief_id: str, body: dict = Body(...), current_user: dict = Depends(get_current_user)):
    out = S.update_content_brief(brief_id, body, current_user["id"])
    if out is None:
        raise HTTPException(status_code=404, detail="Content brief not found")
    return out


@router.get("/workspace-users")
def list_workspace_users_directory(current_user: dict = Depends(get_current_user)):
    """Other accounts on this workspace (for Send to / inbox addressing)."""
    return S.list_workspace_users_directory(current_user["id"])


@router.get("/workspace-messages")
def list_workspace_messages(
    box: str = Query("inbox", description="inbox or sent"),
    current_user: dict = Depends(get_current_user),
):
    if box not in ("inbox", "sent"):
        raise HTTPException(status_code=400, detail="box must be inbox or sent")
    return S.list_workspace_messages(current_user["id"], box)


@router.get("/workspace-messages/unread-count")
def workspace_messages_unread_count(current_user: dict = Depends(get_current_user)):
    return {"count": S.count_unread_workspace_messages(current_user["id"])}


@router.post("/workspace-messages")
def create_workspace_message(body: M.WorkspaceMessageCreate, current_user: dict = Depends(get_current_user)):
    try:
        return S.create_workspace_message(current_user["id"], body)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.patch("/workspace-messages/{message_id}/read")
def mark_workspace_message_read(message_id: str, current_user: dict = Depends(get_current_user)):
    if not S.mark_workspace_message_read(message_id, current_user["id"]):
        raise HTTPException(status_code=404, detail="Message not found")
    return {"ok": True}


@router.get("/seat-requests")
def list_seat_requests(current_user: dict = Depends(get_current_user)):
    return S.list_seat_requests(current_user["id"])


@router.get("/seat-requests/{seat_request_id}")
def get_seat_request(seat_request_id: str, current_user: dict = Depends(get_current_user)):
    out = S.get_seat_request(seat_request_id, current_user["id"])
    if out is None:
        raise HTTPException(status_code=404, detail="Seat request not found")
    return out


@router.post("/seat-requests")
def create_seat_request(body: M.SeatRequestCreate, current_user: dict = Depends(get_current_user)):
    try:
        return S.create_seat_request(body, current_user["id"])
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.patch("/seat-requests/{seat_request_id}")
def update_seat_request(seat_request_id: str, body: M.SeatRequestUpdate, current_user: dict = Depends(get_current_user)):
    try:
        out = S.update_seat_request(seat_request_id, body, current_user["id"])
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if out is None:
        raise HTTPException(status_code=404, detail="Seat request not found")
    return out


@router.delete("/seat-requests/{seat_request_id}")
def delete_seat_request(seat_request_id: str, current_user: dict = Depends(get_current_user)):
    if not S.delete_seat_request(seat_request_id, current_user["id"]):
        raise HTTPException(status_code=404, detail="Seat request not found")
    return {"ok": True}


@router.post("/seat-requests/{seat_request_id}/share")
def share_seat_request(seat_request_id: str, body: M.ShareStateUpdate, current_user: dict = Depends(get_current_user)):
    try:
        out = S.set_seat_request_share_state(seat_request_id, body, current_user["id"])
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if out is None:
        raise HTTPException(status_code=404, detail="Seat request not found")
    return out


@router.get("/seat-requests/{seat_request_id}/candidate-offers")
def candidate_offers_for_seat_request(
    seat_request_id: str,
    limit: int = Query(25, ge=1, le=100),
    current_user: dict = Depends(get_current_user),
):
    out = S.candidate_offers_for_seat_request(seat_request_id, current_user["id"], limit=limit)
    if out is None:
        raise HTTPException(status_code=404, detail="Seat request not found")
    return {"seat_request_id": seat_request_id, "candidates": out}


@router.get("/capability-offers")
def list_capability_offers(current_user: dict = Depends(get_current_user)):
    return S.list_capability_offers(current_user["id"])


@router.get("/capability-offers/{offer_id}")
def get_capability_offer(offer_id: str, current_user: dict = Depends(get_current_user)):
    out = S.get_capability_offer(offer_id, current_user["id"])
    if out is None:
        raise HTTPException(status_code=404, detail="Capability offer not found")
    return out


@router.post("/capability-offers")
def create_capability_offer(body: M.CapabilityOfferCreate, current_user: dict = Depends(get_current_user)):
    try:
        return S.create_capability_offer(body, current_user["id"])
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.patch("/capability-offers/{offer_id}")
def update_capability_offer(offer_id: str, body: M.CapabilityOfferUpdate, current_user: dict = Depends(get_current_user)):
    try:
        out = S.update_capability_offer(offer_id, body, current_user["id"])
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if out is None:
        raise HTTPException(status_code=404, detail="Capability offer not found")
    return out


@router.delete("/capability-offers/{offer_id}")
def delete_capability_offer(offer_id: str, current_user: dict = Depends(get_current_user)):
    if not S.delete_capability_offer(offer_id, current_user["id"]):
        raise HTTPException(status_code=404, detail="Capability offer not found")
    return {"ok": True}


@router.post("/capability-offers/{offer_id}/share")
def share_capability_offer(offer_id: str, body: M.ShareStateUpdate, current_user: dict = Depends(get_current_user)):
    try:
        out = S.set_capability_offer_share_state(offer_id, body, current_user["id"])
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if out is None:
        raise HTTPException(status_code=404, detail="Capability offer not found")
    return out


@router.get("/capability-offers/{offer_id}/candidate-requests")
def candidate_requests_for_capability_offer(
    offer_id: str,
    limit: int = Query(25, ge=1, le=100),
    current_user: dict = Depends(get_current_user),
):
    out = S.candidate_requests_for_capability_offer(offer_id, current_user["id"], limit=limit)
    if out is None:
        raise HTTPException(status_code=404, detail="Capability offer not found")
    return {"capability_offer_id": offer_id, "candidates": out}


@router.get("/material-requests")
def list_material_requests(current_user: dict = Depends(get_current_user)):
    return S.list_material_requests(current_user["id"])


@router.get("/material-requests/{request_id}")
def get_material_request(request_id: str, current_user: dict = Depends(get_current_user)):
    out = S.get_material_request(request_id, current_user["id"])
    if out is None:
        raise HTTPException(status_code=404, detail="Material request not found")
    return out


@router.post("/material-requests")
def create_material_request(body: M.MaterialRequestCreate, current_user: dict = Depends(get_current_user)):
    try:
        return S.create_material_request(body, current_user["id"])
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.patch("/material-requests/{request_id}")
def update_material_request(request_id: str, body: M.MaterialRequestUpdate, current_user: dict = Depends(get_current_user)):
    try:
        out = S.update_material_request(request_id, body, current_user["id"])
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if out is None:
        raise HTTPException(status_code=404, detail="Material request not found")
    return out


@router.delete("/material-requests/{request_id}")
def delete_material_request(request_id: str, current_user: dict = Depends(get_current_user)):
    if not S.delete_material_request(request_id, current_user["id"]):
        raise HTTPException(status_code=404, detail="Material request not found")
    return {"ok": True}


@router.post("/material-requests/{request_id}/share")
def share_material_request(request_id: str, body: M.ShareStateUpdate, current_user: dict = Depends(get_current_user)):
    try:
        out = S.set_material_request_share_state(request_id, body, current_user["id"])
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if out is None:
        raise HTTPException(status_code=404, detail="Material request not found")
    return out


@router.get("/material-requests/{request_id}/candidate-offers")
def candidate_offers_for_material_request(
    request_id: str,
    limit: int = Query(25, ge=1, le=100),
    current_user: dict = Depends(get_current_user),
):
    out = S.candidate_offers_for_material_request(request_id, current_user["id"], limit=limit)
    if out is None:
        raise HTTPException(status_code=404, detail="Material request not found")
    return {"material_request_id": request_id, "candidates": out}


@router.get("/material-offers")
def list_material_offers(current_user: dict = Depends(get_current_user)):
    return S.list_material_offers(current_user["id"])


@router.get("/material-offers/{offer_id}")
def get_material_offer(offer_id: str, current_user: dict = Depends(get_current_user)):
    out = S.get_material_offer(offer_id, current_user["id"])
    if out is None:
        raise HTTPException(status_code=404, detail="Material offer not found")
    return out


@router.post("/material-offers")
def create_material_offer(body: M.MaterialOfferCreate, current_user: dict = Depends(get_current_user)):
    try:
        return S.create_material_offer(body, current_user["id"])
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.patch("/material-offers/{offer_id}")
def update_material_offer(offer_id: str, body: M.MaterialOfferUpdate, current_user: dict = Depends(get_current_user)):
    try:
        out = S.update_material_offer(offer_id, body, current_user["id"])
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if out is None:
        raise HTTPException(status_code=404, detail="Material offer not found")
    return out


@router.delete("/material-offers/{offer_id}")
def delete_material_offer(offer_id: str, current_user: dict = Depends(get_current_user)):
    if not S.delete_material_offer(offer_id, current_user["id"]):
        raise HTTPException(status_code=404, detail="Material offer not found")
    return {"ok": True}


@router.post("/material-offers/{offer_id}/share")
def share_material_offer(offer_id: str, body: M.ShareStateUpdate, current_user: dict = Depends(get_current_user)):
    try:
        out = S.set_material_offer_share_state(offer_id, body, current_user["id"])
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if out is None:
        raise HTTPException(status_code=404, detail="Material offer not found")
    return out


@router.get("/material-offers/{offer_id}/candidate-requests")
def candidate_requests_for_material_offer(
    offer_id: str,
    limit: int = Query(25, ge=1, le=100),
    current_user: dict = Depends(get_current_user),
):
    out = S.candidate_requests_for_material_offer(offer_id, current_user["id"], limit=limit)
    if out is None:
        raise HTTPException(status_code=404, detail="Material offer not found")
    return {"material_offer_id": offer_id, "candidates": out}


@router.post("/distill-source")
def distill_source(body: dict = Body(...), current_user: dict = Depends(get_current_user)):
    """Extract key themes and claims from source materials for pre-filling a content brief."""
    from local_ai.zenaf_tools import distill_content_source
    from local_ai.llm.execution_principal import principal_for_vision_execution_user

    source = (body.get("source_materials") or body.get("source") or "").strip()
    result = distill_content_source(
        source,
        execution_principal=principal_for_vision_execution_user(current_user["id"]),
    )
    _emit_ve_server_trace(
        user_id=current_user["id"],
        action_intent="distill_source",
        subject_type="content_distill",
        subject_id=current_user["id"],
        field_key=None,
        input_snapshot=f"source_char_len={len(source)}",
        result=result,
        action_kind="suggestion_batch",
    )
    return result


@router.post("/focus-actions/rewrite", response_model=M.FocusFieldRewriteResponse)
def focus_action_rewrite(body: M.FocusFieldRewriteRequest, current_user: dict = Depends(get_current_user)):
    """Rewrite text for the focused VE field — returns draft for human review; client applies explicitly."""
    from local_ai.vision_execution.focus_actions import rewrite_focus_field

    out = rewrite_focus_field(body.model_dump(), current_user["id"])
    _emit_ve_server_trace(
        user_id=current_user["id"],
        action_intent="focus_field_rewrite",
        subject_type=body.entity_type,
        subject_id=body.entity_id,
        field_key=body.field_key,
        input_snapshot=f"entity_type={body.entity_type}\nentity_id={body.entity_id}\nfield_key={body.field_key}",
        result=out,
        action_kind="suggestion_batch",
    )
    return M.FocusFieldRewriteResponse(**out)


# --- Meeting capture (extract only; save via existing POST ideas/initiatives) ---
@router.post("/extract-meeting")
def extract_meeting(body: M.ExtractMeetingRequest, current_user: dict = Depends(get_current_user)):
    """Extract ideas, initiatives, and tasks from pasted meeting notes. Optional context for linking to existing entities."""
    ext_pid = (body.profile_id or "").strip() if body.profile_id else ""
    if ext_pid:
        logger.info(
            "core_profile.profile_id_usage classification=extract_meeting_body_override route=POST /vision-execution/extract-meeting user_id=%s profile_id=%s",
            current_user["id"],
            ext_pid,
        )
    from local_ai.vision_execution.meeting_extract import extract_meeting as _extract
    context = body.context.model_dump(by_alias=True) if body.context else None
    rc = body.routing_context
    routing_context = rc if isinstance(rc, dict) else None
    wp = body.workspace_packet.model_dump(by_alias=True) if getattr(body, "workspace_packet", None) else None
    notes_len = len(str(body.notes or "").strip())
    input_snap = f"notes_char_len={notes_len}\nprofile_id={ext_pid or ''}\nreturn_diagnostics={bool(body.return_diagnostics)}"
    out: dict[str, Any]
    try:
        out = _extract(
            body.notes,
            context=context,
            profile_id=body.profile_id,
            return_diagnostics=body.return_diagnostics,
            routing_context=routing_context,
            user_id=current_user["id"],
            skip_harvest=not bool(getattr(body, "include_harvest_ledger", True)),
            evidence_extraction_preset=body.evidence_extraction_preset,
            include_meeting_polish=body.include_meeting_polish,
            workspace_packet=wp,
            use_external_ai_extraction=bool(getattr(body, "use_external_ai_extraction", False)),
            external_ai_engine=body.external_ai_engine,
            wash_data_for_call=bool(getattr(body, "wash_data_for_call", True)),
        )
    except Exception as e:
        logger.exception("[extract-meeting] route exception: %s", e)
        out = {
            "candidates": [],
            "ideas": [],
            "initiatives": [],
            "tasks": [],
            "error": "exception",
            "message": "Extraction failed. Please try again or use shorter notes.",
            "sample": str(e)[:500] if str(e) else None,
        }
    try:
        trace_meeting_debug_extract_route(
            user_id=current_user["id"],
            action_intent="meeting_extract_full_notes",
            result=out,
            input_snapshot=input_snap,
        )
    except Exception:
        logger.warning("server_ai_trace extract-meeting emission failed", exc_info=True)
    return out


@router.post("/suggest-candidate-placement")
def suggest_candidate_placement_route(body: dict = Body(...), current_user: dict = Depends(get_current_user)):
    """Suggest entity type + link placement for one extraction candidate (no persistence)."""
    from local_ai.vision_execution.candidate_placement_suggest import suggest_candidate_placement as _suggest

    candidate, existing, context_str = _normalize_ve_candidate_inputs(body)
    active_profile = _resolve_active_placement_profile(
        body, current_user["id"], route="POST /vision-execution/suggest-candidate-placement"
    )

    def _compute(use_seam: bool, exec_meta: dict[str, Any]):
        return _suggest(
            candidate,
            existing,
            context_str,
            active_profile=active_profile,
            user_id=current_user["id"],
            use_execution_seam=use_seam,
            exec_meta=exec_meta,
        )

    result = _run_ve_llm_with_routing(
        mode="candidate_placement_suggest",
        body=body,
        compute=_compute,
        user_id=current_user["id"],
    )
    if isinstance(result, dict):
        _merge_client_correlation_id(body, result)
    cid = body.get("client_correlation_id") or body.get("clientCorrelationId")
    subj = str(cid).strip()[:512] if cid else f"user:{current_user['id']}"
    _emit_ve_server_trace(
        user_id=current_user["id"],
        action_intent="candidate_placement_suggest",
        subject_type="extraction_candidate",
        subject_id=subj,
        field_key=None,
        input_snapshot=f"client_correlation_id={subj}\ncandidate_keys={list((candidate or {}).keys())[:12]}",
        result=result,
        action_kind="suggestion_batch",
    )
    return result


@router.post("/presort-candidate-triage")
def presort_candidate_triage_route(body: dict = Body(...), current_user: dict = Depends(get_current_user)):
    """Coarse triage only (existing / new / unsure) for batch list presort — no structural placement."""
    from local_ai.vision_execution.candidate_presort_triage import suggest_candidate_presort_triage as _triage

    candidate, existing, context_str = _normalize_ve_candidate_inputs(body)

    staged_raw = body.get("staged_section") or body.get("stagedSection")
    staged_section = str(staged_raw).strip().lower() if isinstance(staged_raw, str) and str(staged_raw).strip() else None

    def _compute(use_seam: bool, exec_meta: dict[str, Any]):
        return _triage(
            candidate,
            existing,
            context_str,
            user_id=current_user["id"],
            use_execution_seam=use_seam,
            exec_meta=exec_meta,
            staged_section=staged_section,
        )

    result = _run_ve_llm_with_routing(
        mode="candidate_presort_triage",
        body=body,
        compute=_compute,
        user_id=current_user["id"],
    )
    if isinstance(result, dict) and result.get("execution_blocked"):
        from local_ai.vision_execution.candidate_presort_triage import heuristic_presort_only

        h = heuristic_presort_only(candidate, existing, staged_section=staged_section)
        for k in ("model_used", "provider_used"):
            if result.get(k) is not None:
                h[k] = result[k]
        base_r = str(h.get("presort_reason") or "").strip()
        suffix = "heuristic only (cloud triage blocked by policy)"
        h["presort_reason"] = f"{base_r} ({suffix})".strip() if base_r else suffix
        _merge_client_correlation_id(body, h)
        cid = body.get("client_correlation_id") or body.get("clientCorrelationId")
        subj = str(cid).strip()[:512] if cid else f"user:{current_user['id']}"
        _emit_ve_server_trace(
            user_id=current_user["id"],
            action_intent="candidate_presort_triage",
            subject_type="extraction_candidate",
            subject_id=subj,
            field_key=None,
            input_snapshot=f"client_correlation_id={subj}\nstaged_section={staged_section or ''}\nheuristic_fallback=1",
            result=h,
            action_kind="suggestion_batch",
        )
        return h
    if isinstance(result, dict):
        _merge_client_correlation_id(body, result)
    cid = body.get("client_correlation_id") or body.get("clientCorrelationId")
    subj = str(cid).strip()[:512] if cid else f"user:{current_user['id']}"
    _emit_ve_server_trace(
        user_id=current_user["id"],
        action_intent="candidate_presort_triage",
        subject_type="extraction_candidate",
        subject_id=subj,
        field_key=None,
        input_snapshot=f"client_correlation_id={subj}\nstaged_section={staged_section or ''}",
        result=result,
        action_kind="suggestion_batch",
    )
    return result


@router.post("/suggest-node-transform")
def suggest_node_transform_route(body: dict = Body(...), current_user: dict = Depends(get_current_user)):
    """Bounded VE transforms (idea→task, etc.): single JSON response, not council SSE."""
    from local_ai.vision_execution.node_transform_suggest import suggest_node_transform as _transform

    active_profile = _resolve_active_placement_profile(
        body, current_user["id"], route="POST /vision-execution/suggest-node-transform"
    )

    def _compute(use_seam: bool, exec_meta: dict[str, Any]):
        return _transform(
            body,
            user_id=current_user["id"],
            use_execution_seam=use_seam,
            exec_meta=exec_meta,
            active_profile=active_profile,
        )

    result = _run_ve_llm_with_routing(
        mode="node_transform_suggest",
        body=body,
        compute=_compute,
        user_id=current_user["id"],
    )
    if isinstance(result, dict):
        _merge_client_correlation_id(body, result)
    cid = body.get("client_correlation_id") or body.get("clientCorrelationId")
    subj = str(cid).strip()[:512] if cid else f"user:{current_user['id']}"
    _emit_ve_server_trace(
        user_id=current_user["id"],
        action_intent="node_transform_suggest",
        subject_type="vision_execution",
        subject_id=subj,
        field_key=None,
        input_snapshot=f"client_correlation_id={subj}\nbody_keys={list(body.keys())[:16] if isinstance(body, dict) else []}",
        result=result,
        action_kind="suggestion_batch",
    )
    return result


@router.post("/extract-segment-summary")
def extract_segment_summary(body: M.ExtractSegmentSummaryRequest):
    """Lightweight extraction for one transcript segment (topic, briefSummary, candidateTasks/Entities/Signals). For long-meeting hierarchical path. Optional priorContext for reference continuity."""
    from local_ai.vision_execution.meeting_extract import extract_segment_summary as _extract_summary

    prior = body.prior_context if hasattr(body, "prior_context") and body.prior_context is not None else None
    rc = body.routing_context
    routing_context = rc if isinstance(rc, dict) else None
    notes = body.notes if hasattr(body, "notes") else ""
    notes_len = len(str(notes or "").strip())
    input_snap = f"notes_char_len={notes_len}\nprior_context={'1' if prior else '0'}"
    out: dict[str, Any] = {}
    try:
        try:
            out = _extract_summary(body.notes, prior_context=prior, routing_context=routing_context)
        except Exception:
            out = {
                "topic": "",
                "briefSummary": "",
                "candidateTasks": [],
                "candidateEntities": [],
                "candidateSignals": [],
                "error": "Segment summary failed. Please try again.",
            }
        enrich_meeting_debug_llm_meta(
            out, routing_context=routing_context, user_id=None, mode="meeting_extract_chunks"
        )
    except Exception as e:
        logger.exception("[extract-segment-summary] route failure: %s", e)
        out = {
            "topic": "",
            "briefSummary": "",
            "candidateTasks": [],
            "candidateEntities": [],
            "candidateSignals": [],
            "error": str(e)[:500],
        }
        enrich_meeting_debug_llm_meta(
            out, routing_context=routing_context, user_id=None, mode="meeting_extract_chunks"
        )
    try:
        trace_meeting_debug_extract_route(
            user_id=None,
            action_intent="meeting_extract_segment_summary",
            result=out,
            input_snapshot=input_snap,
        )
    except Exception:
        logger.warning("server_ai_trace extract-segment-summary emission failed", exc_info=True)
    return out


@router.post("/extract-meeting-segments")
def extract_meeting_segments(body: M.ExtractMeetingSegmentsRequest):
    """Legacy / debug: segment summary extraction with rolling prior_context (not used by primary Vision Execution meeting-capture UI; UI uses chunked ``extract-meeting`` only)."""
    from local_ai.vision_execution.meeting_extract import extract_segments_with_rolling_prior_context

    texts = body.segment_texts if hasattr(body, "segment_texts") and body.segment_texts else []
    profile_id = getattr(body, "profile_id", None)
    return_diagnostics = getattr(body, "return_diagnostics", False) or getattr(body, "returnDiagnostics", False)
    rc = body.routing_context
    routing_context = rc if isinstance(rc, dict) else None
    seg_n = len(texts) if isinstance(texts, list) else 0
    if profile_id and str(profile_id).strip():
        logger.info(
            "core_profile.profile_id_usage classification=legacy_debug_body_override route=POST /vision-execution/extract-meeting-segments user_id=unauthenticated profile_id=%s",
            str(profile_id).strip(),
        )
    input_snap = (
        f"segment_texts_n={seg_n}\nprofile_id={profile_id or ''}\nreturn_diagnostics={bool(return_diagnostics)}"
    )
    out: dict[str, Any] = {}
    try:
        try:
            summaries, _priors_used, segment_diagnostics = extract_segments_with_rolling_prior_context(
                texts,
                profile_id=profile_id,
                return_diagnostics=return_diagnostics,
                routing_context=routing_context,
            )
            if isinstance(segment_diagnostics, dict) and segment_diagnostics.get("execution_blocked"):
                out = {
                    "segment_summaries": [],
                    "error": segment_diagnostics.get("error_detail") or "Execution blocked by privacy policy",
                    "execution_blocked": True,
                }
            else:
                out = {"segment_summaries": summaries}
                if segment_diagnostics:
                    out["_segment_diagnostics"] = segment_diagnostics
        except Exception as e:
            logger.exception("[extract-meeting-segments] %s", e)
            out = {"segment_summaries": [], "error": "Segment extraction failed."}
        enrich_meeting_debug_llm_meta(
            out, routing_context=routing_context, user_id=None, mode="meeting_extract_chunks"
        )
    except Exception as e:
        logger.exception("[extract-meeting-segments] route failure: %s", e)
        out = {"segment_summaries": [], "error": str(e)[:500]}
        enrich_meeting_debug_llm_meta(
            out, routing_context=routing_context, user_id=None, mode="meeting_extract_chunks"
        )
    try:
        trace_meeting_debug_extract_route(
            user_id=None,
            action_intent="meeting_extract_meeting_segments",
            result=out,
            input_snapshot=input_snap,
        )
    except Exception:
        logger.warning("server_ai_trace extract-meeting-segments emission failed", exc_info=True)
    return out


@router.post("/extract-meeting-synthesis")
def extract_meeting_synthesis(body: M.ExtractMeetingSynthesisRequest):
    """Legacy / debug: full extraction from segment summaries (not used by primary meeting-capture UI; UI uses chunked ``extract-meeting`` + client merge)."""
    from local_ai.vision_execution.meeting_extract import extract_meeting_synthesis as _synthesize

    summaries = [s.model_dump(by_alias=True) if hasattr(s, "model_dump") else s for s in body.segment_summaries]
    context = body.context.model_dump(by_alias=True) if body.context else None
    used_rolling = getattr(body, "used_rolling_prior", None) or getattr(body, "usedRollingPrior", False)
    segment_diag = getattr(body, "segment_diagnostics", None) or getattr(body, "segmentDiagnostics", None)
    rc = body.routing_context
    routing_context = rc if isinstance(rc, dict) else None
    sum_n = len(summaries)
    syn_pid = body.profile_id
    if syn_pid and str(syn_pid).strip():
        logger.info(
            "core_profile.profile_id_usage classification=legacy_debug_body_override route=POST /vision-execution/extract-meeting-synthesis user_id=unauthenticated profile_id=%s",
            str(syn_pid).strip(),
        )
    input_snap = (
        f"segment_summaries_n={sum_n}\nprofile_id={body.profile_id or ''}\n"
        f"used_rolling_prior={bool(used_rolling)}"
    )
    out: dict[str, Any] = {}
    try:
        try:
            out = _synthesize(
                summaries,
                context=context,
                profile_id=body.profile_id,
                return_diagnostics=body.return_diagnostics,
                used_rolling_prior=used_rolling,
                segment_diagnostics=segment_diag,
                routing_context=routing_context,
                skip_harvest=not bool(getattr(body, "include_harvest_ledger", True)),
                include_meeting_polish=body.include_meeting_polish,
            )
        except Exception:
            out = {
                "ideas": [],
                "initiatives": [],
                "tasks": [],
                "error": "Synthesis failed. Please try again.",
            }
        enrich_meeting_debug_llm_meta(
            out, routing_context=routing_context, user_id=None, mode="meeting_extract_synthesis"
        )
    except Exception as e:
        logger.exception("[extract-meeting-synthesis] route failure: %s", e)
        out = {"ideas": [], "initiatives": [], "tasks": [], "error": str(e)[:500]}
        enrich_meeting_debug_llm_meta(
            out, routing_context=routing_context, user_id=None, mode="meeting_extract_synthesis"
        )
    try:
        trace_meeting_debug_extract_route(
            user_id=None,
            action_intent="meeting_extract_meeting_synthesis",
            result=out,
            input_snapshot=input_snap,
        )
    except Exception:
        logger.warning("server_ai_trace extract-meeting-synthesis emission failed", exc_info=True)
    return out


@router.post("/prompt-signals")
def post_prompt_signal(
    body: dict[str, Any] = Body(...),
    current_user: dict = Depends(get_current_user),
):
    """
    Record engaged (chose to discuss), deferred (revisit later), or dismissed (suppress this
    ``prompt_id`` for the check window). Append-only; semantics are per exact ``prompt_id``.
    """
    uid = current_user["id"]
    _require_user_permission(
        current_user,
        _PERMISSION_PROFILE_LEARNING,
        detail="Permission required: profile learning from usage.",
    )
    try:
        row = S.record_prompt_signal(
            uid,
            prompt_id=str(body.get("prompt_id") or ""),
            action=str(body.get("action") or ""),
            entity_type=body.get("entity_type"),
            entity_id=body.get("entity_id"),
            prompt_summary=str(body.get("prompt_summary") or ""),
            deferred_until=body.get("deferred_until"),
        )
        return row
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.get("/prompt-signals/check")
def get_prompt_signal_check(
    prompt_id: str = Query(..., min_length=1),
    within_days: int = Query(7, ge=1, le=366),
    current_user: dict = Depends(get_current_user),
):
    """Whether to inject: false if dismissed within ``within_days`` or deferred until a future time."""
    uid = current_user["id"]
    _require_user_permission(
        current_user,
        _PERMISSION_PERSONALIZATION,
        detail="Permission required: personalization / adaptive responses.",
    )
    show = S.should_show_prompt_after_dismiss(uid, prompt_id, within_days=within_days)
    return {"show": show, "prompt_id": prompt_id}


@router.get("/prompt-signals/deferred")
def get_deferred_prompts(
    entity_type: str = Query(..., min_length=1),
    entity_id: str = Query(..., min_length=1),
    current_user: dict = Depends(get_current_user),
):
    _require_user_permission(
        current_user,
        _PERMISSION_PERSONALIZATION,
        detail="Permission required: personalization / adaptive responses.",
    )
    uid = current_user["id"]
    return {"items": S.list_deferred_prompts_for_entity(uid, entity_type, entity_id)}


# --- Workspace identity (local gitignored snapshot; mirror for extraction hints only) ---


def _workspace_identity_status_payload() -> dict[str, Any]:
    from local_ai.workspace_identity.snapshot import (
        REPO_ROOT,
        TTL_STALE_SECONDS,
        build_workspace_packet_from_snapshot,
        compute_branch_key,
        default_workspace_identity_dir,
        read_snapshot_file,
        snapshot_age_seconds,
        snapshot_usable_for_extract,
    )

    base = default_workspace_identity_dir()
    default_scan_root = str(REPO_ROOT.resolve())
    current = compute_branch_key()
    snap = read_snapshot_file(base)
    usable, reason = snapshot_usable_for_extract(snap, current_branch_key=current)
    age = snapshot_age_seconds(snap)
    suggest_age = bool(age is not None and age > TTL_STALE_SECONDS)
    packet = build_workspace_packet_from_snapshot(snap) if usable else None
    summary = None
    if snap:
        sh = snap.get("scanHealth") or {}
        ri = snap.get("rawIndex") or {}
        surfaces = ri.get("surfaces") if isinstance(ri, dict) else None
        if not isinstance(surfaces, list):
            surfaces = snap.get("surfaces") or []
        buf = snap.get("buffers") if isinstance(snap.get("buffers"), dict) else {}
        reason = buf.get("reasoning") if isinstance(buf.get("reasoning"), dict) else {}
        assoc = buf.get("associative_cluster") if isinstance(buf.get("associative_cluster"), dict) else {}
        summary = {
            "schemaVersion": snap.get("schemaVersion"),
            "domainHintCount": len(snap.get("domainHints") or []),
            "surfaceCount": len(surfaces),
            "scanKind": (snap.get("provenance") or {}).get("scan_kind"),
            "nodeCapReached": bool(sh.get("nodeCapReached")),
            "sourceRootCount": len(snap.get("sourceRoots") or []),
            "pathRecords": sh.get("pathRecords"),
            "reasoningThemeCount": len(reason.get("themes") or []),
            "clusterCount": len(assoc.get("clusters") or []),
        }
    status = "ok" if usable else reason
    last_roots: list[str] | None = None
    if snap and isinstance(snap.get("sourceRoots"), list):
        last_roots = [str(x) for x in snap["sourceRoots"] if str(x).strip()]
    identity_quality_warning: str | None = None
    if snap:
        sh = snap.get("scanHealth") if isinstance(snap.get("scanHealth"), dict) else {}
        w = sh.get("identityQualityWarning")
        identity_quality_warning = str(w).strip() if isinstance(w, str) and str(w).strip() else None
    from local_ai.workspace_identity.translation_template import translation_template_path

    tt_path = translation_template_path()
    return {
        "status": status,
        "branchKeyCurrent": current,
        "branchKeySnapshot": snap.get("branchKey") if snap else None,
        "generatedAt": snap.get("generatedAt") if snap else None,
        "ageSeconds": age,
        "suggestRefreshDueToAge": suggest_age and usable,
        "workspacePacket": packet,
        "snapshotSummary": summary,
        "defaultScanRoot": default_scan_root,
        "lastScanSourceRoots": last_roots,
        "identityQualityWarning": identity_quality_warning,
        "translationTemplatePath": str(tt_path),
        "translationTemplatePresent": tt_path.is_file(),
    }


@router.post("/workspace-identity/pick-directory")
async def post_workspace_identity_pick_directory():
    """
    Open a native folder dialog on the machine running this API and return the absolute path.
    The browser cannot read full filesystem paths; this bridges scan roots to the server FS.
    Runs off the asyncio loop so a modal dialog / subprocess cannot stall other HTTP handlers.
    """
    import anyio
    from local_ai.workspace_identity.pick_directory import pick_scan_root_directory

    path, err = await anyio.to_thread.run_sync(pick_scan_root_directory)
    if err:
        raise HTTPException(status_code=503, detail=err)
    return {"ok": True, "path": path, "cancelled": path is None}


@router.get("/workspace-identity/translation-template")
def get_workspace_identity_translation_template():
    """Read optional translation-template.json (user vocabulary for packet merge)."""
    from local_ai.workspace_identity.translation_template import read_translation_template, translation_template_path

    path = translation_template_path()
    if not path.is_file():
        return {"ok": True, "path": str(path), "template": None}
    return {"ok": True, "path": str(path), "template": read_translation_template()}


@router.put("/workspace-identity/translation-template")
def put_workspace_identity_translation_template(body: M.WorkspaceTranslationTemplateBody):
    """Write translation-template.json next to snapshot (gitignored)."""
    from local_ai.workspace_identity.translation_template import write_translation_template

    path = write_translation_template(body.model_dump(by_alias=True, exclude_none=True))
    return {"ok": True, "path": str(path)}


@router.get("/workspace-identity")
def get_workspace_identity():
    """
    Read local snapshot if present; validate branchKey. Returns extraction-sized workspacePacket
    only when usable (no silent stale mirror).
    """
    out = _workspace_identity_status_payload()
    logger.debug(
        "[workspace-identity] GET status=%s branch_current=%s branch_snap=%s hints=%s",
        out.get("status"),
        out.get("branchKeyCurrent"),
        out.get("branchKeySnapshot"),
        len((out.get("workspacePacket") or {}).get("domainHints") or []),
    )
    return out


# --- Aspiration layer (explicit profile + derived signal + proposals) ---


@router.post("/aspiration-profile")
def post_aspiration_profile(body: M.AspirationProfileUpsert, current_user: dict = Depends(get_current_user)):
    from local_ai.aspiration_layer import aspiration_profile_enabled
    from local_ai.vision_execution import storage as St

    if not aspiration_profile_enabled():
        raise HTTPException(status_code=404, detail="Aspiration profile feature disabled")
    _require_user_permission(
        current_user,
        _PERMISSION_ASPIRATION_STORE,
        detail="Consent required: store explicit aspirations (Settings → permissions).",
    )
    try:
        row = St.upsert_aspiration_profile(current_user["id"], body.model_dump())
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {"profile": row}


@router.get("/aspiration-profile")
def get_aspiration_profile_route(current_user: dict = Depends(get_current_user)):
    from local_ai.aspiration_layer import aspiration_profile_enabled
    from local_ai.vision_execution import storage as St

    if not aspiration_profile_enabled():
        raise HTTPException(status_code=404, detail="Aspiration profile feature disabled")
    row = St.get_aspiration_profile(current_user["id"])
    return {"profile": row}


@router.patch("/aspiration-profile")
def patch_aspiration_profile_route(body: M.AspirationProfilePatch, current_user: dict = Depends(get_current_user)):
    from local_ai.aspiration_layer import aspiration_profile_enabled
    from local_ai.vision_execution import storage as St

    if not aspiration_profile_enabled():
        raise HTTPException(status_code=404, detail="Aspiration profile feature disabled")
    _require_user_permission(
        current_user,
        _PERMISSION_ASPIRATION_STORE,
        detail="Consent required: store explicit aspirations (Settings → permissions).",
    )
    patch = {k: v for k, v in body.model_dump(exclude_none=True).items()}
    try:
        row = St.patch_aspiration_profile(current_user["id"], patch)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {"profile": row}


@router.get("/aspiration-signal")
def get_aspiration_signal_route(current_user: dict = Depends(get_current_user)):
    from local_ai.aspiration_layer import aspiration_profile_enabled, derive_aspiration_signal
    from local_ai.vision_execution import storage as St

    if not aspiration_profile_enabled():
        raise HTTPException(status_code=404, detail="Aspiration profile feature disabled")
    prof = St.get_aspiration_profile(current_user["id"])
    sig = derive_aspiration_signal(current_user["id"])
    return {
        "aspiration_signal": sig,
        "profile_present": prof is not None,
        "permissions": {
            "aspiration_store_explicit": St.user_permission_enabled(current_user["id"], _PERMISSION_ASPIRATION_STORE),
            "aspiration_infer_suggestions": St.user_permission_enabled(current_user["id"], _PERMISSION_ASPIRATION_INFER),
            "aspiration_use_in_guidance": St.user_permission_enabled(current_user["id"], _PERMISSION_ASPIRATION_USE),
        },
    }


@router.get("/aspiration-proposals")
def list_aspiration_proposals_route(current_user: dict = Depends(get_current_user)):
    from local_ai.aspiration_layer import aspiration_inference_enabled, sync_aspiration_proposals_to_storage
    from local_ai.vision_execution import storage as St

    if not aspiration_inference_enabled():
        raise HTTPException(status_code=404, detail="Aspiration inference disabled")
    _require_user_permission(
        current_user,
        _PERMISSION_ASPIRATION_INFER,
        detail="Consent required: inferred aspiration suggestions (Settings → permissions).",
    )
    sync_aspiration_proposals_to_storage(current_user["id"])
    rows = St.list_aspiration_proposals(current_user["id"], status="pending")
    return {"proposals": rows}


@router.post("/aspiration-proposals/{proposal_id}/accept")
def accept_aspiration_proposal_route(proposal_id: str, current_user: dict = Depends(get_current_user)):
    from local_ai.aspiration_layer import aspiration_inference_enabled, accept_aspiration_proposal

    if not aspiration_inference_enabled():
        raise HTTPException(status_code=404, detail="Aspiration inference disabled")
    _require_user_permission(
        current_user,
        _PERMISSION_ASPIRATION_INFER,
        detail="Consent required: inferred aspiration suggestions (Settings → permissions).",
    )
    out = accept_aspiration_proposal(current_user["id"], proposal_id)
    if out is None:
        raise HTTPException(status_code=404, detail="Proposal not found")
    return {"ok": True, "accepted_proposal": out}


@router.post("/aspiration-proposals/{proposal_id}/dismiss")
def dismiss_aspiration_proposal_route(proposal_id: str, current_user: dict = Depends(get_current_user)):
    from local_ai.aspiration_layer import aspiration_inference_enabled
    from local_ai.vision_execution import storage as St

    if not aspiration_inference_enabled():
        raise HTTPException(status_code=404, detail="Aspiration inference disabled")
    _require_user_permission(
        current_user,
        _PERMISSION_ASPIRATION_INFER,
        detail="Consent required: inferred aspiration suggestions (Settings → permissions).",
    )
    out = St.set_aspiration_proposal_status(current_user["id"], proposal_id, "dismissed")
    if out is None:
        raise HTTPException(status_code=404, detail="Proposal not found")
    return {"ok": True, "proposal": out}


@router.post("/workspace-identity/scan")
def post_workspace_identity_scan(body: M.WorkspaceIdentityScanRequest):
    """
    Bounded deep/light scan of provided roots (default: repo root). Writes .zenaf/workspace-identity/v1/.
    Does not run during meeting extract.
    """
    from local_ai.workspace_identity.snapshot import (
        REPO_ROOT,
        build_workspace_identity_snapshot,
        build_workspace_packet_from_snapshot,
        write_workspace_identity_snapshot,
    )

    roots = [str(r).strip() for r in (body.roots or []) if str(r).strip()]
    scan_kind = body.mode if body.mode in ("deep_initial", "light_refresh") else "light_refresh"
    snapshot = build_workspace_identity_snapshot(
        roots,
        repo_root=REPO_ROOT,
        scan_kind=scan_kind,
    )
    base = write_workspace_identity_snapshot(snapshot)[0].parent
    packet = build_workspace_packet_from_snapshot(snapshot)
    logger.info("[workspace-identity] scan complete mode=%s roots=%s", scan_kind, len(snapshot.get("sourceRoots") or []))
    st = _workspace_identity_status_payload()
    return {
        "ok": True,
        "written": True,
        "workspaceIdentityDir": str(base),
        "snapshotSummary": st.get("snapshotSummary"),
        "workspacePacket": packet,
        "status": st.get("status"),
        "branchKeyCurrent": st.get("branchKeyCurrent"),
    }
