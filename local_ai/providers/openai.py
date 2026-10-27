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

    def _post(self, prompt: str, *, timeout: int | None = None) -> dict:
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
        return r.json()

    def generate(self, prompt: str, *, timeout: int | None = None) -> str:
        data = self._post(prompt, timeout=timeout)
        choices = data.get("choices") or []
        if not choices:
            raise RuntimeError("OpenAI response missing choices")
        msg = choices[0].get("message") or {}
        content = msg.get("content")
        if content is None:
            raise RuntimeError("OpenAI response missing message content")
        return str(content).strip()

    def generate_structured(self, messages: list, *, tools: list,
                            timeout: int | None = None) -> dict:
        """Structured tool-call channel (tool-access stage-1 increment B).

        POSTs the full message list with a tools schema and returns
        the model's reply as structured data — content text (or
        None) plus a ``tool_calls`` list — separate from model text.
        The runner NEVER parses model text for tool calls; it reads
        only this structured object. Arguments arrive as a JSON
        string from the API and are parsed here into a dict; an
        unparseable arguments string is returned with
        ``arguments=None`` and the raw string preserved, so the
        runner refuses it as malformed instead of guessing.
        """
        if not self.api_key:
            raise RuntimeError("OpenAI API key is not configured. Set OPENAI_API_KEY.")
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "tools": tools,
            "tool_choice": "auto",
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
        tool_calls: list[dict[str, Any]] = []
        for raw in msg.get("tool_calls") or []:
            fn = raw.get("function") or {}
            arguments_raw = fn.get("arguments")
            arguments = None
            if isinstance(arguments_raw, str):
                try:
                    arguments = json.loads(arguments_raw)
                except (json.JSONDecodeError, ValueError):
                    arguments = None
            tool_calls.append({
                "id": raw.get("id") or "",
                "name": fn.get("name") or "",
                "arguments": arguments,
                "arguments_raw": arguments_raw if isinstance(arguments_raw, str) else None,
            })
        return {
            "content": str(content).strip() if isinstance(content, str) else None,
            "tool_calls": tool_calls,
        }

    def generate_with_usage(self, prompt: str, *,
                            timeout: int | None = None) -> tuple[str, dict | None]:
        """Parallel to generate(): identical POST, plus the usage block.

        Returns (text, usage-dict-or-None). The existing generate()
        is untouched and still returns text only. Usage carries
        tokens, never dollars — any charge is calculated from a
        price table by the caller, never read from the provider.
        """
        data = self._post(prompt, timeout=timeout)
        choices = data.get("choices") or []
        if not choices:
            raise RuntimeError("OpenAI response missing choices")
        msg = choices[0].get("message") or {}
        content = msg.get("content")
        if content is None:
            raise RuntimeError("OpenAI response missing message content")
        usage = data.get("usage")
        return str(content).strip(), usage if isinstance(usage, dict) else None


def generate(api_key: str, prompt: str, *, model: str | None = None, timeout: int = 120) -> str:
    """Module-level API matching other cloud providers (used by ``_CloudLLMAdapter``)."""
    prov = OpenAIProvider(model or "gpt-4o-mini", api_key=api_key)
    return prov.generate(prompt, timeout=timeout)


def generate_structured(api_key: str, messages: list, *, model: str | None = None,
                        tools: list | None = None, timeout: int = 120) -> dict:
    """Module-level parallel to generate(): structured tool-call channel."""
    prov = OpenAIProvider(model or "gpt-4o-mini", api_key=api_key)
    return prov.generate_structured(messages, tools=tools or [], timeout=timeout)


def generate_with_usage(api_key: str, prompt: str, *, model: str | None = None,
                        timeout: int = 120) -> tuple[str, dict | None]:
    """Module-level parallel to generate(): (text, usage-dict-or-None)."""
    prov = OpenAIProvider(model or "gpt-4o-mini", api_key=api_key)
    return prov.generate_with_usage(prompt, timeout=timeout)


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
