#!/usr/bin/env python3
"""
Dedupe and summarize persisted LearningRecord JSONL (active + rotated files).

Reads only fields already on disk — no prompt rehydration.

Examples (repo root):

  python scripts/zenaf_learning_jsonl_prep.py data/learning.jsonl -o data/learning_clean.jsonl

  python scripts/zenaf_learning_jsonl_prep.py "data/learning.jsonl*" --sort-files mtime \\
    -o data/learning_clean.jsonl --summary-json data/learning_summary.json

  # Rotated chunks oldest-first, then active (or use --sort-files mtime)
  python scripts/zenaf_learning_jsonl_prep.py old.rotated data/learning.jsonl

See docs/02_ACTIVE_DESIGN/TIERED_DELEGATION_AND_LEARNING.md
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from local_ai.delegation.learning_jsonl_prep import (
    format_summary_text,
    run_prep,
)


def main() -> int:
    p = argparse.ArgumentParser(description="Dedupe LearningRecord JSONL (last line per record_id wins).")
    p.add_argument(
        "inputs",
        nargs="+",
        help="Input JSONL paths or globs (e.g. data/learn.jsonl data/learn.jsonl.*.rotated)",
    )
    p.add_argument(
        "-o",
        "--out-jsonl",
        type=Path,
        metavar="PATH",
        help="Write deduped records sorted by ts_ms (one JSON per line)",
    )
    p.add_argument(
        "--summary-json",
        type=Path,
        metavar="PATH",
        help="Write dedupe stats + count summaries as JSON",
    )
    p.add_argument(
        "--sort-files",
        choices=("none", "path", "mtime"),
        default="none",
        help="File order before streaming: none=CLI order, path=lexicographic, mtime=oldest first",
    )
    p.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        help="Do not print human-readable summary to stdout",
    )
    args = p.parse_args()
    print_summary = not args.quiet
    if not args.out_jsonl and not args.summary_json and not print_summary:
        p.error("Provide --out-jsonl and/or --summary-json, or omit --quiet for stdout summary")

    _deduped, dstats, summary_full = run_prep(
        args.inputs,
        sort_files=args.sort_files,  # type: ignore[arg-type]
        out_jsonl=args.out_jsonl,
        summary_json=args.summary_json,
    )

    if print_summary:
        text = format_summary_text(dstats, summary_full["summary"])
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
