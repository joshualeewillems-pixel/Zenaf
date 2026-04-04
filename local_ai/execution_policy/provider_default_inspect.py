"""
Read-only inspection of implicit provider defaults, policy planes, and per-run resolution traces.

Does not call generate() or mutate execution contextvars. Safe to invoke from Studio and POST /run responses.
"""

from __future__ import annotations

import os
from typing import Any, Mapping

from local_ai.llm.execution_principal import (
    ExecutionPrincipal,
    anonymous_account_principal,
    authenticated_account_principal,
    system_principal,
)
from local_ai.llm.provider_registry import (
    EXECUTION_PROVIDER_IDS,
    display_name,
    execution_provider_gate_for_principal,
    is_provider_configured_for_principal,
    normalize_provider_id,
)
from local_ai.execution_policy.load import load_execution_policy_config
from local_ai.execution_policy.openai_credentials import (
    openai_env_key_present,
    openai_settings_key_present,
    resolve_openai_api_key,
)
from local_ai.execution_policy.resolve import resolve_execution_policy_for_action
from local_ai.execution_policy.types import ActionRoutingContext
from local_ai.execution_policy.privacy_apply import ExecutionPolicyBlocked


# --- Task 1: documented implicit sources (static + pointers) ---

IMPLICIT_DEFAULT_SOURCES: list[dict[str, Any]] = [
    {
        "id": "resolver_general",
        "summary": "Non-council LLM: policy provider override → Ollama model override → profile default_provider (else ollama) → cloud key or block.",
        "ollama_selected_when": "default_provider is ollama or unset; or routed Ollama model override is set.",
        "openai_suggested_when": "profile default_provider is openai (or other cloud) with resolvable API key.",
        "fallback_when": "Cloud selected but no key → BlockedLLMAdapter message (no silent cloud).",
        "code_refs": ["local_ai/llm/resolver.py:get_llm_adapter_for_principal"],
    },
    {
        "id": "resolver_council",
        "summary": "Council without native_provider override: policy override → Ollama model override → ATRIA_COUNCIL_MODEL / config OLLAMA_COUNCIL_MODEL → profile ollama_model (else config OLLAMA_MODEL).",
        "ollama_selected_when": "Default council path uses local Ollama (not profile default cloud).",
        "openai_suggested_when": "Only when native_provider (or teacher) override requests a cloud id with a key.",
        "fallback_when": "Per-seat explicit provider may fall back to default_provider with a note (council_seat_provider).",
        "code_refs": ["local_ai/llm/resolver.py:get_council_llm_adapter_for_principal", "local_ai/llm/council_seat_provider.py:build_council_seat_provider"],
    },
    {
        "id": "seam_routing",
        "summary": "When routing_context is present on POST /run: resolve ai_execution_policy.json → push Ollama model token or OpenAI provider instance.",
        "ollama_selected_when": "Policy primary is ollama, or OpenAI primary failed key check on council → fallback Ollama with council_seam_fallback_reason.",
        "openai_suggested_when": "Policy primary is openai and OPENAI_API_KEY or account key resolves.",
        "fallback_when": "Council + OpenAI primary + no key → Ollama for Auto seats (documented in meta). Other modes may block.",
        "code_refs": ["local_ai/execution_policy/seam_routing.py:apply_seam_routing"],
    },
    {
        "id": "policy_json",
        "summary": "config/ai_execution_policy.json defaults.local (ollama), defaults.cloud (openai), overrides_by_action_intent (e.g. workspace_council → openai).",
        "code_refs": ["local_ai/execution_policy/resolve.py:resolve_execution_policy_for_action", "config/ai_execution_policy.json"],
    },
    {
        "id": "providers_init",
        "summary": "Legacy get_default_provider(): policy override else OllamaProvider() without principal.",
        "code_refs": ["local_ai/providers/__init__.py:get_default_provider"],
    },
]


def _profile_for_principal(principal: ExecutionPrincipal) -> dict[str, Any]:
    from local_ai.vision_execution import storage as St

    if principal.account_user_id:
        return St.get_user_llm_profile(principal.account_user_id)
    return {}


def _council_model_stack() -> dict[str, Any]:
    try:
        from local_ai import config as _config
    except Exception:
        _config = None
    env = os.environ.get("ATRIA_COUNCIL_MODEL", "").strip()
    cfg_cm = str(getattr(_config, "OLLAMA_COUNCIL_MODEL", "") or "").strip() if _config else ""
    cfg_om = str(getattr(_config, "OLLAMA_MODEL", "") or "").strip() if _config else ""
    effective = env or cfg_cm or cfg_om or "(unset — resolver may use profile ollama_model)"
    return {
        "ATRIA_COUNCIL_MODEL": env or None,
        "config_OLLAMA_COUNCIL_MODEL": cfg_cm or None,
        "config_OLLAMA_MODEL": cfg_om or None,
        "effective_council_model_hint": effective,
    }


def _implicit_council_baseline(principal: ExecutionPrincipal) -> dict[str, Any]:
    """Describe council resolver path when force_provider is absent (read-only)."""
    prof = _profile_for_principal(principal)
    stack = _council_model_stack()
    om = (prof.get("ollama_model") or "").strip() or None
    return {
        "effective_path_label": "council_stack → local Ollama",
        "profile_ollama_model": om,
        "env_and_config": stack,
        "notes": "Order matches get_council_llm_adapter_for_principal: policy override token, routed Ollama model, env council model, then profile ollama base + model.",
    }


def _implicit_general_baseline(principal: ExecutionPrincipal) -> dict[str, Any]:
    prof = _profile_for_principal(principal)
    dp = (prof.get("default_provider") or "ollama").strip().lower()
    dm = prof.get("default_model")
    return {
        "effective_default_provider": dp,
        "effective_default_model": dm,
        "notes": "When no policy/override tokens: profile default_provider else 'ollama'; cloud requires key in namespace.",
    }


def build_normalized_policy_payload() -> dict[str, Any]:
    """
    Task 2: normalized planes — account (auth), account (anonymous), system — read-only facts.
    """
    cfg = load_execution_policy_config()
    defaults = dict(cfg.defaults or {})
    local_d = dict(defaults.get("local") or {})
    cloud_d = dict(defaults.get("cloud") or {})

    p_auth = authenticated_account_principal("__inspect_sample_user__")
    p_anon = anonymous_account_principal()
    p_sys = system_principal()

    def plane(principal: ExecutionPrincipal, plane_id: str) -> dict[str, Any]:
        prof = _profile_for_principal(principal)
        usable = inspect_usable_providers_for_principal(principal)
        return {
            "plane_id": plane_id,
            "principal_ref": principal.principal_ref,
            "credential_namespace": principal.credential_namespace,
            "implicit_general": _implicit_general_baseline(principal),
            "implicit_council": _implicit_council_baseline(principal),
            "policy_json_defaults": {
                "local_provider": local_d.get("provider"),
                "local_model": local_d.get("model"),
                "cloud_provider": cloud_d.get("provider"),
                "cloud_model": cloud_d.get("model"),
                "allow_cloud_fallback": defaults.get("allow_cloud_fallback"),
                "max_fallback_steps": defaults.get("max_fallback_steps"),
            },
            "usable_providers": usable,
        }

    # Example intent resolution (workspace_council) — same merge rules as seam; does not execute.
    wc_ctx = ActionRoutingContext(
        surface="workspace",
        action_kind="council",
        action_intent="workspace_council",
        streaming=False,
        sensitivity=None,
    )
    wc_out = resolve_execution_policy_for_action(
        wc_ctx,
        legacy_route="council",
        policy_namespace=p_auth.policy_namespace,
        privacy=None,
    )
    wc_policy: dict[str, Any]
    if isinstance(wc_out, ExecutionPolicyBlocked):
        wc_policy = {"blocked": True, "detail": wc_out.detail, "reason": wc_out.reason}
    else:
        wc_policy = {
            "primary": {"provider": wc_out.primary.provider, "model": wc_out.primary.model},
            "fallback_chain": [{"provider": x.provider, "model": x.model} for x in wc_out.fallback_chain],
            "allow_cloud": wc_out.allow_cloud,
        }

    return {
        "schema_version": 1,
        "implicit_default_sources": IMPLICIT_DEFAULT_SOURCES,
        "policy_file": {
            "path_hint": "config/ai_execution_policy.json",
            "global_priority": cfg.global_priority,
        },
        "example_routing_intent_workspace_council": wc_policy,
        "fallback_order_explanation": [
            "1. Request-scoped: policy provider override (OpenAI instance from seam) — highest.",
            "2. Request-scoped: Ollama model override from seam routing.",
            "3. User profile: default_provider / ollama_model (general path) or council env stack (council path).",
            "4. Policy JSON: defaults.local / overrides_by_action_kind / overrides_by_action_intent (when routing_context set).",
            "5. Seam-specific: council may fall back from OpenAI to Ollama when no API key (see seam meta).",
        ],
        "planes": {
            "account_authenticated": plane(p_auth, "account_authenticated"),
            "account_anonymous": plane(p_anon, "account_anonymous"),
            "system": plane(p_sys, "system"),
        },
        "notes": [
            "Planes use representative principals; authenticated sample uses a placeholder user id only for namespace shape.",
            "Live profile data applies only to the logged-in user via GET /studio/provider-default-policy?scope=current.",
        ],
    }


def inspect_usable_providers_for_principal(principal: ExecutionPrincipal) -> list[dict[str, Any]]:
    """Which providers pass prefs gate and have keys (ollama always listed as usable for routing)."""
    prof = _profile_for_principal(principal)
    out: list[dict[str, Any]] = []
    for pid in EXECUTION_PROVIDER_IDS:
        nid = normalize_provider_id(pid)
        gate = execution_provider_gate_for_principal(principal, nid, prof)
        configured = is_provider_configured_for_principal(principal, nid, prof)
        out.append(
            {
                "provider_id": nid,
                "display_name": display_name(nid),
                "prefs_gate_ok": not bool(gate),
                "prefs_gate_detail": gate,
                "configured_for_credentials": configured,
                "usable_for_execution": (not gate) and configured,
            }
        )
    return out


def _routing_context_to_dict(routing_context: Any) -> dict[str, Any]:
    if routing_context is None:
        return {}
    if hasattr(routing_context, "model_dump"):
        return dict(routing_context.model_dump())
    if isinstance(routing_context, Mapping):
        return dict(routing_context)
    return {}


def inspect_policy_primary_for_routing(
    *,
    mode: str,
    routing_context: Any | None,
    principal: ExecutionPrincipal,
) -> dict[str, Any] | None:
    """Mirror seam's policy resolution (read-only). Returns None if routing_context absent."""
    if not routing_context:
        return None

    rc = _routing_context_to_dict(routing_context)
    ctx = ActionRoutingContext(
        surface=str(rc.get("surface") or "").strip(),
        action_kind=str(rc.get("action_kind") or "").strip(),
        action_intent=(str(rc.get("action_intent") or "").strip() or None),
        streaming=rc.get("streaming"),
        sensitivity=(str(rc.get("sensitivity") or "").strip() or None) if rc.get("sensitivity") else None,
    )
    mode_l = (mode or "").strip().lower()
    legacy_route = "council" if mode_l == "council" else "default"
    pm_raw = rc.get("privacy_mode")
    pm_s = str(pm_raw).strip() if pm_raw is not None else ""
    from local_ai.execution_policy.privacy_apply import privacy_mode_to_partial

    privacy = privacy_mode_to_partial(pm_s if pm_s else None)

    outcome = resolve_execution_policy_for_action(
        ctx,
        legacy_route=legacy_route,
        privacy=privacy,
        policy_namespace=principal.policy_namespace,
    )
    if isinstance(outcome, ExecutionPolicyBlocked):
        return {
            "blocked": True,
            "detail": outcome.detail,
            "reason": outcome.reason,
        }
    return {
        "blocked": False,
        "primary": {"provider": outcome.primary.provider, "model": outcome.primary.model},
        "fallback_chain": [{"provider": x.provider, "model": x.model} for x in outcome.fallback_chain],
        "allow_cloud": outcome.allow_cloud,
        "flags": dict(outcome.flags),
    }


def build_provider_resolution_for_run(
    *,
    mode: str,
    params: Any | None,
    principal: ExecutionPrincipal,
    exec_meta: dict[str, Any] | None,
    routing_context: Any | None,
    teacher_meta: dict[str, Any] | None = None,
    wash_trace: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Task 4: per-run trace — requested vs effective vs fallback reason (inspect-only assembly).

    Does not change execution; consumes the same meta produced by the run.
    """
    exec_meta = dict(exec_meta or {})
    tm = dict(teacher_meta or {})

    routing_present = routing_context is not None
    rc_dict = _routing_context_to_dict(routing_context) if routing_present else {}
    externalization_allowed = True if not routing_present else bool(rc_dict.get("allows_externalization"))

    policy_view = inspect_policy_primary_for_routing(
        mode=mode,
        routing_context=routing_context,
        principal=principal,
    )

    seam_lane: dict[str, Any] | None = None
    if routing_present:
        seam_lane = {
            "policy_resolution": policy_view,
            "effective_provider": exec_meta.get("provider_used"),
            "effective_model": exec_meta.get("model_used"),
            "routing_override_active": exec_meta.get("routing_override_active"),
            "openai_key_source": exec_meta.get("openai_key_source"),
            "fallback_reason": exec_meta.get("council_seam_fallback_reason"),
            "council_seam_fallback_ollama": exec_meta.get("council_seam_fallback_ollama"),
        }
    else:
        seam_lane = {
            "notes": "No routing_context on this request; seam routing did not run. Resolver/profile/env apply directly.",
        }

    council_lane: dict[str, Any] | None = None
    if (mode or "").strip().lower() == "council":
        from local_ai.llm.resolver import peek_council_native_attachment_trace

        np_req = (getattr(params, "native_provider", None) or "").strip() or None
        nm_req = (getattr(params, "native_model", None) or "").strip() or None
        tp_req = (getattr(params, "teacher_provider", None) or "").strip() or None
        tm_req = (getattr(params, "teacher_model", None) or "").strip() or None
        attach_trace = tm.get("council_native_attachment_trace")
        if attach_trace is None:
            attach_trace = peek_council_native_attachment_trace()
        council_lane = {
            "native": {
                "requested_provider": np_req or "implicit (resolver council stack)",
                "requested_model": nm_req,
                "effective_provider": tm.get("native_provider"),
                "effective_model": tm.get("native_model"),
                "fallback_reason": None
                if (np_req and tm.get("native_provider") == np_req)
                or (not np_req)
                else "effective differs from explicit request — check credentials, gates, or blocked adapter message in output",
                **(
                    {
                        "council_native_attachment_requested": attach_trace.get(
                            "council_native_attachment_requested"
                        ),
                        "council_native_attachment_resolved": attach_trace.get(
                            "council_native_attachment_resolved"
                        ),
                        "council_native_fallback_reason": attach_trace.get("council_native_fallback_reason"),
                        "council_native_stack_lane": attach_trace.get("council_native_stack_lane"),
                    }
                    if attach_trace
                    else {}
                ),
            },
            "teacher": {
                "requested_provider": tp_req or "implicit (studio defaults / teacher off)",
                "requested_model": tm_req,
                "effective_provider": tm.get("teacher_provider_effective") or tm.get("teacher_provider"),
                "effective_model": tm.get("teacher_model_effective") or tm.get("teacher_model"),
                "teacher_succeeded": tm.get("teacher_succeeded"),
                "teacher_skipped_reason": tm.get("teacher_skipped_reason"),
                "fallback_reason": None,
            },
        }
        if not tm.get("native_provider"):
            council_lane["notes"] = (
                "Limited metadata: no native effective in response metadata (e.g. teacher_mode off). "
                "Use teacher shadow/replace for native/teacher effective fields in this trace."
            )
        attach_tr = attach_trace or {}
        t_skip = tm.get("teacher_skipped_reason")
        cloud_blk_parts: list[str] = []
        if not externalization_allowed:
            if attach_tr.get("council_native_fallback_reason") == "privacy_requires_local":
                cloud_blk_parts.append("native_main_attachment:privacy_requires_local")
            if t_skip == "privacy_requires_local":
                cloud_blk_parts.append("teacher:privacy_requires_local")
        council_lane["externalization_allowed"] = externalization_allowed
        council_lane["cloud_blocked_reason"] = "; ".join(cloud_blk_parts) if cloud_blk_parts else None
        wt_src: dict[str, Any] = dict(wash_trace or {})
        _tw = tm.get("council_wash_trace")
        if isinstance(_tw, dict) and _tw:
            wt_src = {**wt_src, **_tw}
        if wt_src:
            council_lane["wash"] = {
                "wash_version": wt_src.get("wash_version"),
                "cloud_payload_source": wt_src.get("cloud_payload_source"),
                "wash_applied": wt_src.get("wash_applied"),
                "safety_allow_cloud_with_wash": wt_src.get("safety_allow_cloud_with_wash"),
                "transform_summary": wt_src.get("transform_summary"),
                "safety_refusal_reasons": wt_src.get("safety_refusal_reasons"),
            }

    return {
        "mode": mode,
        "execution_principal_ref": principal.principal_ref,
        "routing_context_present": routing_present,
        "externalization_allowed": externalization_allowed,
        "cloud_blocked_reason": (council_lane or {}).get("cloud_blocked_reason"),
        "seam": seam_lane,
        "council": council_lane,
    }


def build_credential_visibility_for_user(user_id: str) -> dict[str, Any]:
    """
    Admin-facing read-only snapshot of OpenAI credential namespaces (Option B).

    Does not expose key material. Anonymous lane never uses OPENAI_API_KEY.
    """
    _, acct_src = resolve_openai_api_key(user_id)
    sys_openai = bool((os.environ.get("ATRIA_SYSTEM_OPENAI_KEY") or "").strip())
    return {
        "option_b_note": (
            "account:anonymous does not inherit OPENAI_API_KEY; cloud OpenAI requires sign-in + Settings key "
            "or system scope with ATRIA_SYSTEM_OPENAI_KEY."
        ),
        "anonymous_openai_cloud_allowed": False,
        "system": {
            "openai_env_var": "ATRIA_SYSTEM_OPENAI_KEY",
            "openai_configured": sys_openai,
        },
        "account_authenticated": {
            "principal_ref": authenticated_account_principal(user_id).principal_ref,
            "openai_env_key_present": openai_env_key_present(),
            "openai_settings_key_present": openai_settings_key_present(user_id),
            "openai_effective_source": acct_src,
        },
    }


def build_provider_policy_for_current_user(user_id: str) -> dict[str, Any]:
    """Authenticated Studio: merge static payload with live profile for this user."""
    base = build_normalized_policy_payload()
    p = authenticated_account_principal(user_id)
    prof = _profile_for_principal(p)
    base["current_session"] = {
        "plane_id": "current_user",
        "principal_ref": p.principal_ref,
        "credential_namespace": p.credential_namespace,
        "implicit_general": _implicit_general_baseline(p),
        "implicit_council": _implicit_council_baseline(p),
        "live_profile_snippet": {
            "default_provider": prof.get("default_provider"),
            "default_model": prof.get("default_model"),
            "ollama_base_url_set": bool((prof.get("ollama_base_url") or "").strip()),
            "ollama_model": prof.get("ollama_model"),
        },
        "usable_providers": inspect_usable_providers_for_principal(p),
        "credential_visibility": build_credential_visibility_for_user(user_id),
    }
    return base
