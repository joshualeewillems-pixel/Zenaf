"""Pipeline service: journal → story → packs → quote cards → standalone mint.

The LLM is mocked (no network); the rule-based strand analysis runs for real.
"""

from __future__ import annotations

import base64
import io
import json

import pytest
from PIL import Image, ImageDraw

from local_ai.pipeline import service as pipe
from local_ai.pipeline.store import PipelineStore
from local_ai.provenance.store import ProvenanceStore

ALICE = "user-alice"
BOB = "user-bob"

JOURNEY_TEXT = (
    "I left my job back in March and started something of my own. The first "
    "months were hard — I failed twice, felt lost and overwhelmed by doubt. "
    "But I kept going, and I finally learned what I actually want from work. "
    "Now I feel grateful for the struggle; it made me stronger and wiser."
)

STORY_JSON = {
    "title": "Leaving to Begin",
    "narrative": "You left the safe job in March. The first months were hard and you felt lost. But you kept going, and you learned what you actually want. Now you are grateful for the struggle.",
    "key_line": "The struggle taught me what I actually want.",
}

PACK_JSON = {
    "pack_title": "Leaving to Begin — song",
    "prompts": ["Verse one... chorus...", "blues, slow tempo, Muddy Waters vibe"],
    "style_line": "old blues",
    "negative_prompt": "no pop clichés",
}


def _fake_generate(api_key, prompt, **kwargs):
    if "prompt pack" in prompt.lower():
        return json.dumps(PACK_JSON)
    return json.dumps(STORY_JSON)


@pytest.fixture()
def stores(tmp_path, monkeypatch):
    import local_ai.providers.meta as meta

    monkeypatch.setattr(meta, "generate", _fake_generate)
    pstore = PipelineStore(tmp_path / "pipe.db")
    prov = ProvenanceStore(tmp_path / "prov.db")
    yield pstore, prov
    pstore.close()
    prov.close()


def _img_b64() -> str:
    img = Image.new("RGB", (64, 64), "white")
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, 31, 63], fill="black")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()


# -- journal --------------------------------------------------------------------


def test_create_entry_registers_private_artifact_and_suggests(stores):
    pstore, prov = stores
    result = pipe.create_journal_entry(pstore, prov, ALICE, JOURNEY_TEXT)
    entry = result["entry"]
    assert entry["text"] == JOURNEY_TEXT
    assert entry["artifact_id"]
    artifact = prov.get_artifact(entry["artifact_id"])
    assert artifact["visibility"] == "private"  # personal writing: default-deny
    assert artifact["modality"] == "text"
    # marker fired
    assert result["suggestion"] is not None
    assert result["suggestion"]["marker"] == "heros_journey"
    entry2 = pstore.get_entry(entry["entry_id"])
    assert entry2["suggested_marker"] == "heros_journey"


def test_create_entry_empty_rejected(stores):
    pstore, prov = stores
    with pytest.raises(ValueError):
        pipe.create_journal_entry(pstore, prov, ALICE, "   ")


def test_dismiss_records_verdict_and_tunes(stores):
    pstore, prov = stores
    result = pipe.create_journal_entry(pstore, prov, ALICE, JOURNEY_TEXT)
    entry_id = result["entry"]["entry_id"]
    entry = pipe.dismiss_suggestion(pstore, ALICE, entry_id)
    assert entry["dismissed"] == 1
    stats = pstore.record_suggestion("heros_journey", accepted=False)
    assert stats["suggestions"] >= 1


def test_dismiss_other_users_entry_forbidden(stores):
    pstore, prov = stores
    result = pipe.create_journal_entry(pstore, prov, ALICE, JOURNEY_TEXT)
    with pytest.raises(PermissionError):
        pipe.dismiss_suggestion(pstore, BOB, result["entry"]["entry_id"])


# -- stories ----------------------------------------------------------------------


def test_make_story_parents_to_entry(stores):
    pstore, prov = stores
    created = pipe.create_journal_entry(pstore, prov, ALICE, JOURNEY_TEXT)
    entry_id = created["entry"]["entry_id"]
    result = pipe.make_story(pstore, prov, ALICE, entry_id)
    artifact = result["artifact"]
    assert artifact["title"] == "Leaving to Begin"
    assert result["content"]["key_line"] == STORY_JSON["key_line"]
    parents = prov.parents_of(artifact["artifact_id"])
    assert len(parents) == 1
    assert parents[0]["parent_id"] == created["entry"]["artifact_id"]
    assert pstore.get_entry(entry_id)["storified"] == 1


def test_make_story_twice_rejected(stores):
    pstore, prov = stores
    created = pipe.create_journal_entry(pstore, prov, ALICE, JOURNEY_TEXT)
    entry_id = created["entry"]["entry_id"]
    pipe.make_story(pstore, prov, ALICE, entry_id)
    with pytest.raises(ValueError):
        pipe.make_story(pstore, prov, ALICE, entry_id)


def test_make_story_other_users_entry_forbidden(stores):
    pstore, prov = stores
    created = pipe.create_journal_entry(pstore, prov, ALICE, JOURNEY_TEXT)
    with pytest.raises(PermissionError):
        pipe.make_story(pstore, prov, BOB, created["entry"]["entry_id"])


# -- packs --------------------------------------------------------------------------


def _story_id(stores):
    pstore, prov = stores
    created = pipe.create_journal_entry(pstore, prov, ALICE, JOURNEY_TEXT)
    story = pipe.make_story(pstore, prov, ALICE, created["entry"]["entry_id"])
    return story["artifact"]["artifact_id"]


def test_plan_packs_ask_stage(stores):
    pstore, prov = stores
    plan = pipe.plan_packs(pstore, prov, ALICE, _story_id(stores))
    assert plan["stage"] == "ask"
    assert len(plan["questions"]) == 3
    assert plan["questions"][0]["suggestions"]  # generic fallbacks


def test_generate_packs_requires_answers_at_ask_stage(stores):
    pstore, prov = stores
    story_id = _story_id(stores)
    with pytest.raises(ValueError):
        pipe.generate_packs(pstore, prov, ALICE, story_id, ["song"])


def test_generate_packs_registers_pack_artifacts(stores):
    pstore, prov = stores
    story_id = _story_id(stores)
    result = pipe.generate_packs(
        pstore, prov, ALICE, story_id, ["song", "image"],
        answers={"modality": "song", "style": "blues", "tools": "Suno"},
    )
    assert len(result["packs"]) == 2
    for item in result["packs"]:
        artifact = item["artifact"]
        assert artifact["modality"] == "text"
        assert artifact["styled_by"] is None  # step 10 is later work
        parents = prov.parents_of(artifact["artifact_id"])
        assert [p["parent_id"] for p in parents] == [story_id]
    # answers fed the taste compass
    assert pstore.count_observations(ALICE) == 3


def test_regen_pack_variation_of(stores):
    pstore, prov = stores
    story_id = _story_id(stores)
    first = pipe.generate_packs(
        pstore, prov, ALICE, story_id, ["song"],
        answers={"modality": "song", "style": "blues", "tools": "Suno"},
    )["packs"][0]
    regen = pipe.regen_pack(pstore, prov, ALICE, first["artifact"]["artifact_id"])
    assert regen["artifact"]["variation_of"] == first["artifact"]["artifact_id"]
    parents = prov.parents_of(regen["artifact"]["artifact_id"])
    assert [p["parent_id"] for p in parents] == [story_id]  # same story parent


def test_propose_stage_requires_confirm(stores):
    pstore, prov = stores
    for i in range(5):
        pstore.add_taste_observation(ALICE, f"q{i}", f"a{i}")
    story_id = _story_id(stores)
    plan = pipe.plan_packs(pstore, prov, ALICE, story_id)
    assert plan["stage"] == "propose"
    assert "Want me to write the pack?" in plan["proposal"]["copy"]
    with pytest.raises(ValueError):
        pipe.generate_packs(pstore, prov, ALICE, story_id, ["song"])
    result = pipe.generate_packs(
        pstore, prov, ALICE, story_id, ["song"], confirmed=True
    )
    assert len(result["packs"]) == 1


# -- quote cards ----------------------------------------------------------------------


def test_make_quote_card_auto_mints(stores):
    pstore, prov = stores
    story_id = _story_id(stores)
    result = pipe.make_quote_card(pstore, prov, ALICE, story_id, badge=True)
    artifact = result["artifact"]
    assert artifact["modality"] == "image"
    parents = prov.parents_of(artifact["artifact_id"])
    assert [p["parent_id"] for p in parents] == [story_id]
    raw = base64.b64decode(result["image_base64"])
    assert raw[:8] == b"\x89PNG\r\n\x1a\n"


def test_make_quote_card_no_badge(stores):
    pstore, prov = stores
    story_id = _story_id(stores)
    result = pipe.make_quote_card(pstore, prov, ALICE, story_id, badge=False)
    assert result["badge"] is False
    raw = base64.b64decode(result["image_base64"])
    assert raw[:8] == b"\x89PNG\r\n\x1a\n"


# -- standalone mint --------------------------------------------------------------------


def test_standalone_mint_asks_anchoring_question(stores):
    _pstore, prov = stores
    result = pipe.standalone_mint(prov, ALICE, _img_b64(), title="my photo")
    assert result["outcome"] in ("near", "none")
    assert result["anchoring_question"] == pipe.ANCHORING_QUESTION
    # no journal parent
    assert prov.parents_of(result["artifact"]["artifact_id"]) == []


def test_anchor_to_existing_entry(stores):
    pstore, prov = stores
    minted = pipe.standalone_mint(prov, ALICE, _img_b64(), title="my photo")
    created = pipe.create_journal_entry(pstore, prov, ALICE, JOURNEY_TEXT)
    result = pipe.anchor_standalone(
        pstore, prov, ALICE, minted["artifact"]["artifact_id"],
        journal_entry_id=created["entry"]["entry_id"],
    )
    assert result["anchored"] is True
    parents = prov.parents_of(minted["artifact"]["artifact_id"])
    assert [p["parent_id"] for p in parents] == [created["entry"]["artifact_id"]]


def test_anchor_with_micro_reflection_creates_entry(stores):
    pstore, prov = stores
    minted = pipe.standalone_mint(prov, ALICE, _img_b64(), title="my photo")
    result = pipe.anchor_standalone(
        pstore, prov, ALICE, minted["artifact"]["artifact_id"],
        micro_reflection="This photo reminds me of the day I finally quit.",
    )
    assert result["anchored"] is True
    assert result["entry"]["text"].startswith("This photo reminds me")
    parents = prov.parents_of(minted["artifact"]["artifact_id"])
    assert [p["parent_id"] for p in parents] == [result["entry"]["artifact_id"]]


def test_anchor_skipped(stores):
    pstore, prov = stores
    minted = pipe.standalone_mint(prov, ALICE, _img_b64(), title="my photo")
    result = pipe.anchor_standalone(pstore, prov, ALICE, minted["artifact"]["artifact_id"])
    assert result["anchored"] is False
