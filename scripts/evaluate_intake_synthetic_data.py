#!/usr/bin/env python3
"""
Evaluate intake pipeline against the synthetic dataset.

Loads datasets/intake_synthetic_cases.json (or --dataset path), runs each case
through local_ai.intake.pipeline.run_pipeline, compares actual vs expected
category and lane. Prints summary stats, mismatches by lane/category, and
optionally reason codes / confidence for failures.

Usage (from repo root):
  python scripts/evaluate_intake_synthetic_data.py
  python scripts/evaluate_intake_synthetic_data.py --dataset datasets/intake_synthetic_cases.json --show-reasons
  python scripts/evaluate_intake_synthetic_data.py --export-failures [path]
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from local_ai.intake.pipeline import run_pipeline
from local_ai.judgment import get_record


def main() -> None:
    ap = argparse.ArgumentParser(description="Evaluate intake pipeline on synthetic dataset")
    ap.add_argument("--dataset", type=str, default=str(ROOT / "datasets" / "intake_synthetic_cases.json"), help="Path to JSON dataset")
    ap.add_argument("--show-reasons", action="store_true", help="Show reason codes and confidence for mismatches")
    ap.add_argument("--limit", type=int, default=0, help="Limit number of cases (0 = all)")
    ap.add_argument("--export-failures", nargs="?", const="", default=None, metavar="PATH", help="Write mismatches to a JSON file (default: datasets/intake_synthetic_failures.json)")
    args = ap.parse_args()
    path = Path(args.dataset)
    if not path.is_file():
        print(f"Dataset not found: {path}", file=sys.stderr)
        sys.exit(1)
    with open(path, encoding="utf-8") as f:
        cases = json.load(f)
    if args.limit:
        cases = cases[: args.limit]
    total = len(cases)
    category_ok = 0
    lane_ok = 0
    both_ok = 0
    mismatches: list[dict] = []
    by_expected_lane: dict[str, dict[str, int]] = defaultdict(lambda: {"ok": 0, "wrong_lane": 0, "wrong_category": 0})
    by_expected_category: dict[str, dict[str, int]] = defaultdict(lambda: {"ok": 0, "wrong_lane": 0, "wrong_category": 0})
    for c in cases:
        case_id = c.get("id", 0)
        subject = c.get("subject", "")
        body = c.get("body", "")
        expected_cat = c.get("expected_category", "")
        expected_lane = c.get("expected_lane", "")
        item = run_pipeline(body, "email", subject=subject or None)
        actual_cat = item.category
        actual_lane = item.lane
        cat_match = actual_cat == expected_cat
        lane_match = actual_lane == expected_lane
        if cat_match:
            category_ok += 1
        if lane_match:
            lane_ok += 1
        if cat_match and lane_match:
            both_ok += 1
        by_expected_lane[expected_lane]["ok" if lane_match else "wrong_lane"] += 1
        by_expected_category[expected_cat]["ok" if cat_match else "wrong_category"] += 1
        if not cat_match or not lane_match:
            rec = {
                "id": case_id,
                "difficulty": c.get("difficulty", ""),
                "subject": subject[:60],
                "expected_category": expected_cat,
                "actual_category": actual_cat,
                "expected_lane": expected_lane,
                "actual_lane": actual_lane,
                "confidence": item.confidence,
            }
            if args.show_reasons and item.judgment_id:
                j = get_record(item.judgment_id)
                if j:
                    rec["signal_codes"] = j.signal_codes
                    rec["interpretation_codes"] = j.interpretation_codes
                    rec["policy_codes"] = j.policy_codes
            # For export: include all case + pipeline + judgment fields for manual review
            if args.export_failures is not None:
                rec = {
                    "id": case_id,
                    "subject": subject,
                    "body": body,
                    "expected_category": expected_cat,
                    "expected_lane": expected_lane,
                    "actual_category": actual_cat,
                    "actual_lane": actual_lane,
                    "difficulty": c.get("difficulty", ""),
                    "confidence": item.confidence,
                    "confidence_display": item.confidence_display,
                    "summary": item.summary,
                    "suggested_action": item.suggested_action,
                    "priority": item.priority,
                    "judgment_id": item.judgment_id or "",
                }
                for k, v in c.items():
                    if k not in rec and k not in ("subject", "body", "expected_category", "expected_lane"):
                        rec[f"case_{k}"] = v
                if item.judgment_id:
                    j = get_record(item.judgment_id)
                    if j:
                        rec["signal_codes"] = getattr(j, "signal_codes", []) or []
                        rec["interpretation_codes"] = getattr(j, "interpretation_codes", []) or []
                        rec["policy_codes"] = getattr(j, "policy_codes", []) or []
                        rec["observation_ref"] = getattr(j, "observation_ref", None)
                mismatches.append(rec)
            else:
                mismatches.append(rec)
    # Summary
    print("=== Summary ===")
    print(f"Total cases: {total}")
    print(f"Category match: {category_ok} / {total} ({100 * category_ok / total:.1f}%)")
    print(f"Lane match:     {lane_ok} / {total} ({100 * lane_ok / total:.1f}%)")
    print(f"Both match:     {both_ok} / {total} ({100 * both_ok / total:.1f}%)")
    print(f"Mismatches:     {len(mismatches)}")
    # By expected lane
    print("\n=== By expected lane ===")
    for lane in ["needs_attention", "insurance_medical", "ordering_supplies", "waiting_fyi", "likely_junk"]:
        if lane not in by_expected_lane:
            continue
        d = by_expected_lane[lane]
        ok = d["ok"]
        wrong = d["wrong_lane"]
        print(f"  {lane}: ok={ok}, wrong_lane={wrong}")
    # By expected category
    print("\n=== By expected category ===")
    for cat in sorted(by_expected_category.keys()):
        d = by_expected_category[cat]
        ok = d["ok"]
        wrong = d["wrong_category"]
        print(f"  {cat}: ok={ok}, wrong_category={wrong}")
    # Mismatches grouped by expected_lane then expected_category
    print("\n=== Mismatches by expected lane/category ===")
    by_mismatch: dict[str, list[dict]] = defaultdict(list)
    for m in mismatches:
        key = f"{m['expected_lane']} / {m['expected_category']}"
        by_mismatch[key].append(m)
    for key in sorted(by_mismatch.keys()):
        list_ = by_mismatch[key]
        print(f"\n  {key} ({len(list_)} mismatches)")
        for m in list_[:5]:
            print(f"    id={m['id']} difficulty={m['difficulty']} sub={m['subject']!r}")
            print(f"      expected cat={m['expected_category']} lane={m['expected_lane']} -> actual cat={m['actual_category']} lane={m['actual_lane']} conf={m.get('confidence', 0):.2f}")
            if args.show_reasons:
                if m.get("signal_codes"):
                    print(f"      signal_codes: {m['signal_codes']}")
                if m.get("interpretation_codes"):
                    print(f"      interpretation_codes: {m['interpretation_codes']}")
                if m.get("policy_codes"):
                    print(f"      policy_codes: {m['policy_codes']}")
        if len(list_) > 5:
            print(f"    ... and {len(list_) - 5} more")
    if args.export_failures is not None:
        out_path = Path(args.export_failures) if args.export_failures else ROOT / "datasets" / "intake_synthetic_failures.json"
        out_path = out_path.resolve()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(mismatches, f, indent=2, ensure_ascii=False)
        print(f"\nExported {len(mismatches)} failures to {out_path}")
    sys.exit(0 if both_ok == total else 1)

if __name__ == "__main__":
    main()
