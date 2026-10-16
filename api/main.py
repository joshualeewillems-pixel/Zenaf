"""
Zenaf API: thin FastAPI bridge to the local_ai engine.
POST /run dispatches to existing tools; no duplicated business logic.
"""
import subprocess
import sys
from pathlib import Path

# Ensure repo root is on path so we can import local_ai
_repo_root = Path(__file__).resolve().parent.parent
if str(_repo_root) not in sys.path:
    sys.path.insert(0, str(_repo_root))

# Hosted mode: import first so ZENAF_DB_DIR aliasing precedes any storage import,
# and fail fast on misconfigured production before the app is built.
from local_ai.hosted_config import is_prod as _is_prod
from local_ai.hosted_config import validate_prod_config as _validate_prod_config

_validate_prod_config()

import json
import logging
import os
import uuid
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from local_ai.llm.execution_principal import ExecutionPrincipal
from local_ai.perf_trace import perf_begin, perf_mark, perf_read_context, perf_restore

logger = logging.getLogger(__name__)
# Council perf correlation (`local_ai.perf_trace`): always INFO for this logger so runs are diagnosable without raising root log noise.
logging.getLogger("zenaf.perf").setLevel(logging.INFO)
logging.getLogger("zenaf.ollama").setLevel(logging.INFO)
logging.getLogger("zenaf.server_ai_action").setLevel(logging.INFO)

app = FastAPI(
    title="Zenaf API",
    description="Bridge for the cockpit frontend; calls local_ai engine.",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    # Dev SPA is bound to 127.0.0.1 only (see frontend/vite.config.ts) so cookies align with API_BASE.
    # ChatGPT/Claude share pages: the Zenaf bookmarklet POSTs extracted
    # transcripts from these origins (no credentials; share-text endpoint only).
    allow_origins=[
        "http://127.0.0.1:5173",
        "https://chatgpt.com",
        "https://claude.ai",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=[
        "X-Zenaf-Model-Used",
        "X-Zenaf-Provider-Used",
        "X-Zenaf-Routing-Override",
        "X-Zenaf-Perf-Run-Id",
    ],
)

# Router load errors: collected by the try/except blocks below so the
# startup check can report WHY a router is missing, not just that it is.
_router_load_errors: list = []

# Vision → Execution Engine: separate domain (ideas, initiatives, projects, tasks, people, assets). Not part of /run or file sorter.
try:
    from api.routes.vision_execution import router as vision_execution_router
    app.include_router(vision_execution_router)
except Exception as e:
    print(f"Vision Execution routes not loaded: {e}")
    _router_load_errors.append(f"vision_execution: {e}")

# Presence ingestion: "bring your history" — import digital-presence exports,
# distill into candidate training signals, review before they train anything.
try:
    from api.routes.ingest_routes import router as ingest_router
    app.include_router(ingest_router)
except Exception as e:
    print(f"Ingest routes not loaded: {e}")
    _router_load_errors.append(f"ingest: {e}")

# Agent Intake & Sorting ("The Sorting"): connect external AI agents, sort
# them into strand agents as skills/talents/projects, review before anything
# trains.
try:
    from api.routes.agent_routes import router as agent_router
    app.include_router(agent_router)
except Exception as e:
    print(f"Agent routes not loaded: {e}")
    _router_load_errors.append(f"agents: {e}")

# PersonalityProfile (Phase 1): the user-defined side of each strand.
# Propose -> review -> publish; the aspirational defaults are never touched.
try:
    from api.routes.personality_routes import router as personality_router
    app.include_router(personality_router)
except Exception as e:
    print(f"Personality routes not loaded: {e}")
    _router_load_errors.append(f"personality: {e}")

# Phase 5: temporal modeling — snapshots & era addressing (separate router so
# the personality routes file stays untouched).
try:
    from api.routes.personality_temporal_routes import router as personality_temporal_router
    app.include_router(personality_temporal_router)
except Exception as e:
    print(f"Personality temporal routes not loaded: {e}")
    _router_load_errors.append(f"personality-temporal: {e}")

# Phase 5: temporal modeling — snapshots & era addressing (separate router so
# the personality routes file stays untouched).
try:
    from api.routes.personality_temporal_routes import router as personality_temporal_router
    app.include_router(personality_temporal_router)
except Exception as e:
    print(f"Personality temporal routes not loaded: {e}")

# Identity license + consent scopes + takeout: the ownership layer. Every
# doppelganger's data is the owner's property; scopes gate every use.
try:
    from api.routes.identity_routes import router as identity_router
    app.include_router(identity_router)
except Exception as e:
    print(f"Identity routes not loaded: {e}")
    _router_load_errors.append(f"identity: {e}")

# Transcript sorter: paste transcript → topics / candidate tasks/decisions (no storage).
try:
    from api.routes.transcript_routes import router as transcript_router
    app.include_router(transcript_router)
except Exception as e:
    print(f"Transcript routes not loaded: {e}")
    _router_load_errors.append(f"transcripts: {e}")

# Auth: minimal local login/session bootstrap (Phase 1A).
try:
    from api.routes.auth_routes import router as auth_router
    app.include_router(auth_router)
except Exception as e:
    print(f"Auth routes not loaded: {e}")
    _router_load_errors.append(f"auth: {e}")

try:
    from api.routes.settings_routes import router as settings_router
    app.include_router(settings_router, prefix="/settings")
except Exception as e:
    print(f"Settings routes not loaded: {e}")
    _router_load_errors.append(f"settings: {e}")

try:
    from api.routes.openrouter_oauth_routes import router as openrouter_oauth_router
    app.include_router(openrouter_oauth_router, prefix="/settings")
except Exception as e:
    print(f"OpenRouter OAuth routes not loaded: {e}")
    _router_load_errors.append(f"openrouter_oauth: {e}")

try:
    from api.routes.studio_routes import router as studio_router
    app.include_router(studio_router)
except Exception as e:
    print(f"Studio routes not loaded: {e}")
    _router_load_errors.append(f"studio: {e}")

try:
    from api.routes.transcribe_routes import router as transcribe_router
    app.include_router(transcribe_router)
except Exception as e:
    print(f"Transcribe routes not loaded: {e}")
    _router_load_errors.append(f"transcribe: {e}")

try:
    from api.routes.journal_routes import router as journal_router
    app.include_router(journal_router)
except Exception as e:
    print(f"Journal routes not loaded: {e}")
    _router_load_errors.append(f"journal: {e}")

try:
    from api.routes.entity_strand_routes import router as entity_strand_router
    app.include_router(entity_strand_router)
except Exception as e:
    print(f"Entity strand routes not loaded: {e}")
    _router_load_errors.append(f"entity_strands: {e}")

try:
    from api.routes.council_twigs_routes import router as council_twigs_router
    app.include_router(council_twigs_router)
except Exception as e:
    print(f"Council twigs routes not loaded: {e}")
    _router_load_errors.append(f"council_twigs: {e}")

# Council archetype naming unlocks — depth milestones for renaming seats.
try:
    from api.routes.council_archetype_routes import router as council_archetype_router
    app.include_router(council_archetype_router)
except Exception as e:
    print(f"Council archetype routes not loaded: {e}")
    _router_load_errors.append(f"council-archetypes: {e}")


# --- Router registration check (owed follow-up to PR #34) ---
# A broken import inside any router module used to be swallowed by the
# try/except blocks above, silently killing the whole router (the dangling
# soil_api import took down vision-execution with only a printed line).
# This check screams instead: every expected router prefix must be mounted.

EXPECTED_ROUTER_PREFIXES = (
    "/vision-execution",
    "/ingest",
    "/agents",
    "/personality",
    "/identity",
    "/transcripts",
    "/auth",
    "/settings",
    "/studio",
    "/api",  # transcribe_routes mounts at /api
)


def _iter_mounted_paths(routes, _base_prefix=""):
    """
    Yield effective route paths, descending into Starlette's nested
    ``_IncludedRouter`` entries (modern FastAPI/Starlette no longer flattens
    included routers into ``app.routes``).
    """
    for route in routes:
        path = getattr(route, "path", None)
        if path:
            yield _base_prefix + path
            continue
        original = getattr(route, "original_router", None)
        if original is None:
            continue
        include_prefix = getattr(getattr(route, "include_context", None), "prefix", "") or ""
        yield from _iter_mounted_paths(
            getattr(original, "routes", []), _base_prefix + include_prefix
        )


def _nested_router_prefixes(routes):
    """
    Prefixes evidenced by nested router objects themselves (their own
    ``prefix`` or the include-time ``prefix``), independent of how inner
    paths are baked. Belt-and-suspenders alongside path matching.
    """
    prefixes = set()
    for route in routes:
        original = getattr(route, "original_router", None)
        if original is None:
            continue
        router_prefix = getattr(original, "prefix", "") or ""
        if router_prefix:
            prefixes.add(router_prefix)
        include_prefix = getattr(getattr(route, "include_context", None), "prefix", "") or ""
        if include_prefix:
            prefixes.add(include_prefix)
    return prefixes


def assert_routers_registered(fastapi_app=None) -> None:
    """
    Raise RuntimeError if any expected router prefix is not mounted.

    Pass an explicit app to check a synthetic/test app; defaults to this
    module's ``app``. Fails LOUDLY on purpose — a router that failed to
    import must never again pass silently.
    """
    target = fastapi_app if fastapi_app is not None else app
    mounted_paths = list(_iter_mounted_paths(target.routes))
    nested_prefixes = _nested_router_prefixes(target.routes)
    missing = [
        prefix
        for prefix in EXPECTED_ROUTER_PREFIXES
        if prefix not in nested_prefixes
        and not any(p == prefix or p.startswith(prefix + "/") for p in mounted_paths)
    ]
    if missing:
        details = (
            "; ".join(_router_load_errors) if _router_load_errors else "no import errors recorded"
        )
        raise RuntimeError(
            "Zenaf API startup check FAILED: expected router(s) not mounted: "
            + ", ".join(missing)
            + f". Router load errors: {details}. "
            "A router module almost certainly failed to import (see the 'not loaded' "
            "lines above); fix the import instead of silencing this check."
        )


# The check itself runs in _on_startup below (the server refuses to start
# with a crippled router set), and assert_routers_registered() is directly
# callable for tests without booting the server.


# --- Startup dependency check ---
# Verifies that runtime dependencies used by the engine (File Steward, web research, council, etc.)
# are importable at startup so we fail fast with a clear message instead of during the first request.


def _check_startup_dependencies() -> None:
    """
    Try importing each required module and print a short diagnostic.
    Does not crash the API; missing optional deps (e.g. duckduckgo_search) only affect specific modes.
    """
    checks = [
        ("pandas", "pandas", "Required for Analyze/Simulate/Recommend/Assess (File Steward)."),
        ("duckduckgo_search", "duckduckgo-search", "Required for Web Research mode."),
        ("local_ai", "local_ai", "Engine package (must be run from repo root)."),
        ("local_ai.zenaf_tools", "local_ai.zenaf_tools", "Engine tools (analyze, council, web_research, etc.)."),
        ("local_ai.providers", "local_ai.providers", "Provider modules (council resolves via ExecutionPrincipal + resolver)."),
    ]
    print("Zenaf API startup checks")
    for module_name, pip_name, _reason in checks:
        try:
            __import__(module_name)
            print(f"  ok {module_name}")
        except Exception as e:
            print(f"  fail {module_name} missing or failed to load")
            print(f"    Run from repo root and ensure dependencies are installed. ({e})")


@app.on_event("startup")
def _on_startup() -> None:
    """Run dependency checks when the API process starts."""
    # Router check (owed follow-up to PR #34): scream if any expected router
    # failed to mount. Raises RuntimeError -> the server will not start.
    assert_routers_registered()
    _check_startup_dependencies()
    try:
        from local_ai.vision_execution import storage as _vst

        ok = _vst.settings_encryption_available()
        paths = _vst.settings_encryption_key_paths_for_diagnostics()
        print(
            f"  settings API key storage: {'ok' if ok else 'FAILED — check cryptography install and filesystem permissions'}"
            f" (key file candidates: {paths})"
        )
    except Exception as e:
        print(f"  settings encryption check failed: {e}")
    # Learning records: optional JSONL replay into in-memory ring buffer
    try:
        from local_ai.delegation import learning_capture as _lc

        st = _lc.init_learning_persistence_from_env()
        if st and not st.get("already_initialized"):
            print(f"  ok learning persist: {st}")
    except Exception as e:
        print(f"  learning persistence init skipped or failed: {e}")
    # Log the vision-execution DB path at startup for diagnostics.
    try:
        from local_ai.vision_execution.storage import resolved_vision_execution_db_path

        print(f"  sqlite vision_execution: {resolved_vision_execution_db_path()}")
    except Exception as e:
        print(f"  vision_execution db path check skipped or failed: {e}")


@app.exception_handler(Exception)
def _catch_all_exception_handler(request, exc: Exception):
    """Return 500 with error detail so the frontend can show what went wrong. Skip HTTPException (404, 400, etc.)."""
    from fastapi import HTTPException as FastAPIHTTPException
    from fastapi.responses import JSONResponse
    if isinstance(exc, FastAPIHTTPException):
        raise exc
    import traceback
    msg = str(exc) or type(exc).__name__
    print(f"Unhandled exception: {msg}")
    traceback.print_exc()
    return JSONResponse(status_code=500, content={"detail": msg})


# --- Request/response models ---

class RunParams(BaseModel):
    folder_path: str | None = None
    question: str | None = None
    query: str | None = None
    included_agents: list[str] | None = None  # council: seer, guide, songwriter, storyteller, patternist, maker, mediator, zenaf
    # Council: full definitions for selected perspectives (so custom perspectives get their own voice)
    perspective_definitions: list[dict] | None = None
    # Reassess low-confidence: items from assess, one perspective as reviewer
    low_confidence_items: list[dict] | None = None
    perspective_definition: dict | None = None
    suggested_folders: list[str] | None = None
    # Content pipeline V1: brief + source → script or newsletter
    content_brief: dict | None = None
    content_source: str | None = None
    content_output_type: str | None = None  # "script" | "newsletter"
    content_refinement: str | None = None  # "shorten" | "more_direct" for regenerate
    # Council: optional synthesis control
    include_synthesis: bool | None = None
    # Council: optional object-native context
    subject_ref: dict | None = None       # identity of the object under judgment
    object_snapshot: dict | None = None   # small working fact snapshot
    # Council teacher controls (request override; defaults come from studio settings)
    teacher_mode: str | None = None  # off|shadow|warn|veto|replace
    teacher_provider: str | None = None
    teacher_model: str | None = None
    teacher_prompt_version: str | None = None
    # Council: optional native provider override (maps to run_council provider_override_*; not teacher_provider).
    native_provider: str | None = None
    native_model: str | None = None
    # When True with no seats/agents: run full multi-seat council (legacy default). When omitted/False with no seats: single-voice chat.
    force_full_council: bool | None = None
    # Optional narrower question shown to council seats only; full `question` still drives synthesis and packets.
    seat_question: str | None = None
    # Council personality mode: which version of each seat to use — "base" (pure aspirational),
    # "mirror" (user's published PersonalityProfile only), or "blend" (weighted, default).
    # When omitted, the user's saved default (/personality/council-mode) applies.
    council_personality_mode: str | None = None
    # Council decision context: the current decision's coarse envelope, e.g.
    # {"stakes": "significant", "time_pressure": "urgent"}. Seats weight past
    # decision evidence by similarity to it. When omitted, the system derives
    # a conservative envelope from the question (metadata, never a form
    # field); unknown dimensions stay unknown.
    decision_context: dict | None = None


class RunRoutingContext(BaseModel):
    """Optional substrate metadata for execution policy (Workspace /run Phase 1). Omitted => legacy behavior."""

    surface: str
    action_kind: str
    action_intent: str | None = None
    streaming: bool | None = None
    sensitivity: str | None = None
    # Client-sourced privacy mode (e.g. localStorage); merged into policy resolution — no separate persistence.
    privacy_mode: str | None = None
    # When False: council native skips cloud main attachment; cloud teacher is disabled. Default deny when seam is used.
    allows_externalization: bool = False


class RunRequest(BaseModel):
    mode: str
    params: RunParams | None = None
    context: dict | None = None  # optional; for progression, previous result summary, etc.
    routing_context: RunRoutingContext | None = None
    # Explicit execution plane: "account" (default) or "system" (requires ZENAF_SYSTEM_EXECUTION_KEY + header).
    execution_scope: str | None = None


class RunResponse(BaseModel):
    ok: bool
    result: dict | list | str | None = None
    error: str | None = None
    # Populated when request included routing_context (server truth for traces)
    model_used: str | None = None
    provider_used: str | None = None
    routing_override_active: bool | None = None
    # Privacy layer blocked all resolved providers/models (no silent fallback)
    execution_blocked: bool | None = None
    privacy_block_reason: str | None = None
    # Externalization v1 (workspace_next_step + OpenAI + subject_id): never includes PlaceholderMap
    externalization_integrity_ok: bool | None = None
    externalization_unresolved_tokens: list[str] | None = None
    externalization_invalid_tokens: list[str] | None = None
    externalization_unresolved_count: int | None = None
    externalization_invalid_count: int | None = None
    # Structured cloud delegation v1 (e.g. workspace_next_step + OpenAI + routing_context)
    delegation_path: str | None = None
    # When structured delegation was skipped despite OpenAI + workspace_next_step routing (e.g. empty prompt)
    delegation_skip_reason: str | None = None
    # Learning buffer correlation (structured + general delegation tiers); PATCH via /vision-execution/learning-records/user-outcome
    learning_record_id: str | None = None
    # When routing_context + OpenAI primary: env vs Settings key (no raw secrets)
    openai_key_source: str | None = None
    # Policy resolution (may differ from provider_used when anonymous falls back to Ollama)
    policy_primary_provider: str | None = None
    anonymous_openai_fallback_ollama: bool | None = None
    seam_fallback_reason: str | None = None
    # Two-plane execution identity (populated when routing_context applied seam)
    execution_scope: str | None = None
    execution_principal_ref: str | None = None
    credential_namespace: str | None = None
    policy_namespace: str | None = None
    # Council teacher metadata
    teacher_mode: str | None = None
    teacher_provider: str | None = None
    teacher_model: str | None = None
    teacher_provider_effective: str | None = None
    teacher_model_effective: str | None = None
    native_provider: str | None = None
    native_model: str | None = None
    teacher_succeeded: bool | None = None
    teacher_artifact_id: str | None = None
    teacher_prompt_version: str | None = None
    # When teacher cloud pass was skipped (e.g. privacy / allows_externalization=False).
    teacher_skipped_reason: str | None = None
    # Council teacher enforcement (shadow / warn / veto / replace); mirrors effective teacher_mode for council.
    teacher_enforcement_mode: str | None = None
    teacher_vetoed: bool | None = None
    teacher_warning: bool | None = None
    teacher_final_source: str | None = None
    teacher_reason_codes: list[str] | None = None
    teacher_notes: str | None = None
    # Read-only: requested vs effective vs seam fallback (see provider_default_inspect)
    provider_resolution: dict | None = None
    # Native council pass only: attachment resolution trace (see local_ai.llm.resolver)
    council_native_attachment_trace: dict | None = None
    # Council wash-for-externalization v0 (deterministic redaction trace)
    council_wash_trace: dict | None = None
    # Council personality mode for this run: which seat version was used (base|mirror|blend)
    council_personality_mode: str | None = None
    # Mirror mode: strand keys whose seats fell back to aspirational (no published content)
    mirror_empty_strands: list[str] | None = None
    # Human-readable mirror-fallback notice (None when every seat had mirror content)
    mirror_notice: str | None = None
    # Lane A: direct Vision Execution action (integration ran first; early return skips council LLM)
    direct_ve_action: dict | None = None


def _end_run_routing(teardown) -> None:
    """Reset per-request routing (policy provider override, then Ollama model token)."""
    if teardown is not None:
        from local_ai.execution_policy.run_context import end_execution_routing

        end_execution_routing(teardown)


def _optional_user_id_from_request(http_request: Request) -> str | None:
    """Session cookie → user id for Settings-stored API keys on POST /run (optional)."""
    from api.routes.auth_routes import SESSION_COOKIE_NAME
    from local_ai.vision_execution import service as S

    token = http_request.cookies.get(SESSION_COOKIE_NAME)
    if not token:
        return None
    user = S.get_session_user(token)
    if not user:
        return None
    uid = user.get("id")
    return str(uid).strip() if uid else None


def _log_council_routing_trace(mode: str, request: RunRequest, exec_meta: dict) -> None:
    """Diagnostics for council provider selection (routing seam vs legacy Ollama)."""
    if (mode or "").strip().lower() != "council":
        return
    rc = request.routing_context
    from local_ai.execution_policy.openai_credentials import openai_env_key_present

    openai_env = openai_env_key_present()
    logger.info(
        "council routing trace: routing_context_present=%s surface=%r action_kind=%r action_intent=%r "
        "provider_used=%r model_used=%r routing_override_active=%s execution_blocked=%s "
        "openai_env_key_present=%s openai_key_source=%r error_detail=%r",
        rc is not None,
        getattr(rc, "surface", None) if rc else None,
        getattr(rc, "action_kind", None) if rc else None,
        getattr(rc, "action_intent", None) if rc else None,
        exec_meta.get("provider_used"),
        exec_meta.get("model_used"),
        exec_meta.get("routing_override_active"),
        exec_meta.get("execution_blocked"),
        openai_env,
        exec_meta.get("openai_key_source"),
        exec_meta.get("error_detail"),
    )
    if rc is None:
        logger.warning(
            "council: no routing_context on request — execution policy seam not applied; "
            "get_council_provider() uses legacy stack (typically Ollama at localhost:11434)."
        )
    elif (getattr(rc, "action_intent", None) or "").strip() == "workspace_council":
        prov = exec_meta.get("provider_used")
        if prov == "ollama" and not exec_meta.get("execution_blocked"):
            logger.warning(
                "council: workspace_council intent resolved to ollama — check ai_execution_policy.json "
                "overrides_by_action_intent.workspace_council; for cloud OpenAI use an authenticated user "
                "(OPENAI_API_KEY or Settings key) or system ZENAF_SYSTEM_OPENAI_KEY; anonymous does not use OPENAI_API_KEY."
            )


def _preflight_ollama_reachable(provider_used: str | None) -> None:
    """Fail fast if the resolved provider is Ollama but it is unreachable.

    Raises HTTPException(502) with an actionable message. Called from
    /run/stream BEFORE the SSE stream starts: a dead Ollama mid-stream kills
    the response opaquely (mobile clients surface it as "Load failed").
    Non-Ollama providers are not probed here.
    """
    if (provider_used or "").strip().lower() != "ollama":
        return
    from api.routes.settings_routes import _ollama_tags_url

    import requests as _requests

    try:
        _resp = _requests.get(_ollama_tags_url(None), timeout=3)
        _resp.raise_for_status()
    except Exception:
        raise HTTPException(
            status_code=502,
            detail=(
                "Ollama (local) is unreachable from the server. "
                "Ollama only works when Zenaf runs on the same machine as Ollama — "
                "on hosted Zenaf, set Voiced by to 'Auto (policy)' or another provider."
            ),
        )


def _begin_run_routing(request: RunRequest, *, execution_principal, apply_overrides: bool = True):
    """
    Apply optional ``routing_context`` via ``apply_seam_routing`` (shared with Vision Execution).

    Executable providers on this seam: ``ollama``, ``openai``. Any other resolved primary → ``execution_blocked``.

    Returns (RoutingTeardown | None, execution_meta dict for RunResponse).
    ``execution_principal`` is ``local_ai.llm.execution_principal.ExecutionPrincipal``.
    """
    if request.routing_context is None:
        return None, {}
    from local_ai.execution_policy.seam_routing import apply_seam_routing

    rc = request.routing_context
    d = {
        "surface": rc.surface,
        "action_kind": rc.action_kind,
        "action_intent": rc.action_intent,
        "streaming": rc.streaming,
        "sensitivity": rc.sensitivity,
        "privacy_mode": getattr(rc, "privacy_mode", None),
    }
    return apply_seam_routing(
        mode=request.mode or "",
        routing_context=d,
        principal=execution_principal,
        apply_overrides=apply_overrides,
    )


# --- Folder picker: native dialog (for cockpit frontend) ---


@app.post("/folder-picker")
def folder_picker(initial_dir: str | None = None):
    """
    Open a native folder picker dialog and return the selected path.
    Uses a subprocess so the GUI runs on the same machine as the API (local use).
    Optional initial_dir: path to open the dialog at (must exist).
    """
    try:
        initial = (initial_dir or "").strip()
        if initial and not Path(initial).expanduser().resolve().is_dir():
            initial = ""
        code = r"""
import sys
try:
    import tkinter as tk
    from tkinter import filedialog
except ImportError:
    sys.exit(2)
root = tk.Tk()
root.withdraw()
root.attributes("-topmost", True)
kwargs = {}
if sys.argv[1:]:
    kwargs["initialdir"] = sys.argv[1]
path = filedialog.askdirectory(title="Select folder", **kwargs)
root.destroy()
if path:
    print(path)
"""
        cmd = [sys.executable, "-c", code]
        if initial:
            cmd.append(initial)
        out = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=120,
            cwd=str(Path.cwd()),
        )
        if out.returncode == 2:
            return {"error": "tkinter not available; cannot open folder dialog"}
        if out.returncode != 0 and out.stderr:
            return {"error": (out.stderr or "Folder dialog failed").strip()[:500]}
        path = (out.stdout or "").strip()
        if not path:
            return {"folder_path": None}
        return {"folder_path": path}
    except subprocess.TimeoutExpired:
        return {"error": "Folder dialog timed out"}
    except Exception as e:
        return {"error": str(e)[:500]}


# --- Dispatch: analyze and simulate for MVP ---

def _run_analyze(params: RunParams) -> dict:
    if not params or not (params.folder_path or "").strip():
        raise ValueError("analyze requires params.folder_path")
    from local_ai.zenaf_tools import analyze_file_steward_folder
    return analyze_file_steward_folder(params.folder_path.strip())


CONFIDENCE_THRESHOLD = 0.4


def _run_simulate(params: RunParams) -> dict:
    if not params or not (params.folder_path or "").strip():
        raise ValueError("simulate requires params.folder_path")
    from local_ai.zenaf_tools import simulate_folder_plan
    allowed = params.suggested_folders if params.suggested_folders else None
    return simulate_folder_plan(params.folder_path.strip(), allowed_folders=allowed)


def _run_recommend(params: RunParams) -> dict:
    if not params or not (params.folder_path or "").strip():
        raise ValueError("recommend requires params.folder_path")
    from local_ai.zenaf_tools import recommend_child_folders
    raw = recommend_child_folders(params.folder_path.strip())
    if raw.get("error"):
        return raw
    return {
        "folder_path": raw.get("folder_path"),
        "inferred_context_domain": raw.get("inferred_context_domain"),
        "suggested_child_folders": raw.get("suggested_child_folders", []),
        "notes": raw.get("notes"),
    }


def _run_assess_uncertainty(params: RunParams) -> dict:
    """Use simulate_folder_plan; filter proposed_assignments by confidence < 0.4; return compact summary + simulate_tree for UI."""
    if not params or not (params.folder_path or "").strip():
        raise ValueError("assess_uncertainty requires params.folder_path")
    sim = _run_simulate(params)
    if sim.get("error"):
        return sim
    proposed = sim.get("proposed_assignments", [])
    low = [a for a in proposed if (a.get("confidence") or 1.0) < CONFIDENCE_THRESHOLD]
    items = [
        {
            "item_name": a.get("item_name", ""),
            "confidence": a.get("confidence"),
            "suggested_child": a.get("suggested_child", ""),
            "reason": a.get("reason", ""),
        }
        for a in low
    ]
    return {
        "low_confidence_count": len(items),
        "items": items,
        "recommended_actions": [
            "review ambiguous folders",
            "consider new categories",
            "reassess with perspective",
        ],
        "simulate_tree": {
            "folder_path": sim.get("folder_path"),
            "inferred_context_domain": sim.get("inferred_context_domain"),
            "suggested_child_folders": sim.get("suggested_child_folders", []),
            "proposed_assignments": sim.get("proposed_assignments", []),
        },
    }


def _run_reassess_low_confidence(params: RunParams) -> list:
    """Perspective-driven reassessment of low-confidence items; optional folder_path for content-based deeper pass. Returns list of {item_name, suggested_folder, rationale, status, confidence}."""
    if not params or not (params.low_confidence_items and params.perspective_definition):
        raise ValueError("reassess_low_confidence requires params.low_confidence_items and params.perspective_definition")
    from local_ai.zenaf_tools import reassess_low_confidence
    folder_path = (params.folder_path or "").strip() or None
    return reassess_low_confidence(
        items=params.low_confidence_items,
        perspective=params.perspective_definition,
        suggested_folders=params.suggested_folders,
        folder_path=folder_path,
    )


def _run_web_research(params: RunParams) -> dict:
    """Call web_research(query). query required. Returns query, top_findings, sources, notes."""
    if not params or not (params.query or "").strip():
        raise ValueError("web_research requires params.query")
    from local_ai.zenaf_tools import web_research
    raw = web_research(params.query.strip())
    if raw.get("error"):
        return raw
    return {
        "query": raw.get("query", ""),
        "top_findings": raw.get("findings", []),
        "sources": raw.get("sources", []),
        "notes": raw.get("notes"),
    }


def _run_content_generate(params: RunParams, *, execution_principal: ExecutionPrincipal) -> str:
    """Content pipeline V1: brief + source → script or newsletter. Returns plain text or 'Error: ...'."""
    if not params:
        return "Error: params required."
    brief = getattr(params, "content_brief", None) or {}
    source = (getattr(params, "content_source", None) or "").strip()
    output_type = (getattr(params, "content_output_type", None) or "").strip().lower()
    refinement = (getattr(params, "content_refinement", None) or "").strip().lower() or None
    if output_type not in ("script", "newsletter"):
        return "Error: content_output_type must be 'script' or 'newsletter'."
    from local_ai.zenaf_tools import generate_content
    return generate_content(brief, source, output_type, refinement=refinement, execution_principal=execution_principal)


def _extract_next_step_subject_id(params: RunParams | None, context: dict | None) -> str | None:
    if context and isinstance(context.get("subject_id"), str):
        s = context["subject_id"].strip()
        if s:
            return s
    if params and params.subject_ref and isinstance(params.subject_ref, dict):
        sid = params.subject_ref.get("id")
        if isinstance(sid, str) and sid.strip():
            return sid.strip()
    return None


def _run_next_step(
    params: RunParams,
    context: dict | None,
    *,
    exec_meta: dict | None = None,
    routing_payload: dict | None = None,
    privacy_mode: str | None = None,
) -> tuple[dict, dict]:
    """
    Next step with optional externalization hook (``maybe_externalize_for_cloud``) when
    ``routing_payload`` is set: after internal prompt is built, before ``generate``.

    Returns ``(result_dict, response_extra)`` — ``response_extra`` holds externalization
    fields for ``RunResponse`` (no PlaceholderMap; restricted modes use counts only).
    """
    context_str = ""
    if context:
        if context.get("context_block") and isinstance(context["context_block"], str):
            context_str = context["context_block"].strip()
        elif context.get("folder_path") and isinstance(context["folder_path"], str):
            context_str = f"Folder: {context['folder_path'].strip()}"
    question = (params.question or "").strip() if params else ""

    from local_ai.zenaf_tools import build_next_step_prompt, generate_next_step_raw, parse_next_step_model_output
    from local_ai.zenaf_tools import suggest_next_step
    from local_ai.execution_policy.externalization import (
        WORKSPACE_NEXT_STEP_INTENT,
        maybe_externalize_for_cloud,
        rebind_after_cloud_response,
        redact_externalization_for_privacy,
    )

    p_internal = build_next_step_prompt(context_str, question or None)
    if p_internal is None:
        r = suggest_next_step(context_str, question or None)
        extra: dict = {}
        if routing_payload:
            prov_skip = (exec_meta or {}).get("provider_used", "")
            prov_skip_l = prov_skip.strip().lower() if isinstance(prov_skip, str) else ""
            intent_skip = ((routing_payload or {}).get("action_intent") or "").strip()
            policy_p = (exec_meta or {}).get("policy_primary_provider", "").strip().lower()
            openai_primary_ws = policy_p == "openai" and intent_skip == WORKSPACE_NEXT_STEP_INTENT
            ollama_anon_fb = prov_skip_l == "ollama" and (exec_meta or {}).get("anonymous_openai_fallback_ollama")
            if openai_primary_ws and (prov_skip_l == "openai" or ollama_anon_fb):
                extra["delegation_skip_reason"] = "empty_next_step_context_and_question"
                logger.info(
                    "workspace_next_step: structured_cloud_v1 not used — %s (routing_context present, OpenAI primary)",
                    extra["delegation_skip_reason"],
                )
        return r, extra

    prov = (exec_meta or {}).get("provider_used", "").strip().lower()
    policy_primary = (exec_meta or {}).get("policy_primary_provider", "").strip().lower()
    intent = ((routing_payload or {}).get("action_intent") or "").strip()
    structured_policy_openai = policy_primary == "openai" and intent == WORKSPACE_NEXT_STEP_INTENT
    substrate_ok = prov == "openai" or (
        prov == "ollama" and bool((exec_meta or {}).get("anonymous_openai_fallback_ollama"))
    )
    if routing_payload and structured_policy_openai and substrate_ok:
        from local_ai.delegation.workspace_next_step import (
            build_workspace_next_step_contract,
            execute_structured_openai_delegation,
        )

        sid = _extract_next_step_subject_id(params, context)
        contract = build_workspace_next_step_contract(
            bounded_context=context_str,
            question_goal=question or None,
            subject_id_hint=sid,
        )
        return execute_structured_openai_delegation(
            contract=contract,
            exec_meta=exec_meta or {},
            routing_payload=routing_payload,
            privacy_mode=privacy_mode,
            subject_id=sid,
        )

    if not routing_payload:
        raw, err = generate_next_step_raw(p_internal)
        if err is not None:
            return err, {}
        return parse_next_step_model_output(raw), {}

    ex = maybe_externalize_for_cloud(
        mode="next_step",
        routing_context=routing_payload,
        exec_meta=exec_meta or {},
        internal_prompt=p_internal,
        subject_id=_extract_next_step_subject_id(params, context),
    )
    raw, err = generate_next_step_raw(ex.external_prompt)
    if err is not None:
        return err, {}

    rb = rebind_after_cloud_response(raw, ex.placeholder_map)
    mapping_active = ex.strategy != "none" and bool(ex.placeholder_map.by_token)
    if mapping_active:
        fully_ok = rb.integrity_ok and len(rb.unresolved_tokens) == 0
        if not fully_ok:
            extra = redact_externalization_for_privacy(
                privacy_mode=privacy_mode,
                integrity_ok=False,
                unresolved_tokens=rb.unresolved_tokens,
                invalid_tokens=rb.invalid_tokens_in_output,
            )
            return {
                "recommendation": "",
                "rationale": "",
                "alternatives": [],
                "caution": None,
                "error": "Externalized response failed integrity validation (placeholder mismatch or missing echo).",
            }, extra
        parsed = parse_next_step_model_output(rb.text)
        extra = redact_externalization_for_privacy(
            privacy_mode=privacy_mode,
            integrity_ok=True,
            unresolved_tokens=(),
            invalid_tokens=(),
        )
        return {
            "recommendation": parsed.get("recommendation", ""),
            "rationale": parsed.get("rationale", ""),
            "alternatives": parsed.get("alternatives", []),
            "caution": parsed.get("caution"),
        }, extra

    parsed = parse_next_step_model_output(rb.text)
    return {
        "recommendation": parsed.get("recommendation", ""),
        "rationale": parsed.get("rationale", ""),
        "alternatives": parsed.get("alternatives", []),
        "caution": parsed.get("caution"),
    }, {}


def _resolve_council_context(
    request: RunRequest,
    *,
    resonance_user_id: str | None = None,
) -> str | None:
    """
    Preflight: merge UI/runtime hints + Vision & Execution focus + existing context
    into one enriched string for the council packet. Does not force seat modes.
    """
    from local_ai.conversation_trunk import classify_question_kind
    from local_ai.council_preflight import (
        build_enriched_council_context,
        parse_preflight_from_request,
    )

    params = request.params or RunParams()
    context = request.context
    question = (params.question or "").strip()
    preflight = parse_preflight_from_request(context, question)
    _qk_ctx = classify_question_kind(question)
    if request.routing_context is not None and getattr(request.routing_context, "surface", None):
        if not preflight.active_surface:
            preflight.active_surface = str(request.routing_context.surface)
    enriched = build_enriched_council_context(
        preflight,
        legacy_context_str=None,
        subject_ref=params.subject_ref,
        object_snapshot=params.object_snapshot,
        resonance_user_id=resonance_user_id,
        aspiration_user_id=resonance_user_id,
        question_kind=_qk_ctx,
    )
    ctx = context if isinstance(context, dict) else {}
    vf = preflight.ve_focus if isinstance(preflight.ve_focus, dict) else {}
    cblock = ctx.get("context_block")
    cblock_len = len(cblock.strip()) if isinstance(cblock, str) else 0
    raw_rb = (preflight.raw_context_block or "").strip()
    logger.info(
        "council preflight ingest: active_surface=%r ve_focus_type=%r ve_focus_id=%r "
        "ve_focus_title=%r ve_focus_brief_len=%s ve_focus_description_len=%s "
        "use_last_result=%s request_context_block_len=%s raw_context_block_len=%s enriched_len=%s",
        preflight.active_surface,
        vf.get("entity_type"),
        vf.get("entity_id"),
        preflight.ve_focus_title,
        len((preflight.ve_focus_brief or "")),
        len((preflight.ve_focus_description or "")),
        ctx.get("use_last_result"),
        cblock_len,
        len(raw_rb),
        len((enriched or "").strip()),
    )
    if ctx.get("use_last_result") and cblock_len > 0:
        logger.warning(
            "council preflight: use_last_result=True and non-empty context_block (%s chars) — prior AI / workspace output may be prepended to thread context",
            cblock_len,
        )
    return enriched.strip() or None


def _council_allows_externalization(request: RunRequest | None) -> bool:
    """POST /run without routing_context stays permissive; with routing_context, cloud requires explicit opt-in."""
    if request is None or request.routing_context is None:
        return True
    return bool(request.routing_context.allows_externalization)


def _council_native_provider_model_from_studio(
    studio_cfg: dict,
    *,
    effective_cloud: bool,
    params_native_provider: str | None,
    params_native_model: str | None,
) -> tuple[str | None, str | None]:
    """When the client does not override native council provider/model, use Studio attachment roles."""
    np = (params_native_provider or "").strip() or None
    nm = (params_native_model or "").strip() or None
    if np:
        return np, nm
    if effective_cloud:
        mp = studio_cfg.get("main_attachment_provider")
        mm = studio_cfg.get("main_attachment_model")
    else:
        mp = studio_cfg.get("local_attachment_provider")
        mm = studio_cfg.get("local_attachment_model")
    po = str(mp).strip().lower() if mp else None
    mo = str(mm).strip() if mm else None
    return po or None, mo or None


def _apply_council_teacher_mode_resolution(
    s,
    cfg: dict,
    params: RunParams,
    request: RunRequest | None,
) -> None:
    """Resolve effective teacher_mode: explicit params win, then per-capability council override, then routing sensitivity."""
    explicit = bool((getattr(params, "teacher_mode", None) or "").strip())
    if explicit:
        return
    cm = cfg.get("capability_teacher_modes") or {}
    if isinstance(cm, dict) and (cm.get("council") or "").strip():
        s.teacher_mode = str(cm["council"]).strip().lower()
        return
    if request is None or request.routing_context is None:
        return
    sens = (request.routing_context.sensitivity or "").strip().lower().replace(" ", "_")
    if sens in ("high", "grounding_sensitive", "grounding-sensitive"):
        if s.teacher_mode in ("off", "shadow"):
            s.teacher_mode = "warn"
    elif sens in ("adversarial", "max"):
        if s.teacher_mode in ("off", "shadow", "warn"):
            s.teacher_mode = "veto"


def _council_integration_suffix_and_event(
    context: dict | None,
    question: str,
    *,
    user_id: str | None,
) -> tuple[dict | None, str | None]:
    """Try pending-integration commit + optional last-commit location overlay for the council packet."""
    from local_ai.conversation_trunk import classify_question_kind
    from local_ai.integration_commit import (
        format_last_integration_overlay,
        process_pending_integration,
        recover_pending_on_affirm_from_conversation_subject,
        user_affirms_precision_commit,
    )

    pending = None
    last_c = None
    if isinstance(context, dict):
        p = context.get("pending_integration")
        if isinstance(p, dict):
            pending = p
        lc = context.get("last_integration_commit")
        if isinstance(lc, dict):
            last_c = lc
        if pending is None:
            rec = recover_pending_on_affirm_from_conversation_subject(question=question, context=context)
            if rec:
                pending = rec
    q = (question or "").strip()
    # Affirmations must commit pending precision even if the same text could look like a capture turn.
    _is_precision_turn = classify_question_kind(q) == "user_providing_precision"
    _affirms = user_affirms_precision_commit(q)
    # Committed text is always pending["value"] (e.g. DRAFT_VALUE whisper), never the bare "yes" message.
    event, o1 = process_pending_integration(
        question=q,
        pending=pending,
        user_id=user_id,
        skip_commit_because_new_precision=_is_precision_turn and not _affirms,
    )
    o2 = format_last_integration_overlay(last_c)
    parts = [x.strip() for x in (o1, o2) if x and str(x).strip()]
    suf = "\n\n".join(parts) if parts else None
    return event, suf


def _council_deterministic_commit_sse_pay(
    *,
    int_event: dict | None,
    conversation_subject_dict: dict | None,
    wash_trace: dict,
    params: RunParams,
    principal: ExecutionPrincipal,
    exec_meta: dict | None,
    request: RunRequest | None,
) -> dict | None:
    """
    When ``process_pending_integration`` already ran and produced a terminal outcome, skip the LLM and
    return this payload on the final SSE line (same shape the client expects on ``done``).
    """
    from local_ai.execution_policy.provider_default_inspect import build_provider_resolution_for_run
    from local_ai.integration_commit import (
        deterministic_commit_sse_extra_fields,
        deterministic_integration_ack_text,
        integration_event_requires_deterministic_ack,
    )

    if not integration_event_requires_deterministic_ack(int_event):
        return None
    text = deterministic_integration_ack_text(int_event)
    if not (text or "").strip():
        return None
    _ctx = request.context if request and isinstance(request.context, dict) else None
    pay: dict = {
        "chunk": text,
        "done": True,
        **deterministic_commit_sse_extra_fields(int_event, request_context=_ctx),
    }
    if conversation_subject_dict:
        pay["conversation_subject"] = conversation_subject_dict
    pay["council_wash_trace"] = wash_trace
    pay["provider_resolution"] = build_provider_resolution_for_run(
        mode="council",
        params=params,
        principal=principal,
        exec_meta=exec_meta or {},
        routing_context=request.routing_context if request else None,
        teacher_meta=None,
        wash_trace=wash_trace,
    )
    return pay


def _council_direct_ve_sse_pay(
    *,
    question: str,
    context: dict | None,
    conversation_subject_dict: dict | None,
    wash_trace: dict,
    params: RunParams,
    principal: ExecutionPrincipal,
    exec_meta: dict | None,
    request: RunRequest | None,
) -> dict | None:
    """Lane A: deterministic SSE when direct VE mutation handled (or hard error), skipping council LLM."""
    from local_ai.execution_policy.provider_default_inspect import build_provider_resolution_for_run
    from local_ai.vision_execution.direct_action_executor import (
        evaluate_direct_ve_action,
        should_skip_council_for_direct_result,
    )

    res = evaluate_direct_ve_action(
        question=question,
        context=context if isinstance(context, dict) else None,
        user_id=principal.account_user_id,
    )
    setattr(_run_council, "_last_direct_ve_action", res if should_skip_council_for_direct_result(res) else None)
    if not should_skip_council_for_direct_result(res):
        return None
    text = str(res.get("message") or "").strip()
    if not text:
        return None
    pay: dict = {
        "chunk": text,
        "done": True,
        "direct_ve_action": res,
        "synthesis_type": "conversational_partner",
        "council_wash_trace": wash_trace,
        "provider_resolution": build_provider_resolution_for_run(
            mode="council",
            params=params,
            principal=principal,
            exec_meta=exec_meta or {},
            routing_context=request.routing_context if request else None,
            teacher_meta=None,
            wash_trace=wash_trace,
        ),
    }
    if conversation_subject_dict:
        pay["conversation_subject"] = conversation_subject_dict
    if isinstance(res, dict) and "pending_ve_elicitation" in res:
        pay["pending_ve_elicitation"] = res.get("pending_ve_elicitation")
    return pay


def _run_council(
    params: RunParams,
    context: dict | None,
    request: RunRequest | None = None,
    *,
    execution_principal: ExecutionPrincipal,
) -> str:
    """Call run_council(question, context=..., included_roles=...). question required."""
    if not params or not (params.question or "").strip():
        raise ValueError("council requires params.question")
    # Reset per-run personality reporting; every path below sets it explicitly.
    setattr(_run_council, "_last_council_personality", None)
    question = params.question.strip()
    seat_question = (params.seat_question or "").strip() or None
    if request is not None:
        context_str = _resolve_council_context(
            request, resonance_user_id=execution_principal.account_user_id
        )
    else:
        context_str = None
        if context:
            if context.get("context_block") and isinstance(context["context_block"], str):
                context_str = context["context_block"].strip()
            elif context.get("folder_path") and isinstance(context["folder_path"], str):
                context_str = f"Folder: {context['folder_path'].strip()}"
    included = params.included_agents if params and params.included_agents else None
    definitions = getattr(params, "perspective_definitions", None) if params else None
    include_synthesis = getattr(params, "include_synthesis", None)
    subject_ref = getattr(params, "subject_ref", None)
    object_snapshot = getattr(params, "object_snapshot", None)
    allows_ext = _council_allows_externalization(request)
    council_preflight_dict = None
    conversation_subject_dict = None
    pending_integration_dict = None
    last_integration_commit_dict = None
    pending_ve_elicitation_dict = None
    if isinstance(context, dict):
        _cp = context.get("council_preflight")
        if isinstance(_cp, dict):
            council_preflight_dict = _cp
        _cs = context.get("conversation_subject")
        if isinstance(_cs, dict):
            conversation_subject_dict = _cs
        _pi = context.get("pending_integration")
        if isinstance(_pi, dict):
            pending_integration_dict = _pi
        _lic = context.get("last_integration_commit")
        if isinstance(_lic, dict):
            last_integration_commit_dict = _lic
        _pve = context.get("pending_ve_elicitation")
        if isinstance(_pve, dict):
            pending_ve_elicitation_dict = _pve
    from local_ai.council_wash import prepare_council_contexts

    native_ctx, cloud_ctx, wash_trace = prepare_council_contexts(context_str or "")
    effective_cloud = allows_ext and bool(wash_trace.get("safety_allow_cloud_with_wash"))
    setattr(_run_council, "_last_council_wash_trace", wash_trace)

    from local_ai.council_teacher import CouncilTeacherSettings, run_council_with_teacher
    from local_ai.vision_execution import storage as St

    cfg = St.get_studio_council_teacher_settings()
    s = CouncilTeacherSettings.from_dict(cfg)
    if getattr(params, "teacher_mode", None):
        s.teacher_mode = str(params.teacher_mode).strip().lower()
    _apply_council_teacher_mode_resolution(s, cfg, params, request)
    if getattr(params, "teacher_provider", None):
        s.teacher_provider = str(params.teacher_provider).strip().lower()
    if getattr(params, "teacher_model", None):
        s.teacher_model = str(params.teacher_model).strip()
    if getattr(params, "teacher_prompt_version", None):
        s.teacher_prompt_version = str(params.teacher_prompt_version).strip()

    np, nm = _council_native_provider_model_from_studio(
        cfg,
        effective_cloud=effective_cloud,
        params_native_provider=getattr(params, "native_provider", None),
        params_native_model=getattr(params, "native_model", None),
    )

    _int_event, _int_suffix = _council_integration_suffix_and_event(
        context, question, user_id=execution_principal.account_user_id
    )

    from local_ai.integration_commit import (
        deterministic_integration_ack_text,
        integration_event_requires_deterministic_ack,
    )

    if integration_event_requires_deterministic_ack(_int_event):
        setattr(_run_council, "_last_direct_ve_action", None)
        setattr(_run_council, "_last_teacher_meta", None)
        return deterministic_integration_ack_text(_int_event)

    from local_ai.vision_execution.direct_action_executor import (
        evaluate_direct_ve_action,
        should_skip_council_for_direct_result,
    )

    _dve = evaluate_direct_ve_action(
        question=question,
        context=context if isinstance(context, dict) else None,
        user_id=execution_principal.account_user_id,
    )
    if should_skip_council_for_direct_result(_dve):
        setattr(_run_council, "_last_direct_ve_action", _dve)
        setattr(_run_council, "_last_teacher_meta", None)
        return str(_dve.get("message") or "").strip()
    setattr(_run_council, "_last_direct_ve_action", None)

    # Keep existing behavior when teacher is off.
    if s.teacher_mode == "off":
        setattr(_run_council, "_last_teacher_meta", None)
        from local_ai.zenaf_tools import run_council

        _council_mode = getattr(params, "council_personality_mode", None)
        _res = run_council(
            question,
            context=native_ctx,
            included_roles=included,
            perspective_definitions=definitions,
            include_synthesis=include_synthesis,
            subject_ref=subject_ref,
            object_snapshot=object_snapshot,
            execution_principal=execution_principal,
            provider_override_id=np,
            provider_override_model=nm,
            allows_externalization=effective_cloud,
            context_for_cloud=cloud_ctx,
            council_wash_trace=wash_trace,
            force_full_council=getattr(params, "force_full_council", None),
            seat_question=seat_question,
            council_preflight_dict=council_preflight_dict,
            conversation_subject_dict=conversation_subject_dict,
            integration_packet_suffix=_int_suffix,
            integration_event_dict=_int_event,
            pending_integration_dict=pending_integration_dict,
            last_integration_commit_dict=last_integration_commit_dict,
            pending_ve_elicitation_dict=pending_ve_elicitation_dict,
            council_personality_mode=_council_mode,
            decision_context=getattr(params, "decision_context", None),
            return_artifact=True,
        )
        # run_council returns (text, artifact, run_debug) with return_artifact=True;
        # error paths may still return a bare string.
        if isinstance(_res, tuple):
            _text, _art, _dbg = _res[0], _res[1] if len(_res) > 1 else None, _res[2] if len(_res) > 2 else {}
            _rm = _dbg.get("run_meta") if isinstance(_dbg, dict) else {}
            setattr(
                _run_council,
                "_last_council_personality",
                {
                    "council_personality_mode": (_rm or {}).get("council_personality_mode"),
                    "mirror_empty_strands": (_rm or {}).get("mirror_empty_strands") or [],
                    "mirror_notice": (_rm or {}).get("mirror_notice"),
                },
            )
            return _text
        setattr(_run_council, "_last_council_personality", None)
        return _res

    packed = run_council_with_teacher(
        question=question,
        seat_question=seat_question,
        included_roles=included,
        perspective_definitions=definitions,
        include_synthesis=include_synthesis,
        subject_ref=subject_ref,
        object_snapshot=object_snapshot,
        execution_principal=execution_principal,
        settings=s,
        native_provider_override=np,
        native_model_override=nm,
        allows_externalization=effective_cloud,
        context_for_cloud=cloud_ctx,
        council_wash_trace=wash_trace,
        force_full_council=getattr(params, "force_full_council", None),
        council_preflight_dict=council_preflight_dict,
        conversation_subject_dict=conversation_subject_dict,
        integration_packet_suffix=_int_suffix,
        integration_event_dict=_int_event,
        pending_integration_dict=pending_integration_dict,
        last_integration_commit_dict=last_integration_commit_dict,
        pending_ve_elicitation_dict=pending_ve_elicitation_dict,
        council_personality_mode=getattr(params, "council_personality_mode", None),
    )
    rid = St.append_council_teacher_run(
        {
            "user_id": execution_principal.account_user_id,
            "execution_scope": execution_principal.scope,
            "execution_principal_ref": execution_principal.principal_ref,
            "capability_name": "council",
            "teacher_mode": s.teacher_mode,
            "final_selection_policy": packed.get("final_selection_policy"),
            "prompt_version": s.teacher_prompt_version,
            "native_provider": packed.get("native_provider"),
            "native_model": packed.get("native_model"),
            "teacher_provider_requested": s.teacher_provider,
            "teacher_model_requested": s.teacher_model,
            "teacher_provider_effective": packed.get("teacher_provider_effective"),
            "teacher_model_effective": packed.get("teacher_model_effective"),
            "teacher_succeeded": bool(packed.get("teacher_succeeded")),
            "native_text": packed.get("native_text"),
            "teacher_text": packed.get("teacher_text"),
            "native_artifact": packed.get("native_artifact"),
            "teacher_artifact": packed.get("teacher_artifact"),
            "native_run_debug": packed.get("native_run_debug"),
            "teacher_run_debug": packed.get("teacher_run_debug"),
            "comparison": packed.get("comparison"),
            "error": packed.get("teacher_error"),
            "teacher_enforcement_mode": packed.get("teacher_enforcement_mode"),
            "teacher_vetoed": packed.get("teacher_vetoed"),
            "teacher_warning": packed.get("teacher_warning"),
            "teacher_final_source": packed.get("teacher_final_source"),
            "teacher_reason_codes": packed.get("teacher_reason_codes"),
            "teacher_notes": packed.get("teacher_notes"),
        }
    )
    # Store run-local metadata for response wiring.
    _nat_debug = packed.get("native_run_debug") or {}
    _nat_meta = _nat_debug.get("run_meta") if isinstance(_nat_debug, dict) else {}
    _meta = {
        "teacher_mode": s.teacher_mode,
        "teacher_provider": s.teacher_provider,
        "teacher_model": s.teacher_model,
        "teacher_provider_effective": packed.get("teacher_provider_effective"),
        "teacher_model_effective": packed.get("teacher_model_effective"),
        "native_provider": packed.get("native_provider"),
        "native_model": packed.get("native_model"),
        "teacher_prompt_version": s.teacher_prompt_version,
        "teacher_succeeded": bool(packed.get("teacher_succeeded")),
        "teacher_artifact_id": rid,
        "teacher_skipped_reason": packed.get("teacher_skipped_reason"),
        "teacher_enforcement_mode": packed.get("teacher_enforcement_mode"),
        "teacher_vetoed": bool(packed.get("teacher_vetoed")),
        "teacher_warning": bool(packed.get("teacher_warning")),
        "teacher_final_source": packed.get("teacher_final_source"),
        "teacher_reason_codes": packed.get("teacher_reason_codes") or [],
        "teacher_notes": packed.get("teacher_notes"),
        "council_native_attachment_trace": _nat_meta.get("council_native_attachment_trace")
        if isinstance(_nat_meta, dict)
        else None,
        "council_wash_trace": wash_trace,
        "council_personality_mode": _nat_meta.get("council_personality_mode")
        if isinstance(_nat_meta, dict)
        else None,
        "mirror_empty_strands": _nat_meta.get("mirror_empty_strands")
        if isinstance(_nat_meta, dict)
        else [],
        "mirror_notice": _nat_meta.get("mirror_notice") if isinstance(_nat_meta, dict) else None,
    }
    setattr(_run_council, "_last_teacher_meta", _meta)
    setattr(
        _run_council,
        "_last_council_personality",
        {
            "council_personality_mode": _meta["council_personality_mode"],
            "mirror_empty_strands": _meta["mirror_empty_strands"],
            "mirror_notice": _meta["mirror_notice"],
        },
    )
    return str(packed.get("selected_text") or "")


# --- Folder workflow: internal web escalation for ambiguity (no user-facing web research) ---

_WEAK_DOMAINS = frozenset({"", "misc", "general", "mixed", "unknown", "files", "other"})
_MAX_AMBIGUITY_QUERIES = 2
_MAX_WEB_CONTEXT_CHARS = 400


def _is_weak_domain(domain: str | None) -> bool:
    if not domain or not isinstance(domain, str):
        return True
    d = domain.strip().lower()
    if len(d) < 3:
        return True
    return d in _WEAK_DOMAINS


def _folder_ambiguity_trigger(signals: dict | None) -> bool:
    """Trigger internal web escalation only when low confidence or weak domain (not repeated_tokens alone)."""
    if not signals or not isinstance(signals, dict):
        return False
    low = signals.get("low_confidence_count")
    if isinstance(low, (int, float)) and low > 0:
        return True
    domain = signals.get("inferred_context_domain")
    if _is_weak_domain(domain):
        return True
    return False


def _build_ambiguity_queries(signals: dict | None) -> list[str]:
    """Build up to 2 queries for term/domain disambiguation (not folder-organization advice)."""
    if not signals or not isinstance(signals, dict):
        return []
    queries: list[str] = []
    domain = (signals.get("inferred_context_domain") or "").strip().lower()
    tokens = signals.get("repeated_tokens")
    if isinstance(tokens, list) and tokens:
        # Use first 1–2 tokens for meaning/domain context
        terms = [str(t).strip() for t in tokens[:2] if t and len(str(t).strip()) >= 2]
        if terms:
            queries.append(f"{' '.join(terms)} meaning domain context")
    if _is_weak_domain(domain) and domain and len(queries) < _MAX_AMBIGUITY_QUERIES:
        queries.append(f"{domain} domain context")
    return queries[: _MAX_AMBIGUITY_QUERIES]


def _enrich_context_with_ambiguity_resolution(context_str: str | None, signals: dict | None) -> str | None:
    """If trigger fires, run internal web_research (max 2 queries), append compact block to context_str."""
    if not _folder_ambiguity_trigger(signals):
        return context_str
    queries = _build_ambiguity_queries(signals)
    if not queries:
        return context_str
    try:
        from local_ai.zenaf_tools import web_research
    except ImportError:
        return context_str
    findings: list[str] = []
    for q in queries:
        raw = web_research(q)
        if raw.get("error"):
            continue
        for f in raw.get("findings") or []:
            if f and isinstance(f, str):
                findings.append(f.strip()[:120])
    if not findings:
        return context_str
    block = "Web context (ambiguity resolution; use only to disambiguate folder meaning):\n• " + "\n• ".join(findings[:5])
    if len(block) > _MAX_WEB_CONTEXT_CHARS:
        block = block[:_MAX_WEB_CONTEXT_CHARS].rsplit("\n", 1)[0] + "\n…"
    base = (context_str or "").strip()
    return f"{base}\n\n{block}" if base else block


def _council_stream_gen(
    params: RunParams,
    context: dict | None,
    request: RunRequest | None = None,
    *,
    execution_principal: ExecutionPrincipal,
    exec_meta: dict | None = None,
):
    """Generator for council SSE: yields 'data: {...}\n\n' for each chunk."""
    from local_ai.execution_policy.provider_default_inspect import build_provider_resolution_for_run

    perf_mark("_council_stream_gen_enter")

    if not params or not (params.question or "").strip():
        yield f"data: {json.dumps({'chunk': '', 'done': True, 'error': 'council requires params.question'})}\n\n"
        return
    question = params.question.strip()
    seat_question = (params.seat_question or "").strip() or None
    if request is not None:
        perf_mark("_council_stream_gen_before_resolve_council_context")
        context_str = _resolve_council_context(
            request, resonance_user_id=execution_principal.account_user_id
        )
        perf_mark("_council_stream_gen_after_resolve_council_context", context_len=len(context_str or ""))
    else:
        context_str = None
        if context:
            if context.get("context_block") and isinstance(context["context_block"], str):
                context_str = context["context_block"].strip()
            elif context.get("folder_path") and isinstance(context["folder_path"], str):
                context_str = f"Folder: {context['folder_path'].strip()}"
    folder_workflow = (context or {}).get("workflow_kind") == "folder"
    if folder_workflow and context and context.get("ambiguity_signals"):
        context_str = _enrich_context_with_ambiguity_resolution(context_str, context.get("ambiguity_signals"))
    included = params.included_agents if params and params.included_agents else None
    definitions = getattr(params, "perspective_definitions", None) if params else None
    include_synthesis = getattr(params, "include_synthesis", None)
    subject_ref = getattr(params, "subject_ref", None)
    object_snapshot = getattr(params, "object_snapshot", None)
    allows_ext = _council_allows_externalization(request)
    from local_ai.council_wash import prepare_council_contexts

    perf_mark("_council_stream_gen_before_prepare_council_contexts")
    native_ctx, cloud_ctx, wash_trace = prepare_council_contexts(context_str or "")
    perf_mark(
        "_council_stream_gen_after_prepare_council_contexts",
        native_len=len(native_ctx or ""),
        cloud_len=len(cloud_ctx or ""),
    )
    effective_cloud = allows_ext and bool(wash_trace.get("safety_allow_cloud_with_wash"))
    setattr(_council_stream_gen, "_last_council_wash_trace", wash_trace)

    perf_mark("_council_stream_gen_before_teacher_settings_load")
    from local_ai.council_teacher import CouncilTeacherSettings, run_council_with_teacher
    from local_ai.vision_execution import storage as St

    cfg = St.get_studio_council_teacher_settings()
    s = CouncilTeacherSettings.from_dict(cfg)
    if getattr(params, "teacher_mode", None):
        s.teacher_mode = str(params.teacher_mode).strip().lower()
    _apply_council_teacher_mode_resolution(s, cfg, params, request)
    if getattr(params, "teacher_provider", None):
        s.teacher_provider = str(params.teacher_provider).strip().lower()
    if getattr(params, "teacher_model", None):
        s.teacher_model = str(params.teacher_model).strip()
    if getattr(params, "teacher_prompt_version", None):
        s.teacher_prompt_version = str(params.teacher_prompt_version).strip()

    perf_mark("_council_stream_gen_before_native_provider_model_from_studio")
    np_s, nm_s = _council_native_provider_model_from_studio(
        cfg,
        effective_cloud=effective_cloud,
        params_native_provider=getattr(params, "native_provider", None),
        params_native_model=getattr(params, "native_model", None),
    )
    perf_mark("_council_stream_gen_after_native_provider_model_from_studio")

    _stream_preflight = (context or {}).get("council_preflight")
    if _stream_preflight is not None and not isinstance(_stream_preflight, dict):
        _stream_preflight = None
    _stream_conv_subj = (context or {}).get("conversation_subject")
    if _stream_conv_subj is not None and not isinstance(_stream_conv_subj, dict):
        _stream_conv_subj = None
    _stream_pending = (context or {}).get("pending_integration")
    if _stream_pending is not None and not isinstance(_stream_pending, dict):
        _stream_pending = None
    _stream_last_commit = (context or {}).get("last_integration_commit")
    if _stream_last_commit is not None and not isinstance(_stream_last_commit, dict):
        _stream_last_commit = None
    _stream_ve_elicitation = (context or {}).get("pending_ve_elicitation")
    if _stream_ve_elicitation is not None and not isinstance(_stream_ve_elicitation, dict):
        _stream_ve_elicitation = None
    _int_event_s, _int_suffix_s = _council_integration_suffix_and_event(
        context, question, user_id=execution_principal.account_user_id
    )

    _det_pay = _council_deterministic_commit_sse_pay(
        int_event=_int_event_s,
        conversation_subject_dict=_stream_conv_subj,
        wash_trace=wash_trace,
        params=params,
        principal=execution_principal,
        exec_meta=exec_meta,
        request=request,
    )
    if _det_pay is not None:
        perf_mark("_council_stream_gen_deterministic_commit_bypass")
        yield f"data: {json.dumps(_det_pay)}\n\n"
        return

    _dve_pay = _council_direct_ve_sse_pay(
        question=question,
        context=context,
        conversation_subject_dict=_stream_conv_subj,
        wash_trace=wash_trace,
        params=params,
        principal=execution_principal,
        exec_meta=exec_meta,
        request=request,
    )
    if _dve_pay is not None:
        perf_mark("_council_stream_gen_direct_ve_bypass")
        yield f"data: {json.dumps(_dve_pay)}\n\n"
        return

    if s.teacher_mode in ("shadow", "warn", "veto", "replace"):
        perf_mark(
            "_council_stream_gen_teacher_branch_enter",
            teacher_mode=s.teacher_mode,
        )
        packed = run_council_with_teacher(
            question=question,
            seat_question=seat_question,
            context=native_ctx,
            included_roles=included,
            perspective_definitions=definitions,
            include_synthesis=include_synthesis,
            subject_ref=subject_ref,
            object_snapshot=object_snapshot,
            execution_principal=execution_principal,
            settings=s,
            native_provider_override=np_s,
            native_model_override=nm_s,
            allows_externalization=effective_cloud,
            context_for_cloud=cloud_ctx,
            council_wash_trace=wash_trace,
            force_full_council=getattr(params, "force_full_council", None),
            council_preflight_dict=_stream_preflight,
            conversation_subject_dict=_stream_conv_subj,
            integration_packet_suffix=_int_suffix_s,
            integration_event_dict=_int_event_s,
            pending_integration_dict=_stream_pending,
            last_integration_commit_dict=_stream_last_commit,
            pending_ve_elicitation_dict=_stream_ve_elicitation,
            council_personality_mode=getattr(params, "council_personality_mode", None),
        )
        perf_mark(
            "_council_stream_gen_after_run_council_with_teacher",
            selected_len=len(str(packed.get("selected_text") or "")),
        )
        rid = St.append_council_teacher_run(
            {
                "user_id": execution_principal.account_user_id,
                "execution_scope": execution_principal.scope,
                "execution_principal_ref": execution_principal.principal_ref,
                "capability_name": "council",
                "teacher_mode": s.teacher_mode,
                "final_selection_policy": packed.get("final_selection_policy"),
                "prompt_version": s.teacher_prompt_version,
                "native_provider": packed.get("native_provider"),
                "native_model": packed.get("native_model"),
                "teacher_provider_requested": s.teacher_provider,
                "teacher_model_requested": s.teacher_model,
                "teacher_provider_effective": packed.get("teacher_provider_effective"),
                "teacher_model_effective": packed.get("teacher_model_effective"),
                "teacher_succeeded": bool(packed.get("teacher_succeeded")),
                "native_text": packed.get("native_text"),
                "teacher_text": packed.get("teacher_text"),
                "native_artifact": packed.get("native_artifact"),
                "teacher_artifact": packed.get("teacher_artifact"),
                "native_run_debug": packed.get("native_run_debug"),
                "teacher_run_debug": packed.get("teacher_run_debug"),
                "comparison": packed.get("comparison"),
                "error": packed.get("teacher_error"),
                "teacher_enforcement_mode": packed.get("teacher_enforcement_mode"),
                "teacher_vetoed": packed.get("teacher_vetoed"),
                "teacher_warning": packed.get("teacher_warning"),
                "teacher_final_source": packed.get("teacher_final_source"),
                "teacher_reason_codes": packed.get("teacher_reason_codes"),
                "teacher_notes": packed.get("teacher_notes"),
            }
        )
        _snd = packed.get("native_run_debug") or {}
        _snm = _snd.get("run_meta") if isinstance(_snd, dict) else {}
        meta = {
            "teacher_mode": s.teacher_mode,
            "teacher_provider": s.teacher_provider,
            "teacher_model": s.teacher_model,
            "teacher_provider_effective": packed.get("teacher_provider_effective"),
            "teacher_model_effective": packed.get("teacher_model_effective"),
            "native_provider": packed.get("native_provider"),
            "native_model": packed.get("native_model"),
            "teacher_prompt_version": s.teacher_prompt_version,
            "teacher_succeeded": bool(packed.get("teacher_succeeded")),
            "teacher_artifact_id": rid,
            "teacher_skipped_reason": packed.get("teacher_skipped_reason"),
            "teacher_enforcement_mode": packed.get("teacher_enforcement_mode"),
            "teacher_vetoed": bool(packed.get("teacher_vetoed")),
            "teacher_warning": bool(packed.get("teacher_warning")),
            "teacher_final_source": packed.get("teacher_final_source"),
            "teacher_reason_codes": packed.get("teacher_reason_codes") or [],
            "teacher_notes": packed.get("teacher_notes"),
            "council_native_attachment_trace": _snm.get("council_native_attachment_trace")
            if isinstance(_snm, dict)
            else None,
            "council_wash_trace": wash_trace,
        }
        if isinstance(_snm, dict):
            for _k in (
                "conversation_subject",
                "pending_integration",
                "pending_ve_elicitation",
                "last_integration_commit",
                "integration_commit",
                "council_personality_mode",
                "mirror_empty_strands",
                "mirror_notice",
            ):
                if _k in _snm:
                    meta[_k] = _snm[_k]
        setattr(_council_stream_gen, "_last_teacher_meta", meta)
        selected = str(packed.get("selected_text") or "")
        meta["provider_resolution"] = build_provider_resolution_for_run(
            mode="council",
            params=params,
            principal=execution_principal,
            exec_meta=exec_meta or {},
            routing_context=request.routing_context if request else None,
            teacher_meta=meta,
            wash_trace=wash_trace,
        )
        perf_mark("_council_stream_gen_teacher_branch_yield_done", selected_len=len(selected))
        yield f"data: {json.dumps({'chunk': selected, 'done': True, **meta})}\n\n"
        return

    perf_mark("_council_stream_gen_no_teacher_path", teacher_mode=getattr(s, "teacher_mode", None))
    setattr(_council_stream_gen, "_last_teacher_meta", None)
    from local_ai.zenaf_tools import run_council_stream

    council_integrity_run_id = str(uuid.uuid4())
    council_preflight_dict = _stream_preflight
    conversation_subject_dict = _stream_conv_subj

    perf_mark("_council_stream_gen_before_run_council_stream_iter")
    _yield_i = 0
    for chunk, done, extra in run_council_stream(
        question,
        context=native_ctx,
        included_roles=included,
        perspective_definitions=definitions,
        include_synthesis=include_synthesis,
        subject_ref=subject_ref,
        object_snapshot=object_snapshot,
        folder_workflow=folder_workflow,
        execution_principal=execution_principal,
        allows_externalization=effective_cloud,
        context_for_cloud=cloud_ctx,
        council_integrity_run_id=council_integrity_run_id,
        council_preflight_dict=council_preflight_dict,
        council_wash_trace=wash_trace,
        council_routing_allows_externalization=allows_ext,
        council_routing_effective_cloud=effective_cloud,
        force_full_council=getattr(params, "force_full_council", None),
        seat_question=seat_question,
        conversation_subject_dict=conversation_subject_dict,
        integration_packet_suffix=_int_suffix_s,
        integration_event_dict=_int_event_s,
        pending_integration_dict=_stream_pending,
        last_integration_commit_dict=_stream_last_commit,
        pending_ve_elicitation_dict=_stream_ve_elicitation,
        council_personality_mode=getattr(params, "council_personality_mode", None),
    ):
        perf_mark(
            "_council_stream_gen_run_council_stream_tuple_received",
            i=_yield_i,
            done=done,
            chunk_len=len(chunk or ""),
        )
        pay: dict = {"chunk": chunk, "done": done}
        if isinstance(extra, dict):
            for k, v in extra.items():
                if k in ("chunk", "done"):
                    continue
                pay[k] = v
        if done:
            pay["council_wash_trace"] = wash_trace
            pay["provider_resolution"] = build_provider_resolution_for_run(
                mode="council",
                params=params,
                principal=execution_principal,
                exec_meta=exec_meta or {},
                routing_context=request.routing_context if request else None,
                teacher_meta=None,
                wash_trace=wash_trace,
            )
            if isinstance(extra, dict):
                _council_aid = extra.get("council_artifact_id")
                if _council_aid:
                    pay["council_artifact_id"] = _council_aid
        perf_mark("_council_stream_gen_before_yield_sse_line", i=_yield_i, done=done)
        yield f"data: {json.dumps(pay)}\n\n"
        _yield_i += 1


@app.post("/run", response_model=RunResponse)
def run(body: RunRequest, http_request: Request):
    """
    Run one cockpit mode. Supported: analyze, simulate, assess_uncertainty, recommend, council, web_research, next_step.
    Others return 501.
    """
    import time as _time
    # #region agent log
    _t0 = _time.perf_counter()
    mode = (body.mode or "").strip().lower()
    _log_path = _repo_root / "debug-5581d2.log"
    try:
        with open(_log_path, "a", encoding="utf-8") as _f:
            _f.write(json.dumps({"sessionId": "5581d2", "hypothesisId": "H4", "location": "api/main.py:run", "message": "POST /run start", "data": {"mode": mode}, "timestamp": int(_time.time() * 1000)}) + "\n")
    except Exception:
        pass
    # #endregion

    from local_ai.llm.execution_principal import resolve_execution_principal_for_run_http

    principal, principal_err = resolve_execution_principal_for_run_http(
        request=http_request,
        execution_scope_raw=body.execution_scope,
    )
    if principal_err:
        if "Invalid execution_scope" in principal_err:
            p_code = 400
        elif "not configured" in principal_err.lower():
            p_code = 503
        else:
            p_code = 403
        raise HTTPException(status_code=p_code, detail=principal_err)

    rt_token, exec_meta = _begin_run_routing(body, execution_principal=principal)
    _log_council_routing_trace(mode, body, exec_meta)
    if body.routing_context is not None:
        logger.info(
            "POST /run execution_routing: mode=%s scope=%s principal_ref=%r provider_used=%r model_used=%r routing_override=%s execution_blocked=%s",
            mode,
            exec_meta.get("execution_scope"),
            exec_meta.get("execution_principal_ref"),
            exec_meta.get("provider_used"),
            exec_meta.get("model_used"),
            exec_meta.get("routing_override_active"),
            exec_meta.get("execution_blocked"),
        )

    params = body.params or RunParams()
    from local_ai.execution_policy.provider_default_inspect import build_provider_resolution_for_run

    def R(ok: bool, result=None, error=None, **extra):
        b: dict = {"ok": ok, "result": result, "error": error, **extra}
        if exec_meta:
            b.update(exec_meta)
        # Echo execution identity even when routing_context is absent (e.g. bare POST /run council).
        if principal is not None:
            b.setdefault("execution_scope", principal.scope)
            b.setdefault("execution_principal_ref", principal.principal_ref)
            b.setdefault("credential_namespace", principal.credential_namespace)
            b.setdefault("policy_namespace", principal.policy_namespace)
        tm = getattr(_run_council, "_last_teacher_meta", None) if mode == "council" else None
        wtr = getattr(_run_council, "_last_council_wash_trace", None) if mode == "council" else None
        dva = getattr(_run_council, "_last_direct_ve_action", None) if mode == "council" else None
        if mode == "council" and dva is not None:
            b["direct_ve_action"] = dva
        if mode == "council" and wtr is not None:
            b["council_wash_trace"] = wtr
        b["provider_resolution"] = build_provider_resolution_for_run(
            mode=mode,
            params=params,
            principal=principal,
            exec_meta=exec_meta or {},
            routing_context=body.routing_context,
            teacher_meta=tm,
            wash_trace=wtr,
        )
        return RunResponse(**b)

    if exec_meta.get("execution_blocked"):
        _end_run_routing(rt_token)
        return RunResponse(
            ok=False,
            result=None,
            error=exec_meta.get("error_detail") or "Execution blocked by privacy policy",
            execution_blocked=True,
            privacy_block_reason=exec_meta.get("privacy_block_reason"),
            model_used=None,
            provider_used=None,
            routing_override_active=False,
            openai_key_source=exec_meta.get("openai_key_source"),
            execution_scope=exec_meta.get("execution_scope"),
            execution_principal_ref=exec_meta.get("execution_principal_ref"),
            credential_namespace=exec_meta.get("credential_namespace"),
            policy_namespace=exec_meta.get("policy_namespace"),
            provider_resolution=build_provider_resolution_for_run(
                mode=mode,
                params=params,
                principal=principal,
                exec_meta=exec_meta or {},
                routing_context=body.routing_context,
                teacher_meta=None,
                wash_trace=None,
            ),
        )
    try:
        if mode == "analyze":
            try:
                result = _run_analyze(params)
                return R(ok=True, result=result)
            except ValueError as e:
                raise HTTPException(status_code=400, detail=str(e))
            except Exception as e:
                return R(ok=False, error=str(e))

        if mode == "simulate":
            try:
                result = _run_simulate(params)
                return R(ok=True, result=result)
            except ValueError as e:
                raise HTTPException(status_code=400, detail=str(e))
            except Exception as e:
                return R(ok=False, error=str(e))

        if mode == "assess_uncertainty":
            try:
                result = _run_assess_uncertainty(params)
                if result.get("error"):
                    return R(ok=False, error=result["error"])
                return R(ok=True, result=result)
            except ValueError as e:
                raise HTTPException(status_code=400, detail=str(e))
            except Exception as e:
                return R(ok=False, error=str(e))

        if mode == "reassess_low_confidence":
            try:
                result = _run_reassess_low_confidence(params)
                if isinstance(result, dict) and result.get("error"):
                    return R(ok=False, error=result["error"])
                return R(ok=True, result=result)
            except ValueError as e:
                raise HTTPException(status_code=400, detail=str(e))
            except Exception as e:
                return R(ok=False, error=str(e))

        if mode == "council":
            try:
                result = _run_council(
                    params,
                    body.context,
                    body,
                    execution_principal=principal,
                )
                if isinstance(result, str) and result.strip().startswith("Error:"):
                    return R(ok=False, error=result.strip())
                tmeta = getattr(_run_council, "_last_teacher_meta", None) or {}
                pmeta = getattr(_run_council, "_last_council_personality", None) or {}
                return R(ok=True, result=result, **tmeta, **pmeta)
            except ValueError as e:
                raise HTTPException(status_code=400, detail=str(e))
            except Exception as e:
                return R(ok=False, error=str(e))

        if mode == "recommend":
            try:
                result = _run_recommend(params)
                if result.get("error"):
                    return R(ok=False, error=result["error"])
                return R(ok=True, result=result)
            except ValueError as e:
                raise HTTPException(status_code=400, detail=str(e))
            except Exception as e:
                return R(ok=False, error=str(e))

        if mode == "web_research":
            try:
                result = _run_web_research(params)
                if result.get("error"):
                    return R(ok=False, error=result["error"])
                return R(ok=True, result=result)
            except ValueError as e:
                raise HTTPException(status_code=400, detail=str(e))
            except Exception as e:
                return R(ok=False, error=str(e))

        if mode == "next_step":
            try:
                rc_payload = None
                priv_m = None
                if body.routing_context is not None:
                    rc = body.routing_context
                    rc_payload = {
                        "surface": rc.surface,
                        "action_kind": rc.action_kind,
                        "action_intent": rc.action_intent,
                        "streaming": rc.streaming,
                        "sensitivity": rc.sensitivity,
                        "privacy_mode": getattr(rc, "privacy_mode", None),
                    }
                    priv_m = getattr(rc, "privacy_mode", None)
                result, ext_x = _run_next_step(
                    params,
                    body.context,
                    exec_meta=exec_meta,
                    routing_payload=rc_payload,
                    privacy_mode=priv_m,
                )
                if result.get("error"):
                    return R(ok=False, error=result["error"], **ext_x)
                return R(ok=True, result=result, **ext_x)
            except Exception as e:
                return R(ok=False, error=str(e))

        if mode in ("content_script", "content_newsletter"):
            try:
                result = _run_content_generate(params, execution_principal=principal)
                if isinstance(result, str) and result.strip().startswith("Error:"):
                    return R(ok=False, error=result.strip())
                return R(ok=True, result=result)
            except Exception as e:
                return R(ok=False, error=str(e))

        # Placeholder for other modes
        raise HTTPException(
            status_code=501,
            detail=f"Mode '{body.mode}' not implemented. Use mode=analyze, simulate, assess_uncertainty, reassess_low_confidence, recommend, council, web_research, next_step, content_script, or content_newsletter.",
        )
    finally:
        _end_run_routing(rt_token)
        _dur = int((_time.perf_counter() - _t0) * 1000)
        try:
            with open(_log_path, "a", encoding="utf-8") as _f:
                _f.write(json.dumps({"sessionId": "5581d2", "hypothesisId": "H4", "location": "api/main.py:run", "message": "POST /run end", "data": {"mode": mode, "duration_ms": _dur}, "timestamp": int(_time.time() * 1000)}) + "\n")
        except Exception:
            pass


@app.post("/run/stream")
def run_stream(body: RunRequest, http_request: Request):
    """
    Streaming run: only mode=council supported. Returns Server-Sent Events;
    each event is data: {"chunk": "...", "done": false} or {"chunk": "...", "done": true}.
    """
    import time as _time
    # #region agent log
    _t0 = _time.perf_counter()
    mode = (body.mode or "").strip().lower()
    _log_path = _repo_root / "debug-5581d2.log"
    try:
        with open(_log_path, "a", encoding="utf-8") as _f:
            _f.write(json.dumps({"sessionId": "5581d2", "hypothesisId": "H4", "location": "api/main.py:run_stream", "message": "POST /run/stream start", "data": {"mode": mode}, "timestamp": int(_time.time() * 1000)}) + "\n")
    except Exception:
        pass
    # #endregion
    if mode != "council":
        raise HTTPException(status_code=400, detail="Streaming only supported for mode=council")
    perf_correlation_id = str(uuid.uuid4())
    perf_begin(perf_correlation_id)
    perf_mark("run_stream_entry", question_len=len((body.params.question or "").strip()) if body.params else 0)
    params = body.params or RunParams()
    from local_ai.llm.execution_principal import resolve_execution_principal_for_run_http

    perf_mark("run_stream_before_resolve_execution_principal")
    principal_s, principal_err_s = resolve_execution_principal_for_run_http(
        request=http_request,
        execution_scope_raw=body.execution_scope,
    )
    perf_mark("run_stream_after_resolve_execution_principal", ok=not bool(principal_err_s))
    if principal_err_s:
        if "Invalid execution_scope" in principal_err_s:
            s_code = 400
        elif "not configured" in principal_err_s.lower():
            s_code = 503
        else:
            s_code = 403
        raise HTTPException(status_code=s_code, detail=principal_err_s)

    # Stream preflight: resolve policy metadata for headers/blocking without mutating ContextVar overrides yet.
    perf_mark("run_stream_before_begin_run_routing_preflight")
    rt_token, exec_meta = _begin_run_routing(body, execution_principal=principal_s, apply_overrides=False)
    perf_mark(
        "run_stream_after_begin_run_routing_preflight",
        provider_used=exec_meta.get("provider_used"),
        model_used=exec_meta.get("model_used"),
        execution_blocked=bool(exec_meta.get("execution_blocked")),
    )
    _log_council_routing_trace(mode, body, exec_meta)
    if body.routing_context is not None:
        logger.info(
            "POST /run/stream execution_routing: mode=%s scope=%s principal_ref=%r provider_used=%r model_used=%r routing_override=%s execution_blocked=%s",
            mode,
            exec_meta.get("execution_scope"),
            exec_meta.get("execution_principal_ref"),
            exec_meta.get("provider_used"),
            exec_meta.get("model_used"),
            exec_meta.get("routing_override_active"),
            exec_meta.get("execution_blocked"),
        )
    if exec_meta.get("execution_blocked"):
        _end_run_routing(rt_token)
        raise HTTPException(
            status_code=403,
            detail={
                "message": exec_meta.get("error_detail") or "Execution blocked by privacy policy",
                "execution_blocked": True,
                "privacy_block_reason": exec_meta.get("privacy_block_reason"),
            },
        )
    # Pre-flight: if the resolved provider is Ollama, verify it is reachable
    # BEFORE the SSE stream starts. A dead Ollama mid-stream kills the
    # response opaquely (mobile clients surface it as "Load failed"); failing
    # here returns a clean, actionable 502 instead.
    try:
        _preflight_ollama_reachable(exec_meta.get("provider_used"))
    except HTTPException:
        _end_run_routing(rt_token)
        raise
    headers: dict[str, str] = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
    if exec_meta.get("model_used"):
        headers["X-Zenaf-Model-Used"] = str(exec_meta["model_used"])
    if exec_meta.get("provider_used"):
        headers["X-Zenaf-Provider-Used"] = str(exec_meta["provider_used"])
    if "routing_override_active" in exec_meta:
        headers["X-Zenaf-Routing-Override"] = "1" if exec_meta["routing_override_active"] else "0"
    if exec_meta.get("execution_principal_ref"):
        headers["X-Zenaf-Execution-Principal"] = str(exec_meta["execution_principal_ref"])
    if exec_meta.get("execution_scope"):
        headers["X-Zenaf-Execution-Scope"] = str(exec_meta["execution_scope"])
    headers["X-Zenaf-Perf-Run-Id"] = perf_correlation_id

    def _stream_body():
        _cid = _stream_perf_cid or perf_correlation_id
        _anchor = _stream_perf_anchor

        def _perf_resume() -> None:
            # Generator may resume on a different threadpool worker after each yield; ContextVars do not persist.
            perf_restore(_cid, _anchor)

        _perf_resume()
        # Immediate SSE line so clients and dev proxies see bytes before any LLM work.
        # Vite's http-proxy default timeout is 120s waiting on the target; without an early chunk,
        # some stacks also defer surfacing the response until the first body write.
        perf_mark("stream_body_before_yield_stream_open")
        yield f"data: {json.dumps({'stream_open': True})}\n\n"
        _perf_resume()
        perf_mark("stream_body_after_yield_stream_open")
        # Advance the stream generator in steps; each step gets its own routing override scope.
        # This keeps ContextVar token setup/reset in the same call context and avoids cross-context reset errors.
        perf_mark("stream_body_before_construct_council_stream_gen")
        inner = _council_stream_gen(
            params,
            body.context,
            body,
            execution_principal=principal_s,
            exec_meta=exec_meta,
        )
        perf_mark("stream_body_after_construct_council_stream_gen")
        _iter_n = 0
        while True:
            _perf_resume()
            perf_mark("stream_body_loop_before_begin_run_routing", iteration=_iter_n)
            rt_token_stream, _ = _begin_run_routing(body, execution_principal=principal_s, apply_overrides=True)
            try:
                perf_mark("stream_body_loop_before_next_inner", iteration=_iter_n)
                item = next(inner)
                perf_mark("stream_body_loop_after_next_inner", iteration=_iter_n, sse_len=len(item) if item else 0)
            except StopIteration:
                perf_mark("stream_body_loop_stop_iteration", iteration=_iter_n)
                return
            finally:
                _end_run_routing(rt_token_stream)
            yield item
            _iter_n += 1

    try:
        perf_mark("run_stream_immediately_before_return_streaming_response")
        # StreamingResponse body runs in Starlette's thread pool; ContextVars do not copy across.
        _stream_perf_cid, _stream_perf_anchor = perf_read_context()
        return StreamingResponse(
            _stream_body(),
            media_type="text/event-stream",
            headers=headers,
        )
    except ValueError as e:
        _end_run_routing(rt_token)
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/health")
def health():
    """Simple health check for dev and deployment."""
    return {"status": "ok", "service": "zenaf-api"}


@app.get("/healthz")
def healthz():
    """Platform health check (load balancers expect /healthz)."""
    return {"ok": True}


# --- Hosted mode: serve the built frontend ---------------------------------
# In production (ZENAF_PROD=1) the Docker image bakes the Vite build into
# api/static/. API routes above take precedence (registered first); anything
# else serves the SPA. Dev behavior is unchanged (no static dir present).
_STATIC_DIR = _repo_root / "api" / "static"
_SPA_INDEX = _STATIC_DIR / "index.html"
# Prefixes that must never fall through to the SPA (real 404s, not index.html).
_SPA_EXCLUDED_PREFIXES = (
    "/run",
    "/auth",
    "/transcripts",
    "/settings",
    "/studio",
    "/transcribe",
    "/vision-execution",
    "/ingest",
    "/identity",
    "/health",
    "/healthz",
    "/folder-picker",
    "/docs",
    "/redoc",
    "/openapi.json",
)

if _is_prod() and _SPA_INDEX.is_file():
    from fastapi.responses import FileResponse

    @app.get("/{full_path:path}")
    def _spa_fallback(full_path: str):
        # Serve real static files (favicon, manifest, hashed assets) when present.
        # Guard against path traversal: resolved candidate must stay under _STATIC_DIR.
        if full_path:
            _candidate = (_STATIC_DIR / full_path).resolve()
            if _STATIC_DIR.resolve() in _candidate.parents and _candidate.is_file():
                return FileResponse(str(_candidate))
        # API namespaces must 404 honestly, never fall through to the SPA.
        if any(("/" + full_path).startswith(p) for p in _SPA_EXCLUDED_PREFIXES):
            raise HTTPException(status_code=404, detail="Not found")
        # Never let browsers cache the SPA shell: a stale index.html points at
        # the previous deploy's hashed bundles, so phones keep showing the old
        # app after a release. Hashed assets under /assets/ stay cached.
        return FileResponse(
            str(_SPA_INDEX),
            headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
        )
