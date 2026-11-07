"""Loader tests for the wash harness (fixtures.py).

Covers: the shipped set loads clean (62 fixtures, 10 per category + 2 empty),
version agreement is enforced, and every gold-integrity violation fails
loudly at load time instead of silently scoring.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from local_ai.eval.wash.fixtures import FixtureError, default_fixture_path, load_fixture_set

SHIPPED = default_fixture_path()


@pytest.fixture(scope="module")
def shipped_data() -> dict:
    return json.loads(SHIPPED.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def shipped_set():
    return load_fixture_set(SHIPPED)


def _write_mutated(tmp_path: Path, data: dict, name: str = "mutated.json") -> Path:
    path = tmp_path / name
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_shipped_set_loads_with_expected_shape(shipped_set):
    assert len(shipped_set.fixtures) == 62
    assert shipped_set.fixture_set_version == "1.0-draft"
    assert shipped_set.gold_label_version == "1.0-draft"
    assert shipped_set.semantic_contract_version == "1.0"
    assert shipped_set.extraction_version == "1.0"
    counts = {}
    for fx in shipped_set.fixtures:
        counts[fx.category] = counts.get(fx.category, 0) + 1
    assert counts == {
        "negation": 10,
        "uncertainty": 10,
        "commitments": 10,
        "rejections": 10,
        "attribution": 10,
        "evidence_preservation": 10,
        "empty": 2,
    }


def test_segment_ids_are_stable_and_sequential(shipped_set):
    assert [fx.segment_id for fx in shipped_set.fixtures][:3] == [
        "seg-0000",
        "seg-0001",
        "seg-0002",
    ]
    assert shipped_set.fixtures[-1].segment_id == "seg-0061"
    assert len({fx.segment_id for fx in shipped_set.fixtures}) == 62


def test_canonical_reversal_fixture_is_present(shipped_set):
    fx = shipped_set.by_id("rej-01")
    assert fx.segment.startswith("We agreed to ship Friday")
    assert len(fx.expected) == 2
    assert fx.expected[0].stance == "rejected"
    assert fx.expected[1].stance == "proposed"
    assert any(
        fb.forbidden_class == "commitment_inflation" for fb in fx.forbidden
    )


def test_gold_counts(shipped_set):
    assert sum(len(fx.expected) for fx in shipped_set.fixtures) == 67
    assert sum(len(fx.forbidden) for fx in shipped_set.fixtures) == 62


def test_version_disagreement_refuses_to_run(tmp_path, shipped_data):
    data = copy.deepcopy(shipped_data)
    data["gold_label_version"] = "1.0-draft-2"
    with pytest.raises(FixtureError, match="disagree"):
        load_fixture_set(_write_mutated(tmp_path, data))


def test_wrong_pinned_versions_refuse_to_run(tmp_path, shipped_data):
    data = copy.deepcopy(shipped_data)
    data["fixture_set_version"] = "2.0-draft"
    data["gold_label_version"] = "2.0-draft"
    with pytest.raises(FixtureError, match="pinned"):
        load_fixture_set(_write_mutated(tmp_path, data))
    data = copy.deepcopy(shipped_data)
    data["semantic_contract_version"] = "2.0"
    with pytest.raises(FixtureError, match="semantic contract"):
        load_fixture_set(_write_mutated(tmp_path, data))


def test_duplicate_fixture_id_refuses(tmp_path, shipped_data):
    data = copy.deepcopy(shipped_data)
    data["fixtures"].append(copy.deepcopy(data["fixtures"][0]))
    with pytest.raises(FixtureError, match="duplicate fixture id"):
        load_fixture_set(_write_mutated(tmp_path, data))


def test_unknown_category_refuses(tmp_path, shipped_data):
    data = copy.deepcopy(shipped_data)
    data["fixtures"][0]["category"] = "vibes"
    with pytest.raises(FixtureError, match="unknown category"):
        load_fixture_set(_write_mutated(tmp_path, data))


def test_expected_quote_must_be_an_exact_substring(tmp_path, shipped_data):
    data = copy.deepcopy(shipped_data)
    data["fixtures"][0]["expected"][0]["quote"] = "a paraphrase, not the segment words"
    with pytest.raises(FixtureError, match="not an exact substring"):
        load_fixture_set(_write_mutated(tmp_path, data))


def test_supporting_quote_must_be_an_exact_substring(tmp_path, shipped_data):
    data = copy.deepcopy(shipped_data)
    data["fixtures"][0]["expected"][0]["supporting_quotes"] = ["nowhere in the segment"]
    with pytest.raises(FixtureError, match="not an exact substring"):
        load_fixture_set(_write_mutated(tmp_path, data))


def test_speaker_flag_must_match_segment_text(tmp_path, shipped_data):
    data = copy.deepcopy(shipped_data)
    data["fixtures"][0]["has_explicit_speakers"] = True  # neg-01 has no speaker lines
    with pytest.raises(FixtureError, match="has_explicit_speakers"):
        load_fixture_set(_write_mutated(tmp_path, data))
    data = copy.deepcopy(shipped_data)
    att = next(f for f in data["fixtures"] if f["id"] == "att-01")
    att["has_explicit_speakers"] = False
    with pytest.raises(FixtureError, match="has_explicit_speakers"):
        load_fixture_set(_write_mutated(tmp_path, data))


def test_empty_category_must_have_no_expected_rows(tmp_path, shipped_data):
    data = copy.deepcopy(shipped_data)
    emp = next(f for f in data["fixtures"] if f["id"] == "emp-01")
    # The added row's quote must itself be a valid substring, so that the
    # empty-category rule (not the gold-integrity rule) is what fires.
    emp["expected"] = [
        {
            "text": "We chatted about the weekend and the weather",
            "stance": "considered",
            "speaker": None,
            "quote": "We chatted about the weekend",
            "equivalents": [],
            "supporting_quotes": ["We chatted about the weekend"],
        }
    ]
    with pytest.raises(FixtureError, match="empty-category"):
        load_fixture_set(_write_mutated(tmp_path, data))


def test_unknown_stance_refuses(tmp_path, shipped_data):
    data = copy.deepcopy(shipped_data)
    data["fixtures"][0]["expected"][0]["stance"] = "definitely"
    with pytest.raises(FixtureError, match="stance vocabulary"):
        load_fixture_set(_write_mutated(tmp_path, data))


def test_unknown_forbidden_class_refuses(tmp_path, shipped_data):
    data = copy.deepcopy(shipped_data)
    data["fixtures"][0]["forbidden"][0]["class"] = "vibes_error"
    with pytest.raises(FixtureError, match="forbidden-output class"):
        load_fixture_set(_write_mutated(tmp_path, data))


def test_missing_file_refuses():
    with pytest.raises(FixtureError, match="not found"):
        load_fixture_set("/nonexistent/wash-fixtures.json")


def test_invalid_json_refuses(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(FixtureError, match="not valid JSON"):
        load_fixture_set(path)
