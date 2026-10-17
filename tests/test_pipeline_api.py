"""Pipeline API routes via TestClient (auth overridden, tmp dbs, mocked LLM)."""

from __future__ import annotations

import base64
import io
import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw

import api.routes.pipeline_routes as pipe_routes
import api.routes.provenance_routes as prov_routes
from api.routes.auth_routes import get_current_user
from local_ai.pipeline.store import PipelineStore
from local_ai.provenance.store import ProvenanceStore

ALICE = {"id": "user-alice", "email": "alice@x", "display_name": "Alice"}

JOURNEY_TEXT = (
    "I left my job back in March and started something of my own. The first "
    "months were hard — I failed twice, felt lost and overwhelmed by doubt. "
    "But I kept going, and I finally learned what I actually want from work. "
    "Now I feel grateful for the struggle; it made me stronger and wiser."
)

STORY_JSON = {
    "title": "Leaving to Begin",
    "narrative": "You left the safe job in March. The first months were hard and you felt lost. But you kept going, and you learned what you actually want.",
    "key_line": "The struggle taught me what I actually want.",
}
PACK_JSON = {
    "pack_title": "Leaving to Begin — song",
    "prompts": ["Verse one... chorus...", "blues, slow tempo"],
    "style_line": "old blues",
    "negative_prompt": "no pop clichés",
}


def _fake_generate(api_key, prompt, **kwargs):
    if "prompt pack" in prompt.lower():
        return json.dumps(PACK_JSON)
    return json.dumps(STORY_JSON)


def _img_b64() -> str:
    img = Image.new("RGB", (64, 64), "white")
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, 31, 63], fill="black")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()


@pytest.fixture()
def client(tmp_path, monkeypatch):
    import local_ai.providers.meta as meta

    monkeypatch.setattr(meta, "generate", _fake_generate)
    prov = ProvenanceStore(tmp_path / "prov.db")
    pstore = PipelineStore(tmp_path / "pipe.db")
    monkeypatch.setattr(pipe_routes, "_store", lambda: prov)
    monkeypatch.setattr(pipe_routes, "_pstore", lambda: pstore)
    monkeypatch.setattr(prov_routes, "_store", lambda: prov)
    app = FastAPI()
    app.include_router(pipe_routes.router)
    app.include_router(prov_routes.router)
    app.dependency_overrides[get_current_user] = lambda: ALICE
    c = TestClient(app)
    yield c
    prov.close()
    pstore.close()


def _entry(client, text=JOURNEY_TEXT):
    r = client.post("/pipeline/journal", json={"text": text})
    assert r.status_code == 200, r.text
    return r.json()


def _story(client, entry_id):
    r = client.post("/pipeline/story", json={"journal_entry_id": entry_id})
    assert r.status_code == 200, r.text
    return r.json()


def test_journal_create_and_list(client):
    created = _entry(client)
    assert created["entry"]["text"] == JOURNEY_TEXT
    assert created["suggestion"]["marker"] == "heros_journey"
    r = client.get("/pipeline/journal")
    assert r.status_code == 200
    assert len(r.json()["entries"]) == 1


def test_journal_rejects_empty(client):
    r = client.post("/pipeline/journal", json={"text": "   "})
    assert r.status_code == 422


def test_dismiss_suggestion(client):
    entry_id = _entry(client)["entry"]["entry_id"]
    r = client.post(f"/pipeline/journal/{entry_id}/dismiss")
    assert r.status_code == 200
    assert r.json()["entry"]["dismissed"] == 1


def test_story_flow(client):
    entry_id = _entry(client)["entry"]["entry_id"]
    story = _story(client, entry_id)
    assert story["artifact"]["title"] == "Leaving to Begin"
    assert story["content"]["key_line"] == STORY_JSON["key_line"]
    # second story for the same entry is rejected
    r = client.post("/pipeline/story", json={"journal_entry_id": entry_id})
    assert r.status_code == 422


def test_packs_plan_and_generate(client):
    entry_id = _entry(client)["entry"]["entry_id"]
    story_id = _story(client, entry_id)["artifact"]["artifact_id"]
    r = client.get("/pipeline/packs/plan", params={"story_id": story_id})
    assert r.status_code == 200
    assert r.json()["stage"] == "ask"
    assert len(r.json()["questions"]) == 3
    # answers required at ask stage
    r = client.post(
        "/pipeline/packs", json={"story_id": story_id, "modalities": ["song"]}
    )
    assert r.status_code == 422
    r = client.post(
        "/pipeline/packs",
        json={
            "story_id": story_id,
            "modalities": ["song", "image"],
            "answers": {"modality": "song", "style": "blues", "tools": "Suno"},
        },
    )
    assert r.status_code == 200, r.text
    packs = r.json()["packs"]
    assert len(packs) == 2
    assert packs[0]["artifact"]["styled_by"] is None


def test_packs_rejects_bad_modality(client):
    entry_id = _entry(client)["entry"]["entry_id"]
    story_id = _story(client, entry_id)["artifact"]["artifact_id"]
    r = client.post(
        "/pipeline/packs",
        json={"story_id": story_id, "modalities": ["hologram"]},
    )
    assert r.status_code == 422


def test_regen_pack(client):
    entry_id = _entry(client)["entry"]["entry_id"]
    story_id = _story(client, entry_id)["artifact"]["artifact_id"]
    r = client.post(
        "/pipeline/packs",
        json={
            "story_id": story_id,
            "modalities": ["song"],
            "answers": {"modality": "song", "style": "blues", "tools": "Suno"},
        },
    )
    pack_id = r.json()["packs"][0]["artifact"]["artifact_id"]
    r = client.post(f"/pipeline/packs/{pack_id}/regen")
    assert r.status_code == 200, r.text
    assert r.json()["artifact"]["variation_of"] == pack_id


def test_quote_card(client):
    entry_id = _entry(client)["entry"]["entry_id"]
    story_id = _story(client, entry_id)["artifact"]["artifact_id"]
    r = client.post(
        "/pipeline/quote-card", json={"story_id": story_id, "badge": True}
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["artifact"]["modality"] == "image"
    assert base64.b64decode(body["image_base64"])[:8] == b"\x89PNG\r\n\x1a\n"


def test_import_the_result_links_pack(client):
    """The full chain: entry → story → pack → (external render) → import
    with the pack as declared parent."""
    entry_id = _entry(client)["entry"]["entry_id"]
    story_id = _story(client, entry_id)["artifact"]["artifact_id"]
    r = client.post(
        "/pipeline/packs",
        json={
            "story_id": story_id,
            "modalities": ["image"],
            "answers": {"modality": "image", "style": "Van Gogh", "tools": "Midjourney"},
        },
    )
    pack_id = r.json()["packs"][0]["artifact"]["artifact_id"]
    # "Import the result": the rendered image, pack pre-selected as parent.
    r = client.post(
        "/provenance/ingest",
        json={
            "image_base64": _img_b64(),
            "title": "rendered image",
            "declared_parent_ids": [pack_id],
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["outcome"] in ("near", "none")
    assert body["linked_parents"][0]["parent_id"] == pack_id
    assert body["linked_parents"][0]["status"] == "linked"


def test_ingest_rejects_unknown_declared_parent(client):
    r = client.post(
        "/provenance/ingest",
        json={"image_base64": _img_b64(), "declared_parent_ids": ["nope"]},
    )
    assert r.status_code == 404
    r = client.post(
        "/pipeline/mint-standalone",
        json={"image_base64": _img_b64(), "title": "my photo"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert "How does this piece express this moment to you?" in body["anchoring_question"]
    artifact_id = body["artifact"]["artifact_id"]
    # skip
    r = client.post(f"/pipeline/mint-standalone/{artifact_id}/anchor", json={})
    assert r.json()["anchored"] is False
    # anchor via micro-reflection
    r = client.post(
        f"/pipeline/mint-standalone/{artifact_id}/anchor",
        json={"micro_reflection": "This photo is from the day I quit."},
    )
    assert r.status_code == 200, r.text
    assert r.json()["anchored"] is True
    assert r.json()["entry"]["text"] == "This photo is from the day I quit."
