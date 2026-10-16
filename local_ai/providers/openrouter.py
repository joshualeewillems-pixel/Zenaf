"""
OpenRouter provider — OpenAI-compatible chat completions via https://openrouter.ai/api/v1.

Used when execution policy primary is ``openrouter``.

Requires an OpenRouter API key (``sk-or-v1-...``) in the environment
(``OPENROUTER_API_KEY``) or explicit ``api_key`` in constructor; the recommended
onboarding path is "Sign in with OpenRouter" (OAuth PKCE), which mints a
user-owned key and stores it encrypted via the settings credential path.
"""

from __future__ import annotations

import json
import os
from typing import Any

import requests

DEFAULT_MODEL = "openai/gpt-4o-mini"


def _app_referer() -> str:
    return (os.environ.get("ZENAF_PUBLIC_URL") or "https://zenaf.ai").strip() or "https://zenaf.ai"


class OpenRouterProvider:
    """Chat-completions client pointed at OpenRouter; same ``generate(prompt, **kwargs) -> str`` contract."""

    CHAT_COMPLETIONS_URL = "https://openrouter.ai/api/v1/chat/completions"

    def __init__(
        self,
        model: str,
        *,
        api_key: str | None = None,
        timeout: int | None = None,
    ):
        self.model = (model or "").strip() or DEFAULT_MODEL
        self.api_key = (api_key or os.environ.get("OPENROUTER_API_KEY") or "").strip()
        self.timeout = int(timeout if timeout is not None else os.environ.get("OPENROUTER_TIMEOUT", "120"))

    def _headers(self) -> dict[str, str]:
        # OpenRouter asks apps to identify themselves; harmless on other OpenAI-compatible hosts.
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": _app_referer(),
            "X-Title": "Zenaf",
        }

    def generate(self, prompt: str, *, timeout: int | None = None) -> str:
        if not self.api_key:
            raise RuntimeError("OpenRouter API key is not configured. Sign in with OpenRouter in Settings.")
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.7,
        }
        r = requests.post(
            self.CHAT_COMPLETIONS_URL,
            headers=self._headers(),
            data=json.dumps(payload),
            timeout=timeout if timeout is not None else self.timeout,
        )
        if not r.ok:
            detail = (r.text or "")[:1200] or f"HTTP {r.status_code}"
            try:
                j = r.json()
                err = j.get("error")
                if isinstance(err, dict) and err.get("message"):
                    detail = str(err["message"])[:1200]
                elif isinstance(err, str) and err:
                    detail = err[:1200]
            except Exception:
                pass
            raise RuntimeError(f"OpenRouter error (HTTP {r.status_code}): {detail}")
        data = r.json()
        choices = data.get("choices") or []
        if not choices:
            raise RuntimeError("OpenRouter response missing choices")
        msg = choices[0].get("message") or {}
        content = msg.get("content")
        if content is None:
            raise RuntimeError("OpenRouter response missing message content")
        return str(content).strip()


def generate(api_key: str, prompt: str, *, model: str | None = None, timeout: int = 120) -> str:
    """Module-level API matching other cloud providers (used by ``_CloudLLMAdapter``)."""
    prov = OpenRouterProvider(model or DEFAULT_MODEL, api_key=api_key)
    return prov.generate(prompt, timeout=timeout)


def test_connection(api_key: str, model: str | None = None) -> tuple[bool, str]:
    """Lightweight chat-completions probe for Settings → Test LLM (matches other provider modules)."""
    key = (api_key or "").strip()
    if not key:
        return False, "Missing API key"
    m = (model or "").strip() or DEFAULT_MODEL
    try:
        r = requests.post(
            OpenRouterProvider.CHAT_COMPLETIONS_URL,
            headers={
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
                "HTTP-Referer": _app_referer(),
                "X-Title": "Zenaf",
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
