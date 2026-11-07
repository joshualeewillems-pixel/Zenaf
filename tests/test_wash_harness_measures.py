"""Measure tests for the wash harness (measures.py).

Covers: recall / false-positive / stance / negation scoring, the forbidden
-output critical-error gate, the gate-rejection rate, reproducibility
(structural vs. semantic vs. exact-identity diagnostic), the pass rule, and
the skip-variant fail rule. All inputs are synthetic — no model is called.
"""

from __future__ import annotations

import json

import pytest

from local_ai.eval.wash.fixtures import default_fixture_path, load_fixture_set
from local_ai.eval.wash.measures import (
    aggregate_scores,
    compare_runs,
    finalize_pass,
    score_fixture,
    variant_check,
)
from local_ai.eval.wash.validator import validate_segment_output


@pytest.fixture(scope="module")
def fixture_set():
    return load_fixture_set(default_fixture_path())


def _rows_json(rows) -> str:
    return json.dumps({"rows": rows})


def _row(text, quote, stance="committed", confidence="high"):
    return {
        "text": text,
        "summary": "A test row.",
        "evidence_quote": quote,
        "confidence": confidence,
        "stance": stance,
    }


def _perfect_raw(fx) -> str:
    rows = [
        _row(g.text, g.quote, stance=g.stance) for g in fx.expected
    ]
    return _rows_json(rows)


def _validate(fx, raw, **kwargs):
    return validate_segment_output(raw, fx.segment, fx, **kwargs)


# --- per-fixture scoring ----------------------------------------------------


def test_perfect_fixture_scores_full_marks(fixture_set):
    fx = fixture_set.by_id("com-01")
    score = score_fixture(fx, _validate(fx, _perfect_raw(fx)))
    assert score.recall == 1.0
    assert score.stance_correct == 1 and score.stance_total == 1
    assert score.forbidden_hits == []
    assert score.unsupported_proposed == 0
    assert score.emitted_rows == 1


def test_reversal_fixture_perfect_output_scores_full_marks(fixture_set):
    fx = fixture_set.by_id("rej-01")
    score = score_fixture(fx, _validate(fx, _perfect_raw(fx)))
    assert score.recall == 1.0
    assert score.stance_correct == 2 and score.stance_total == 2
    assert score.forbidden_hits == []


def test_friday_ship_as_live_commitment_is_a_critical_error(fixture_set):
    fx = fixture_set.by_id("rej-01")
    bad = _row("We will ship on Friday", "We agreed to ship Friday", stance="committed")
    score = score_fixture(fx, _validate(fx, _rows_json([bad])))
    assert len(score.forbidden_hits) == 1
    assert score.forbidden_hits[0].forbidden_class == "commitment_inflation"
    assert score.emitted_rows == 0  # the gate dropped it; recall is 0, not a pass
    assert score.recall == 0.0


def test_negation_inversion_zeroes_negation_preservation(fixture_set):
    fx = fixture_set.by_id("neg-01")
    bad = _row("The old vendor will be used for the migration", "We will not use the old vendor")
    score = score_fixture(fx, _validate(fx, _rows_json([bad])))
    assert score.negation_total == 1
    assert score.negation_preserved == 0
    assert any(h.forbidden_class == "negation_inversion" for h in score.forbidden_hits)


def test_negation_perfect_output_preserves(fixture_set):
    fx = fixture_set.by_id("neg-01")
    score = score_fixture(fx, _validate(fx, _perfect_raw(fx)))
    assert score.negation_preserved == 1
    assert score.negation_total == 1


def test_certainty_upgrade_detected_by_stance_strength(fixture_set):
    fx = fixture_set.by_id("unc-01")
    row = _row(
        "The new onboarding flow might be tried with the next cohort",
        "We might try the new onboarding flow",
        stance="committed",  # gold says "considered"
    )
    score = score_fixture(fx, _validate(fx, _rows_json([row])))
    assert any(h.forbidden_class == "certainty_upgrade" for h in score.forbidden_hits)


def test_extra_row_counts_as_unsupported_and_extra(fixture_set):
    fx = fixture_set.by_id("com-01")
    rows = [
        _row("The team decided to ship on Friday", "We decided to ship on Friday"),
        _row("The team celebrated with cake on Friday", "We decided to ship on Friday"),
    ]
    score = score_fixture(fx, _validate(fx, _rows_json(rows)))
    assert score.extra_rows == 1
    assert score.unsupported_proposed == 1
    assert score.emitted_rows == 1


def test_honest_empty_is_a_correct_result(fixture_set):
    fx = fixture_set.by_id("emp-01")
    score = score_fixture(fx, _validate(fx, '{"rows": []}'))
    assert score.honest_empty is True
    assert score.recall == 1.0
    assert score.failed is False


def test_abstention_on_a_real_proposition_loses_recall(fixture_set):
    fx = fixture_set.by_id("com-01")
    score = score_fixture(fx, _validate(fx, '{"rows": []}'))
    assert score.honest_empty is False
    assert score.recall == 0.0


def test_failed_call_scores_as_failure_not_empty(fixture_set):
    fx = fixture_set.by_id("emp-01")
    score = score_fixture(fx, _validate(fx, "", failure_code="timeout"))
    assert score.failed is True
    assert score.failure_code == "timeout"
    assert score.honest_empty is False
    assert score.recall is None


def test_misattribution_is_a_critical_error(fixture_set):
    fx = fixture_set.by_id("att-01")
    row = _row(
        "Friday is too soon to ship the beta because the tests aren't green",
        "We should ship the beta on Friday",
        stance="rejected",
    )
    score = score_fixture(fx, _validate(fx, _rows_json([row])))
    assert any(h.forbidden_class == "attribution_error" for h in score.forbidden_hits)


# --- aggregation + pass rule --------------------------------------------------


def _all_perfect_scores(fixture_set):
    return [
        score_fixture(fx, _validate(fx, _perfect_raw(fx)))
        for fx in fixture_set.fixtures
    ]


def test_aggregate_perfect_run_passes_quality_measures(fixture_set):
    scores = _all_perfect_scores(fixture_set)
    validations = {
        fx.id: _validate(fx, _perfect_raw(fx)) for fx in fixture_set.fixtures
    }
    segments = {fx.id: fx.segment for fx in fixture_set.fixtures}
    agg = aggregate_scores(
        scores,
        variant="model-on",
        candidate=None,
        emitted_validations=validations,
        segments=segments,
    )
    assert agg.recall == 1.0
    assert agg.false_positive_rate == 0.0
    assert agg.stance_accuracy == 1.0
    assert agg.negation_preservation == 1.0
    assert agg.emitted_exactness == 1.0
    assert agg.forbidden_hits == []
    assert agg.gate_rejection_rate == 0.0
    assert agg.honest_empties == 2
    assert agg.failures == 0
    assert agg.per_category["negation"]["recall"] == 1.0
    assert agg.per_category["attribution"]["recall"] == 1.0


def test_aggregate_noisy_run_fails(fixture_set):
    # Every fixture gets its gold rows plus one fabricated-quote row.
    scores = []
    validations = {}
    segments = {}
    for fx in fixture_set.fixtures:
        rows = [_row(g.text, g.quote, stance=g.stance) for g in fx.expected]
        rows.append(_row("Something else entirely happened here today", "fabricated words here"))
        validation = _validate(fx, _rows_json(rows))
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
    assert agg.recall == 1.0  # gold rows still recovered
    assert agg.gate_rejection_rate is not None and agg.gate_rejection_rate > 0
    assert agg.gate_rejection_by_reason.get("quote_not_verbatim", 0) == len(
        fixture_set.fixtures
    )
    assert agg.emitted_exactness == 1.0  # the gate kept the emitted set clean


def test_finalize_pass_needs_reproducibility(fixture_set):
    scores = _all_perfect_scores(fixture_set)
    validations = {
        fx.id: _validate(fx, _perfect_raw(fx)) for fx in fixture_set.fixtures
    }
    segments = {fx.id: fx.segment for fx in fixture_set.fixtures}
    agg = aggregate_scores(
        scores,
        variant="model-on",
        candidate=None,
        emitted_validations=validations,
        segments=segments,
    )
    finalize_pass(agg)
    # No 3-run comparison yet: the verdict is UNDECIDED, never a pass.
    assert agg.passed is None
    assert agg.pass_fail["reproducibility"] is None


# --- reproducibility (measure R) ----------------------------------------------


def _three_runs(fixture_set, raw_fn):
    runs = []
    for _ in range(3):
        run = {}
        for fx in fixture_set.fixtures:
            run[fx.id] = _validate(fx, raw_fn(fx))
        runs.append(run)
    return runs


def test_reproducibility_identical_runs(fixture_set):
    runs = _three_runs(fixture_set, _perfect_raw)
    result = compare_runs(runs, fixture_set)
    assert result["structural"] == 1.0
    assert result["semantic"] == 1.0
    assert result["exact_identity"] == 1.0


def test_reproducibility_semantic_but_not_structural(fixture_set):
    # Run 3 uses an equivalent wording for one gold proposition: the supported
    # proposition is the same (semantic pass) but the row structure differs.
    def raw_variant(fx, run_index):
        if run_index == 2 and fx.id == "com-01":
            return _rows_json(
                [_row("Shipping on Friday was decided", "We decided to ship on Friday")]
            )
        return _perfect_raw(fx)

    runs = []
    for i in range(3):
        run = {}
        for fx in fixture_set.fixtures:
            run[fx.id] = _validate(fx, raw_variant(fx, i))
        runs.append(run)
    result = compare_runs(runs, fixture_set)
    assert result["semantic"] == 1.0
    assert result["structural"] < 1.0
    assert result["exact_identity"] < 1.0
    assert result["per_fixture"]["com-01"]["structural"] is False
    assert result["per_fixture"]["com-01"]["semantic"] is True


def test_reproducibility_failed_run_fails_fixture(fixture_set):
    runs = _three_runs(fixture_set, _perfect_raw)
    fx = fixture_set.by_id("com-01")
    runs[1]["com-01"] = _validate(fx, "", failure_code="timeout")
    result = compare_runs(runs, fixture_set)
    assert result["per_fixture"]["com-01"]["structural"] is False
    assert result["per_fixture"]["com-01"]["semantic"] is False
    assert result["structural"] < 1.0


def test_compare_runs_requires_exactly_three(fixture_set):
    runs = _three_runs(fixture_set, _perfect_raw)[:2]
    with pytest.raises(ValueError, match="exactly 3 runs"):
        compare_runs(runs, fixture_set)


# --- skip-variant fail rule (§4.3) ----------------------------------------------


def test_variant_check_model_on_always_passes(fixture_set):
    scores = _all_perfect_scores(fixture_set)
    agg = aggregate_scores(scores, variant="model-on", candidate=None)
    passed, reasons = variant_check(agg)
    assert passed is True
    assert reasons == []


def test_variant_check_skip_fails_on_reversal(fixture_set):
    fx = fixture_set.by_id("rej-01")
    bad = _row("We will ship on Friday", "We agreed to ship Friday", stance="committed")
    score = score_fixture(fx, _validate(fx, _rows_json([bad])))
    agg = aggregate_scores([score], variant="skip-enabled", candidate=None)
    passed, reasons = variant_check(agg)
    assert passed is False
    assert any("commitment_inflation" in r for r in reasons)


def test_variant_check_skip_passes_when_clean(fixture_set):
    fx = fixture_set.by_id("com-01")
    score = score_fixture(fx, _validate(fx, _perfect_raw(fx)))
    agg = aggregate_scores([score], variant="skip-enabled", candidate=None)
    passed, reasons = variant_check(agg)
    assert passed is True
    assert reasons == []
