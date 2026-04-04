"""Vision Execution soil API: append + promote (authenticated, VE-guarded)."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api.main import app
from api.routes.auth_routes import get_current_user
from local_ai.soil import api_guard as soil_api_guard


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def client_authed():
    app.dependency_overrides[get_current_user] = lambda: {
        "id": "soil-test-user",
        "email": "soil@test.local",
        "display_name": "Soil Test",
    }
    yield TestClient(app)
    app.dependency_overrides.pop(get_current_user, None)


@pytest.fixture(autouse=True)
def _soil_ve_guard_bypass(monkeypatch):
    """Most tests skip SQLite VE; integration-style tests re-bind to real guard."""
    monkeypatch.setattr(
        "api.routes.soil_api.verify_ve_subject_exists_for_soil_api",
        lambda *a, **k: None,
    )


def test_soil_append_requires_auth(client):
    r = client.post(
        "/vision-execution/soil/append",
        json={
            "entity_type": "task",
            "entity_id": "t1",
            "soil_type": "tension",
            "body": "x",
            "capture_source": "user_action",
        },
    )
    assert r.status_code == 401


def test_soil_append_ok(client_authed, tmp_path, monkeypatch):
    monkeypatch.setenv("ATRIA_SOIL_ROOT", str(tmp_path))
    r = client_authed.post(
        "/vision-execution/soil/append",
        json={
            "entity_type": "task",
            "entity_id": "t1",
            "soil_type": "tension",
            "body": "Scope unclear.",
            "capture_source": "user_action",
            "title": "Note",
        },
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["ok"] is True
    assert data["soil_id"].startswith("soil_")
    assert "nodes/task/t1/" in data["relative_path"].replace("\\", "/")


def test_soil_append_named_capture_allowlisted(client_authed, tmp_path, monkeypatch):
    monkeypatch.setenv("ATRIA_SOIL_ROOT", str(tmp_path))
    r = client_authed.post(
        "/vision-execution/soil/append",
        json={
            "entity_type": "task",
            "entity_id": "t2",
            "soil_type": "hypothesis",
            "body": "h",
            "capture_source": "named_system_capture",
            "capture_name": "dev_soil_export",
        },
    )
    assert r.status_code == 200, r.text


def test_soil_append_named_capture_unknown_name(client_authed, tmp_path, monkeypatch):
    monkeypatch.setenv("ATRIA_SOIL_ROOT", str(tmp_path))
    r = client_authed.post(
        "/vision-execution/soil/append",
        json={
            "entity_type": "task",
            "entity_id": "t3",
            "soil_type": "hypothesis",
            "body": "h",
            "capture_source": "named_system_capture",
            "capture_name": "council_auto_dump",
        },
    )
    assert r.status_code == 400


def test_soil_append_root_without_explicit_flag(client_authed, tmp_path, monkeypatch):
    monkeypatch.setenv("ATRIA_SOIL_ROOT", str(tmp_path))
    monkeypatch.setattr(
        "api.routes.soil_api.verify_ve_subject_exists_for_soil_api",
        soil_api_guard.verify_ve_subject_exists_for_soil_api,
    )
    r = client_authed.post(
        "/vision-execution/soil/append",
        json={
            "entity_type": "_root",
            "entity_id": "",
            "soil_type": "inbox",
            "body": "x",
            "capture_source": "user_action",
            "explicit_root_bucket": False,
        },
    )
    assert r.status_code == 403
    assert "root_bucket" in r.json()["detail"]


def test_soil_append_root_when_explicit(client_authed, tmp_path, monkeypatch):
    monkeypatch.setenv("ATRIA_SOIL_ROOT", str(tmp_path))
    monkeypatch.setattr(
        "api.routes.soil_api.verify_ve_subject_exists_for_soil_api",
        soil_api_guard.verify_ve_subject_exists_for_soil_api,
    )
    r = client_authed.post(
        "/vision-execution/soil/append",
        json={
            "entity_type": "_root",
            "entity_id": "",
            "soil_type": "inbox",
            "body": "global inbox",
            "capture_source": "user_action",
            "explicit_root_bucket": True,
        },
    )
    assert r.status_code == 200, r.text
    assert "_root" in r.json()["relative_path"].replace("\\", "/")


def test_soil_promote_after_append(client_authed, tmp_path, monkeypatch):
    monkeypatch.setenv("ATRIA_SOIL_ROOT", str(tmp_path))
    a = client_authed.post(
        "/vision-execution/soil/append",
        json={
            "entity_type": "initiative",
            "entity_id": "i9",
            "soil_type": "excerpt",
            "body": "evidence",
            "capture_source": "user_action",
        },
    )
    assert a.status_code == 200
    soil_id = a.json()["soil_id"]

    p = client_authed.post(
        "/vision-execution/soil/promote",
        json={
            "entity_type": "initiative",
            "entity_id": "i9",
            "from_soil_id": soil_id,
            "to_node_id": "project:abc",
            "reason": "audit only",
        },
    )
    assert p.status_code == 200, p.text
    data = p.json()
    assert data["ok"] is True
    assert data["promotion_id"]
    root = tmp_path.resolve()
    rel = data["relative_path"].replace("/", os.sep)
    jpath = root / rel
    rec = json.loads(Path(jpath).read_text(encoding="utf-8"))
    assert rec["accepted_by"] == "api:soil-test-user"
    assert rec["to_node_id"] == "project:abc"
    assert rec["to_canonical_ref"]["kind"] == "unspecified"


def test_soil_append_body_at_max_and_over_max(client_authed, tmp_path, monkeypatch):
    monkeypatch.setenv("ATRIA_SOIL_ROOT", str(tmp_path))
    ok = client_authed.post(
        "/vision-execution/soil/append",
        json={
            "entity_type": "task",
            "entity_id": "t1",
            "soil_type": "tension",
            "body": "B" * 262_144,
            "capture_source": "user_action",
        },
    )
    assert ok.status_code == 200, ok.text
    root = tmp_path.resolve()
    rel = ok.json()["relative_path"]
    text = root.joinpath(*rel.split("/")).read_text(encoding="utf-8")
    assert text.count("B") == 262_144

    bad = client_authed.post(
        "/vision-execution/soil/append",
        json={
            "entity_type": "task",
            "entity_id": "t1",
            "soil_type": "tension",
            "body": "C" * 262_145,
            "capture_source": "user_action",
        },
    )
    assert bad.status_code == 422


def test_soil_ve_guard_not_found(client_authed, tmp_path, monkeypatch):
    monkeypatch.setenv("ATRIA_SOIL_ROOT", str(tmp_path))
    monkeypatch.setattr(
        "api.routes.soil_api.verify_ve_subject_exists_for_soil_api",
        soil_api_guard.verify_ve_subject_exists_for_soil_api,
    )
    monkeypatch.setattr(
        "local_ai.vision_execution.service.get_task",
        lambda tid, uid: None,
    )
    r = client_authed.post(
        "/vision-execution/soil/append",
        json={
            "entity_type": "task",
            "entity_id": "missing-task",
            "soil_type": "tension",
            "body": "x",
            "capture_source": "user_action",
        },
    )
    assert r.status_code == 404
    assert r.json()["detail"] == "soil_api_ve_subject_not_found"
