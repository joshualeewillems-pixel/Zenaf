"""Orchestration + thin CLI for the wash benchmark harness (design §6, §8).

The runner takes RAW MODEL TEXT as input (one entry per fixture per run) and
produces validated rows, measures, a manifest, and a report. It never calls
a model, never loads a runtime, and never performs a benchmark run itself —
runs are separately authorized (§6.2) and their raw outputs are supplied as
an input file.

Run-input format (JSON)::

    {
      "variant": "model-on",            // or "skip-enabled" (§4.3, §8)
      "candidate": "qwen3:1.7b",        // model id, or null for self-proof
      "runtime": {...},                  // manifest runtime block (§2.2)
      "runs": [                          // 1-3 runs; 3 required for measure R
        [ {"fixture_id": "neg-01", "raw_text": "{...}", "failure_code": null,
           "model_call_count": 1, "timing_ms": null}, ... ],
        ...
      ]
    }

A run entry with ``failure_code`` set (one of §2.1.4) records a failed model
call — it is never scored as an empty. A run entry with ``raw_text`` of
``{"rows": []}`` on a segment with no valid propositions is an honest empty.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from local_ai.eval.wash import FAILURE_CODES, VARIANTS, VARIANT_MODEL_ON
from local_ai.eval.wash.measures import DEFAULT_THRESHOLDS as _DEFAULTS
from local_ai.eval.wash.fixtures import FixtureSet, default_fixture_path, load_fixture_set
from local_ai.eval.wash.manifest import Manifest, new_manifest, write_manifest
from local_ai.eval.wash.measures import (
    BenchmarkScore,
    aggregate_scores,
    compare_runs,
    register_fixture_context,
    score_fixture,
    variant_check,
)
from local_ai.eval.wash.report import build_report, write_markdown, write_report
from local_ai.eval.wash.validator import ValidationResult, validate_segment_output

DEFAULT_THRESHOLDS = dict(_DEFAULTS)


@dataclass
class RunResult:
    """One scored run: score + per-fixture validations + crash record."""

    score: BenchmarkScore
    validations: dict[str, ValidationResult] = field(default_factory=dict)
    fixture_scores: dict[str, Any] = field(default_factory=dict)
    crashes: list[dict[str, Any]] = field(default_factory=list)


def _score_one_run(
    fixture_set: FixtureSet,
    entries: list[dict[str, Any]],
    *,
    variant: str,
    candidate: str | None,
    thresholds: dict[str, float],
) -> RunResult:
    """Score a single run (one list of per-fixture raw outputs)."""
    validations: dict[str, ValidationResult] = {}
    fixture_scores: dict[str, Any] = {}
    crashes: list[dict[str, Any]] = []
    segments = {fx.id: fx.segment for fx in fixture_set.fixtures}
    by_id = {e.get("fixture_id"): e for e in entries if isinstance(e, dict)}

    for fx in fixture_set.fixtures:
        entry = by_id.get(fx.id)
        if entry is None:
            continue  # fixture not scored in this run; recorded by absence
        try:
            failure_code = entry.get("failure_code")
            raw_text = entry.get("raw_text") or ""
            if failure_code is not None and failure_code not in FAILURE_CODES:
                raise ValueError(f"unknown failure code: {failure_code!r}")
            validation = validate_segment_output(
                raw_text, fx.segment, fx, failure_code=failure_code
            )
            validations[fx.id] = validation
            fixture_scores[fx.id] = score_fixture(
                fx,
                validation,
                model_calls=int(entry.get("model_call_count") or 0),
            )
        except Exception as exc:  # noqa: BLE001 — a crash must never kill the run
            crashes.append(
                {"fixture_id": fx.id, "error": f"{type(exc).__name__}: {exc}"}
            )

    score = aggregate_scores(
        list(fixture_scores.values()),
        variant=variant,
        candidate=candidate,
        thresholds=thresholds,
        emitted_validations=validations,
        segments=segments,
    )
    return RunResult(
        score=score,
        validations=validations,
        fixture_scores=fixture_scores,
        crashes=crashes,
    )


def score_candidate(
    fixture_set: FixtureSet,
    runs_inputs: list[list[dict[str, Any]]],
    *,
    variant: str = VARIANT_MODEL_ON,
    candidate: str | None = None,
    runtime: dict[str, Any] | None = None,
    thresholds: dict[str, float] | None = None,
    notes: str = "",
) -> tuple[dict[str, Any], Manifest, list[RunResult]]:
    """Score 1-3 runs of the same fixtures and build the manifest + report.

    Measure R (reproducibility) is computed only when exactly 3 runs are
    supplied; with fewer runs the pass rule stays undecided on R.
    """
    if variant not in VARIANTS:
        raise ValueError(f"unknown variant: {variant!r} (known: {VARIANTS})")
    if not 1 <= len(runs_inputs) <= 3:
        raise ValueError(f"expected 1-3 runs, got {len(runs_inputs)}")
    th = dict(DEFAULT_THRESHOLDS if thresholds is None else thresholds)
    register_fixture_context(fixture_set)

    run_results = [
        _score_one_run(
            fixture_set, entries, variant=variant, candidate=candidate, thresholds=th
        )
        for entries in runs_inputs
    ]

    # The report describes the FIRST run; reproducibility compares all runs.
    primary = run_results[0]
    reproducibility = None
    if len(run_results) == 3:
        reproducibility = compare_runs(
            [r.validations for r in run_results], fixture_set
        )
        primary.score.reproducibility_structural = reproducibility["structural"]
        primary.score.reproducibility_semantic = reproducibility["semantic"]
        primary.score.reproducibility_exact_identity = reproducibility["exact_identity"]
    all_crashes = [c for r in run_results for c in r.crashes]

    manifest = new_manifest(
        variant=variant,
        candidate=candidate,
        runtime=runtime,
        thresholds={k: v for k, v in th.items()},
        notes=notes,
    )
    report = build_report(
        primary.score,
        manifest=manifest.to_dict(),
        reproducibility=reproducibility,
        variant_check=variant_check(primary.score),
    )
    report["crashes"] = all_crashes
    report["runs_scored"] = len(run_results)
    if all_crashes:
        report["measures"]["zero_crashes"] = False
    return report, manifest, run_results


def write_scores(path: str | Path, result: RunResult) -> Path:
    """Serialize one run's per-fixture scores (amendment B4/P2).

    The per-row scored records (``row_scores``) ride along: each carries
    its matched gold row's identity and preservation-only provenance, so
    the reported/performed distinction is verifiable from the run outputs
    themselves, not only from the rendered report.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        fid: asdict(fs) for fid, fs in sorted(result.fixture_scores.items())
    }
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return path


def _load_inputs(path: str | Path) -> dict[str, Any]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("run-input file root must be an object")
    runs = data.get("runs")
    if not isinstance(runs, list) or not runs or len(runs) > 3:
        raise ValueError("run-input file must carry 'runs': a list of 1-3 run lists")
    return data


def main(argv: list[str] | None = None) -> int:
    """CLI: score a run-input file and write manifest + report + markdown."""
    parser = argparse.ArgumentParser(
        prog="wash-harness",
        description="Score raw model outputs against the wash fixture set (deterministic; no model calls).",
    )
    parser.add_argument("--fixtures", default=str(default_fixture_path()))
    parser.add_argument("--inputs", required=True, help="run-input JSON file (see runner docstring)")
    parser.add_argument("--variant", default=VARIANT_MODEL_ON, choices=list(VARIANTS))
    parser.add_argument("--candidate", default=None)
    parser.add_argument("--out", required=True, help="output directory for manifest.json, report.json, report.md, scores.json")
    parser.add_argument("--notes", default="")
    args = parser.parse_args(argv)

    fixture_set = load_fixture_set(args.fixtures)
    inputs = _load_inputs(args.inputs)
    variant = inputs.get("variant", args.variant)
    candidate = inputs.get("candidate", args.candidate)
    runtime = inputs.get("runtime")
    report, manifest, run_results = score_candidate(
        fixture_set,
        inputs["runs"],
        variant=variant,
        candidate=candidate,
        runtime=runtime,
        notes=args.notes or str(inputs.get("notes", "")),
    )
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    write_manifest(out / "manifest.json", manifest)
    write_report(out / "report.json", report)
    write_markdown(out / "report.md", report)
    write_scores(out / "scores.json", run_results[0])
    status = report["passed"]
    print(f"fixtures scored: {report['fixtures_scored']}  runs: {report['runs_scored']}  "
          f"variant: {report['variant']}  candidate: {report['candidate']}")
    print(f"recall: {report['measures']['recall']}  "
          f"critical errors: {report['critical_errors']['total']}  "
          f"passed: {status}")
    if report["crashes"]:
        print(f"WARNING: {len(report['crashes'])} harness crash(es) recorded (measure 6: zero crashes required)")
    return 0 if status is not False else 1


if __name__ == "__main__":
    sys.exit(main())
