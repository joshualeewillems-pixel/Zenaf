"""tasteCompass bootstrap — graduated ask → suggest → propose (no network)."""

from __future__ import annotations

import pytest

from local_ai.pipeline import taste
from local_ai.pipeline.store import PipelineStore

USER = "user-taste"


@pytest.fixture()
def pstore(tmp_path):
    s = PipelineStore(tmp_path / "pipe.db")
    yield s
    s.close()


def test_stage_ask_with_no_data(pstore):
    assert taste.get_stage(pstore, USER) == "ask"


def test_stage_suggest_after_first_answers(pstore):
    taste.record_answers(
        pstore, USER,
        {"modality": "song", "style": "blues", "tools": "Suno"},
    )
    assert taste.get_stage(pstore, USER) == "suggest"


def test_stage_propose_after_five_observations(pstore):
    for i in range(5):
        pstore.add_taste_observation(USER, f"q{i}", f"a{i}")
    assert taste.get_stage(pstore, USER) == "propose"


def test_record_answers_updates_profile(pstore):
    profile = taste.record_answers(
        pstore, USER,
        {"modality": "comic strip", "style": "manga, Quentin Tarantino", "tools": "Midjourney"},
    )
    assert profile["shaped"] is True
    assert "manga" in profile["style_anchors"]
    assert "Midjourney" in profile["tools"]
    assert "comic strip" in profile["modalities"]
    assert pstore.count_observations(USER) == 3


def test_personalized_suggestions_use_own_answers(pstore):
    taste.record_answers(
        pstore, USER,
        {"modality": "song", "style": "blues", "tools": "Suno"},
    )
    sugg = taste.personalized_suggestions(pstore, USER)
    assert sugg["style"][0] == "blues"
    assert sugg["tools"][0] == "Suno"
    # generic fallbacks still present
    assert "rock" in sugg["style"]


def test_build_proposal_is_declarative(pstore):
    taste.record_answers(
        pstore, USER,
        {"modality": "song", "style": "old Muddy Waters vibe", "tools": "Suno"},
    )
    proposal = taste.build_proposal(
        pstore, USER, [{"marker": "emotional_charge", "modality": "song"}]
    )
    assert "Suno" in proposal["copy"]
    assert "Muddy Waters" in proposal["copy"]
    assert "Want me to write the pack?" in proposal["copy"]


def test_record_confirmation_with_tweak_is_signal(pstore):
    taste.record_answers(
        pstore, USER, {"modality": "song", "style": "blues", "tools": "Suno"}
    )
    before = pstore.count_observations(USER)
    taste.record_confirmation(pstore, USER, tweak="make it more rock")
    assert pstore.count_observations(USER) == before + 1
    profile = pstore.get_taste_profile(USER)
    assert any("rock" in s for s in profile["style_anchors"])


def test_style_anchors_for_prompt(pstore):
    assert taste.style_anchors_for_prompt(pstore, USER) == ""
    taste.record_answers(
        pstore, USER, {"modality": "song", "style": "blues", "tools": "Suno"}
    )
    anchors = taste.style_anchors_for_prompt(pstore, USER)
    assert "blues" in anchors and "Suno" in anchors
