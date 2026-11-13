"""Deterministic self-tests for the ratified wash freeze-readiness amendment.

Implements amendment B5's control suite ST-0–ST-9 plus the A4/B4
provenance-preservation acceptance assertion P1–P3 as executable checks.
All inputs are deterministic and local: crafted outputs fed through
``validate_segment_output`` + ``score_fixture`` (the governing
reconciliation's §5 method). No model is called.

ST-4 half (iii) is marked xfail (strict): as ratified, att-04's gold
declares no supporting quote on Speaker A's line, so a quote from A's
line cannot enter the B4 evidence-speaker set — the amendment's stated
expectation ("att-04 is the same shape" as att-09) does not hold
against the filed gold. See the implementation report; the gap is a
one-line gold authoring item for the founder, not something this suite
may silently paper over.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

import pytest

from local_ai.eval.wash.fixtures import (
    FixtureError,
    FixtureSet,
    default_fixture_path,
    load_fixture_set,
)
from local_ai.eval.wash.measures import (
    _row_matches_gold,
    aggregate_scores,
    score_fixture,
)
from local_ai.eval.wash.report import build_report, render_markdown
from local_ai.eval.wash.runner import score_candidate, write_scores
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


def _row_no_stance(text, quote, confidence="high"):
    return {
        "text": text,
        "summary": "A test row.",
        "evidence_quote": quote,
        "confidence": confidence,
    }


def _score(fx, raw):
    validation = validate_segment_output(raw, fx.segment, fx)
    return validation, score_fixture(fx, validation)


def _aggregate(score):
    return aggregate_scores([score], variant="model-on", candidate=None)


# --- ST-0 / ST-1: stance omission on stance-bearing gold --------------------


def test_st0_st1_omission_on_stance_bearing_gold_dilutes(fixture_set):
    """ST-0 (characterization) / ST-1 (amended expectation), same observation.

    com-01's perfect row with the stance key omitted: the row is emitted,
    stance_total = 1, stance_correct = 0 — omission already dilutes stance
    accuracy through the denominator, so the governing reconciliation
    §5.3's premise ("omission is not penalized anywhere") is wrong as a
    description of the code. B2 changes only unset-gold handling, so the
    observation is identical before and after the amendment; the dispute
    is settled by this observation.
    """
    fx = fixture_set.by_id("com-01")
    gold = fx.expected[0]
    _, score = _score(fx, _rows_json([_row_no_stance(gold.text, gold.quote)]))
    assert score.emitted_rows == 1
    assert score.stance_total == 1
    assert score.stance_correct == 0


def test_st1_invalid_stance_word_is_treated_as_omission(fixture_set):
    """ST-1 variant: stance "factual" normalizes to None (invalid_stance)."""
    fx = fixture_set.by_id("com-01")
    gold = fx.expected[0]
    validation, score = _score(
        fx, _rows_json([_row(gold.text, gold.quote, stance="factual")])
    )
    assert score.emitted_rows == 1
    assert score.stance_total == 1
    assert score.stance_correct == 0
    assert any(d.startswith("invalid_stance") for d in validation.diagnostics)


# --- ST-2 / ST-3: unset gold (neg-10 as corrected by Case 3) ----------------


def test_st2_omission_on_unset_gold_is_correct_behaviour(fixture_set):
    fx = fixture_set.by_id("neg-10")
    gold = fx.expected[0]
    assert gold.stance is None
    _, score = _score(fx, _rows_json([_row_no_stance(gold.text, gold.quote)]))
    assert score.emitted_rows == 1
    assert score.recall == 1.0
    assert score.stance_total == 0 and score.stance_correct == 0
    assert score.stance_unset_matched == 1
    assert score.unsupported_attempted == 0
    assert score.unsupported_emitted == 0
    assert score.unsupported_matched == 1


@pytest.mark.parametrize("stance", ["committed", "rejected"])
def test_st3_stance_on_unset_gold_is_unsupported_stance_only(fixture_set, stance):
    fx = fixture_set.by_id("neg-10")
    gold = fx.expected[0]
    _, score = _score(fx, _rows_json([_row(gold.text, gold.quote, stance=stance)]))
    assert score.emitted_rows == 1  # the gate has no stance check
    assert score.stance_total == 0 and score.stance_correct == 0  # B2 exclusion
    assert score.stance_unset_matched == 1
    assert score.unsupported_attempted == 1
    assert score.unsupported_emitted == 1
    # B3, not measure F, polices this: unset gold is off the strength scale.
    assert all(h.forbidden_class != "certainty_upgrade" for h in score.forbidden_hits)
    assert score.forbidden_hits == []
    # The run fails the B6 gate term.
    assert _aggregate(score).pass_fail["unsupported_stance"] is False


# --- ST-4 / ST-5: the B4 evidence-speaker set --------------------------------


def test_st4_i_att09_row1_quoted_from_proposers_line(fixture_set):
    fx = fixture_set.by_id("att-09")
    row1 = fx.expected[0]
    validation, score = _score(
        fx,
        _rows_json([_row(row1.text, "Should we invite the design team?", stance="committed")]),
    )
    assert score.emitted_rows == 1
    assert any(
        d.startswith("attribution_multi_speaker") for d in validation.diagnostics
    )
    assert score.recovered_count == 1  # recall credit for row 1


def test_st4_ii_att09_row1_quoted_from_assenters_line(fixture_set):
    fx = fixture_set.by_id("att-09")
    row1 = fx.expected[0]
    validation, score = _score(
        fx,
        _rows_json([_row(row1.text, "Yes, and the data team too", stance="committed")]),
    )
    assert score.emitted_rows == 1
    assert score.recovered_count == 1


@pytest.mark.xfail(
    strict=True,
    reason=(
        "ST-4(iii) as specified cannot pass against the ratified gold: "
        "att-04 declares no supporting quote on Speaker A's line, so A's "
        "line is not in the B4 evidence-speaker set S(gold) and a quote "
        "from it drops quote_misattributed. Closing the gap needs a "
        "founder-approved gold authoring change (add A's proposal line "
        "to att-04's supporting_quotes, the Case 6 att-09 pattern). "
        "Stopped and reported; not silently resolved."
    ),
)
def test_st4_iii_att04_row_quoted_from_proposers_line(fixture_set):
    fx = fixture_set.by_id("att-04")
    gold = fx.expected[0]
    validation, score = _score(
        fx,
        _rows_json([_row(gold.text, "I think we should pause hiring", stance="committed")]),
    )
    assert score.emitted_rows == 1
    assert score.recovered_count == 1


def test_st5_wrong_speaker_quote_still_drops(fixture_set):
    fx = fixture_set.by_id("att-01")
    bs_row = fx.expected[1]  # Speaker B's proposition
    validation, score = _score(
        fx,
        _rows_json([_row(bs_row.text, "We should ship the beta on Friday", stance="rejected")]),
    )
    assert score.emitted_rows == 0
    assert [d.reason for d in validation.dropped] == ["quote_misattributed"]
    assert any(
        h.forbidden_class == "attribution_error" for h in score.forbidden_hits
    )


# --- ST-6: loader behaviour (B1) ----------------------------------------------

_ENVELOPE = {
    "format": "wash-fixtures",
    "fixture_set_version": "1.0-draft",
    "gold_label_version": "1.0-draft",
    "semantic_contract_version": "1.0",
    "extraction_version": "1.0",
    "status": "crafted self-test file",
}


def _crafted_file(tmp_path: Path, expected_row: dict, name: str = "crafted.json") -> Path:
    fixture = {
        "id": "craft-01",
        "category": "negation",
        "segment": "We will not use the old vendor for the migration.",
        "has_explicit_speakers": False,
        "expected": [expected_row],
        "forbidden": [],
        "notes": "",
    }
    data = dict(_ENVELOPE)
    data["fixtures"] = [fixture]
    path = tmp_path / name
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


_BASE_ROW = {
    "text": "The old vendor will not be used for the migration",
    "speaker": None,
    "quote": "We will not use the old vendor",
    "equivalents": [],
    "supporting_quotes": ["We will not use the old vendor"],
}


def test_st6_i_null_stance_loads_as_none(tmp_path):
    row = dict(_BASE_ROW, stance=None)
    loaded = load_fixture_set(_crafted_file(tmp_path, row))
    assert loaded.fixtures[0].expected[0].stance is None


def test_st6_ii_absent_stance_key_refuses(tmp_path):
    with pytest.raises(FixtureError, match="stance key is required"):
        load_fixture_set(_crafted_file(tmp_path, dict(_BASE_ROW)))


def test_st6_iii_invented_stance_value_refuses(tmp_path):
    row = dict(_BASE_ROW, stance="disputed")
    with pytest.raises(FixtureError, match="stance vocabulary"):
        load_fixture_set(_crafted_file(tmp_path, row))


def test_st6_iv_pre_amendment_shape_and_role_keys_load(tmp_path):
    # Pre-amendment shape: stance-bearing rows, no role keys — loads.
    row = dict(_BASE_ROW, stance="rejected")
    loaded = load_fixture_set(_crafted_file(tmp_path, row, "plain.json"))
    parsed = loaded.fixtures[0].expected[0]
    assert parsed.stance == "rejected"
    assert parsed.originator is None and parsed.reporter is None
    assert parsed.assenter is None and parsed.decision_class is None
    # A file authored with role keys loads with the roles populated.
    row = dict(
        _BASE_ROW,
        stance="committed",
        originator="the client",
        reporter="Speaker B",
        assenter="Speaker A",
        decision_class="reported_decision",
    )
    loaded = load_fixture_set(_crafted_file(tmp_path, row, "roles.json"))
    parsed = loaded.fixtures[0].expected[0]
    assert parsed.originator == "the client"
    assert parsed.reporter == "Speaker B"
    assert parsed.assenter == "Speaker A"
    assert parsed.decision_class == "reported_decision"


# --- ST-7: a dropped attempt counts as attempted only -------------------------


def test_st7_dropped_attempt_counts_attempted_only(fixture_set):
    fx = fixture_set.by_id("neg-10")
    gold = fx.expected[0]
    validation, score = _score(
        fx,
        _rows_json(
            [_row(gold.text, "does not cover a second designer", stance="committed")]
        ),
    )
    assert [d.reason for d in validation.dropped] == ["quote_unsupported"]
    assert score.unsupported_attempted == 1
    assert score.unsupported_emitted == 0
    assert _aggregate(score).pass_fail["unsupported_stance"] is True


# --- ST-8: reported decision vs reported preference ---------------------------


def test_st8_i_reported_decision_carries_stance_with_provenance(fixture_set):
    fx = fixture_set.by_id("evp-08")
    gold = fx.expected[0]
    _, score = _score(fx, _rows_json([_row(gold.text, gold.quote, stance="committed")]))
    assert score.emitted_rows == 1
    assert score.stance_total == 1 and score.stance_correct == 1
    assert score.unsupported_attempted == 0 and score.unsupported_emitted == 0
    (rs,) = [r for r in score.row_scores if r.matched_gold_index is not None]
    assert rs.reported is True
    assert rs.decision_class == "reported_decision"
    assert rs.originator == "the team"
    assert rs.reporter is None  # unknown stays unknown
    assert rs.stance_outcome == "correct"


def test_st8_ii_reported_preference_carries_no_stance(fixture_set):
    fx = fixture_set.by_id("neg-06")
    gold = fx.expected[0]
    assert gold.stance is None
    _, score = _score(fx, _rows_json([_row(gold.text, gold.quote, stance="rejected")]))
    assert score.emitted_rows == 1
    assert score.stance_total == 0 and score.stance_correct == 0
    assert score.unsupported_attempted == 1
    assert score.unsupported_emitted == 1
    assert _aggregate(score).pass_fail["unsupported_stance"] is False


# --- ST-9: overlapping matches and contention ---------------------------------
# Half (i)'s crafted fixture is a SYNTHETIC matcher stress test: its two
# gold rows are deliberately overlapping wordings engineered to pin
# matcher/counting behaviour. It is not production gold, never enters the
# production fixture file or any distribution, and no semantic conclusion
# is drawn from its labels.


def _st9_file(tmp_path: Path, order: str) -> Path:
    segment = "The budget does not cover a second designer this quarter"
    unset = {
        "text": segment,
        "stance": None,
        "speaker": None,
        "quote": segment,
        "equivalents": [],
        "supporting_quotes": [segment],
    }
    stance_bearing = {
        "text": "A second designer will not be hired this quarter",
        "stance": "rejected",
        "speaker": None,
        "quote": segment,
        "equivalents": [segment],
        "supporting_quotes": [segment],
    }
    expected = [unset, stance_bearing] if order == "unset-first" else [stance_bearing, unset]
    fixture = {
        "id": "st-09-synthetic",
        "category": "negation",
        "segment": segment,
        "has_explicit_speakers": False,
        "expected": expected,
        "forbidden": [],
        "notes": "SYNTHETIC matcher stress fixture (ST-9) — not production gold.",
    }
    data = dict(_ENVELOPE)
    data["fixtures"] = [fixture]
    path = tmp_path / f"st9-{order}.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_st9_i_unset_row_first_governs(tmp_path):
    loaded = load_fixture_set(_st9_file(tmp_path, "unset-first"))
    fx = loaded.fixtures[0]
    segment = fx.segment
    validation, score = _score(
        fx, _rows_json([_row(segment, segment, stance="committed")])
    )
    (emitted_row,) = validation.emitted
    governing = _row_matches_gold(emitted_row, fx)
    assert governing is fx.expected[0] and governing.stance is None
    assert score.unsupported_attempted == 1
    assert score.unsupported_emitted == 1
    assert score.unsupported_matched == 1  # counted once, not again under S
    assert score.forbidden_hits == []


def test_st9_i_stance_row_first_governs(tmp_path):
    loaded = load_fixture_set(_st9_file(tmp_path, "stance-first"))
    fx = loaded.fixtures[0]
    segment = fx.segment
    validation, score = _score(
        fx, _rows_json([_row(segment, segment, stance="committed")])
    )
    (emitted_row,) = validation.emitted
    governing = _row_matches_gold(emitted_row, fx)
    assert governing is fx.expected[0] and governing.stance == "rejected"
    assert score.unsupported_attempted == 0
    assert score.unsupported_emitted == 0
    assert score.unsupported_matched == 0
    assert score.stance_total == 1 and score.stance_correct == 0
    assert all(
        h.forbidden_class != "certainty_upgrade" for h in score.forbidden_hits
    )


def test_st9_ii_contention_counts_distinct_rows_once(fixture_set):
    fx = fixture_set.by_id("neg-10")
    gold = fx.expected[0]
    segment_line = gold.quote
    rows = [
        _row(gold.text, segment_line, stance="committed"),
        _row(gold.equivalents[0], segment_line, stance="committed"),
        _row(gold.text, segment_line, stance="committed"),  # verbatim repeat
    ]
    validation, score = _score(fx, _rows_json(rows))
    assert score.emitted_rows == 2
    assert [d.reason for d in validation.dropped] == ["duplicate"]
    assert score.unsupported_attempted == 2
    assert score.unsupported_emitted == 2
    assert score.unsupported_matched == 2  # the duplicate adds no count
    assert _aggregate(score).pass_fail["unsupported_stance"] is False


# --- P1–P3: provenance-preservation acceptance assertion ----------------------

_CLASS1_IDS = ("evp-08", "att-05", "com-04", "att-03")


def test_p1_gold_record_roles_exactly_as_authored(fixture_set):
    evp08 = fixture_set.by_id("evp-08").expected[0]
    assert evp08.decision_class == "reported_decision"
    assert evp08.speaker is None
    assert evp08.originator == "the team"
    assert evp08.reporter is None  # the segment names no reporter

    att05 = fixture_set.by_id("att-05").expected[0]
    assert att05.decision_class == "reported_decision"
    assert att05.speaker == "Speaker B"
    assert att05.reporter == "Speaker B"
    assert att05.originator is None  # the deciding party is not named

    com04 = fixture_set.by_id("com-04").expected[0]
    assert com04.decision_class == "reported_decision"
    assert com04.speaker is None
    assert com04.originator is None and com04.reporter is None

    att03 = fixture_set.by_id("att-03").expected[0]
    assert att03.decision_class == "reported_decision"
    assert att03.speaker == "Speaker B"
    assert att03.reporter == "Speaker B"
    assert att03.originator is None


def _class1_subset_run(fixture_set):
    """One perfect run over the four class-1 fixtures + com-01 (performed)."""
    ids = list(_CLASS1_IDS) + ["com-01"]
    subset = FixtureSet(
        fixtures=[fixture_set.by_id(i) for i in ids],
        fixture_set_version="1.0-draft",
        gold_label_version="1.0-draft",
        semantic_contract_version="1.0",
        extraction_version="1.0",
    )
    entries = []
    for fx in subset.fixtures:
        rows = [
            _row(g.text, g.quote, stance=g.stance) for g in fx.expected
        ]
        entries.append(
            {"fixture_id": fx.id, "raw_text": _rows_json(rows), "model_call_count": 1}
        )
    return score_candidate(subset, [entries])


def test_p2_scored_record_identifies_reported_rows(fixture_set, tmp_path):
    _, _, run_results = _class1_subset_run(fixture_set)
    result = run_results[0]
    # The serialized scored record (scores.json shape) carries the class.
    scores_path = write_scores(tmp_path / "scores.json", result)
    serialized = json.loads(scores_path.read_text(encoding="utf-8"))
    for fid in _CLASS1_IDS:
        (rs,) = [
            r
            for r in serialized[fid]["row_scores"]
            if r["matched_gold_index"] is not None
        ]
        assert rs["reported"] is True
        assert rs["decision_class"] == "reported_decision"
        assert rs["stance_outcome"] == "correct"
    # Provenance rides along per row, field by field.
    evp08_rs = serialized["evp-08"]["row_scores"][0]
    assert evp08_rs["originator"] == "the team" and evp08_rs["reporter"] is None
    # The performed row (com-01) is not classified reported.
    (com01_rs,) = serialized["com-01"]["row_scores"]
    assert com01_rs["reported"] is False and com01_rs["decision_class"] is None
    # asdict round-trip: the in-memory record matches the serialized one.
    assert asdict(result.fixture_scores["evp-08"])["row_scores"][0]["reported"] is True


def test_p3_report_keeps_reported_and_performed_distinguishable(fixture_set):
    report, _, _ = _class1_subset_run(fixture_set)
    prov = report["decision_provenance"]
    reported = prov["reported_decisions"]
    performed = prov["performed_decisions"]
    # Every class-1 fixture's row is listed individually, provenance attached.
    assert {r["fixture_id"] for r in reported["rows"]} == set(_CLASS1_IDS)
    assert reported["tally"]["total"] == 4
    assert reported["tally"]["correct"] == 4
    for r in reported["rows"]:
        assert r["decision_class"] == "reported_decision"
        assert "originator" in r and "reporter" in r and "speaker" in r
    # The performed tally is separate — never merged with the reported one.
    assert performed["tally"]["total"] == 1  # com-01 only
    assert "authorship" in prov["note"]  # the standing caveat is rendered
    md = render_markdown(report)
    assert "## Decision provenance" in md
    assert "evp-08" in md and "the team" in md
    # The unsupported-stance measure is reported with its two counts apart.
    us = report["measures"]["unsupported_stance"]
    assert us == {"attempted": 0, "emitted": 0, "matched_unset": 0, "rate": None}
    assert report["measures"]["stance_unset_matched"] == 0
    assert report["pass_fail"]["unsupported_stance"] is True
