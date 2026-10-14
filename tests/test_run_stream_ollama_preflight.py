"""Tests for the /run/stream Ollama pre-flight reachability check.

A dead Ollama mid-stream kills the SSE response opaquely (mobile clients
surface it as "Load failed"). The pre-flight fails fast with a clean 502
before the stream starts.
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException


def test_preflight_skips_non_ollama_providers():
    from api.main import _preflight_ollama_reachable

    # Must not probe the network for other providers (would raise without mocks).
    _preflight_ollama_reachable("anthropic")
    _preflight_ollama_reachable("openai")
    _preflight_ollama_reachable("")
    _preflight_ollama_reachable(None)


def test_preflight_passes_when_ollama_reachable(monkeypatch):
    from api.main import _preflight_ollama_reachable

    class _Resp:
        def raise_for_status(self):
            return None

    import requests

    monkeypatch.setattr(requests, "get", lambda url, timeout: _Resp())
    _preflight_ollama_reachable("ollama")
    _preflight_ollama_reachable("Ollama")  # case-insensitive


def test_preflight_502_when_ollama_unreachable(monkeypatch):
    from api.main import _preflight_ollama_reachable

    import requests

    def _boom(url, timeout):
        raise requests.ConnectionError("refused")

    monkeypatch.setattr(requests, "get", _boom)
    with pytest.raises(HTTPException) as ei:
        _preflight_ollama_reachable("ollama")
    assert ei.value.status_code == 502
    assert "Ollama" in str(ei.value.detail)
    assert "Auto (policy)" in str(ei.value.detail)
