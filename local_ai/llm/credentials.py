"""
Principal-aware API key resolution for execution providers.

Separates credential namespace (system vs account) while allowing the same vendor key
in env vars for both during migration.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from local_ai.llm.execution_principal import ExecutionPrincipal

CredentialSource = Literal["none", "system_env", "env", "settings", "account_storage"]

# Authenticated account: same resolution order as OpenAI (env first, then Settings). Anonymous skips env (Option B).
_ACCOUNT_CLOUD_ENV_KEYS: dict[str, tuple[str, ...]] = {
    "anthropic": ("ANTHROPIC_API_KEY",),
    "google": ("GOOGLE_API_KEY", "GEMINI_API_KEY"),
    "xai": ("XAI_API_KEY",),
}


def _account_env_cloud_key(provider_id: str) -> str | None:
    for name in _ACCOUNT_CLOUD_ENV_KEYS.get(provider_id, ()):
        v = (os.environ.get(name) or "").strip()
        if v:
            return v
    return None


def resolve_cloud_api_key(principal: ExecutionPrincipal, provider_id: str) -> tuple[str | None, CredentialSource]:
    """
    Resolve decrypted API key for a cloud provider and principal.

    System namespace: ZENAF_SYSTEM_* env vars only (no user Settings).
    Account namespace: provider-specific rules; OpenAI uses OPENAI_API_KEY then Settings.
    """
    from local_ai.llm.execution_principal import ExecutionPrincipal
    from local_ai.llm.provider_registry import normalize_provider_id

    if not isinstance(principal, ExecutionPrincipal):
        raise TypeError("principal must be ExecutionPrincipal")

    pid = normalize_provider_id(provider_id)
    if pid == "ollama":
        return None, "none"

    if principal.scope == "system":
        env_names = {
            "openai": "ZENAF_SYSTEM_OPENAI_KEY",
            "anthropic": "ZENAF_SYSTEM_ANTHROPIC_API_KEY",
            "google": "ZENAF_SYSTEM_GOOGLE_API_KEY",
            "xai": "ZENAF_SYSTEM_XAI_API_KEY",
        }
        en = env_names.get(pid)
        if not en:
            return None, "none"
        v = (os.environ.get(en) or "").strip()
        if v:
            return v, "system_env"
        return None, "none"

    # Account scope
    if pid == "openai":
        from local_ai.execution_policy.openai_credentials import resolve_openai_api_key_for_principal

        key, src = resolve_openai_api_key_for_principal(principal)
        if not key:
            return None, "none"
        if src == "env":
            return key, "env"
        if src == "settings":
            return key, "settings"
        if src == "system_env":
            return key, "system_env"
        return key, "none"

    uid = principal.account_user_id
    if not uid:
        return None, "none"

    env_k = _account_env_cloud_key(pid)
    if env_k:
        return env_k, "env"

    from local_ai.vision_execution import storage as St

    raw = St.get_decrypted_llm_api_key(uid, pid)
    if raw and str(raw).strip():
        return str(raw).strip(), "account_storage"
    return None, "none"
