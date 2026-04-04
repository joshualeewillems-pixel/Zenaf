"""
Shared POST /run and Vision Execution LLM seams: resolve policy, enforce supported providers.

Only ``ollama`` and ``openai`` are executable on this seam until additional adapters are wired.
Unsupported primaries **block** with a clear error (no silent Ollama with misleading metadata).
"""

from __future__ import annotations

from typing import Any, Mapping, Optional, cast

from local_ai.llm.execution_principal import ExecutionPrincipal, execution_principal_from_legacy_user_id
from local_ai.llm.provider_registry import execution_provider_gate_for_principal

from .openai_credentials import describe_missing_openai_key_for_principal, resolve_openai_api_key_for_principal
from .privacy_apply import ExecutionPolicyBlocked, privacy_mode_to_partial
from .resolve import resolve_execution_policy_for_action
from .types import ActionRoutingContext
from .run_context import RoutingTeardown, push_ollama_model_override, push_policy_provider_override

# Providers for which we push a real override / model token so resolver-backed execution matches policy.
SUPPORTED_SEAM_PROVIDERS = frozenset({"ollama", "openai"})


def _ollama_reachable_for_seam_fallback(*, timeout: float = 1.5) -> bool:
    """
    Quick check before anonymous OpenAI→Ollama fallback (non-council).
    Council path keeps historical behavior (fallback without preflight).
    """
    try:
        import requests
        from urllib.parse import urlparse, urlunparse

        from local_ai import config as _cfg

        raw = ((_cfg.OLLAMA_URL or "") or "http://localhost:11434/api/generate").strip()
        u = urlparse(raw)
        netloc = u.netloc or "localhost:11434"
        scheme = u.scheme or "http"
        tags_url = urlunparse((scheme, netloc, "/api/tags", "", "", ""))
        r = requests.get(tags_url, timeout=timeout)
        return r.status_code == 200
    except Exception:
        return False


def _normalize_provider_id(raw: str) -> str:
    s = (raw or "").strip().lower().replace("-", "_")
    aliases = {"open_ai": "openai", "local_ollama": "ollama"}
    return aliases.get(s, s)


def apply_seam_routing(
    *,
    mode: str,
    routing_context: Optional[Mapping[str, Any]] = None,
    principal: ExecutionPrincipal | None = None,
    user_id: str | None = None,
    apply_overrides: bool = True,
) -> tuple[Optional[RoutingTeardown], dict[str, Any]]:
    """
    Apply optional routing_context dict (same shape as API ``RunRoutingContext``).

    ``principal``: resolved execution identity (system vs account, namespaces). If omitted,
    ``user_id`` is mapped to an account principal via ``execution_principal_from_legacy_user_id``.

    Returns ``(teardown, meta)`` including ``execution_scope``, ``execution_principal_ref``,
    ``credential_namespace``, ``policy_namespace`` when routing_context is present.
    """
    if not routing_context:
        return None, {}

    exec_principal = principal if principal is not None else execution_principal_from_legacy_user_id(user_id)

    rc = routing_context
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
    privacy = privacy_mode_to_partial(pm_s if pm_s else None)

    outcome = resolve_execution_policy_for_action(
        ctx,
        legacy_route=legacy_route,
        privacy=privacy,
        policy_namespace=exec_principal.policy_namespace,
    )
    meta: dict[str, Any] = {
        "model_used": None,
        "provider_used": None,
        "routing_override_active": False,
        "openai_key_source": None,
        "execution_scope": exec_principal.scope,
        "execution_principal_ref": exec_principal.principal_ref,
        "credential_namespace": exec_principal.credential_namespace,
        "policy_namespace": exec_principal.policy_namespace,
    }
    if isinstance(outcome, ExecutionPolicyBlocked):
        return None, {
            **meta,
            "execution_blocked": True,
            "error_detail": outcome.detail or "Execution blocked by privacy policy",
            "privacy_block_reason": outcome.reason,
        }

    resolution = outcome
    prov = _normalize_provider_id(resolution.primary.provider)
    meta["policy_primary_provider"] = prov

    profile: dict[str, Any] = {}
    gate_uid = exec_principal.gate_user_id
    if gate_uid:
        from local_ai.vision_execution import storage as St

        profile = cast(dict[str, Any], St.get_user_llm_profile(gate_uid))
    gate_msg = execution_provider_gate_for_principal(exec_principal, prov, profile)
    if gate_msg:
        return None, {
            **meta,
            "execution_blocked": True,
            "error_detail": gate_msg,
            "privacy_block_reason": None,
        }

    if prov == "ollama":
        meta["model_used"] = resolution.primary.model
        meta["provider_used"] = "ollama"
        meta["routing_override_active"] = True
        if not apply_overrides:
            return None, meta
        o_tok = push_ollama_model_override(resolution.primary.model)
        return RoutingTeardown(ollama_token=o_tok), meta

    if prov == "openai":
        api_key, key_src = resolve_openai_api_key_for_principal(exec_principal)
        meta["openai_key_source"] = key_src
        if not api_key:
            # Council can use per-seat providers (Anthropic, xAI, …). If OpenAI is not configured,
            # fall through to local Ollama for the policy default instead of blocking the whole run.
            if mode_l == "council":
                meta["model_used"] = None
                meta["provider_used"] = "ollama"
                meta["routing_override_active"] = True
                meta["council_seam_fallback_ollama"] = True
                if key_src == "anonymous_blocked":
                    meta["council_seam_fallback_reason"] = (
                        "OpenAI was selected by policy but account:anonymous cannot use OPENAI_API_KEY (Option B). "
                        "Using local Ollama for default council seats. Sign in and save an OpenAI key to use cloud here."
                    )
                else:
                    meta["council_seam_fallback_reason"] = (
                        "OpenAI was selected by policy but no API key is set; using local Ollama for "
                        "'Auto' seats. Seats with an explicit provider still use that provider when configured."
                    )
                if not apply_overrides:
                    return None, meta
                o_tok = push_ollama_model_override(None)
                return RoutingTeardown(ollama_token=o_tok), meta
            # Anonymous account: policy chose OpenAI but this lane has no key (Option B). Use local Ollama
            # when the daemon responds, so /run next_step and similar seams can execute without cloud keys.
            if (
                exec_principal.scope == "account"
                and not exec_principal.account_user_id
                and key_src == "anonymous_blocked"
                and _ollama_reachable_for_seam_fallback()
            ):
                meta["model_used"] = None
                meta["provider_used"] = "ollama"
                meta["routing_override_active"] = True
                meta["anonymous_openai_fallback_ollama"] = True
                meta["seam_fallback_reason"] = (
                    "OpenAI was selected by policy but account:anonymous has no OpenAI key in this lane; "
                    "using local Ollama while the daemon is reachable."
                )
                if not apply_overrides:
                    return None, meta
                o_tok = push_ollama_model_override(None)
                return RoutingTeardown(ollama_token=o_tok), meta
            return None, {
                **meta,
                "execution_blocked": True,
                "error_detail": describe_missing_openai_key_for_principal(exec_principal),
                "privacy_block_reason": None,
            }
        from local_ai.providers.openai import OpenAIProvider

        openai_provider = OpenAIProvider(model=resolution.primary.model, api_key=api_key)
        meta["model_used"] = openai_provider.model
        meta["provider_used"] = "openai"
        meta["routing_override_active"] = True
        if not apply_overrides:
            return None, meta
        p_tok = push_policy_provider_override(openai_provider)
        return RoutingTeardown(policy_provider_token=p_tok), meta

    raw = (resolution.primary.provider or "").strip() or "(unknown)"
    return None, {
        **meta,
        "execution_blocked": True,
        "error_detail": (
            f"Execution policy selected provider {raw!r}, which is not supported on this server seam. "
            f"Supported providers: {', '.join(sorted(SUPPORTED_SEAM_PROVIDERS))}. "
            f"Configure policy to use ollama or openai, or add an adapter."
        ),
        "privacy_block_reason": None,
    }
