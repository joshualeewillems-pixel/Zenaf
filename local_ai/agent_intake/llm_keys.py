"""Resolve the Anthropic API key for agent-intake LLM calls, per user.

Billing rule: a user's own key first (Settings → decrypted per-account
storage), then the server env key as fallback. Every resolution is logged
(user, key source, operation) so shared-key usage can be metered later —
one user's intake never silently spends without a trace.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

_USAGE_LOG = Path.home() / ".zenaf" / "agent_intake_usage.jsonl"


def resolve_anthropic_key(
    user_id: str | None = None, operation: str = "intake"
) -> str | None:
    """Return the Anthropic key to bill this user's intake to, if any."""
    key, source = None, "none"
    uid = (user_id or "").strip()
    if uid:
        try:
            from local_ai.llm.credentials import resolve_cloud_api_key
            from local_ai.llm.execution_principal import authenticated_account_principal

            key, source = resolve_cloud_api_key(
                authenticated_account_principal(uid), "anthropic"
            )
            key = (key or "").strip() or None
        except Exception:
            key, source = None, "none"
    if not key:
        key = (os.environ.get("ANTHROPIC_API_KEY") or "").strip() or None
        source = "server_env" if key else "none"
    if key:
        _log_usage(uid or "anonymous", source, operation)
    return key


def _log_usage(user_id: str, source: str, operation: str) -> None:
    try:
        _USAGE_LOG.parent.mkdir(parents=True, exist_ok=True)
        with _USAGE_LOG.open("a") as f:
            f.write(json.dumps({
                "ts": time.time(),
                "user_id": user_id,
                "key_source": source,
                "operation": operation,
            }) + "\n")
    except Exception:
        pass
