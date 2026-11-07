"""Runner tests for the wash harness (runner.py).

Covers: scoring a run from raw model text, the 3-run reproducibility path,
the CLI end-to-end (manifest + report + markdown on disk), and crash
containment (one bad entry never kills the run). All inputs are synthetic —
no model is called.
"""

from __future__ import annotations

import json

import pytest

from local_ai.eval.wash.fixtures import default_fixture_path, load_fixture_set
from local_ai.eval.wash.runner import main, score_candidate


@pytest.fixture(scope="module")
def fixture_set():
    return load_fixture_set(default_fixture_path())


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


def _perfect_run(fixture_set):
    return [
        {"fixture_id": fx.id, "raw_text": _perfect_raw(fx), "model_call_count": 1}
        for fx in fixture_set.fixtures
    ]


def test_score_candidate_single_perfect_run(fixture_set):
    report, manifest, run_results = score_candidate(
        fixture_set, [_perfect_run(fixture_set)], variant="model-on"
    )
    assert report["measures"]["recall"] == 1.0
    assert report["critical_errors"]["total"] == 0
    assert report["runs_scored"] == 1
    # Without 3 runs, reproducibility is unmeasured and the verdict is undecided.
    assert report["passed"] is None
    assert manifest.variant == "model-on"
    assert manifest.semantic_contract_version == "1.0"


def test_score_candidate_three_identical_runs_passes(fixture_set):
    perfect = _perfect_run(fixture_set)
    report, _, _ = score_candidate(
        fixture_set, [perfect, perfect, perfect], variant="model-on"
    )
    assert report["measures"]["recall"] == 1.0
    assert report["measures"]["reproducibility_structural"] == 1.0
    assert report["measures"]["reproducibility_semantic"] == 1.0
    assert report["passed"] is True


def test_score_candidate_unknown_variant_rejected(fixture_set):
    with pytest.raises(ValueError, match="unknown variant"):
        score_candidate(fixture_set, [_perfect_run(fixture_set)], variant="turbo")


def test_score_candidate_too_many_runs_rejected(fixture_set):
    perfect = _perfect_run(fixture_set)
    with pytest.raises(ValueError, match="1-3 runs"):
        score_candidate(fixture_set, [perfect] * 4)


def test_bad_entry_is_a_crash_not_a_killed_run(fixture_set):
    entries = _perfect_run(fixture_set)
    entries[0] = {"fixture_id": "neg-01", "raw_text": "{}", "failure_code": "bogus"}
    report, _, run_results = score_candidate(
        fixture_set, [entries], variant="model-on"
    )
    assert len(run_results[0].crashes) == 1
    assert run_results[0].crashes[0]["fixture_id"] == "neg-01"
    assert "bogus" in run_results[0].crashes[0]["error"]
    assert report["crashes"]
    # The run continued past the crash: 61 fixtures scored, 1 crash recorded.
    assert report["fixtures_scored"] == 61


def test_cli_writes_manifest_report_markdown(tmp_path, fixture_set):
    inputs = {
        "variant": "model-on",
        "candidate": "self-proof-perfect",
        "runs": [_perfect_run(fixture_set)],
    }
    inputs_path = tmp_path / "inputs.json"
    inputs_path.write_text(json.dumps(inputs), encoding="utf-8")
    out = tmp_path / "out"
    rc = main(
        [
            "--fixtures", str(default_fixture_path()),
            "--inputs", str(inputs_path),
            "--out", str(out),
        ]
    )
    assert rc == 0
    manifest = json.loads((out / "manifest.json").read_text())
    report = json.loads((out / "report.json").read_text())
    assert manifest["candidate"] == "self-proof-perfect"
    assert report["measures"]["recall"] == 1.0
    assert "Wash benchmark report" in (out / "report.md").read_text()


def test_cli_skip_variant_report_marks_variant(tmp_path, fixture_set):
    inputs = {
        "variant": "skip-enabled",
        "runs": [_perfect_run(fixture_set)],
    }
    inputs_path = tmp_path / "inputs.json"
    inputs_path.write_text(json.dumps(inputs), encoding="utf-8")
    out = tmp_path / "out"
    rc = main(
        [
            "--fixtures", str(default_fixture_path()),
            "--inputs", str(inputs_path),
            "--out", str(out),
        ]
    )
    assert rc == 0
    report = json.loads((out / "report.json").read_text())
    assert report["variant"] == "skip-enabled"
    assert report["variant_check"]["passed"] is True
