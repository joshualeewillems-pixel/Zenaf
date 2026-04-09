"""Anthropic Messages API — minimal generate + test."""
from __future__ import annotations

import os
import requests

# Default for Test / generate when no model is stored. Use a current alias — dated Claude 3
# snapshots often return not_found_error on the Messages API. Override with ZENAF_ANTHROPIC_MODEL.
DEFAULT_MODEL = (os.environ.get("ZENAF_ANTHROPIC_MODEL") or "").strip() or "claude-haiku-4-5"


def _effective_model(model: str | None) -> str:
    """Return a non-empty model id; default when missing or blank."""
    m = (model or "").strip()
    return m if m else DEFAULT_MODEL
BASE = "https://api.anthropic.com/v1"


def test_connection(api_key: str, model: str | None = None) -> tuple[bool, str]:
    key = (api_key or "").strip()
    if not key:
        return False, "Missing API key"
    m = _effective_model(model)
    try:
        r = requests.post(
            f"{BASE}/messages",
            headers={
                "x-api-key": key,
                "anthropic-version": "2023-06-01",
                "Content-Type": "application/json",
            },
            json={
                "model": m,
                "max_tokens": 8,
                "messages": [{"role": "user", "content": "Reply with OK"}],
            },
            timeout=25,
        )
        if r.status_code < 400:
            return True, ""
        return False, r.text[:500] or f"HTTP {r.status_code}"
    except Exception as e:
        return False, str(e)


def generate(api_key: str, prompt: str, *, model: str | None = None, timeout: int = 120) -> str:
    key = (api_key or "").strip()
    m = _effective_model(model)
    r = requests.post(
        f"{BASE}/messages",
        headers={
            "x-api-key": key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        },
        json={
            "model": m,
            "max_tokens": 4096,
            "messages": [{"role": "user", "content": prompt}],
        },
        timeout=timeout,
    )
    r.raise_for_status()
    data = r.json()
    blocks = data.get("content") or []
    parts = [b.get("text", "") for b in blocks if isinstance(b, dict) and b.get("type") == "text"]
    return "\n".join(parts).strip()
