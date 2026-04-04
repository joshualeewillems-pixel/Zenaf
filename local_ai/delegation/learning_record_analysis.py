"""
Evidence-first breakdowns for cleaned LearningRecord JSONL (one object per line).

No ML, no dashboards — notebook- or CLI-friendly aggregates for prompt/validator prioritization.
"""

from __future__ import annotations

import json
import math
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Mapping, Sequence


def outcome_label(r: Mapping[str, Any]) -> str:
    u = r.get("user_outcome")
    if u is None or u == "":
        return "none"
    return str(u).strip().lower()


def load_cleaned_jsonl(path: Path | str) -> list[dict[str, Any]]:
    """Load newline-delimited JSON; skip blank lines; raise on first invalid JSON."""
    p = Path(path)
    rows: list[dict[str, Any]] = []
    with open(p, encoding="utf-8-sig") as f:
        for i, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
            except json.JSONDecodeError as e:
                raise ValueError(f"{p}: line {i}: invalid JSON ({e})") from e
            if not isinstance(d, dict):
                raise ValueError(f"{p}: line {i}: expected JSON object")
            rows.append(d)
    return rows


def _intent(r: Mapping[str, Any]) -> str:
    return str(r.get("action_intent") or "unknown").strip() or "unknown"


def _surface(r: Mapping[str, Any]) -> str:
    return str(r.get("surface") or "unknown").strip() or "unknown"


def _capture(r: Mapping[str, Any]) -> str:
    return str(r.get("capture_mode") or "unknown").strip() or "unknown"


def _provider_model_key(r: Mapping[str, Any]) -> tuple[str, str]:
    pu = r.get("provider_used")
    mu = r.get("model_used")
    p = "null" if pu in (None, "") else str(pu).strip()
    m = "null" if mu in (None, "") else str(mu).strip()
    return p, m


def validation_failure_rate_by_action_intent(
    rows: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """
    Per ``action_intent``: counts and failure rate among rows with known pass/fail.

    ``failure_rate`` is ``fails / (passes + fails)`` when denominator > 0; else ``null``.
    """
    by_int: dict[str, dict[str, int]] = defaultdict(
        lambda: {"n": 0, "pass_true": 0, "pass_false": 0, "pass_other": 0}
    )
    for r in rows:
        ai = _intent(r)
        by_int[ai]["n"] += 1
        v = r.get("validation_passed")
        if v is True:
            by_int[ai]["pass_true"] += 1
        elif v is False:
            by_int[ai]["pass_false"] += 1
        else:
            by_int[ai]["pass_other"] += 1

    out: list[dict[str, Any]] = []
    for intent, c in sorted(by_int.items(), key=lambda kv: (-kv[1]["n"], kv[0])):
        denom = c["pass_true"] + c["pass_false"]
        rate = (c["pass_false"] / denom) if denom > 0 else None
        out.append(
            {
                "action_intent": intent,
                "n": c["n"],
                "validation_passed_true": c["pass_true"],
                "validation_passed_false": c["pass_false"],
                "validation_other_or_missing": c["pass_other"],
                "failure_rate_among_labeled": round(rate, 4) if rate is not None else None,
            }
        )
    return out


def user_outcome_distribution_by_action_intent(
    rows: Sequence[Mapping[str, Any]],
) -> dict[str, dict[str, int]]:
    nested: dict[str, Counter[str]] = defaultdict(Counter)
    for r in rows:
        nested[_intent(r)][outcome_label(r)] += 1
    return {k: dict(sorted(v.items(), key=lambda x: (-x[1], x[0]))) for k, v in sorted(nested.items())}


def user_outcome_distribution_by_surface(
    rows: Sequence[Mapping[str, Any]],
) -> dict[str, dict[str, int]]:
    nested: dict[str, Counter[str]] = defaultdict(Counter)
    for r in rows:
        nested[_surface(r)][outcome_label(r)] += 1
    return {k: dict(sorted(v.items(), key=lambda x: (-x[1], x[0]))) for k, v in sorted(nested.items())}


def capture_mode_distribution_by_action_intent(
    rows: Sequence[Mapping[str, Any]],
) -> dict[str, dict[str, int]]:
    nested: dict[str, Counter[str]] = defaultdict(Counter)
    for r in rows:
        nested[_intent(r)][_capture(r)] += 1
    return {k: dict(sorted(v.items(), key=lambda x: (-x[1], x[0]))) for k, v in sorted(nested.items())}


def _intent_validation_stats(rows: Sequence[Mapping[str, Any]], intent: str) -> tuple[int, int, int]:
    pt = pf = 0
    for r in rows:
        if _intent(r) != intent:
            continue
        v = r.get("validation_passed")
        if v is True:
            pt += 1
        elif v is False:
            pf += 1
    return pt, pf, pt + pf


def _failure_rate(pt: int, pf: int) -> float | None:
    d = pt + pf
    return (pf / d) if d > 0 else None


def pick_high_failure_intents(
    rows: Sequence[Mapping[str, Any]],
    *,
    min_labeled: int = 5,
    top_k: int = 5,
) -> list[str]:
    intents = {_intent(r) for r in rows}
    ranked: list[tuple[float, str]] = []
    for ai in intents:
        pt, pf, denom = _intent_validation_stats(rows, ai)
        if denom < min_labeled or pf < 1:
            continue
        fr = _failure_rate(pt, pf)
        if fr is None:
            continue
        ranked.append((fr, ai))
    ranked.sort(key=lambda x: (-x[0], x[1]))
    return [ai for _, ai in ranked[:top_k]]


def pick_high_success_intents(
    rows: Sequence[Mapping[str, Any]],
    *,
    min_labeled: int = 8,
    top_k: int = 5,
    max_failure_rate: float = 0.15,
) -> list[str]:
    """Intents with enough labeled rows and low failure rate (validator-stable)."""
    intents = {_intent(r) for r in rows}
    ranked: list[tuple[float, str]] = []
    for ai in intents:
        pt, pf, denom = _intent_validation_stats(rows, ai)
        if denom < min_labeled or pt < 1:
            continue
        fr = _failure_rate(pt, pf)
        if fr is None or fr > max_failure_rate:
            continue
        ranked.append((fr, ai))
    ranked.sort(key=lambda x: (x[0], -_intent_volume(rows, x[1]), x[1]))
    return [ai for _, ai in ranked[:top_k]]


def _intent_volume(rows: Sequence[Mapping[str, Any]], intent: str) -> int:
    return sum(1 for r in rows if _intent(r) == intent)


def provider_model_breakdown_for_intents(
    rows: Sequence[Mapping[str, Any]],
    intents: Sequence[str],
) -> dict[str, Any]:
    """Nested provider -> model counts for rows whose action_intent is in ``intents``."""
    want = frozenset(intents)
    prov_model: Counter[tuple[str, str]] = Counter()
    for r in rows:
        if _intent(r) not in want:
            continue
        prov_model[_provider_model_key(r)] += 1
    by_prov: dict[str, Counter[str]] = defaultdict(Counter)
    for (p, m), n in prov_model.items():
        by_prov[p][m] += n
    return {
        "intents": list(want),
        "provider_model_counts": {
            p: dict(sorted(c.items(), key=lambda x: (-x[1], x[0])))
            for p, c in sorted(by_prov.items(), key=lambda x: str(x[0]))
        },
    }


def _surface_stats(rows: Sequence[Mapping[str, Any]], surface: str) -> dict[str, Any]:
    sub = [r for r in rows if _surface(r) == surface]
    n = len(sub)
    pt = sum(1 for r in sub if r.get("validation_passed") is True)
    pf = sum(1 for r in sub if r.get("validation_passed") is False)
    denom = pt + pf
    fr = (pf / denom) if denom > 0 else None
    oc = Counter(outcome_label(r) for r in sub)
    non_none = n - oc.get("none", 0)
    distinct_non_none = len([k for k in oc if k != "none" and oc[k] > 0])
    full = sum(1 for r in sub if _capture(r) == "full")
    return {
        "surface": surface,
        "n": n,
        "validation_passed_true": pt,
        "validation_passed_false": pf,
        "failure_rate_among_labeled": round(fr, 4) if fr is not None else None,
        "user_outcome_counts": dict(sorted(oc.items(), key=lambda x: (-x[1], x[0]))),
        "non_none_outcome_rows": non_none,
        "distinct_non_none_outcome_types": distinct_non_none,
        "capture_full_rows": full,
        "capture_full_share": round(full / n, 4) if n else None,
    }


def recommend_surfaces_for_tuning(
    rows: Sequence[Mapping[str, Any]],
    *,
    min_volume: int = 5,
    top_recommendations: int = 2,
) -> list[dict[str, Any]]:
    """
    Heuristic ranking: volume × failure pain + mixed real-world outcomes.

    Returns sorted list of dicts with ``surface``, ``priority_score``, ``rationale`` (list of str).
    """
    surfaces = {_surface(r) for r in rows}
    stats = [_surface_stats(rows, s) for s in surfaces]
    scored: list[dict[str, Any]] = []
    for st in stats:
        if st["n"] < min_volume:
            continue
        n = st["n"]
        fr = st["failure_rate_among_labeled"]
        fr_term = (fr if fr is not None else 0.0) * math.log1p(n)
        non_none = st["non_none_outcome_rows"]
        mix_term = (non_none / n) * (1.2 if st["distinct_non_none_outcome_types"] >= 2 else 0.6)
        score = fr_term + 0.35 * mix_term * math.log1p(n)
        rationale: list[str] = []
        if st["n"] >= min_volume * 3:
            rationale.append(f"high volume (n={n})")
        if fr is not None and fr >= 0.2:
            rationale.append(f"elevated validation failure rate ({fr:.0%} among labeled)")
        elif fr is not None and fr >= 0.08:
            rationale.append(f"non-trivial validation failures ({fr:.0%} among labeled)")
        if non_none > 0 and st["distinct_non_none_outcome_types"] >= 2:
            rationale.append("mixed user outcomes (suggests real disagreement / friction)")
        elif non_none > 0:
            rationale.append("some user-reported outcomes (not all unlabeled)")
        if st["capture_full_share"] is not None and st["capture_full_share"] < 0.25:
            rationale.append("mostly minimal capture_mode - limited text signal for deep tuning")
        if not rationale:
            rationale.append("meets minimum volume for review")
        scored.append({**st, "priority_score": round(score, 4), "rationale": rationale})
    scored.sort(key=lambda x: (-x["priority_score"], -x["n"], x["surface"]))
    return scored[:top_recommendations]


def assess_distillation_pilot_readiness(
    rows: Sequence[Mapping[str, Any]],
    *,
    min_total: int = 200,
    min_full_share: float = 0.25,
    min_non_none_outcome_share: float = 0.08,
) -> dict[str, Any]:
    """
    Narrow pilot only: conservative gates on volume, full captures, and outcome labels.
    """
    n = len(rows)
    full = sum(1 for r in rows if _capture(r) == "full")
    non_none = sum(1 for r in rows if outcome_label(r) != "none")
    full_share = full / n if n else 0.0
    out_share = non_none / n if n else 0.0
    reasons: list[str] = []
    ok = True
    if n < min_total:
        ok = False
        reasons.append(f"total_rows={n} < suggested minimum {min_total} for any pilot")
    if full_share < min_full_share:
        ok = False
        reasons.append(
            f"capture_mode full share {full_share:.1%} < {min_full_share:.0%} - minimal rows dominate"
        )
    if out_share < min_non_none_outcome_share:
        ok = False
        reasons.append(
            f"user_outcome labeled share {out_share:.1%} < {min_non_none_outcome_share:.0%} - weak supervision"
        )
    if ok:
        reasons.append(
            "Meets coarse gates for a **very narrow** distillation experiment (single surface/model); "
            "still run human review on redacted payloads."
        )
    return {
        "narrow_pilot_recommended": ok,
        "total_rows": n,
        "capture_full_rows": full,
        "capture_full_share": round(full_share, 4),
        "user_outcome_non_none_rows": non_none,
        "user_outcome_non_none_share": round(out_share, 4),
        "reasons": reasons,
    }


def run_full_analysis(
    rows: Sequence[Mapping[str, Any]],
    *,
    min_volume_surface: int = 5,
    min_labeled_intent: int = 5,
    top_intents: int = 5,
) -> dict[str, Any]:
    hf = pick_high_failure_intents(rows, min_labeled=min_labeled_intent, top_k=top_intents)
    hs = pick_high_success_intents(rows, min_labeled=max(8, min_labeled_intent + 3), top_k=top_intents)
    return {
        "meta": {"total_rows": len(rows)},
        "validation_failure_rate_by_action_intent": validation_failure_rate_by_action_intent(rows),
        "user_outcome_by_action_intent": user_outcome_distribution_by_action_intent(rows),
        "user_outcome_by_surface": user_outcome_distribution_by_surface(rows),
        "capture_mode_by_action_intent": capture_mode_distribution_by_action_intent(rows),
        "high_failure_action_intents": hf,
        "high_success_action_intents": hs,
        "provider_model_breakdown_high_failure_intents": provider_model_breakdown_for_intents(rows, hf),
        "provider_model_breakdown_high_success_intents": provider_model_breakdown_for_intents(rows, hs),
        "recommended_surfaces": recommend_surfaces_for_tuning(
            rows, min_volume=min_volume_surface, top_recommendations=2
        ),
        "distillation_readiness": assess_distillation_pilot_readiness(rows),
    }


def format_analysis_report(analysis: Mapping[str, Any]) -> str:
    """Plain-text report for CLI / notebooks."""
    lines: list[str] = []
    m = analysis["meta"]
    lines.append("=== LearningRecord analysis (cleaned JSONL) ===")
    lines.append(f"Total rows: {m['total_rows']}")
    lines.append("")

    lines.append("-- Validation failure rate by action_intent --")
    for row in analysis["validation_failure_rate_by_action_intent"][:25]:
        rate = row["failure_rate_among_labeled"]
        rtxt = f"{rate:.1%}" if rate is not None else "n/a (no pass/fail)"
        lines.append(
            f"  {row['action_intent']}: n={row['n']} fail={row['validation_passed_false']} "
            f"pass={row['validation_passed_true']} other={row['validation_other_or_missing']} "
            f"failure_rate(labeled)={rtxt}"
        )
    if len(analysis["validation_failure_rate_by_action_intent"]) > 25:
        lines.append(f"  ... ({len(analysis['validation_failure_rate_by_action_intent'])} intents total)")
    lines.append("")

    lines.append("-- User outcome by action_intent --")
    for intent, dist in list(analysis["user_outcome_by_action_intent"].items())[:20]:
        lines.append(f"  {intent}: {dist}")
    lines.append("")

    lines.append("-- User outcome by surface --")
    for surf, dist in list(analysis["user_outcome_by_surface"].items())[:20]:
        lines.append(f"  {surf}: {dist}")
    lines.append("")

    lines.append("-- capture_mode by action_intent --")
    for intent, dist in list(analysis["capture_mode_by_action_intent"].items())[:20]:
        lines.append(f"  {intent}: {dist}")
    lines.append("")

    lines.append("-- High-failure action_intents (for provider/model lens) --")
    lines.append(f"  {analysis['high_failure_action_intents']}")
    lines.append("  Provider -> model counts:")
    pm = analysis["provider_model_breakdown_high_failure_intents"]["provider_model_counts"]
    for prov, models in pm.items():
        lines.append(f"    {prov}: {models}")
    lines.append("")

    lines.append("-- High-success action_intents (for provider/model lens) --")
    lines.append(f"  {analysis['high_success_action_intents']}")
    pm2 = analysis["provider_model_breakdown_high_success_intents"]["provider_model_counts"]
    for prov, models in pm2.items():
        lines.append(f"    {prov}: {models}")
    lines.append("")

    lines.append("-- Recommended surfaces (1-2 highest-leverage prompt/validator targets) --")
    for i, rec in enumerate(analysis["recommended_surfaces"], start=1):
        lines.append(f"  {i}. {rec['surface']} (priority_score={rec['priority_score']}, n={rec['n']})")
        for r in rec["rationale"]:
            lines.append(f"      - {r}")
    if not analysis["recommended_surfaces"]:
        lines.append("  (no surface met min_volume - collect more rows or lower min_volume)")
    lines.append("")

    dr = analysis["distillation_readiness"]
    lines.append("-- Distillation pilot (narrow, conservative) --")
    lines.append(f"  sufficient: {dr['narrow_pilot_recommended']}")
    for r in dr["reasons"]:
        lines.append(f"  - {r}")
    lines.append("")
    return "\n".join(lines)
