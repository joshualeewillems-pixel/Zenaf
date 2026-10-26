"""Gemini provider: defaults and error shaping (no live API calls)."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


def test_default_model_is_current_generation() -> None:
    from local_ai.providers import google_genai as g

    assert g.DEFAULT_MODEL == "gemini-3.8-flash"
    assert "gemini-1.5" not in g.DEFAULT_MODEL


def test_normalize_model_id_strips_models_prefix() -> None:
    from local_ai.providers.google_genai import _normalize_model_id

    assert _normalize_model_id("models/gemini-3.8-flash") == "gemini-3.8-flash"
    assert _normalize_model_id(None) == "gemini-3.8-flash"


def test_format_gemini_http_error_surfaces_not_found() -> None:
    from local_ai.providers.google_genai import _format_gemini_http_error

    r = MagicMock()
    r.status_code = 404
    r.json.return_value = {
        "error": {
            "code": 404,
            "message": "models/gemini-1.5-flash is not found for API version v1beta",
            "status": "NOT_FOUND",
        }
    }
    r.text = ""
    msg = _format_gemini_http_error(r)
    assert "not found" in msg.lower() or "NOT_FOUND" in msg
    assert "generateContent" in msg


@patch("local_ai.providers.google_genai.requests.post")
def test_test_connection_logs_and_returns_false_on_http_error(mock_post: MagicMock) -> None:
    from local_ai.providers import google_genai as g

    mock_post.return_value = MagicMock()
    mock_post.return_value.status_code = 404
    mock_post.return_value.ok = False
    mock_post.return_value.json.return_value = {
        "error": {"message": "model not found", "status": "NOT_FOUND"}
    }
    mock_post.return_value.text = ""

    ok, err = g.test_connection("fake-key", model="gemini-3.8-flash")
    assert ok is False
    assert err
