"""Account-scoped cloud keys: env vars (like OPENAI) apply when signed in."""
from __future__ import annotations

import os
import uuid

import pytest

from local_ai.llm.credentials import resolve_cloud_api_key
from local_ai.llm.execution_principal import authenticated_account_principal


@pytest.fixture
def fake_uid() -> str:
    return str(uuid.uuid4())


def test_anthropic_env_before_storage(monkeypatch: pytest.MonkeyPatch, fake_uid: str) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    p = authenticated_account_principal(fake_uid)
    key, src = resolve_cloud_api_key(p, "anthropic")
    assert key == "sk-ant-test"
    assert src == "env"


def test_google_env_gemini_fallback(monkeypatch: pytest.MonkeyPatch, fake_uid: str) -> None:
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.setenv("GEMINI_API_KEY", "AIza-gemini")
    p = authenticated_account_principal(fake_uid)
    key, src = resolve_cloud_api_key(p, "google")
    assert key == "AIza-gemini"
    assert src == "env"


def test_xai_env(monkeypatch: pytest.MonkeyPatch, fake_uid: str) -> None:
    monkeypatch.setenv("XAI_API_KEY", "xai-test")
    p = authenticated_account_principal(fake_uid)
    key, src = resolve_cloud_api_key(p, "xai")
    assert key == "xai-test"
    assert src == "env"


def test_anonymous_skips_non_openai_env(monkeypatch: pytest.MonkeyPatch) -> None:
    from local_ai.llm.execution_principal import anonymous_account_principal

    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    p = anonymous_account_principal()
    key, src = resolve_cloud_api_key(p, "anthropic")
    assert key is None
    assert src == "none"
