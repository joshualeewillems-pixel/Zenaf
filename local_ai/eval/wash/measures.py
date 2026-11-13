"""Deterministic measure computations for the wash benchmark (design §6.4).

Scoring rules (§6.4.1):
- Structural checks are deterministic rules (exactness, parse success, dedupe,
  row-structure identity, manifest completeness, failure-code assignment).
- Proposition checks use the FROZEN semantic-equivalence judgments carried in
  the gold labels — the harness applies them deterministically; it never
  re-judges and never uses a model as an evaluator.
- Forbidden-output checks are explicit per-case gold labels (measure F).
- Raw-model quality (measure 6, pre-validation) is reported separately from
  post-validation emitted quality (measures 1-5, F, G).
- An honest empty (``{"rows": []}`` on a segment with no valid propositions)
  is a correct result; a failed model call is never scored as an empty; a
  model that abstains on a segment that DOES contain gold propositions loses
  recall for those propositions.

Decided ambiguities (flagged in the build report — the design leaves these
two points genuinely tense):
1. Measure F (forbidden outputs) is scored on PROPOSED rows (what the model
   attempted), with F_emitted reported separately as gate leakage (must be
   zero). §6.4.1 groups F with emitted output, but §8.1 requires the harness
   to *identify* a reversed commitment as a critical error — a gate-caught
   reversal would be invisible if F were post-gate only.
2. Measure 2 (false-positive rate) uses the design's literal AND formula on
   proposed rows: unsupported iff no gold proposition is semantically
   equivalent AND the quote fails exactness, attribution, or support. Because
   the gate's support check uses the same gold matching, the formula
   collapses in practice to "matches no gold proposition" — the harness also
   reports ``extra_rows`` (proposed rows matching no gold proposition) as a
   diagnostic so any undercount is visible.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from local_ai.eval.wash.fixtures import Fixture
from local_ai.eval.wash.textutil import normalize_text, texts_equivalent
from local_ai.eval.wash.validator import ProposedRow, ValidationResult

# Stance strength order for the certainty-upgrade rule. ``rejected`` is
# off-scale (a rejection is not a weaker/stronger commitment).
_STANCE_STRENGTH = {"unresolved": 0, "considered": 1, "proposed": 2, "committed": 3}

# Quote-check failure reasons (a row dropped for one of these "fails a quote
# check" in the measure-2 formula).
_QUOTE_FAILURE_REASONS = frozenset(
    {"missing_quote", "quote_not_verbatim", "quote_misattributed", "quote_unsupported"}
)

# Proposed §7 thresholds (PROVISIONAL — the founder approves final thresholds
# before any run, §6.2; a run whose thresholds changed after it executed is
# void for the changed fixtures).
DEFAULT_THRESHOLDS: dict[str, float] = {
    "recall": 0.80,
    "false_positive_rate": 0.10,
    "stance_accuracy": 0.90,
    "negation_preservation": 0.90,
    "emitted_exactness": 1.00,
    "raw_json_clean": 0.95,  # diagnostic threshold, not evidence pass/fail (§6.4.1)
    "duplication": 0.05,
    "reproducibility_structural": 0.95,
    "reproducibility_semantic": 0.95,
    "critical_errors": 0,  # proposed gate: zero critical errors (§7)
}


@dataclass
class ForbiddenHit:
    """One critical error: a proposed row hit a forbidden output."""

    fixture_id: str
    forbidden_class: str
    text: str
    detail: str


@dataclass
class RowScore:
    """Per-row scored record (ratified amendment B4/P2).

    One record per proposed row (emitted or dropped), carrying the matched
    gold row's identity and its preservation-only provenance (the gold
    record's ``speaker`` and A4 role fields, and its decision class), so
    the reported/performed distinction survives scoring into the run
    outputs and the report. The provenance fields describe the GOLD
    record the row matched; ``reported`` is true exactly when that gold
    row is classified ``reported_decision``. Attribution here is
    evidence provenance only — decision authorship is not measured.
    """

    fixture_id: str
    text: str
    status: str  # "emitted" | "dropped"
    drop_reason: str | None = None
    matched_gold_index: int | None = None  # index into fixture.expected
    gold_text: str | None = None
    gold_stance: str | None = None
    row_stance: str | None = None
    stance_outcome: str = "not_scored"  # correct | incorrect | excluded_unset | not_scored
    speaker: str | None = None
    originator: str | None = None
    reporter: str | None = None
    assenter: str | None = None
    decision_class: str | None = None
    reported: bool = False


@dataclass
class FixtureScore:
    """Everything scored for one fixture in one run."""

    fixture_id: str
    category: str
    gold_count: int
    recovered_count: int
    recall: float | None  # None when the fixture has no gold propositions
    honest_empty: bool  # correct {"rows": []} on a segment with no propositions
    failed: bool
    failure_code: str | None
    proposed_rows: int
    emitted_rows: int
    dropped_counts: dict[str, int] = field(default_factory=dict)
    unsupported_proposed: int = 0
    extra_rows: int = 0  # proposed rows matching no gold proposition (diagnostic)
    stance_correct: int = 0
    stance_total: int = 0
    # Amendment B2/B3: emitted rows matched to stance-unset gold (excluded
    # from measure 3 both ways, counted here), and the unsupported-stance
    # measure on the proposed-row basis.
    stance_unset_matched: int = 0
    unsupported_attempted: int = 0  # proposed (non-duplicate) rows carrying a stance, matched to unset gold
    unsupported_emitted: int = 0  # of those, the rows the gate emitted (B6 gate: must be 0)
    unsupported_matched: int = 0  # denominator: proposed (non-duplicate) rows matched to unset gold
    row_scores: list[RowScore] = field(default_factory=list)
    negation_preserved: int = 0  # 1 when a negation gold proposition is recovered cleanly
    negation_total: int = 0
    exactness_passed_proposed: int = 0
    attribution_passed_proposed: int = 0
    support_passed_proposed: int = 0
    duplicates_dropped: int = 0
    forbidden_hits: list[ForbiddenHit] = field(default_factory=list)
    clean_parse: bool = False
    decode_ok: bool = False
    parse_reason: str = ""
    model_calls: int = 0
    diagnostics: list[str] = field(default_factory=list)


def _row_matches_gold(row: ProposedRow, fixture: Fixture) -> Any | None:
    """The gold proposition a row expresses, or None (frozen judgments)."""
    for gold in fixture.expected:
        if texts_equivalent(row.text, gold.text):
            return gold
        for eq in gold.equivalents:
            if texts_equivalent(row.text, eq):
                return gold
    return None


def _row_matches_forbidden(
    row: ProposedRow, fixture: Fixture
) -> tuple[str, str] | None:
    """(class, detail) when a proposed row matches a forbidden-output label."""
    for fb in fixture.forbidden:
        matched = texts_equivalent(row.text, fb.text) or any(
            texts_equivalent(row.text, eq) for eq in fb.equivalents
        )
        if not matched:
            continue
        if fb.stance is not None and row.stance != fb.stance:
            continue
        return fb.forbidden_class, fb.note or fb.text
    return None


def _forbidden_hits_for_row(
    row: ProposedRow, fixture: Fixture, dropped_reason: str | None
) -> list[ForbiddenHit]:
    """All forbidden-output hits for one proposed row (measure F, proposed)."""
    hits: list[ForbiddenHit] = []
    matched = _row_matches_forbidden(row, fixture)
    if matched is not None:
        fclass, detail = matched
        hits.append(
            ForbiddenHit(
                fixture_id=fixture.id,
                forbidden_class=fclass,
                text=row.text,
                detail=detail,
            )
        )
    # Attribution errors: any row the attribution check drops is a critical
    # attribution error, whether or not a forbidden entry names it.
    if dropped_reason == "quote_misattributed" and all(
        h.forbidden_class != "attribution_error" for h in hits
    ):
        hits.append(
            ForbiddenHit(
                fixture_id=fixture.id,
                forbidden_class="attribution_error",
                text=row.text,
                detail="quote attributed to the wrong speaker (gate diagnostic)",
            )
        )
    # Certainty upgrades: a row that states a gold proposition with a
    # strictly stronger stance than the gold (committed > proposed >
    # considered > unresolved). Rejected gold is off-scale and excluded.
    gold = _row_matches_gold(row, fixture)
    if (
        gold is not None
        and row.stance in _STANCE_STRENGTH
        and gold.stance in _STANCE_STRENGTH
        and _STANCE_STRENGTH[row.stance] > _STANCE_STRENGTH[gold.stance]
        and all(h.forbidden_class != "certainty_upgrade" for h in hits)
    ):
        hits.append(
            ForbiddenHit(
                fixture_id=fixture.id,
                forbidden_class="certainty_upgrade",
                text=row.text,
                detail=f"row stance {row.stance!r} is stronger than gold stance {gold.stance!r}",
            )
        )
    return hits


def score_fixture(
    fixture: Fixture,
    validation: ValidationResult,
    *,
    model_calls: int = 0,
) -> FixtureScore:
    """Score one fixture's validated output (one run, one variant)."""
    score = FixtureScore(
        fixture_id=fixture.id,
        category=fixture.category,
        gold_count=len(fixture.expected),
        recovered_count=0,
        recall=None,
        honest_empty=False,
        failed=validation.failure is not None,
        failure_code=(validation.failure or {}).get("code"),
        proposed_rows=validation.proposed_count,
        emitted_rows=len(validation.emitted),
        dropped_counts=dict(validation.gate_counts),
        clean_parse=bool(validation.parse_meta.get("clean_parse")),
        decode_ok=bool(validation.parse_meta.get("decode_ok")),
        parse_reason=str(validation.parse_meta.get("reason") or ""),
        model_calls=model_calls,
        diagnostics=list(validation.diagnostics),
    )

    if score.failed:
        return score

    # Recall: gold propositions recovered by emitted rows (post-gate, §6.4.1).
    # A model that proposes the right proposition with an unusable quote loses
    # recall — the gate dropped it, so it is not recovered.
    recovered_ids: set[int] = set()
    for row in validation.emitted:
        gold = _row_matches_gold(row, fixture)
        if gold is not None:
            recovered_ids.add(id(gold))
    score.recovered_count = len(recovered_ids)
    if fixture.expected:
        score.recall = score.recovered_count / len(fixture.expected)
    else:
        # No gold propositions: an honest empty is a correct result.
        score.honest_empty = validation.hard_empty and not validation.emitted
        score.recall = 1.0 if score.honest_empty else 0.0

    # Proposed rows (emitted + gate-dropped) — the basis for measure 5,
    # measure F, the B3 unsupported-stance measure, and the per-row scored
    # records. Emitted rows carry drop reason None.
    proposed: list[tuple[ProposedRow, str | None]] = [
        (row, None) for row in validation.emitted
    ] + [(d.row, d.reason) for d in validation.dropped]

    def _gold_index(gold: Any) -> int:
        return next(i for i, g in enumerate(fixture.expected) if g is gold)

    def _row_score(
        row: ProposedRow,
        status: str,
        drop_reason: str | None,
        gold: Any | None,
        stance_outcome: str,
    ) -> RowScore:
        if gold is None:
            return RowScore(
                fixture_id=fixture.id,
                text=row.text,
                status=status,
                drop_reason=drop_reason,
                row_stance=row.stance,
                stance_outcome=stance_outcome,
            )
        return RowScore(
            fixture_id=fixture.id,
            text=row.text,
            status=status,
            drop_reason=drop_reason,
            matched_gold_index=_gold_index(gold),
            gold_text=gold.text,
            gold_stance=gold.stance,
            row_stance=row.stance,
            stance_outcome=stance_outcome,
            speaker=gold.speaker,
            originator=gold.originator,
            reporter=gold.reporter,
            assenter=gold.assenter,
            decision_class=gold.decision_class,
            reported=gold.decision_class == "reported_decision",
        )

    # Stance distinction (measure 3): emitted rows matched to gold, stance
    # equal. Amendment B2: a row matched to stance-unset gold is excluded
    # from BOTH the numerator and the denominator (the model is neither
    # right nor wrong about a stance the gold does not assert) and is
    # counted separately as an excluded match.
    row_scores: list[RowScore] = []
    for row in validation.emitted:
        gold = _row_matches_gold(row, fixture)
        if gold is None:
            row_scores.append(_row_score(row, "emitted", None, None, "not_scored"))
            continue
        if gold.stance is None:
            score.stance_unset_matched += 1
            outcome = "excluded_unset"
        else:
            score.stance_total += 1
            if row.stance is not None and row.stance == gold.stance:
                score.stance_correct += 1
                outcome = "correct"
            else:
                outcome = "incorrect"
        row_scores.append(_row_score(row, "emitted", None, gold, outcome))
    for dropped in validation.dropped:
        gold = _row_matches_gold(dropped.row, fixture)
        row_scores.append(
            _row_score(dropped.row, "dropped", dropped.reason, gold, "not_scored")
        )
    score.row_scores = row_scores

    # Negation + qualification preservation (measure 4) is computed after the
    # forbidden hits below (a negation inversion on the fixture zeroes it).

    # Measure 5 sub-checks on proposed rows (pass rates) + forbidden hits.
    for row, dropped_reason in proposed:
        if dropped_reason not in ("missing_quote", "quote_not_verbatim"):
            score.exactness_passed_proposed += 1
        if dropped_reason != "quote_misattributed":
            score.attribution_passed_proposed += 1
        if dropped_reason != "quote_unsupported":
            score.support_passed_proposed += 1
        score.forbidden_hits.extend(
            _forbidden_hits_for_row(row, fixture, dropped_reason)
        )
        # Measure 2, literal AND formula (proposed rows): unsupported iff no
        # gold proposition is semantically equivalent AND the quote fails a
        # check.
        gold = _row_matches_gold(row, fixture)
        quote_failed = dropped_reason in _QUOTE_FAILURE_REASONS
        if gold is None and quote_failed:
            score.unsupported_proposed += 1
        if gold is None:
            score.extra_rows += 1

    score.duplicates_dropped = score.dropped_counts.get("duplicate", 0)

    # Unsupported-stance measure (amendment B3): on the proposed-row basis
    # above, a row counts when its GOVERNING match — the same first-match
    # mechanism (_row_matches_gold, first in fixture order) that row-level
    # scoring uses — is a stance-unset gold row. Attempted (the row carries
    # a stance) and emitted (the gate let it through) are counted
    # separately; a stance-less row on unset gold is correct behaviour and
    # counts only in the denominator. Rows the validator dropped as
    # duplicates add no count of any kind: duplication is already its own
    # measure, and a duplicate must never inflate the denominator, the
    # attempt count, or the emitted count. (Recall's recovered-id set is a
    # distinct basis — gold-identity recovery — and is not reused here.)
    for row, dropped_reason in proposed:
        if dropped_reason == "duplicate":
            continue
        gold = _row_matches_gold(row, fixture)
        if gold is None or gold.stance is not None:
            continue
        score.unsupported_matched += 1
        if row.stance is not None:
            score.unsupported_attempted += 1
            if dropped_reason is None:
                score.unsupported_emitted += 1

    # Negation + qualification preservation (measure 4): negation-category gold
    # propositions recovered without a negation-inversion hit on the fixture.
    if fixture.category == "negation":
        score.negation_total = len(fixture.expected)
        inversion = any(
            h.forbidden_class == "negation_inversion" for h in score.forbidden_hits
        )
        score.negation_preserved = (
            score.recovered_count if not inversion else 0
        ) if fixture.expected else 0
    return score


@dataclass
class BenchmarkScore:
    """Aggregate scores for one candidate, one variant, over scored fixtures."""

    variant: str
    candidate: str | None
    fixtures_scored: int
    recall: float | None
    false_positive_rate: float | None
    stance_accuracy: float | None
    negation_preservation: float | None
    emitted_exactness: float | None  # must be 1.0; verified, not assumed
    proposed_exactness_rate: float | None
    proposed_attribution_rate: float | None
    proposed_support_rate: float | None
    raw_json_clean_rate: float | None  # diagnostic threshold (§6.4.1)
    post_repair_yield: float | None
    duplication_rate: float | None
    forbidden_hits: list[ForbiddenHit] = field(default_factory=list)
    forbidden_by_class: dict[str, int] = field(default_factory=dict)
    forbidden_emitted: list[ForbiddenHit] = field(default_factory=list)  # gate leakage (must be 0)
    gate_rejection_rate: float | None = None
    gate_rejection_by_reason: dict[str, int] = field(default_factory=dict)
    honest_empties: int = 0
    failures: int = 0
    failure_codes: dict[str, int] = field(default_factory=dict)
    model_calls_total: int = 0
    segments_resolved_deterministically: int = 0  # model_calls == 0
    reproducibility_structural: float | None = None  # set when 3 runs are compared
    reproducibility_semantic: float | None = None
    reproducibility_exact_identity: float | None = None  # diagnostic only
    # Amendment B2/B3 aggregates + the per-row scored records (B4/P2).
    stance_unset_matched: int = 0
    unsupported_attempted: int = 0
    unsupported_emitted: int = 0
    unsupported_matched: int = 0
    unsupported_stance_rate: float | None = None  # attempted / matched; None when no unset matches
    row_scores: list[RowScore] = field(default_factory=list)
    operational: dict[str, Any] = field(default_factory=dict)  # measures 8-10: measured or "not measured"
    per_category: dict[str, dict[str, Any]] = field(default_factory=dict)
    thresholds: dict[str, float] = field(default_factory=dict)
    passed: bool | None = None
    pass_fail: dict[str, bool | None] = field(default_factory=dict)


def aggregate_scores(
    fixture_scores: list[FixtureScore],
    *,
    variant: str,
    candidate: str | None,
    thresholds: dict[str, float] | None = None,
    emitted_validations: dict[str, ValidationResult] | None = None,
    segments: dict[str, str] | None = None,
    operational: dict[str, Any] | None = None,
) -> BenchmarkScore:
    """Aggregate per-fixture scores into one benchmark score."""
    th = dict(DEFAULT_THRESHOLDS if thresholds is None else thresholds)
    scored = [s for s in fixture_scores if not s.failed]
    failed = [s for s in fixture_scores if s.failed]

    total_gold = sum(s.gold_count for s in scored)
    total_recovered = sum(s.recovered_count for s in scored)
    recall = (total_recovered / total_gold) if total_gold else None

    total_proposed = sum(s.proposed_rows for s in fixture_scores)
    total_unsupported = sum(s.unsupported_proposed for s in fixture_scores)
    fp_rate = (total_unsupported / total_proposed) if total_proposed else None

    stance_total = sum(s.stance_total for s in scored)
    stance_correct = sum(s.stance_correct for s in scored)
    stance_acc = (stance_correct / stance_total) if stance_total else None

    # Amendment B2/B3 aggregates (over all fixture scores, like the other
    # proposed-row measures; failed fixtures contribute zeros).
    unset_matched = sum(s.stance_unset_matched for s in fixture_scores)
    unsupported_attempted = sum(s.unsupported_attempted for s in fixture_scores)
    unsupported_emitted = sum(s.unsupported_emitted for s in fixture_scores)
    unsupported_matched = sum(s.unsupported_matched for s in fixture_scores)
    unsupported_rate = (
        (unsupported_attempted / unsupported_matched) if unsupported_matched else None
    )
    all_row_scores: list[RowScore] = []
    for s in fixture_scores:
        all_row_scores.extend(s.row_scores)

    neg_total = sum(s.negation_total for s in scored)
    neg_preserved = sum(s.negation_preserved for s in scored)
    neg_rate = (neg_preserved / neg_total) if neg_total else None

    # Emitted exactness: verified on the emitted rows themselves (every emitted
    # row's quote must be an exact substring of its segment).
    emitted_exactness: float | None = None
    if emitted_validations is not None:
        segment_texts = segments if segments is not None else _SEGMENTS
        checked = 0
        passed = 0
        for fx_id, validation in emitted_validations.items():
            segment = segment_texts.get(fx_id, "")
            for row in validation.emitted:
                checked += 1
                if row.evidence_quote and row.evidence_quote in segment:
                    passed += 1
        emitted_exactness = (passed / checked) if checked else None

    def _rate(numer: int, denom: int) -> float | None:
        return (numer / denom) if denom else None

    proposed_exact = _rate(
        sum(s.exactness_passed_proposed for s in fixture_scores), total_proposed
    )
    proposed_attr = _rate(
        sum(s.attribution_passed_proposed for s in fixture_scores), total_proposed
    )
    proposed_support = _rate(
        sum(s.support_passed_proposed for s in fixture_scores), total_proposed
    )

    clean = sum(1 for s in fixture_scores if s.clean_parse and s.decode_ok)
    decodable = sum(1 for s in fixture_scores if s.decode_ok)
    clean_rate = _rate(clean, len(fixture_scores)) if fixture_scores else None
    post_repair = _rate(decodable, len(fixture_scores)) if fixture_scores else None

    dup = sum(s.duplicates_dropped for s in fixture_scores)
    dup_rate = _rate(dup, total_proposed)

    all_hits: list[ForbiddenHit] = []
    for s in fixture_scores:
        all_hits.extend(s.forbidden_hits)
    by_class: dict[str, int] = {}
    for h in all_hits:
        by_class[h.forbidden_class] = by_class.get(h.forbidden_class, 0) + 1

    # Gate leakage: forbidden hits among EMITTED rows only (must be zero).
    emitted_hits: list[ForbiddenHit] = []
    if emitted_validations is not None:
        for s in fixture_scores:
            validation = emitted_validations.get(s.fixture_id)
            if validation is None:
                continue
            fx = _FIXTURES.get(s.fixture_id)
            if fx is None:
                continue
            for row in validation.emitted:
                emitted_hits.extend(_forbidden_hits_for_row(row, fx, None))

    dropped_total = sum(sum(s.dropped_counts.values()) for s in fixture_scores)
    gate_rate = _rate(dropped_total, total_proposed)
    gate_by_reason: dict[str, int] = {}
    for s in fixture_scores:
        for reason, count in s.dropped_counts.items():
            gate_by_reason[reason] = gate_by_reason.get(reason, 0) + count

    failure_codes: dict[str, int] = {}
    for s in failed:
        if s.failure_code:
            failure_codes[s.failure_code] = failure_codes.get(s.failure_code, 0) + 1

    # Per-category breakdown.
    per_category: dict[str, dict[str, Any]] = {}
    for s in fixture_scores:
        cat = per_category.setdefault(
            s.category,
            {"fixtures": 0, "gold": 0, "recovered": 0, "forbidden_hits": 0, "failures": 0},
        )
        cat["fixtures"] += 1
        cat["gold"] += s.gold_count
        cat["recovered"] += s.recovered_count
        cat["forbidden_hits"] += len(s.forbidden_hits)
        cat["failures"] += 1 if s.failed else 0
    for cat in per_category.values():
        cat["recall"] = (
            (cat["recovered"] / cat["gold"]) if cat["gold"] else None
        )

    score = BenchmarkScore(
        variant=variant,
        candidate=candidate,
        fixtures_scored=len(fixture_scores),
        recall=recall,
        false_positive_rate=fp_rate,
        stance_accuracy=stance_acc,
        negation_preservation=neg_rate,
        emitted_exactness=emitted_exactness,
        proposed_exactness_rate=proposed_exact,
        proposed_attribution_rate=proposed_attr,
        proposed_support_rate=proposed_support,
        raw_json_clean_rate=clean_rate,
        post_repair_yield=post_repair,
        duplication_rate=dup_rate,
        forbidden_hits=all_hits,
        forbidden_by_class=by_class,
        forbidden_emitted=emitted_hits,
        gate_rejection_rate=gate_rate,
        gate_rejection_by_reason=gate_by_reason,
        honest_empties=sum(1 for s in fixture_scores if s.honest_empty),
        failures=len(failed),
        failure_codes=failure_codes,
        model_calls_total=sum(s.model_calls for s in fixture_scores),
        segments_resolved_deterministically=sum(
            1 for s in fixture_scores if s.model_calls == 0 and not s.failed
        ),
        operational=operational or {
            "latency": "not measured — no runtime data in this run",
            "memory_thermal": "not measured — no runtime data in this run",
            "cost": "not measured — no runtime data in this run",
        },
        per_category=per_category,
        thresholds=th,
        stance_unset_matched=unset_matched,
        unsupported_attempted=unsupported_attempted,
        unsupported_emitted=unsupported_emitted,
        unsupported_matched=unsupported_matched,
        unsupported_stance_rate=unsupported_rate,
        row_scores=all_row_scores,
    )

    # Pass rule (§7): all of measures 1-7 and R and the critical-error gate.
    # R is set by compare_runs afterwards; until then the pass rule is partial.
    pf: dict[str, bool | None] = {
        "recall": (recall is not None and recall >= th["recall"]),
        "false_positive_rate": (fp_rate is not None and fp_rate <= th["false_positive_rate"]),
        "stance_accuracy": (stance_acc is not None and stance_acc >= th["stance_accuracy"]),
        "negation_preservation": (neg_rate is not None and neg_rate >= th["negation_preservation"]),
        "emitted_exactness": (
            emitted_exactness is not None and emitted_exactness >= th["emitted_exactness"]
        ),
        "duplication": (dup_rate is not None and dup_rate <= th["duplication"]),
        "critical_error_gate": len(all_hits) == 0 and len(emitted_hits) == 0,
        # Amendment B6 gate term: no stance the model asserted on
        # stance-unset gold may survive the gate. A hard zero on the
        # EMITTED count only — attempted-but-dropped rows are reported,
        # not gated (the gate caught them). No threshold value changes.
        "unsupported_stance": unsupported_emitted == 0,
        "reproducibility": None,  # set by compare_runs
    }
    score.pass_fail = pf
    score.passed = None  # finalized by finalize_pass() once R is known
    return score


def finalize_pass(score: BenchmarkScore) -> BenchmarkScore:
    """Apply the reproducibility verdict and finalize the pass rule (§7).

    The pass rule requires ALL of measures 1-7 AND R AND the critical-error
    gate. Until R is measured (exactly 3 runs), the verdict stays UNDECIDED
    (``passed is None``) — a single run can never pass on its own.
    """
    r_struct = score.reproducibility_structural
    r_sem = score.reproducibility_semantic
    th = score.thresholds
    r_ok: bool | None = None
    if r_struct is not None and r_sem is not None:
        r_ok = (
            r_struct >= th["reproducibility_structural"]
            and r_sem >= th["reproducibility_semantic"]
        )
    score.pass_fail["reproducibility"] = r_ok
    if r_ok is None:
        score.passed = None
        return score
    checks = [v for v in score.pass_fail.values() if v is not None]
    score.passed = bool(checks) and all(checks)
    return score


# --- Reproducibility (measure R, §6.2) -------------------------------------
# compare_runs needs each fixture's segment text (for the emitted-exactness
# check) and fixture objects (for semantic matching). The runner registers
# them here; the harness never reads files at score time.
_SEGMENTS: dict[str, str] = {}
_FIXTURES: dict[str, Fixture] = {}


def register_fixture_context(fixture_set: Any) -> None:
    """Register fixture segments/objects for the emitted-exactness check."""
    _SEGMENTS.clear()
    _FIXTURES.clear()
    for fx in fixture_set.fixtures:
        _SEGMENTS[fx.id] = fx.segment
        _FIXTURES[fx.id] = fx


def _structural_key(row: ProposedRow, segment: str) -> tuple[Any, ...]:
    """Row structure: normalized text + stance + evidence reference + attribution.

    The normalized text is part of the structure: two runs that express the
    same proposition with different wording are semantically reproducible but
    NOT structurally reproducible. Exact row-set identity (the diagnostic)
    is stricter still: raw text + confidence must also match.
    """
    from local_ai.eval.wash.textutil import resolve_quote_speaker

    speaker, _ = resolve_quote_speaker(segment, row.evidence_quote)
    return (normalize_text(row.text), row.stance, row.evidence_quote, speaker)


def compare_runs(
    runs: list[dict[str, ValidationResult]],
    fixture_set: Any,
) -> dict[str, Any]:
    """Compare 3 runs of the same fixtures (measure R, §6.2, §6.4).

    Returns per-fixture and aggregate structural / semantic reproducibility
    plus exact row-set identity as a diagnostic only. A fixture with a failed
    run fails both reproducibility measures for that fixture.
    """
    if len(runs) != 3:
        raise ValueError(f"reproducibility requires exactly 3 runs, got {len(runs)}")
    register_fixture_context(fixture_set)
    per_fixture: dict[str, dict[str, bool]] = {}
    for fx in fixture_set.fixtures:
        validations = [run.get(fx.id) for run in runs]
        if any(v is None or v.failure is not None for v in validations):
            per_fixture[fx.id] = {
                "structural": False,
                "semantic": False,
                "exact_identity": False,
            }
            continue
        keys = [
            sorted(_structural_key(r, fx.segment) for r in v.emitted)  # type: ignore[union-attr]
            for v in validations
        ]
        structural = keys[0] == keys[1] == keys[2]
        # Semantic: the same supported propositions (gold ids) in every run.
        gold_sets = []
        for v in validations:
            matched: set[str] = set()
            for row in v.emitted:  # type: ignore[union-attr]
                gold = _row_matches_gold(row, fx)
                if gold is not None:
                    matched.add(gold.text)
            gold_sets.append(matched)
        semantic = gold_sets[0] == gold_sets[1] == gold_sets[2]
        exact = (
            [tuple(sorted((r.text, r.stance, r.evidence_quote, r.confidence) for r in v.emitted))  # type: ignore[union-attr]
             for v in validations]
        )
        exact_identity = exact[0] == exact[1] == exact[2]
        per_fixture[fx.id] = {
            "structural": structural,
            "semantic": semantic,
            "exact_identity": exact_identity,
        }
    n = len(per_fixture) or 1
    return {
        "per_fixture": per_fixture,
        "structural": sum(1 for v in per_fixture.values() if v["structural"]) / n,
        "semantic": sum(1 for v in per_fixture.values() if v["semantic"]) / n,
        "exact_identity": sum(1 for v in per_fixture.values() if v["exact_identity"]) / n,
    }


def variant_check(
    score: BenchmarkScore,
) -> tuple[bool, list[str]]:
    """Skip-variant fail rule (§4.3, §8): the variant FAILS on commitment
    reversals or certainty upgrades even if aggregate recall passes.

    Applies to ``skip-enabled`` runs only; model-on runs always pass this
    check (it is a variant rule, not a default-v1 rule).
    """
    if score.variant != "skip-enabled":
        return True, []
    reasons: list[str] = []
    for fclass in ("commitment_inflation", "certainty_upgrade"):
        count = score.forbidden_by_class.get(fclass, 0)
        if count:
            reasons.append(
                f"variant failed: {count} {fclass} critical error(s) — "
                "the skip variant fails on commitment reversals or certainty "
                "upgrades even if aggregate recall passes (§4.3)"
            )
    return (not reasons), reasons


__all__ = [
    "DEFAULT_THRESHOLDS",
    "ForbiddenHit",
    "RowScore",
    "FixtureScore",
    "BenchmarkScore",
    "score_fixture",
    "aggregate_scores",
    "finalize_pass",
    "compare_runs",
    "variant_check",
    "register_fixture_context",
]
