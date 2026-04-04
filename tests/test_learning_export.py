"""Learning buffer export/inspect (env-gated, authenticated)."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from api.main import app
from api.routes.auth_routes import get_current_user
from local_ai.delegation.learning_capture import capture_general_delegation_outcome, get_learning_buffer


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture(autouse=True)
def _auth_override():
    app.dependency_overrides[get_current_user] = lambda: {
        "id": "test-user",
        "email": "t@test.local",
        "display_name": "Test",
    }
    yield
    app.dependency_overrides.pop(get_current_user, None)


@pytest.fixture(autouse=True)
def _clear_buffer():
    get_learning_buffer().clear()
    yield
    get_learning_buffer().clear()


def test_export_forbidden_when_env_disabled(client, monkeypatch):
    monkeypatch.delenv("ATRIA_LEARNING_EXPORT_ENABLED", raising=False)
    r = client.get("/vision-execution/learning-records/export")
    assert r.status_code == 403


def test_export_jsonl_when_enabled(client, monkeypatch):
    monkeypatch.setenv("ATRIA_LEARNING_EXPORT_ENABLED", "1")
    rid = capture_general_delegation_outcome(
        surface="s",
        action_intent="a",
        privacy_mode="normal",
        provider_used="openai",
        model_used="m",
        input_snapshot="ctx",
        compiled_prompt="p",
        validation_passed=True,
        validation_error=None,
        raw_or_parsed_output="out",
    )
    assert rid
    r = client.get("/vision-execution/learning-records/export?format=jsonl&limit=10")
    assert r.status_code == 200
    assert "application/x-ndjson" in r.headers.get("content-type", "") or "ndjson" in r.headers.get("content-type", "")
    lines = [ln for ln in r.text.strip().split("\n") if ln.strip()]
    assert len(lines) == 1
    row = json.loads(lines[0])
    assert row["record_id"] == rid
    assert row["action_intent"] == "a"
    assert row["delegation_tier"] == "general"
    assert row["capture_mode"] == "full"
    assert "ts_ms" in row


def test_stats_endpoint(client, monkeypatch):
    monkeypatch.setenv("ATRIA_LEARNING_EXPORT_ENABLED", "1")
    capture_general_delegation_outcome(
        surface="s",
        action_intent="x",
        privacy_mode="restricted",
        provider_used="openai",
        model_used="m",
        input_snapshot="secret",
        compiled_prompt="p",
        validation_passed=False,
        validation_error="e",
        raw_or_parsed_output="z",
    )
    r = client.get("/vision-execution/learning-records/stats")
    assert r.status_code == 200
    data = r.json()
    assert data["total_in_buffer"] >= 1
    assert "general" in str(data.get("delegation_tier_counts", {}))


def test_inspect_json_pagination(client, monkeypatch):
    monkeypatch.setenv("ATRIA_LEARNING_EXPORT_ENABLED", "1")
    for i in range(3):
        capture_general_delegation_outcome(
            surface="s",
            action_intent=f"intent_{i}",
            privacy_mode="normal",
            provider_used="p",
            model_used="m",
            input_snapshot="x",
            compiled_prompt="p",
            validation_passed=True,
            validation_error=None,
            raw_or_parsed_output="o",
        )
    r = client.get("/vision-execution/learning-records/inspect?limit=2&offset=0&order=asc")
    assert r.status_code == 200
    data = r.json()
    assert data["total_in_buffer"] == 3
    assert len(data["records"]) == 2
    assert data["records"][0]["action_intent"] == "intent_0"
