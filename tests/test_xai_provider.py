"""xAI provider: defaults and error shaping (no live API calls)."""
from __future__ import annotations

from unittest.mock import MagicMock, patch


def test_default_model_is_current_generation() -> None:
    from local_ai.providers import xai as x

    assert x.DEFAULT_MODEL == "grok-4-1-fast-reasoning"
    assert "grok-2" not in x.DEFAULT_MODEL


def test_normalize_model_falls_back_to_default() -> None:
    from local_ai.providers.xai import _normalize_model

    assert _normalize_model(None) == "grok-4-1-fast-reasoning"
    assert _normalize_model("  ") == "grok-4-1-fast-reasoning"
    assert _normalize_model("grok-4.20-reasoning") == "grok-4.20-reasoning"


def test_format_xai_error_surfaces_configured_model_on_not_found() -> None:
    from local_ai.providers.xai import _format_xai_error

    r = MagicMock()
    r.status_code = 400
    r.json.return_value = {
        "error": {
            "message": "Model not found: grok-2-latest",
            "type": "invalid_request_error",
        }
    }
    r.text = ""
    msg = _format_xai_error(r, "grok-2-latest")
    assert "grok-2-latest" in msg
    assert "model" in msg.lower()


@patch("local_ai.providers.xai.requests.post")
def test_test_connection_returns_false_on_model_error(mock_post: MagicMock) -> None:
    from local_ai.providers import xai as x

    mock_post.return_value = MagicMock()
    mock_post.return_value.status_code = 400
    mock_post.return_value.ok = False
    mock_post.return_value.json.return_value = {
        "error": {"message": "Client specified an invalid argument", "code": "invalid_argument"}
    }
    mock_post.return_value.text = ""

    ok, err = x.test_connection("fake-key", model="grok-4-1-fast-reasoning")
    assert ok is False
    assert err
    assert "grok-4-1-fast-reasoning" in err
