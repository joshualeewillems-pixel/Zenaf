"""Studio admin bakeoff endpoint (council native attachment lane)."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pytest
from fastapi.testclient import TestClient

from api.main import app
from api.routes.auth_routes import get_current_admin_user
from api.routes.studio_routes import (
    BAKEOFF_LANE_COUNCIL_NATIVE,
    run_council_native_bakeoff_for_admin,
)
from local_ai.llm.adapter import BlockedLLMAdapter, LLMRequest


class _FakeOkAdapter:
    def generate_text(self, request: LLMRequest) -> str:
        return f"echo:{request.prompt[:20]}"


@pytest.fixture
def admin_client():
    def _admin():
        return {"id": "studio-bakeoff-test-user", "email": "sb@example.com", "is_admin": True}

    app.dependency_overrides[get_current_admin_user] = _admin
    yield TestClient(app)
    app.dependency_overrides.pop(get_current_admin_user, None)


def test_bakeoff_endpoint_wrong_lane(admin_client):
    r = admin_client.post(
        "/studio/attachment-lane/bakeoff",
        json={
            "lane": "other_lane",
            "prompt": "hi",
            "providers": [{"provider": "ollama", "model": "m"}],
        },
    )
    assert r.status_code == 400


def test_bakeoff_endpoint_success_rows(admin_client, monkeypatch):
    def fake_get_adapter(principal, *, force_provider=None, force_model=None, allows_externalization=True):
        fp = (force_provider or "").strip().lower()
        if fp == "openai":
            return BlockedLLMAdapter("no key for test")
        return _FakeOkAdapter()

    monkeypatch.setattr("api.routes.studio_routes.get_council_llm_adapter_for_principal", fake_get_adapter)
    monkeypatch.setattr("local_ai.studio.bakeoff_scoring.get_council_llm_adapter_for_principal", fake_get_adapter)
    r = admin_client.post(
        "/studio/attachment-lane/bakeoff",
        json={
            "lane": BAKEOFF_LANE_COUNCIL_NATIVE,
            "prompt": "What is 2+2?",
            "score_bakeoff": False,
            "providers": [
                {"provider": "ollama", "model": "q"},
                {"provider": "openai", "model": "gpt-x"},
            ],
        },
    )
    assert r.status_code == 200
    data = r.json()
    assert data["lane"] == BAKEOFF_LANE_COUNCIL_NATIVE
    assert data["principal_ref"] == "account:studio-bakeoff-test-user"
    assert len(data["results"]) == 2
    by_p = {r["provider"]: r for r in data["results"]}
    assert by_p["ollama"]["ok"] is True
    assert "echo:" in (by_p["ollama"].get("output_preview") or "")
    assert by_p["openai"]["ok"] is False
    assert "no key" in (by_p["openai"].get("error") or "").lower()


def test_run_council_native_bakeoff_unknown_provider_unit():
    from api.routes.studio_routes import AttachmentLaneBakeoffProviderSpec

    out = run_council_native_bakeoff_for_admin(
        admin_user_id="u-bakeoff",
        prompt="p",
        provider_specs=[
            AttachmentLaneBakeoffProviderSpec(provider="not_a_provider", model="x"),
        ],
        score_bakeoff=False,
    )
    assert out["results"][0]["ok"] is False
    assert "Unsupported provider" in (out["results"][0].get("error") or "")
    assert out["results"][0].get("total_score") == 0


def test_provider_default_models_endpoint(admin_client):
    r = admin_client.get("/studio/provider-default-models")
    assert r.status_code == 200
    j = r.json()
    assert j.get("google") == "gemini-3.8-flash"
    assert j.get("xai") == "grok-4-1-fast-reasoning"
    assert "source" in j


def test_bakeoff_suggested_model_on_generation_404(admin_client, monkeypatch):
    class Boom:
        def generate_text(self, request):
            raise RuntimeError(
                "Gemini model not found or not supported for generateContent (HTTP 404, NOT_FOUND). models/old is not found."
            )

    def fake_get_adapter(principal, *, force_provider=None, force_model=None, allows_externalization=True):
        fp = (force_provider or "").strip().lower()
        if fp == "google":
            return Boom()
        return BlockedLLMAdapter("skip")

    monkeypatch.setattr("api.routes.studio_routes.get_council_llm_adapter_for_principal", fake_get_adapter)
    monkeypatch.setattr("local_ai.studio.bakeoff_scoring.get_council_llm_adapter_for_principal", fake_get_adapter)
    r = admin_client.post(
        "/studio/attachment-lane/bakeoff",
        json={
            "lane": BAKEOFF_LANE_COUNCIL_NATIVE,
            "prompt": "test",
            "score_bakeoff": False,
            "providers": [{"provider": "google", "model": "deprecated-model"}],
        },
    )
    assert r.status_code == 200
    row = r.json()["results"][0]
    assert row["ok"] is False
    assert row.get("suggested_default_model") == "gemini-3.8-flash"


def test_bakeoff_scoring_mocked_judge(admin_client, monkeypatch):
    def fake_get_adapter(principal, *, force_provider=None, force_model=None, allows_externalization=True):
        fp = (force_provider or "").strip().lower()
        if fp == "ollama":
            return _FakeOkAdapter()

        class _JudgeAdapter:
            def generate_text(self, request: LLMRequest) -> str:
                return (
                    '{"grounding_score":4,"structure_score":3,"specificity_score":3,'
                    '"constraint_obedience_score":4,"usefulness_score":4,'
                    '"score_notes":"ok"}'
                )

        if fp == "openai":
            return _JudgeAdapter()
        return BlockedLLMAdapter("test: unsupported provider in mock")

    monkeypatch.setattr("api.routes.studio_routes.get_council_llm_adapter_for_principal", fake_get_adapter)
    monkeypatch.setattr("local_ai.studio.bakeoff_scoring.get_council_llm_adapter_for_principal", fake_get_adapter)
    r = admin_client.post(
        "/studio/attachment-lane/bakeoff",
        json={
            "lane": BAKEOFF_LANE_COUNCIL_NATIVE,
            "prompt": "Clarify council grounding for software.",
            "score_bakeoff": True,
            "providers": [{"provider": "ollama", "model": "q"}],
        },
    )
    assert r.status_code == 200
    row = r.json()["results"][0]
    assert row["ok"] is True
    assert row.get("total_score") == 18
    assert row.get("grounding_score") == 4
