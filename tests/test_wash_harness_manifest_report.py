"""Manifest + report tests for the wash harness (manifest.py, report.py).

Covers: every run carries a complete manifest (both contract versions,
fixture + harness versions, variant tagging), manifest round-trips through
JSON, and the report states plainly what is still gated (draft labels,
provisional thresholds, no live model runs).
"""

from __future__ import annotations

import json

from local_ai.eval.wash import (
    EXTRACTION_VERSION,
    FIXTURE_SET_VERSION,
    GOLD_LABEL_VERSION,
    HARNESS_VERSION,
    SEMANTIC_VERSION,
    VALIDATOR_VERSION,
)
from local_ai.eval.wash.fixtures import default_fixture_path, load_fixture_set
from local_ai.eval.wash.manifest import new_manifest, read_manifest, write_manifest
from local_ai.eval.wash.measures import aggregate_scores, score_fixture
from local_ai.eval.wash.report import build_report, render_markdown, write_markdown, write_report
from local_ai.eval.wash.validator import validate_segment_output


def _perfect_raw(fx) -> str:
    rows = [
        {
            "text": g.text,
            "summary": "s",
            "evidence_quote": g.quote,
            "confidence": "high",
            "stance": g.stance,
        }
        for g in fx.expected
    ]
    return json.dumps({"rows": rows})


def _perfect_score():
    fixture_set = load_fixture_set(default_fixture_path())
    scores = []
    validations = {}
    segments = {}
    for fx in fixture_set.fixtures:
        validation = validate_segment_output(_perfect_raw(fx), fx.segment, fx)
        validations[fx.id] = validation
        segments[fx.id] = fx.segment
        scores.append(score_fixture(fx, validation))
    agg = aggregate_scores(
        scores,
        variant="model-on",
        candidate=None,
        emitted_validations=validations,
        segments=segments,
    )
    return agg


def test_manifest_carries_both_contract_versions():
    manifest = new_manifest(variant="model-on", candidate="qwen3:1.7b")
    assert manifest.semantic_contract_version == SEMANTIC_VERSION == "1.0"
    assert manifest.extraction_version == EXTRACTION_VERSION == "1.0"
    assert manifest.harness_version == HARNESS_VERSION
    assert manifest.validator_version == VALIDATOR_VERSION
    assert manifest.fixture_set_version == FIXTURE_SET_VERSION
    assert manifest.gold_label_version == GOLD_LABEL_VERSION
    assert manifest.variant == "model-on"
    assert manifest.candidate == "qwen3:1.7b"
    assert manifest.run_id.startswith("wash-")
    assert manifest.created_at


def test_manifest_variant_tagging():
    skip = new_manifest(variant="skip-enabled")
    assert skip.variant == "skip-enabled"
    assert skip.to_dict()["variant"] == "skip-enabled"


def test_manifest_round_trip(tmp_path):
    manifest = new_manifest(variant="skip-enabled", candidate="qwen3:0.6b")
    path = write_manifest(tmp_path / "manifest.json", manifest)
    back = read_manifest(path)
    assert back["variant"] == "skip-enabled"
    assert back["candidate"] == "qwen3:0.6b"
    assert back["run_id"] == manifest.run_id
    assert back["semantic_contract_version"] == "1.0"


def test_report_states_what_is_still_gated():
    score = _perfect_score()
    report = build_report(score)
    assert report["gold_label_status"].startswith("DRAFT")
    assert report["threshold_status"].startswith("PROVISIONAL")
    assert report["fixture_set_version"] == "1.0-draft"
    assert report["measures"]["recall"] == 1.0
    assert report["critical_errors"]["total"] == 0
    assert report["critical_errors"]["emitted_leakage"] == 0


def test_report_markdown_names_the_gates():
    score = _perfect_score()
    report = build_report(score)
    md = render_markdown(report)
    assert "Gold labels are DRAFT" in md
    assert "Thresholds are PROVISIONAL" in md
    assert "No benchmark run against a live model has been authorized" in md
    assert "Evidence recall" in md
    assert "Critical errors" in md


def test_report_files_round_trip(tmp_path):
    score = _perfect_score()
    report = build_report(score)
    json_path = write_report(tmp_path / "report.json", report)
    md_path = write_markdown(tmp_path / "report.md", report)
    assert json.loads(json_path.read_text())["measures"]["recall"] == 1.0
    assert "Wash benchmark report" in md_path.read_text()
