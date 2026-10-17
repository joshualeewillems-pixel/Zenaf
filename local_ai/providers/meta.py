"""Meta Model API provider — minimal generate + test.

OpenAI-compatible Chat Completions wire at https://api.meta.ai/v1.
Default model is muse-spark-1.3 (Standard tier, Meta's recommended default).
Key from META_API_KEY (Meta's docs also name MODEL_API_KEY; we accept both).
"""
from __future__ import annotations

import json
import os
from typing import Iterator

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
    reasoning_effort: str | None = None,
) -> str:
    """Send prompt to the Meta Model API; return the reply text.

    reasoning_effort (minimal/low/medium/high/xhigh) controls how long Muse
    Spark reasons before answering. Reasoning is always on and its tokens
    bill as output — so short-reply surfaces (like the landing demo) should
    pass "low" or "minimal" to cut both latency and cost. None = API default.
    """
    key = _api_key(api_key)
    if not key:
        raise RuntimeError("Meta API key is not configured. Set META_API_KEY.")
    body: dict = {
        "model": _effective_model(model),
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.7,
    }
    if reasoning_effort:
        body["reasoning_effort"] = reasoning_effort
    r = requests.post(
        f"{BASE}/chat/completions",
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        json=body,
        timeout=timeout,
    )
    r.raise_for_status()
    data = r.json()
    try:
        return data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        raise RuntimeError(f"Unexpected Meta API response: {str(data)[:200]}")


def generate_stream(
    api_key: str,
    prompt: str,
    *,
    model: str | None = None,
    timeout: int = 120,
    reasoning_effort: str | None = None,
) -> Iterator[str]:
    """Yield reply text chunks (OpenAI-compatible SSE) from the Meta Model API.

    Same contract as generate(), but streams. Raises RuntimeError if the key
    is missing; raises on HTTP errors before yielding.
    """
    key = _api_key(api_key)
    if not key:
        raise RuntimeError("Meta API key is not configured. Set META_API_KEY.")
    body: dict = {
        "model": _effective_model(model),
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.7,
        "stream": True,
    }
    if reasoning_effort:
        body["reasoning_effort"] = reasoning_effort
    with requests.post(
        f"{BASE}/chat/completions",
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        json=body,
        timeout=timeout,
        stream=True,
    ) as r:
        r.raise_for_status()
        # Decode bytes as UTF-8 explicitly: iter_lines(decode_unicode=True) would
        # use the response's declared encoding (Latin-1 fallback for text/*),
        # mojibake-ing every em-dash and curly quote into â€”-style garbage.
        for raw_line in r.iter_lines(decode_unicode=False):
            if not raw_line:
                continue
            try:
                line = raw_line.decode("utf-8")
            except UnicodeDecodeError:
                continue
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                break
            try:
                chunk = json.loads(data)["choices"][0]["delta"].get("content")
            except (ValueError, KeyError, IndexError, TypeError):
                continue
            if chunk:
                yield chunk


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

    def generate(
        self,
        prompt: str,
        *,
        timeout: int | None = None,
        reasoning_effort: str | None = None,
    ) -> str:
        """Send prompt to the Meta Model API; return model response text. Raises on HTTP/API errors."""
        key = ((self._api_key_kwarg or "").strip()) or None
        return generate(
            key or "",
            prompt,
            model=self.model,
            timeout=timeout if timeout is not None else (self.timeout or 120),
            reasoning_effort=reasoning_effort,
        )
