#!/usr/bin/env python3
"""
Evidence-first analysis on **cleaned** LearningRecord JSONL (e.g. from zenaf_learning_jsonl_prep.py).

Reports validation and outcome breakdowns by action_intent / surface, provider/model slices for
high-failure vs high-success intents, heuristic surface recommendations, and a coarse distillation check.

Run from repo root:

  python scripts/zenaf_learning_analysis.py data/learning_clean.jsonl
  python scripts/zenaf_learning_analysis.py data/learning_clean.jsonl --json-out analysis.json -q

Library: local_ai.delegation.learning_record_analysis
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from local_ai.delegation.learning_record_analysis import (
    format_analysis_report,
    load_cleaned_jsonl,
    run_full_analysis,
)


def main() -> int:
    p = argparse.ArgumentParser(description="Analyze cleaned LearningRecord JSONL.")
    p.add_argument("cleaned_jsonl", type=Path, help="Path to deduped/cleaned JSONL (one object per line)")
    p.add_argument(
        "--min-volume-surface",
        type=int,
        default=5,
        metavar="N",
        help="Minimum rows per surface to include in recommendations (default: 5)",
    )
    p.add_argument(
        "--min-labeled-intent",
        type=int,
        default=5,
        metavar="N",
        help="Minimum pass+fail rows per intent for high-failure / high-success buckets (default: 5)",
    )
    p.add_argument("--json-out", type=Path, metavar="PATH", help="Write full analysis JSON")
    p.add_argument("-q", "--quiet", action="store_true", help="Do not print text report")
    args = p.parse_args()

    rows = load_cleaned_jsonl(args.cleaned_jsonl)
    analysis = run_full_analysis(
        rows,
        min_volume_surface=args.min_volume_surface,
        min_labeled_intent=args.min_labeled_intent,
    )

    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        with open(args.json_out, "w", encoding="utf-8") as f:
            json.dump(analysis, f, ensure_ascii=False, indent=2, default=str)
            f.write("\n")

    if not args.quiet:
        sys.stdout.write(format_analysis_report(analysis))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
