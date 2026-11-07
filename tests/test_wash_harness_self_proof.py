"""Harness-first proof (§8.1): the benchmark must prove itself before it
judges a model.

Four required demonstrations, each a first-class test with a name that says
what it proves:

1. A genuine empty segment is distinguished from a failed model call.
2. Fabricated quotes are rejected.
3. Speaker misattribution is caught.
4. A reversed commitment is identified.

Plus: the experimental skip variant fails on the reversal (and passes a
benign control), and a perfect model passes the whole suite — the benchmark
does not false-fail a good model. All inputs are synthetic — no model is
called, no benchmark run against a live model is performed here.
"""

from __future__ import annotations

import json

import pytest

from local_ai.eval.wash.fixtures import default_fixture_path, load_fixture_set
from local_ai.eval.wash.measures import aggregate_scores, score_fixture, variant_check
from local_ai.eval.wash.runner import score_candidate
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
    return _rows_json(
        [_row(g.text, g.quote, stance=g.stance) for g in fx.expected]
    )


def _validate(fx, raw, **kwargs):
    return validate_segment_output(raw, fx.segment, fx, **kwargs)


# --- Demonstration 1: genuine empty vs. failed call --------------------------


def test_self_proof_honest_empty_vs_failed_call(fixture_set):
    """An honest empty scores as a correct result; a failed call scores as a
    failure with its diagnostic — never as an empty (§8.1.1, §2.1.4)."""
    fx = fixture_set.by_id("emp-01")

    empty = score_fixture(fx, _validate(fx, '{"rows": []}'))
    assert empty.honest_empty is True
    assert empty.failed is False
    assert empty.recall == 1.0

    failed = score_fixture(fx, _validate(fx, "", failure_code="unreachable"))
    assert failed.failed is True
    assert failed.failure_code == "unreachable"
    assert failed.honest_empty is False
    assert failed.recall is None  # a failure is never scored as an empty

    timed_out = score_fixture(fx, _validate(fx, "", failure_code="timeout"))
    assert timed_out.failed is True
    assert timed_out.failure_code == "timeout"


# --- Demonstration 2: fabricated quotes rejected ------------------------------


def test_self_proof_fabricated_quote_rejected(fixture_set):
    """A proposed row whose evidence_quote is not an exact substring is
    dropped (quote_not_verbatim), counted in the gate-rejection rate, and
    never appears in emitted output (§8.1.2, refinement B)."""
    fx = fixture_set.by_id("com-01")
    fabricated = _row(
        "The team decided to ship on Friday",
        "We decided to ship Friday, definitely, no take-backs",
    )
    validation = _validate(fx, _rows_json([fabricated]))
    assert validation.emitted == []
    assert validation.gate_counts == {"quote_not_verbatim": 1}
    score = score_fixture(fx, validation)
    assert score.emitted_rows == 0
    assert score.recall == 0.0  # a missing usable quote lowers recall

    # The same trap via a paraphrased quote on an evidence-preservation case.
    evp = fixture_set.by_id("evp-02")
    paraphrase = _row(
        "Mara approved the $12,400 pilot spend, not the $18,000 request",
        "Mara approved twelve thousand four hundred for the pilot",
    )
    validation2 = _validate(evp, _rows_json([paraphrase]))
    assert validation2.emitted == []
    assert validation2.gate_counts == {"quote_not_verbatim": 1}


# --- Demonstration 3: speaker misattribution caught ----------------------------


def test_self_proof_speaker_misattribution_caught(fixture_set):
    """A verbatim quote attributed to the wrong speaker fails the attribution
    check (quote_misattributed, measure F) on a segment with explicit speaker
    boundaries (§8.1.3, refinement A)."""
    fx = fixture_set.by_id("att-01")
    # B's proposition ("Friday is too soon") quoted from A's line.
    misattributed = _row(
        "Friday is too soon to ship the beta because the tests aren't green",
        "We should ship the beta on Friday",
        stance="rejected",
    )
    validation = _validate(fx, _rows_json([misattributed]))
    assert validation.emitted == []
    assert validation.gate_counts == {"quote_misattributed": 1}
    score = score_fixture(fx, validation)
    assert any(
        h.forbidden_class == "attribution_error" for h in score.forbidden_hits
    )

    # Control: the same proposition with B's own line passes.
    correct = _row(
        "Friday is too soon to ship the beta because the tests aren't green",
        "Friday is too soon, the tests aren't green",
        stance="rejected",
    )
    validation2 = _validate(fx, _rows_json([correct]))
    assert len(validation2.emitted) == 1


# --- Demonstration 4: reversed commitment identified ----------------------------


def test_self_proof_reversed_commitment_identified(fixture_set):
    """The canonical reversal fixture (§5.1) must not yield the Friday ship
    as a live commitment; the reversal is caught as a commitment-inflation
    critical error (measure F) (§8.1.4, refinement D)."""
    fx = fixture_set.by_id("rej-01")

    # The trap: the initial commitment emitted as live, the reversal ignored.
    trap = _row("We will ship on Friday", "We agreed to ship Friday", stance="committed")
    validation = _validate(fx, _rows_json([trap]))
    assert validation.emitted == []  # the gate dropped it
    score = score_fixture(fx, validation)
    assert len(score.forbidden_hits) == 1
    assert score.forbidden_hits[0].forbidden_class == "commitment_inflation"
    assert score.recall == 0.0

    # The correct output: the rejection + the revisit plan, both recovered.
    correct = score_fixture(fx, _validate(fx, _perfect_raw(fx)))
    assert correct.recall == 1.0
    assert correct.forbidden_hits == []
    assert correct.stance_correct == 2


# --- Skip variant: fails on the reversal, passes a benign control -------------


def test_self_proof_skip_variant_fails_on_reversal(fixture_set):
    """The experimental skip variant (§4.3): a segment where deterministic
    extraction yields the commitment-level row and the model is skipped
    produces only the Friday-ship row — the reversal is never seen. The
    variant FAILS on the commitment reversal even if aggregate recall were
    to pass."""
    fx = fixture_set.by_id("rej-01")
    # What the skip variant yields for rej-01: the deterministic row only.
    skipped = _row("We will ship on Friday", "We agreed to ship Friday", stance="committed")
    score = score_fixture(fx, _validate(fx, _rows_json([skipped])))
    agg = aggregate_scores([score], variant="skip-enabled", candidate=None)
    passed, reasons = variant_check(agg)
    assert passed is False
    assert any("commitment_inflation" in r for r in reasons)


def test_self_proof_skip_variant_passes_benign_control(fixture_set):
    """Control: on a fixture with no reversal, the skip variant's
    deterministic row is the correct row and the variant check passes."""
    fx = fixture_set.by_id("com-01")
    score = score_fixture(fx, _validate(fx, _perfect_raw(fx)))
    agg = aggregate_scores([score], variant="skip-enabled", candidate=None)
    passed, reasons = variant_check(agg)
    assert passed is True
    assert reasons == []


# --- The benchmark does not false-fail a good model ------------------------------


def test_self_proof_perfect_model_passes_whole_suite(fixture_set):
    """Three identical perfect runs: recall 1.0, zero critical errors, full
    reproducibility, overall PASS. If a correct model failed here, the
    benchmark itself would be broken — this is the harness proving itself."""
    perfect = [
        {"fixture_id": fx.id, "raw_text": _perfect_raw(fx), "model_call_count": 1}
        for fx in fixture_set.fixtures
    ]
    report, _, _ = score_candidate(
        fixture_set, [perfect, perfect, perfect], variant="model-on"
    )
    assert report["measures"]["recall"] == 1.0
    assert report["measures"]["false_positive_rate"] == 0.0
    assert report["measures"]["stance_accuracy"] == 1.0
    assert report["measures"]["negation_preservation"] == 1.0
    assert report["measures"]["emitted_exactness"] == 1.0
    assert report["measures"]["reproducibility_structural"] == 1.0
    assert report["measures"]["reproducibility_semantic"] == 1.0
    assert report["critical_errors"]["total"] == 0
    assert report["passed"] is True
