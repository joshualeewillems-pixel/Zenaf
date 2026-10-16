"""reasoning_effort passthrough on the Meta provider (mocked HTTP)."""

from __future__ import annotations

import json

import local_ai.providers.meta as meta


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


def _capture(monkeypatch):
    captured = {}

    def fake_post(url, headers=None, json=None, timeout=None):
        captured["url"] = url
        captured["json"] = json
        captured["timeout"] = timeout
        return _FakeResponse({"choices": [{"message": {"content": "ok"}}]})

    monkeypatch.setattr(meta.requests, "post", fake_post)
    return captured


def test_reasoning_effort_passed_when_set(monkeypatch):
    captured = _capture(monkeypatch)
    out = meta.generate("k", "hi", reasoning_effort="low")
    assert out == "ok"
    assert captured["json"]["reasoning_effort"] == "low"


def test_reasoning_effort_omitted_by_default(monkeypatch):
    captured = _capture(monkeypatch)
    meta.generate("k", "hi")
    assert "reasoning_effort" not in captured["json"]


def test_provider_class_forwards_reasoning_effort(monkeypatch):
    captured = _capture(monkeypatch)
    p = meta.MetaProvider(api_key="k")
    p.generate("hi", reasoning_effort="minimal")
    assert captured["json"]["reasoning_effort"] == "minimal"


def test_missing_key_still_raises(monkeypatch):
    monkeypatch.delenv("META_API_KEY", raising=False)
    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    try:
        meta.generate("", "hi", reasoning_effort="low")
    except RuntimeError as exc:
        assert "not configured" in str(exc)
    else:
        raise AssertionError("expected RuntimeError")
