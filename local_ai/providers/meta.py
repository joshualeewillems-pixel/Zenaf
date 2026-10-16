"""Meta Model API provider — minimal generate + test.

OpenAI-compatible Chat Completions wire at https://api.meta.ai/v1.
Default model is muse-spark-1.3 (Standard tier, Meta's recommended default).
Key from META_API_KEY (Meta's docs also name MODEL_API_KEY; we accept both).
"""
from __future__ import annotations

import os

import requests

BASE = "https://api.meta.ai/v1"
DEFAULT_MODEL = (os.environ.get("ZENAF_META_MODEL") or "").strip() or "muse-spark-1.3"


def _effective_model(model: str | None) -> str:
    m = (model or "").strip()
    return m if m else DEFAULT_MODEL


def _api_key(api_key: str | None = None) -> str:
    return (
        (api_key or "").strip()
        or (os.environ.get("META_API_KEY") or "").strip()
        or (os.environ.get("MODEL_API_KEY") or "").strip()
    )


def test_connection(api_key: str, model: str | None = None) -> tuple[bool, str]:
    key = _api_key(api_key)
    if not key:
        return False, "Missing API key"
    try:
        r = requests.get(
            f"{BASE}/models",
            headers={"Authorization": f"Bearer {key}"},
            timeout=30,
        )
    except Exception as exc:
        return False, f"request failed: {exc}"
    if r.status_code == 200:
        return True, "ok"
    return False, f"HTTP {r.status_code}: {r.text[:200]}"


def generate(
    api_key: str,
    prompt: str,
    *,
    model: str | None = None,
    timeout: int = 120,
) -> str:
    key = _api_key(api_key)
    if not key:
        raise RuntimeError("Meta API key is not configured. Set META_API_KEY.")
    r = requests.post(
        f"{BASE}/chat/completions",
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        json={
            "model": _effective_model(model),
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.7,
        },
        timeout=timeout,
    )
    r.raise_for_status()
    data = r.json()
    try:
        return data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        raise RuntimeError(f"Unexpected Meta API response: {str(data)[:200]}")


class MetaProvider:
    """Meta Model API provider instance. Single method used by Zenaf: generate(prompt) -> response text."""

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        timeout: int | None = None,
    ):
        # None key means "read from env" (META_API_KEY, then MODEL_API_KEY) at generate time.
        self._api_key_kwarg = api_key
        self.model = model
        self.timeout = timeout

    def generate(self, prompt: str, *, timeout: int | None = None) -> str:
        """Send prompt to the Meta Model API; return model response text. Raises on HTTP/API errors."""
        key = ((self._api_key_kwarg or "").strip()) or None
        return generate(
            key or "",
            prompt,
            model=self.model,
            timeout=timeout if timeout is not None else (self.timeout or 120),
        )
