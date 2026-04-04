"""
Canonical LLM provider registry, per-user prefs interpretation, and execution gating.

Used by Settings API, ``apply_seam_routing``, and ``get_llm_adapter_for_principal`` so enable/disable
and configured state stay consistent.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, Literal

from local_ai import config as _config

if TYPE_CHECKING:
    from local_ai.llm.execution_principal import ExecutionPrincipal

TestStatus = Literal["never", "passed", "failed"]

# Order matches product surface (Settings + execution).
EXECUTION_PROVIDER_IDS: tuple[str, ...] = ("ollama", "openai", "anthropic", "google", "xai")

_CLOUD_KEY_PROVIDERS = frozenset({"openai", "anthropic", "google", "xai"})


def normalize_provider_id(raw: str) -> str:
    s = (raw or "").strip().lower().replace("-", "_")
    aliases = {"open_ai": "openai", "local_ollama": "ollama", "gemini": "google", "google_genai": "google"}
    return aliases.get(s, s)


def default_model_hint(provider_id: str) -> str:
    """Shipped default model id for UI hints (matches provider modules where defined)."""
    pid = normalize_provider_id(provider_id)
    if pid == "openai":
        return "gpt-4o-mini"
    if pid == "anthropic":
        from local_ai.providers import anthropic as pa

        return pa.DEFAULT_MODEL
    if pid == "google":
        from local_ai.providers import google_genai as pg

        return pg.DEFAULT_MODEL
    if pid == "xai":
        from local_ai.providers import xai as px

        return px.DEFAULT_MODEL
    if pid == "ollama":
        return (_config.OLLAMA_MODEL or "llama3.2").strip() or "llama3.2"
    return ""


def display_name(provider_id: str) -> str:
    pid = normalize_provider_id(provider_id)
    return {
        "ollama": "Ollama (local)",
        "openai": "OpenAI",
        "anthropic": "Anthropic",
        "google": "Google (Gemini)",
        "xai": "xAI",
    }.get(pid, pid)


def needs_stored_api_key(provider_id: str) -> bool:
    return normalize_provider_id(provider_id) in _CLOUD_KEY_PROVIDERS


def _parse_prefs_json(raw: str | None) -> dict[str, Any]:
    if not raw or not str(raw).strip():
        return {}
    try:
        data = json.loads(raw)
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def pref_enabled(provider_prefs: dict[str, Any], provider_id: str) -> bool:
    """Default True when unset (backward compatible)."""
    pid = normalize_provider_id(provider_id)
    block = provider_prefs.get(pid)
    if not isinstance(block, dict):
        return True
    if "enabled" not in block:
        return True
    return bool(block["enabled"])


def pref_test_meta(provider_prefs: dict[str, Any], provider_id: str) -> tuple[TestStatus, str | None, str | None]:
    pid = normalize_provider_id(provider_id)
    block = provider_prefs.get(pid)
    if not isinstance(block, dict):
        return "never", None, None
    lt = block.get("last_test")
    if not isinstance(lt, dict):
        return "never", None, None
    ok = lt.get("ok")
    if ok is True:
        return "passed", (lt.get("at") if isinstance(lt.get("at"), str) else None), None
    if ok is False:
        err = lt.get("error")
        return "failed", (lt.get("at") if isinstance(lt.get("at"), str) else None), err if isinstance(err, str) else None
    return "never", None, None


def is_provider_configured_for_principal(principal: ExecutionPrincipal, provider_id: str, profile: dict[str, Any]) -> bool:
    """Whether this provider has a resolvable key for the given principal (namespaced)."""
    from local_ai.llm.credentials import resolve_cloud_api_key
    from local_ai.llm.execution_principal import ExecutionPrincipal

    if not isinstance(principal, ExecutionPrincipal):
        raise TypeError("principal must be ExecutionPrincipal")
    pid = normalize_provider_id(provider_id)
    if pid == "ollama":
        return True
    key, _src = resolve_cloud_api_key(principal, pid)
    return bool(key and key.strip())


def is_provider_configured(user_id: str | None, provider_id: str, profile: dict[str, Any]) -> bool:
    """Backward-compatible: bridge user id to account principal."""
    from local_ai.llm.execution_principal import authenticated_account_principal, anonymous_account_principal

    p = authenticated_account_principal(user_id) if user_id else anonymous_account_principal()
    return is_provider_configured_for_principal(p, provider_id, profile)


def effective_default_model_for_profile(profile: dict[str, Any], provider_id: str) -> str:
    """Default model hint for a provider given stored profile (no execution identity)."""
    pid = normalize_provider_id(provider_id)
    dp = (profile.get("default_provider") or "ollama").strip().lower()
    dm = (profile.get("default_model") or "").strip()
    om = (profile.get("ollama_model") or "").strip()
    if pid == "ollama":
        return om or (_config.OLLAMA_MODEL or "") or default_model_hint("ollama")
    if pid == dp and dm:
        return dm
    return default_model_hint(pid)


def user_effective_default_model(user_id: str | None, profile: dict[str, Any], provider_id: str) -> str:
    """Deprecated name: use ``effective_default_model_for_profile`` (``user_id`` is ignored)."""
    return effective_default_model_for_profile(profile, provider_id)


def provider_prefs_from_profile(profile: dict[str, Any]) -> dict[str, Any]:
    pp = profile.get("provider_prefs")
    if isinstance(pp, dict):
        return pp
    raw = profile.get("llm_provider_prefs_json")
    return _parse_prefs_json(raw if isinstance(raw, str) else None)


def build_provider_status_rows_for_principal(
    principal: ExecutionPrincipal,
    profile: dict[str, Any],
    creds_mask: dict[str, bool],
) -> list[dict[str, Any]]:
    """One row per execution provider for API / UI (credential state via ``principal``)."""
    from local_ai.llm.execution_principal import ExecutionPrincipal

    if not isinstance(principal, ExecutionPrincipal):
        raise TypeError("principal must be ExecutionPrincipal")
    provider_prefs = provider_prefs_from_profile(profile)

    rows: list[dict[str, Any]] = []
    for pid in EXECUTION_PROVIDER_IDS:
        enabled = pref_enabled(provider_prefs, pid)
        configured = is_provider_configured_for_principal(principal, pid, profile)
        test_status, last_at, last_err = pref_test_meta(provider_prefs, pid)
        avail = enabled and configured
        reasons: list[str] = []
        if not enabled:
            reasons.append("Disabled by you in provider settings.")
        if not configured:
            if pid == "openai":
                if principal.scope == "account" and not principal.account_user_id:
                    reasons.append(
                        "No OpenAI key for anonymous lane (OPENAI_API_KEY is not used; sign in and save a key in Settings)."
                    )
                else:
                    reasons.append("No OpenAI key (set OPENAI_API_KEY on the server or save a key in Settings).")
            elif needs_stored_api_key(pid):
                reasons.append("No API key saved for this provider.")
        row = {
            "id": pid,
            "display_name": display_name(pid),
            "needs_api_key": needs_stored_api_key(pid),
            "key_saved": bool(creds_mask.get(pid)) if needs_stored_api_key(pid) else False,
            "enabled": enabled,
            "configured": configured,
            "available": avail,
            "default_model": effective_default_model_for_profile(profile, pid),
            "test_status": test_status,
            "last_test_at": last_at,
            "last_test_error": last_err,
            "status_message": " ".join(reasons) if reasons else None,
        }
        rows.append(row)
    return rows


def build_provider_status_rows(user_id: str | None, profile: dict[str, Any], creds_mask: dict[str, bool]) -> list[dict[str, Any]]:
    """Compatibility: optional legacy user id → account principal for status rows."""
    from local_ai.llm.execution_principal import execution_principal_from_legacy_user_id

    return build_provider_status_rows_for_principal(execution_principal_from_legacy_user_id(user_id), profile, creds_mask)


def execution_provider_gate_for_principal(
    principal: ExecutionPrincipal,
    provider_id: str,
    profile: dict[str, Any],
) -> str | None:
    """
    Routed execution: block when authenticated account user disabled the provider in Settings.
    System scope and anonymous account skip user-pref gating (no Settings subject).
    """
    from local_ai.llm.execution_principal import ExecutionPrincipal

    if not isinstance(principal, ExecutionPrincipal):
        raise TypeError("principal must be ExecutionPrincipal")
    pid = normalize_provider_id(provider_id)
    if pid not in EXECUTION_PROVIDER_IDS:
        return f"Unknown provider {provider_id!r}."
    if principal.scope == "system":
        return None
    gate_uid = principal.gate_user_id
    if not gate_uid:
        return None
    provider_prefs = provider_prefs_from_profile(profile)
    if not pref_enabled(provider_prefs, pid):
        return (
            f"{display_name(pid)} is disabled in your provider settings. "
            "Enable it under Settings → Model connections or the AI agents panel."
        )
    return None


def execution_provider_gate_message(user_id: str | None, provider_id: str, profile: dict[str, Any]) -> str | None:
    """Backward-compatible wrapper around ``execution_provider_gate_for_principal``."""
    from local_ai.llm.execution_principal import execution_principal_from_legacy_user_id

    return execution_provider_gate_for_principal(execution_principal_from_legacy_user_id(user_id), provider_id, profile)


def user_llm_adapter_gate_for_principal(
    principal: ExecutionPrincipal,
    provider_id: str,
    profile: dict[str, Any],
) -> str | None:
    """Adapter path: execution gate plus cloud must be configured for this principal's namespace."""
    base = execution_provider_gate_for_principal(principal, provider_id, profile)
    if base:
        return base
    pid = normalize_provider_id(provider_id)
    if pid == "ollama":
        return None
    if not is_provider_configured_for_principal(principal, pid, profile):
        if principal.scope == "system":
            return (
                f"{display_name(pid)} has no API key in the system credential namespace "
                f"(set ATRIA_SYSTEM_* key for this provider)."
            )
        if pid == "openai":
            if principal.scope == "account" and not principal.account_user_id:
                return (
                    "OpenAI is enabled but no API key is available for anonymous requests. "
                    "Sign in and save an OpenAI key in Settings, or use Ollama. "
                    "(Deployment OPENAI_API_KEY is not applied to account:anonymous — Option B.)"
                )
            return "OpenAI is enabled but no API key is available. Set OPENAI_API_KEY or save a key in Settings."
        if needs_stored_api_key(pid):
            if not principal.account_user_id:
                return (
                    f"{display_name(pid)} requires signing in to save API keys in Settings. "
                    "Anonymous account runs cannot use the server's OPENAI_API_KEY."
                )
            return f"{display_name(pid)} is enabled but no API key is saved. Add one in Settings."
    return None


def user_llm_adapter_gate_message(user_id: str | None, provider_id: str, profile: dict[str, Any]) -> str | None:
    """Backward-compatible wrapper around ``user_llm_adapter_gate_for_principal``."""
    from local_ai.llm.execution_principal import execution_principal_from_legacy_user_id

    return user_llm_adapter_gate_for_principal(execution_principal_from_legacy_user_id(user_id), provider_id, profile)
