"""
OpenAI Chat Completions provider — used when execution policy primary is ``openai``.

Requires ``OPENAI_API_KEY`` in the environment (or explicit ``api_key`` in constructor).
"""

from __future__ import annotations

import json
import os
from typing import Any

import requests


class OpenAIProvider:
    """Minimal chat-completions client; same ``generate(prompt, **kwargs) -> str`` contract as OllamaProvider."""

    CHAT_COMPLETIONS_URL = "https://api.openai.com/v1/chat/completions"

    def __init__(
        self,
        model: str,
        *,
        api_key: str | None = None,
        timeout: int | None = None,
    ):
        self.model = (model or "").strip() or "gpt-4o-mini"
        self.api_key = (api_key or os.environ.get("OPENAI_API_KEY") or "").strip()
        self.timeout = int(timeout if timeout is not None else os.environ.get("OPENAI_TIMEOUT", "120"))

    def generate(self, prompt: str, *, timeout: int | None = None) -> str:
        if not self.api_key:
            raise RuntimeError("OpenAI API key is not configured. Set OPENAI_API_KEY.")
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.7,
        }
        r = requests.post(
            self.CHAT_COMPLETIONS_URL,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            data=json.dumps(payload),
            timeout=timeout if timeout is not None else self.timeout,
        )
        if not r.ok:
            from local_ai.execution_policy.openai_credentials import classify_openai_http_error

            detail = classify_openai_http_error(r.status_code, r.text or "")
            try:
                j = r.json()
                err = j.get("error")
                if isinstance(err, dict) and err.get("message"):
                    detail = f"{detail} ({err['message']})"[:1200]
            except Exception:
                pass
            raise RuntimeError(detail)
        data = r.json()
        choices = data.get("choices") or []
        if not choices:
            raise RuntimeError("OpenAI response missing choices")
        msg = choices[0].get("message") or {}
        content = msg.get("content")
        if content is None:
            raise RuntimeError("OpenAI response missing message content")
        return str(content).strip()


def generate(api_key: str, prompt: str, *, model: str | None = None, timeout: int = 120) -> str:
    """Module-level API matching other cloud providers (used by ``_CloudLLMAdapter``)."""
    prov = OpenAIProvider(model or "gpt-4o-mini", api_key=api_key)
    return prov.generate(prompt, timeout=timeout)


def test_connection(api_key: str, model: str | None = None) -> tuple[bool, str]:
    """Lightweight chat-completions probe for Settings → Test LLM (matches other provider modules)."""
    key = (api_key or "").strip()
    if not key:
        return False, "Missing API key"
    m = (model or "").strip() or "gpt-4o-mini"
    try:
        r = requests.post(
            OpenAIProvider.CHAT_COMPLETIONS_URL,
            headers={
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
            },
            json={
                "model": m,
                "messages": [{"role": "user", "content": "Reply with OK"}],
                "max_tokens": 8,
                "temperature": 0,
            },
            timeout=25,
        )
        if r.status_code < 400:
            return True, ""
        return False, (r.text or "")[:500] or f"HTTP {r.status_code}"
    except Exception as e:
        return False, str(e)
