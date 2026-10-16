"""Intake LLM wiring: provider-agnostic key resolution, generation, and metering.

The intake (sorter, project miner, Muse chat) talks to *a* provider through
the prompt→text contract — not hardcoded to Anthropic. Which provider runs
is chosen by ZENAF_INTAKE_PROVIDER (default "meta"); "anthropic" selects
the Anthropic sorter engine.

Billing rule: a user's own Settings key first, then the server env key.
Every resolution is metered to ~/.zenaf/agent_intake_usage.jsonl so
shared-key usage can be factored into pricing later.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

_USAGE_LOG = Path.home() / ".zenaf" / "agent_intake_usage.jsonl"


def resolve_intake_provider() -> str:
    """Which provider the intake pipeline uses. Env-overridable, default meta."""
    return (os.environ.get("ZENAF_INTAKE_PROVIDER") or "").strip().lower() or "meta"


def resolve_key(
    provider_id: str | None = None,
    user_id: str | None = None,
    operation: str = "intake",
) -> str | None:
    """Return the key to bill this user's operation to, if any.

    Order: the user's own Settings key (per-account storage) first, then the
    server env key for that provider.
    """
    from local_ai.llm.provider_registry import normalize_provider_id

    pid = normalize_provider_id(provider_id or resolve_intake_provider())
    key, source = None, "none"
    uid = (user_id or "").strip()
    if uid:
        try:
            from local_ai.llm.credentials import resolve_cloud_api_key
            from local_ai.llm.execution_principal import authenticated_account_principal

            key, source = resolve_cloud_api_key(authenticated_account_principal(uid), pid)
            key = (key or "").strip() or None
        except Exception:
            key, source = None, "none"
    if not key:
        key = _provider_env_key(pid)
        source = "server_env" if key else "none"
    if key:
        _log_usage(uid or "anonymous", pid, source, operation)
    return key


def _provider_env_key(pid: str) -> str | None:
    env_names = {
        "anthropic": ("ANTHROPIC_API_KEY",),
        "meta": ("META_API_KEY", "MODEL_API_KEY"),
        "openai": ("OPENAI_API_KEY",),
        "google": ("GOOGLE_API_KEY", "GEMINI_API_KEY"),
        "xai": ("XAI_API_KEY",),
    }
    for name in env_names.get(pid, ()):
        v = (os.environ.get(name) or "").strip()
        if v:
            return v
    return None


def generate(
    prompt: str,
    *,
    provider_id: str | None = None,
    api_key: str | None = None,
    user_id: str | None = None,
    operation: str = "intake",
    timeout: int = 120,
) -> str:
    """Generate text via the intake provider. Raises RuntimeError when unusable."""
    from local_ai.llm.provider_registry import normalize_provider_id

    pid = normalize_provider_id(provider_id or resolve_intake_provider())
    key = (api_key or "").strip() or resolve_key(pid, user_id, operation)
    if not key:
        raise RuntimeError(f"No API key for intake provider '{pid}'")
    if pid == "anthropic":
        from local_ai.providers import anthropic as provider

        return provider.generate(key, prompt, timeout=timeout)
    if pid == "meta":
        from local_ai.providers import meta as provider

        return provider.generate(key, prompt, timeout=timeout)
    if pid == "openai":
        from local_ai.providers import openai as provider

        return provider.generate(key, prompt, timeout=timeout)
    raise RuntimeError(f"Intake provider '{pid}' is not wired for generation")


def _log_usage(user_id: str, provider: str, source: str, operation: str) -> None:
    try:
        _USAGE_LOG.parent.mkdir(parents=True, exist_ok=True)
        with _USAGE_LOG.open("a") as f:
            f.write(json.dumps({
                "ts": time.time(),
                "user_id": user_id,
                "provider": provider,
                "key_source": source,
                "operation": operation,
            }) + "\n")
    except Exception:
        pass


# Backwards-compat alias for the previous Anthropic-only helper.
def resolve_anthropic_key(user_id: str | None = None, operation: str = "intake") -> str | None:
    return resolve_key("anthropic", user_id, operation)
