"""Report generator for the wash benchmark harness (design §8).

Produces per-candidate, per-measure results with the 3-run spread, tagged
with both contract versions. Two outputs:

- a JSON report (machine-readable, complete);
- a markdown summary (human-readable: measure table, per-category breakdown,
  forbidden hits, variant section, gate counts, and the gating footer).

The report always states what is NOT yet decided: gold labels are DRAFT
(founder approval pending, §8.1), thresholds are PROVISIONAL (§7), and no
benchmark run against a live model has been authorized or executed by this
harness build.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from local_ai.eval.wash import (
    EXTRACTION_VERSION,
    FIXTURE_SET_VERSION,
    GOLD_LABEL_VERSION,
    HARNESS_VERSION,
    SEMANTIC_VERSION,
)
from local_ai.eval.wash.measures import BenchmarkScore


def _fmt(value: float | None, digits: int = 3) -> str:
    if value is None:
        return "n/a"
    return f"{value:.{digits}f}"


def build_report(
    score: BenchmarkScore,
    *,
    manifest: dict[str, Any] | None = None,
    reproducibility: dict[str, Any] | None = None,
    variant_check: tuple[bool, list[str]] | None = None,
) -> dict[str, Any]:
    """Build the JSON report dict for one scored candidate + variant."""
    if reproducibility is not None:
        score.reproducibility_structural = reproducibility.get("structural")
        score.reproducibility_semantic = reproducibility.get("semantic")
        score.reproducibility_exact_identity = reproducibility.get("exact_identity")
    from local_ai.eval.wash.measures import finalize_pass

    finalize_pass(score)

    report: dict[str, Any] = {
        "harness_version": HARNESS_VERSION,
        "semantic_contract_version": SEMANTIC_VERSION,
        "extraction_version": EXTRACTION_VERSION,
        "fixture_set_version": FIXTURE_SET_VERSION,
        "gold_label_version": GOLD_LABEL_VERSION,
        "gold_label_status": "DRAFT — founder approval required before any benchmark run (§8.1)",
        "threshold_status": "PROVISIONAL — founder approves final thresholds before any run (§7)",
        "variant": score.variant,
        "candidate": score.candidate,
        "fixtures_scored": score.fixtures_scored,
        "passed": score.passed,
        "pass_fail": score.pass_fail,
        "measures": {
            "recall": score.recall,
            "false_positive_rate": score.false_positive_rate,
            "stance_accuracy": score.stance_accuracy,
            "negation_preservation": score.negation_preservation,
            "emitted_exactness": score.emitted_exactness,
            "proposed_exactness_rate": score.proposed_exactness_rate,
            "proposed_attribution_rate": score.proposed_attribution_rate,
            "proposed_support_rate": score.proposed_support_rate,
            "raw_json_clean_rate": score.raw_json_clean_rate,
            "post_repair_yield": score.post_repair_yield,
            "duplication_rate": score.duplication_rate,
            "gate_rejection_rate": score.gate_rejection_rate,
            "gate_rejection_by_reason": score.gate_rejection_by_reason,
            "reproducibility_structural": score.reproducibility_structural,
            "reproducibility_semantic": score.reproducibility_semantic,
            "reproducibility_exact_identity_diagnostic": score.reproducibility_exact_identity,
            "model_calls_total": score.model_calls_total,
            "segments_resolved_deterministically": score.segments_resolved_deterministically,
            "honest_empties": score.honest_empties,
            "failures": score.failures,
            "failure_codes": score.failure_codes,
            "operational": score.operational,
        },
        "critical_errors": {
            "total": len(score.forbidden_hits),
            "by_class": score.forbidden_by_class,
            "gate": "zero critical errors (proposed, §7)",
            "emitted_leakage": len(score.forbidden_emitted),
            "hits": [
                {
                    "fixture_id": h.fixture_id,
                    "class": h.forbidden_class,
                    "text": h.text,
                    "detail": h.detail,
                }
                for h in score.forbidden_hits
            ],
        },
        "per_category": score.per_category,
        "thresholds_applied": score.thresholds,
    }
    if manifest is not None:
        report["manifest"] = manifest
    if variant_check is not None:
        passed, reasons = variant_check
        report["variant_check"] = {"passed": passed, "reasons": reasons}
    return report


def render_markdown(report: dict[str, Any]) -> str:
    """Render the JSON report as a human-readable markdown summary."""
    m = report["measures"]
    lines: list[str] = []
    lines.append("# Wash benchmark report")
    lines.append("")
    lines.append(
        f"Candidate: **{report['candidate'] or 'none (harness self-proof)'}** · "
        f"Variant: **{report['variant']}** · "
        f"Fixtures scored: **{report['fixtures_scored']}**"
    )
    lines.append(
        f"Contract: wash-semantic {report['semantic_contract_version']} / "
        f"wash-extraction {report['extraction_version']} · "
        f"Fixture set {report['fixture_set_version']} "
        f"(gold labels **{report['gold_label_status'].split(' — ')[0]}**)"
    )
    passed = report["passed"]
    lines.append(f"**Overall: {'PASS' if passed else 'FAIL' if passed is False else 'UNDECIDED (reproducibility not yet measured)'}**")
    lines.append("")
    lines.append("## Measures")
    lines.append("")
    lines.append("| Measure | Value | Threshold | Verdict |")
    lines.append("|---|---|---|---|")
    th = report["thresholds_applied"]
    rows = [
        ("1 Evidence recall", m["recall"], th["recall"], ">="),
        ("2 False-positive rate", m["false_positive_rate"], th["false_positive_rate"], "<="),
        ("3 Stance accuracy", m["stance_accuracy"], th["stance_accuracy"], ">="),
        ("4 Negation preservation", m["negation_preservation"], th["negation_preservation"], ">="),
        ("5 Emitted exactness", m["emitted_exactness"], th["emitted_exactness"], ">="),
        ("6 Raw JSON clean (diagnostic)", m["raw_json_clean_rate"], th["raw_json_clean"], ">="),
        ("7 Duplication", m["duplication_rate"], th["duplication"], "<="),
        ("R Structural reproducibility", m["reproducibility_structural"], th["reproducibility_structural"], ">="),
        ("R Semantic reproducibility", m["reproducibility_semantic"], th["reproducibility_semantic"], ">="),
    ]
    pf = report["pass_fail"]
    pf_keys = [
        "recall", "false_positive_rate", "stance_accuracy", "negation_preservation",
        "emitted_exactness", None, "duplication", "reproducibility", "reproducibility",
    ]
    for (name, value, threshold, op), key in zip(rows, pf_keys):
        verdict = ""
        if key is not None:
            v = pf.get(key)
            verdict = "pass" if v is True else ("fail" if v is False else "n/a")
        lines.append(f"| {name} | {_fmt(value)} | {op} {_fmt(threshold)} | {verdict} |")
    lines.append(f"| F Critical errors | {report['critical_errors']['total']} | 0 | {'pass' if report['critical_errors']['total'] == 0 else 'fail'} |")
    lines.append(f"| F Emitted leakage | {report['critical_errors']['emitted_leakage']} | 0 | {'pass' if report['critical_errors']['emitted_leakage'] == 0 else 'fail'} |")
    lines.append(f"| G Gate-rejection rate | {_fmt(m['gate_rejection_rate'])} | reported, no threshold | — |")
    lines.append(f"| M Model calls | {m['model_calls_total']} | reported, no threshold | — |")
    lines.append("")
    lines.append(f"Proposed-row sub-checks: exactness {_fmt(m['proposed_exactness_rate'])}, "
                 f"attribution {_fmt(m['proposed_attribution_rate'])}, "
                 f"support {_fmt(m['proposed_support_rate'])}.")
    lines.append(f"Gate rejections by reason: {m['gate_rejection_by_reason'] or 'none'}.")
    lines.append(f"Honest empties: {m['honest_empties']} · Failures: {m['failures']} "
                 f"{m['failure_codes'] or ''} · Post-repair yield: {_fmt(m['post_repair_yield'])}.")
    lines.append(f"Operational: latency {m['operational'].get('latency')}; "
                 f"memory/thermal {m['operational'].get('memory_thermal')}; "
                 f"cost {m['operational'].get('cost')}.")
    lines.append("")
    if report["critical_errors"]["hits"]:
        lines.append("## Critical errors")
        lines.append("")
        for h in report["critical_errors"]["hits"]:
            lines.append(f"- **{h['fixture_id']}** [{h['class']}] {h['text']} — {h['detail']}")
        lines.append("")
    lines.append("## Per-category")
    lines.append("")
    for cat, vals in report["per_category"].items():
        lines.append(
            f"- **{cat}**: {vals['fixtures']} fixtures, "
            f"recall {_fmt(vals.get('recall'))}, "
            f"{vals['forbidden_hits']} critical error(s), {vals['failures']} failure(s)"
        )
    lines.append("")
    vc = report.get("variant_check")
    if vc is not None:
        lines.append("## Variant check")
        lines.append("")
        lines.append(f"Passed: **{vc['passed']}**")
        for reason in vc["reasons"]:
            lines.append(f"- {reason}")
        lines.append("")
    lines.append("## Still gated")
    lines.append("")
    lines.append("- Gold labels are DRAFT: frozen labels need founder approval (§8.1).")
    lines.append("- Thresholds are PROVISIONAL: final thresholds need founder approval (§7).")
    lines.append("- No benchmark run against a live model has been authorized or executed.")
    lines.append("")
    return "\n".join(lines)


def write_report(path: str | Path, report: dict[str, Any]) -> Path:
    """Write the JSON report. Returns the path written."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def write_markdown(path: str | Path, report: dict[str, Any]) -> Path:
    """Write the markdown summary. Returns the path written."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_markdown(report), encoding="utf-8")
    return path


__all__ = ["build_report", "render_markdown", "write_report", "write_markdown"]
