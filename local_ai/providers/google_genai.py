"""
Google Generative Language API — minimal generate + test.

Uses the REST endpoint ``POST .../v1beta/models/{model}:generateContent`` (same family as AI Studio).
Default model id is centralized in ``DEFAULT_MODEL`` — update when Google deprecates names.

Supported text defaults (verify in Google AI Studio / Cloud console):
- gemini-2.5-flash (default)
- gemini-2.5-flash-lite
- gemini-2.5-pro
"""

from __future__ import annotations

import logging

import requests

logger = logging.getLogger(__name__)

# API surface (documented for diagnostics).
API_VERSION = "v1beta"
BASE = f"https://generativelanguage.googleapis.com/{API_VERSION}"

# Default for Settings test + resolver when profile model is empty.
# Was gemini-1.5-flash (removed from many API versions — use current generation).
DEFAULT_MODEL = "gemini-2.5-flash"

# Optional aliases for docs / UI hints only (not enforced here).
SUGGESTED_TEXT_MODELS = (
    "gemini-2.5-flash",
    "gemini-2.5-flash-lite",
    "gemini-2.5-pro",
)


def _normalize_model_id(model: str | None) -> str:
    m = (model or DEFAULT_MODEL).strip() or DEFAULT_MODEL
    if m.startswith("models/"):
        m = m[len("models/") :].strip()
    return m


def _generate_content_url(model_id: str) -> str:
    return f"{BASE}/models/{model_id}:generateContent"


def _format_gemini_http_error(r: requests.Response) -> str:
    """Surface NOT_FOUND / unsupported model clearly for tests and UI."""
    try:
        data = r.json()
        err = data.get("error") or {}
        msg = (err.get("message") or "").strip()
        status = err.get("status") or ""
        code = err.get("code") or r.status_code
        low = (msg + str(status)).lower()
        if r.status_code == 404 or "not found" in low or "not_found" in low:
            return (
                f"Gemini model not found or not supported for generateContent (HTTP {r.status_code}, "
                f"{status or code}). {msg or r.text[:400]} "
                f"Try DEFAULT_MODEL or list_gemini_model_ids() / AI Studio model picker."
            )
        return msg or r.text[:500] or f"HTTP {r.status_code}"
    except Exception:
        return r.text[:500] or f"HTTP {r.status_code}"


def list_gemini_model_ids(api_key: str, *, timeout: int = 20) -> tuple[list[str] | None, str]:
    """
    GET ``v1beta/models`` — best-effort list of model resource names (paginated first page only).
    Returns (ids without ``models/`` prefix, error string if request failed).
    """
    key = (api_key or "").strip()
    if not key:
        return None, "Missing API key"
    try:
        r = requests.get(
            f"{BASE}/models",
            params={"key": key, "pageSize": 50},
            timeout=timeout,
        )
        if not r.ok:
            return None, _format_gemini_http_error(r)
        data = r.json()
        out: list[str] = []
        for m in data.get("models") or []:
            if not isinstance(m, dict):
                continue
            name = (m.get("name") or "").strip()
            if name.startswith("models/"):
                name = name[len("models/") :]
            if name:
                out.append(name)
        return out, ""
    except Exception as e:
        return None, str(e)


def test_connection(api_key: str, model: str | None = None) -> tuple[bool, str]:
    key = (api_key or "").strip()
    if not key:
        return False, "Missing API key"
    m = _normalize_model_id(model)
    url = _generate_content_url(m)
    logger.info(
        "Gemini test_connection: api_version=%s model_id=%s method=generateContent url=%s",
        API_VERSION,
        m,
        url,
    )
    try:
        r = requests.post(
            url,
            params={"key": key},
            json={"contents": [{"parts": [{"text": "Say OK"}]}]},
            timeout=25,
        )
        if r.status_code < 400:
            return True, ""
        err = _format_gemini_http_error(r)
        logger.warning("Gemini test_connection failed: model_id=%s status=%s detail=%s", m, r.status_code, err[:300])
        return False, err
    except Exception as e:
        logger.exception("Gemini test_connection exception model_id=%s", m)
        return False, str(e)


def generate(api_key: str, prompt: str, *, model: str | None = None, timeout: int = 120) -> str:
    key = (api_key or "").strip()
    m = _normalize_model_id(model)
    url = _generate_content_url(m)
    logger.info(
        "Gemini generate: api_version=%s model_id=%s method=generateContent",
        API_VERSION,
        m,
    )
    r = requests.post(
        url,
        params={"key": key},
        json={"contents": [{"parts": [{"text": prompt}]}]},
        timeout=timeout,
    )
    if not r.ok:
        raise RuntimeError(_format_gemini_http_error(r))
    data = r.json()
    candidates = data.get("candidates") or []
    if not candidates:
        return ""
    parts = ((candidates[0].get("content") or {}).get("parts")) or []
    texts = [p.get("text", "") for p in parts if isinstance(p, dict)]
    return "".join(texts).strip()
