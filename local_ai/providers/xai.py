"""
xAI Grok — OpenAI-compatible Chat Completions API.

Endpoint: ``POST https://api.x.ai/v1/chat/completions`` (same request shape as OpenAI).

Default model id is centralized in ``DEFAULT_MODEL`` — update when xAI deprecates names.
"""

from __future__ import annotations

import logging

import requests

logger = logging.getLogger(__name__)

# OpenAI-compatible base (xAI docs).
API_BASE = "https://api.x.ai/v1"
CHAT_COMPLETIONS_PATH = f"{API_BASE}/chat/completions"

# Was ``grok-2-latest`` (no longer valid for many accounts / API versions).
DEFAULT_MODEL = "grok-4-1-fast-reasoning"

# Stronger / alternate (documented for operators; not validated here).
SUGGESTED_MODELS = (
    "grok-4-1-fast-reasoning",
    "grok-4.20-reasoning",
)


def _normalize_model(model: str | None) -> str:
    return (model or DEFAULT_MODEL).strip() or DEFAULT_MODEL


def _format_xai_error(r: requests.Response, configured_model: str) -> str:
    """Surface model-not-found and include the configured model id for debugging."""
    snippet = ""
    try:
        j = r.json()
        err = j.get("error")
        if isinstance(err, dict):
            msg = (err.get("message") or err.get("param") or "").strip()
            typ = str(err.get("type") or "")
            code = err.get("code")
            parts = [f"HTTP {r.status_code}"]
            if typ:
                parts.append(typ)
            if code is not None:
                parts.append(str(code))
            if msg:
                parts.append(msg)
            snippet = ": ".join(parts)
        elif err is not None:
            snippet = str(err)
        else:
            snippet = str(j)[:600]
    except Exception:
        snippet = (r.text or "")[:500] or f"HTTP {r.status_code}"

    low = snippet.lower()
    if r.status_code >= 400 and (
        "model" in low
        and ("not found" in low or "invalid" in low or "does not exist" in low or "unknown model" in low)
    ):
        return (
            f"xAI rejected the request for model {configured_model!r} (model missing or not allowed for this key). "
            f"{snippet}"
        )
    return f"xAI error for model {configured_model!r}: {snippet}"


def test_connection(api_key: str, model: str | None = None) -> tuple[bool, str]:
    key = (api_key or "").strip()
    if not key:
        return False, "Missing API key"
    m = _normalize_model(model)
    logger.info(
        "xAI test_connection: provider_used=xai model_used=%s endpoint=%s",
        m,
        CHAT_COMPLETIONS_PATH,
    )
    try:
        r = requests.post(
            CHAT_COMPLETIONS_PATH,
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            json={
                "model": m,
                "messages": [{"role": "user", "content": "Say OK"}],
                "max_tokens": 8,
            },
            timeout=25,
        )
        if r.status_code < 400:
            return True, ""
        err = _format_xai_error(r, m)
        logger.warning(
            "xAI test_connection failed: model_used=%s status=%s detail=%s",
            m,
            r.status_code,
            err[:400],
        )
        return False, err
    except Exception as e:
        logger.exception("xAI test_connection exception model_used=%s", m)
        return False, str(e)


def generate(api_key: str, prompt: str, *, model: str | None = None, timeout: int = 120) -> str:
    key = (api_key or "").strip()
    m = _normalize_model(model)
    logger.info(
        "xAI generate: provider_used=xai model_used=%s endpoint=%s",
        m,
        CHAT_COMPLETIONS_PATH,
    )
    r = requests.post(
        CHAT_COMPLETIONS_PATH,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        json={
            "model": m,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 4096,
        },
        timeout=timeout,
    )
    if not r.ok:
        raise RuntimeError(_format_xai_error(r, m))
    data = r.json()
    return (data["choices"][0]["message"]["content"] or "").strip()
