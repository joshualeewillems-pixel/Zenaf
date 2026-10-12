from __future__ import annotations

import time
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException
from pydantic import BaseModel, Field

from api.routes.auth_routes import get_current_admin_user
from local_ai.llm.adapter import BlockedLLMAdapter, LLMRequest
from local_ai.llm.execution_principal import authenticated_account_principal
from local_ai.llm.provider_registry import EXECUTION_PROVIDER_IDS, default_model_hint, normalize_provider_id
from local_ai.llm.resolver import get_council_llm_adapter_for_principal
from local_ai.vision_execution import storage as St

router = APIRouter(prefix="/studio", tags=["studio"])


class StudioTeacherSettingsUpdate(BaseModel):
    teacher_mode: str
    teacher_provider: str | None = None
    teacher_model: str | None = None
    teacher_prompt_version: str | None = None
    teacher_prompt_overlay: str | None = None
    main_attachment_provider: str | None = None
    main_attachment_model: str | None = None
    local_attachment_provider: str | None = None
    local_attachment_model: str | None = None
    experimental_google_provider: str | None = None
    experimental_google_model: str | None = None
    experimental_xai_provider: str | None = None
    experimental_xai_model: str | None = None
    capability_teacher_modes: dict[str, str] | None = None


BAKEOFF_LANE_COUNCIL_NATIVE = "council_native_attachment"
_BAKEOFF_ALLOWED_PROVIDERS = frozenset(EXECUTION_PROVIDER_IDS)
_BAKEOFF_OUTPUT_PREVIEW_CHARS = 480


class AttachmentLaneBakeoffProviderSpec(BaseModel):
    provider: str = Field(..., min_length=1, max_length=64)
    model: str = Field(default="", max_length=256)


class AttachmentLaneBakeoffRequest(BaseModel):
    lane: str = Field(..., min_length=1, max_length=80)
    prompt: str = Field(..., min_length=1, max_length=48_000)
    providers: list[AttachmentLaneBakeoffProviderSpec] = Field(..., min_length=1, max_length=16)
    score_bakeoff: bool = True


def _looks_like_model_id_failure(error_text: str | None) -> bool:
    """True when failure is likely an invalid/deprecated model id vs key/auth."""
    if not error_text:
        return False
    low = error_text.lower()
    if "no api key" in low and "namespace" in low:
        return False
    if "disabled" in low and "prefs" in low:
        return False
    needles = (
        "not found",
        "404",
        "not_found",
        "model not found",
        "model missing",
        "rejected the request for model",
        "not supported for generatecontent",
        "not supported for chat",
        "is not found for api",
        "unknown model",
        "invalid model",
    )
    return any(n in low for n in needles)


def _attach_suggested_default_model(row: dict[str, Any], provider_id: str) -> None:
    err = row.get("error")
    if not _looks_like_model_id_failure(err):
        return
    hint = (default_model_hint(provider_id) or "").strip()
    if hint:
        row["suggested_default_model"] = hint


def _bakeoff_output_preview(text: str, limit: int = _BAKEOFF_OUTPUT_PREVIEW_CHARS) -> str:
    t = (text or "").strip()
    if len(t) <= limit:
        return t
    return t[: limit - 1] + "…"


def run_council_native_bakeoff_for_admin(
    *,
    admin_user_id: str,
    prompt: str,
    provider_specs: list[AttachmentLaneBakeoffProviderSpec],
    score_bakeoff: bool = True,
) -> dict[str, Any]:
    """
    Sequential council-native attachment bakeoff using the same resolver/gates as production.
    Each row succeeds or fails independently.
    Optional LLM judge + heuristics populate per-row scores (admin inspectability).
    """
    from local_ai.studio.bakeoff_scoring import enrich_bakeoff_results_with_scores, sort_bakeoff_results

    principal = authenticated_account_principal(admin_user_id)
    results: list[dict[str, Any]] = []
    for spec in provider_specs:
        raw_pid = (spec.provider or "").strip()
        pid = normalize_provider_id(raw_pid)
        if pid not in _BAKEOFF_ALLOWED_PROVIDERS:
            results.append(
                {
                    "provider": raw_pid,
                    "model": (spec.model or "").strip() or None,
                    "ok": False,
                    "latency_ms": None,
                    "output_preview": None,
                    "error": f"Unsupported provider {raw_pid!r}; allowed: {', '.join(EXECUTION_PROVIDER_IDS)}.",
                    "grounding_score": 0,
                    "structure_score": 0,
                    "specificity_score": 0,
                    "constraint_obedience_score": 0,
                    "usefulness_score": 0,
                    "total_score": 0,
                    "score_notes": "Not run (unsupported provider).",
                }
            )
            continue
        model = (spec.model or "").strip() or None
        t0 = time.perf_counter()
        adapter = get_council_llm_adapter_for_principal(
            principal,
            force_provider=pid,
            force_model=model,
            allows_externalization=True,
        )
        if isinstance(adapter, BlockedLLMAdapter):
            results.append(
                {
                    "provider": pid,
                    "model": model,
                    "ok": False,
                    "latency_ms": round((time.perf_counter() - t0) * 1000.0, 2),
                    "output_preview": None,
                    "error": adapter.reason,
                    "grounding_score": 0,
                    "structure_score": 0,
                    "specificity_score": 0,
                    "constraint_obedience_score": 0,
                    "usefulness_score": 0,
                    "total_score": 0,
                    "score_notes": "Not scored (provider blocked).",
                }
            )
            _attach_suggested_default_model(results[-1], pid)
            continue
        try:
            out = adapter.generate_text(LLMRequest(task="council", prompt=prompt, timeout=120))
            ms = round((time.perf_counter() - t0) * 1000.0, 2)
            results.append(
                {
                    "provider": pid,
                    "model": model,
                    "ok": True,
                    "latency_ms": ms,
                    "output_preview": _bakeoff_output_preview(out),
                    "error": None,
                    "_full_output": out,
                }
            )
        except Exception as e:
            ms = round((time.perf_counter() - t0) * 1000.0, 2)
            err_s = str(e).strip() or type(e).__name__
            results.append(
                {
                    "provider": pid,
                    "model": model,
                    "ok": False,
                    "latency_ms": ms,
                    "output_preview": None,
                    "error": err_s[:4000],
                    "grounding_score": 0,
                    "structure_score": 0,
                    "specificity_score": 0,
                    "constraint_obedience_score": 0,
                    "usefulness_score": 0,
                    "total_score": 0,
                    "score_notes": "Not scored (generation error).",
                }
            )
            _attach_suggested_default_model(results[-1], pid)

    scoring_meta = enrich_bakeoff_results_with_scores(
        principal,
        prompt,
        results,
        enabled=score_bakeoff,
    )
    sort_bakeoff_results(results)
    return {
        "lane": BAKEOFF_LANE_COUNCIL_NATIVE,
        "prompt": prompt,
        "principal_ref": principal.principal_ref,
        "credential_namespace": principal.credential_namespace,
        "scoring": scoring_meta,
        "results": results,
    }


def _build_system_index_payload() -> dict:
    teacher_settings = St.get_studio_council_teacher_settings()
    recent_runs = St.list_recent_council_teacher_runs(limit=1)

    capabilities = [
        {
            "id": "council",
            "name": "Council + Teacher Supervision",
            "purpose": "Multi-seat council generation with optional teacher shadow/replace supervision.",
            "status": "active",
            "inspectability": "summary",
            "teacher_support": "council-only",
            "ui_entry_points": [
                {"label": "Studio recent runs", "location": "/studio (Recent Runs tab)"},
                {"label": "Workspace organizer council flow", "location": "App > Workspace Organizer"},
            ],
            "api_entry_points": [
                {"method": "POST", "path": "/run", "mode": "council"},
                {"method": "POST", "path": "/run/stream", "mode": "council"},
                {"method": "GET", "path": "/studio/council/recent-runs"},
            ],
            "main_files": [
                "api/main.py",
                "local_ai/zenaf_tools.py",
                "local_ai/council_teacher.py",
            ],
            "artifacts": ["council_teacher_runs", "CouncilRunArtifact"],
        },
        {
            "id": "vision_execution_eval",
            "name": "Vision Execution Evaluation",
            "purpose": "Idea/initiative/core-profile evaluation and reconciliation tasks.",
            "status": "active",
            "inspectability": "none",
            "teacher_support": "none",
            "ui_entry_points": [{"label": "Vision & Execution", "location": "App > Vision & Execution"}],
            "api_entry_points": [
                {"method": "POST", "path": "/vision-execution/ideas/{idea_id}/evaluate"},
                {"method": "POST", "path": "/vision-execution/initiatives/{initiative_id}/evaluate"},
                {"method": "POST", "path": "/vision-execution/core-profiles/{profile_id}/reconcile"},
            ],
            "main_files": [
                "api/routes/vision_execution.py",
                "local_ai/vision_execution/idea_evaluate.py",
                "local_ai/vision_execution/initiative_evaluate.py",
                "local_ai/vision_execution/core_profile_reconcile.py",
            ],
            "artifacts": ["learning_records (optional)"],
        },
        {
            "id": "meeting_extraction",
            "name": "Meeting Extraction",
            "purpose": "Extract action items and structure from transcripts and segment chunks.",
            "status": "active",
            "inspectability": "none",
            "teacher_support": "none",
            "ui_entry_points": [{"label": "Meeting Capture", "location": "Vision & Execution > meeting_capture"}],
            "api_entry_points": [
                {"method": "POST", "path": "/vision-execution/extract-meeting"},
                {"method": "POST", "path": "/vision-execution/extract-meeting-segments"},
                {"method": "POST", "path": "/vision-execution/extract-meeting-synthesis"},
            ],
            "main_files": [
                "api/routes/vision_execution.py",
                "local_ai/vision_execution/meeting_extract.py",
                "local_ai/vision_execution/meeting_extraction_execution.py",
            ],
            "artifacts": ["meeting extraction response payloads", "learning_records (optional)"],
        },
        {
            "id": "content_generation",
            "name": "Content Generation",
            "purpose": "Generate script/newsletter outputs from content briefs and source material.",
            "status": "active",
            "inspectability": "none",
            "teacher_support": "none",
            "ui_entry_points": [{"label": "Content", "location": "App > Content"}],
            "api_entry_points": [
                {"method": "POST", "path": "/run", "mode": "content_script"},
                {"method": "POST", "path": "/run", "mode": "content_newsletter"},
            ],
            "main_files": ["api/main.py", "local_ai/zenaf_tools.py"],
            "artifacts": ["content output text"],
        },
        {
            "id": "focus_rewrite",
            "name": "Focus Rewrite",
            "purpose": "Rewrite initiative/idea/task fields with focused, constrained output.",
            "status": "active",
            "inspectability": "none",
            "teacher_support": "none",
            "ui_entry_points": [{"label": "Focus Actions", "location": "Vision & Execution focus panels"}],
            "api_entry_points": [{"method": "POST", "path": "/vision-execution/focus-actions/rewrite"}],
            "main_files": ["api/routes/vision_execution.py", "local_ai/vision_execution/focus_actions.py"],
            "artifacts": ["rewrite draft payload"],
        },
        {
            "id": "workspace_file_steward",
            "name": "Workspace File Steward",
            "purpose": "Analyze/simulate/recommend folder organization using LLM-assisted classification.",
            "status": "active",
            "inspectability": "none",
            "teacher_support": "none",
            "ui_entry_points": [{"label": "Workspace Organizer", "location": "App > Workspace Organizer"}],
            "api_entry_points": [
                {"method": "POST", "path": "/run", "mode": "analyze"},
                {"method": "POST", "path": "/run", "mode": "simulate"},
                {"method": "POST", "path": "/run", "mode": "recommend"},
                {"method": "POST", "path": "/run", "mode": "assess_uncertainty"},
                {"method": "POST", "path": "/run", "mode": "reassess_low_confidence"},
            ],
            "main_files": ["api/main.py", "local_ai/zenaf_tools.py", "tools/file_steward/app.py"],
            "artifacts": ["analysis/simulation payloads"],
        },
        {
            "id": "delegation_routing",
            "name": "Delegation Routing + Externalization",
            "purpose": "Execution policy seam, provider routing, and structured delegation paths.",
            "status": "partial",
            "inspectability": "summary",
            "teacher_support": "none",
            "ui_entry_points": [{"label": "Trace metadata", "location": "multiple surfaces via AI actions"}],
            "api_entry_points": [{"method": "POST", "path": "/run"}, {"method": "POST", "path": "/vision-execution/*"}],
            "main_files": [
                "local_ai/execution_policy/resolve.py",
                "local_ai/execution_policy/seam_routing.py",
                "local_ai/delegation/general_lane.py",
                "local_ai/delegation/workspace_next_step.py",
            ],
            "artifacts": ["learning_records", "delegation_path metadata"],
        },
        {
            "id": "zenaf_next_step",
            "name": "Zenaf Ask / Next Step",
            "purpose": "Generate next-step recommendations from question + context.",
            "status": "active",
            "inspectability": "none",
            "teacher_support": "none",
            "ui_entry_points": [{"label": "Workspace Organizer", "location": "App > Workspace Organizer"}],
            "api_entry_points": [{"method": "POST", "path": "/run", "mode": "next_step"}],
            "main_files": ["api/main.py", "local_ai/zenaf_tools.py", "local_ai/delegation/workspace_next_step.py"],
            "artifacts": ["next_step payload", "learning_record_id (when captured)"],
        },
    ]

    ui_surfaces = [
        {"id": "studio", "location": "/studio", "purpose": "Admin studio", "status": "active"},
        {"id": "home", "location": "App > home", "purpose": "Radar home dashboard", "status": "active"},
        {"id": "perspectives", "location": "App > perspectives", "purpose": "Perspective management", "status": "active"},
        {"id": "vision_execution", "location": "App > vision_execution", "purpose": "Operational system of record", "status": "active"},
        {"id": "workspace", "location": "App > workspace", "purpose": "Workspace organizer and ask workflows", "status": "active"},
        {"id": "content", "location": "App > content", "purpose": "Content generation surface", "status": "active"},
        {"id": "settings", "location": "App > settings", "purpose": "Model/provider and account settings", "status": "active"},
        {
            "id": "workspace_legacy_intake_modes",
            "location": "App workspace mode IDs email_intake/fax_intake",
            "purpose": "Legacy mode IDs now superseded by clinic intake section",
            "status": "legacy",
        },
    ]

    prompts = [
        {
            "id": "council_seat_prompts",
            "name": "Council Seat Prompts",
            "definition": "local_ai/zenaf_tools.py",
            "composition": "_build_council_persona_block + _assemble_council_seat_prompt",
            "versioning": "code_based",
            "exposed_in_studio": True,
        },
        {
            "id": "council_synthesis_prompt",
            "name": "Council Synthesis Prompt",
            "definition": "local_ai/zenaf_tools.py",
            "composition": "_run_council_synthesis",
            "versioning": "code_based",
            "exposed_in_studio": True,
        },
        {
            "id": "teacher_prompt_versions",
            "name": "Teacher Prompt Versions",
            "definition": "local_ai/council_teacher.py",
            "composition": "CouncilTeacherSettings.prompt_overlay",
            "versioning": "explicit",
            "exposed_in_studio": True,
        },
        {
            "id": "initiative_idea_eval",
            "name": "Initiative + Idea Evaluation Prompts",
            "definition": "local_ai/vision_execution/initiative_evaluate.py, idea_evaluate.py",
            "composition": "evaluate_* prompt templates + strict JSON retries",
            "versioning": "code_based_with_trace_labels",
            "exposed_in_studio": False,
        },
        {
            "id": "focus_rewrite_prompt",
            "name": "Focus Rewrite Prompt",
            "definition": "local_ai/vision_execution/focus_actions.py",
            "composition": "_rewrite_prompt",
            "versioning": "code_based_with_trace_labels",
            "exposed_in_studio": False,
        },
        {
            "id": "meeting_extraction_prompts",
            "name": "Meeting Extraction Prompts",
            "definition": "local_ai/vision_execution/meeting_extract.py",
            "composition": "extract/synthesis prompt builders",
            "versioning": "code_based_with_trace_labels",
            "exposed_in_studio": False,
        },
    ]

    artifacts = [
        {
            "id": "council_teacher_runs",
            "name": "Council Teacher Runs",
            "schema_anchor": "local_ai/vision_execution/storage.py:council_teacher_runs",
            "persistence": "sqlite:data/vision_execution/vision_execution.db",
            "access": ["/studio/council/recent-runs"],
            "status": "active",
            "inspectability": "summary",
            "teacher_support": "council-only",
            "ui_access": "studio",
        },
        {
            "id": "council_run_artifact",
            "name": "CouncilRunArtifact",
            "schema_anchor": "local_ai/council_run_artifact.py:CouncilRunArtifact",
            "persistence": "embedded in teacher run JSON columns",
            "access": ["/studio/council/recent-runs"],
            "status": "partial",
            "inspectability": "summary",
            "teacher_support": "council-only",
            "ui_access": "studio",
        },
        {
            "id": "learning_records",
            "name": "Learning Records",
            "schema_anchor": "local_ai/delegation/learning_capture.py:LearningRecord",
            "persistence": "in-memory ring + optional JSONL",
            "access": [
                "/vision-execution/learning-records/stats",
                "/vision-execution/learning-records/inspect",
                "/vision-execution/learning-records/export",
            ],
            "status": "partial",
            "inspectability": "none",
            "teacher_support": "none",
            "ui_access": "none",
        },
        {
            "id": "frontend_ai_trace_ring",
            "name": "Frontend AI Trace Ring",
            "schema_anchor": "frontend/src/ai-actions/types.ts:AiActionTrace",
            "persistence": "frontend in-memory ring",
            "access": ["frontend trace helpers / in-app consumers"],
            "status": "partial",
            "inspectability": "none",
            "teacher_support": "none",
            "ui_access": "none",
        },
        {
            "id": "activity_log",
            "name": "Activity Log",
            "schema_anchor": "local_ai/activity.py:ActivityEvent",
            "persistence": "JSONL file activity.log",
            "access": ["not surfaced in Studio"],
            "status": "legacy",
            "inspectability": "none",
            "teacher_support": "none",
            "ui_access": "none",
        },
    ]

    hidden_unsurfaced = {
        "capabilities_without_studio_inspection": [
            c for c in capabilities if (c.get("inspectability") or "none") == "none"
        ],
        "prompts_not_exposed": [p for p in prompts if not p.get("exposed_in_studio")],
        "artifacts_without_ui_access": [a for a in artifacts if (a.get("ui_access") or "none") == "none"],
        "orphan_or_experimental_surfaces": [
            s for s in ui_surfaces if (s.get("status") or "").strip().lower() in ("legacy", "experimental")
        ],
    }

    capability_count = len(capabilities)
    capability_active_count = sum(1 for c in capabilities if c.get("status") == "active")
    capability_partial_or_experimental_count = sum(
        1 for c in capabilities if c.get("status") in ("partial", "experimental")
    )
    capability_teacher_supported_count = sum(1 for c in capabilities if c.get("teacher_support") != "none")
    artifact_not_surfaced_count = sum(1 for a in artifacts if a.get("ui_access") == "none")

    return {
        "generated_for": "studio_system_index",
        "status_legend": {
            "active": "Used and reachable from current UI/API paths",
            "experimental": "Present but not yet stable or central",
            "partial": "Exists and runs, but inspection/navigation is scattered",
            "legacy": "Likely redundant, replaced, or unsurfaced",
        },
        "inspectability_legend": {
            "none": "No practical Studio inspection path",
            "summary": "Summary-level inspection available in Studio",
            "detailed": "Detailed drill-down available in Studio",
        },
        "teacher_support_legend": {
            "none": "No teacher supervision path",
            "council-only": "Teacher supervision only for council",
            "available": "Teacher path available for this system",
        },
        "summary": {
            "total_capabilities": capability_count,
            "active_capabilities": capability_active_count,
            "partial_or_experimental_capabilities": capability_partial_or_experimental_count,
            "capabilities_with_teacher_support": capability_teacher_supported_count,
            "artifact_systems_not_surfaced_in_ui": artifact_not_surfaced_count,
            "ui_surface_count": len(ui_surfaces),
            "prompt_family_count": len(prompts),
            "artifact_system_count": len(artifacts),
            "teacher_mode": teacher_settings.get("teacher_mode"),
            "teacher_provider": teacher_settings.get("teacher_provider"),
            "teacher_model": teacher_settings.get("teacher_model"),
            "recent_teacher_runs": len(recent_runs),
        },
        "capabilities": capabilities,
        "ui_surfaces": ui_surfaces,
        "prompt_systems": prompts,
        "artifact_systems": artifacts,
        "hidden_unsurfaced": hidden_unsurfaced,
    }


@router.get("/me")
def studio_me(current_user: dict = Depends(get_current_admin_user)):
    return {
        "id": current_user["id"],
        "email": current_user["email"],
        "display_name": current_user["display_name"],
        "is_admin": bool(current_user.get("is_admin")),
    }


@router.get("/council/prompts")
def studio_council_prompts(current_user: dict = Depends(get_current_admin_user)):
    from local_ai import zenaf_tools as T
    from local_ai.council_teacher import TEACHER_PROMPT_VERSIONS

    personas = {}
    for role in T.COUNCIL_ROLE_KEYS:
        try:
            personas[role] = T._built_in_persona_dict(role)  # noqa: SLF001 - intentional admin inspection
        except Exception:
            personas[role] = {}
    return {
        "components": {
            "COUNCIL_SEAT_ROLE_LIMIT": T.COUNCIL_SEAT_ROLE_LIMIT,
            "COUNCIL_SEAT_PRIMARY_ANCHOR": T.COUNCIL_SEAT_PRIMARY_ANCHOR,
            "COUNCIL_SYNTHESIS_PROMPT": T.COUNCIL_SYNTHESIS_PROMPT,
            "COUNCIL_SYNTHESIS_INSTRUCTION_GUARDS": T.COUNCIL_SYNTHESIS_INSTRUCTION_GUARDS,
        },
        "personas": personas,
        "teacher_prompt_versions": dict(TEACHER_PROMPT_VERSIONS),
    }


@router.get("/council/teacher-settings")
def studio_get_teacher_settings(current_user: dict = Depends(get_current_admin_user)):
    return St.get_studio_council_teacher_settings()


@router.put("/council/teacher-settings")
def studio_put_teacher_settings(
    body: StudioTeacherSettingsUpdate,
    current_user: dict = Depends(get_current_admin_user),
):
    try:
        return St.upsert_studio_council_teacher_settings(
            teacher_mode=body.teacher_mode,
            teacher_provider=body.teacher_provider,
            teacher_model=body.teacher_model,
            teacher_prompt_version=body.teacher_prompt_version,
            teacher_prompt_overlay=body.teacher_prompt_overlay,
            main_attachment_provider=body.main_attachment_provider,
            main_attachment_model=body.main_attachment_model,
            local_attachment_provider=body.local_attachment_provider,
            local_attachment_model=body.local_attachment_model,
            experimental_google_provider=body.experimental_google_provider,
            experimental_google_model=body.experimental_google_model,
            experimental_xai_provider=body.experimental_xai_provider,
            experimental_xai_model=body.experimental_xai_model,
            capability_teacher_modes=body.capability_teacher_modes,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/council/recent-runs")
def studio_recent_runs(limit: int = 20, current_user: dict = Depends(get_current_admin_user)):
    return {"items": St.list_recent_council_teacher_runs(limit=limit)}


@router.get("/council/runs/{run_id}")
def studio_get_run(run_id: str, current_user: dict = Depends(get_current_admin_user)):
    row = St.get_council_teacher_run(run_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return row


@router.get("/system-index")
def studio_system_index(current_user: dict = Depends(get_current_admin_user)):
    return _build_system_index_payload()


@router.get("/provider-default-policy")
def studio_provider_default_policy(
    scope: str = "current",
    current_user: dict = Depends(get_current_admin_user),
):
    """
    Read-only: implicit default sources, normalized planes (auth / anonymous / system),
    fallback order notes, usable providers per principal, and (scope=current) live profile slice.
    When scope=current, ``current_session.credential_visibility`` summarizes system vs account OpenAI
    status (no secrets) and Option B anonymous policy.
    """
    from local_ai.execution_policy.provider_default_inspect import (
        build_normalized_policy_payload,
        build_provider_policy_for_current_user,
    )

    if (scope or "").strip().lower() == "static":
        return build_normalized_policy_payload()
    return build_provider_policy_for_current_user(current_user["id"])


@router.get("/provider-default-models")
def studio_provider_default_models(current_user: dict = Depends(get_current_admin_user)):
    """
    Read-only: recommended default model id per execution provider (from provider modules via
    ``default_model_hint``). Use to prefill Studio bakeoff JSON. Includes ``source`` provenance string.
    """
    from local_ai.studio.provider_default_models import default_models_response_payload

    return default_models_response_payload()


@router.post("/attachment-lane/bakeoff")
def studio_attachment_lane_bakeoff(
    body: AttachmentLaneBakeoffRequest,
    current_user: dict = Depends(get_current_admin_user),
):
    """
    Admin-only: run the same prompt through multiple providers using the council native attachment
    resolver path (``get_council_llm_adapter_for_principal`` with explicit provider/model).
    Sequential; per-provider failures do not abort the batch.
    """
    lane = (body.lane or "").strip()
    if lane != BAKEOFF_LANE_COUNCIL_NATIVE:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Unsupported lane {lane!r}. This endpoint only implements "
                f"{BAKEOFF_LANE_COUNCIL_NATIVE!r} for now."
            ),
        )
    uid = str(current_user.get("id") or "").strip()
    if not uid:
        raise HTTPException(status_code=400, detail="Admin user id missing.")
    return run_council_native_bakeoff_for_admin(
        admin_user_id=uid,
        prompt=body.prompt.strip(),
        provider_specs=body.providers,
        score_bakeoff=body.score_bakeoff,
    )


@router.post("/council/compare-placeholder")
def studio_patch_compare(
    body: dict = Body(...),
    current_user: dict = Depends(get_current_admin_user),
):
    # v1 inspection-first: placeholder endpoint for future review edits.
    run_id = str(body.get("run_id") or "").strip()
    if not run_id:
        raise HTTPException(status_code=400, detail="run_id is required")
    return {"ok": True, "run_id": run_id, "note": "comparison editing is deferred in v1"}
