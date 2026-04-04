#!/usr/bin/env python3
"""
Philosophy enforcement — reads docs/01_TRUTH/global_philosophy_integration_matrix.json,
docs/01_TRUTH/convergence_program_state.json (program state for reports; not parsed from Markdown),
runs registered static checkers, writes Markdown + JSON under reports/philosophy_enforcement/.

Exit code: 0 normally (report-only), 2 if convergence_program_state.json is missing or invalid.
Set PHILOSOPHY_ENFORCE_STRICT=1 to exit 1 on any confirmed violation.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

# Allow `python scripts/philosophy_enforcement/run_all.py` from repo root
_REPO = Path(__file__).resolve().parents[2]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from scripts.philosophy_enforcement.checkers import CHECKERS, load_all_checkers  # noqa: E402
from scripts.philosophy_enforcement.models import (  # noqa: E402
    CheckerRun,
    Finding,
    FindingKind,
    PhilosophyRow,
    RowStatus,
    aggregate_status,
)
from scripts.philosophy_enforcement.registry import load_matrix_registry, philosophy_checker_map  # noqa: E402
from scripts.philosophy_enforcement.program_state import ProgramStateError, load_program_state  # noqa: E402
from scripts.philosophy_enforcement.reports import render_markdown, write_reports  # noqa: E402


def _suggested_action(status: RowStatus, slug: str) -> str:
    if status == RowStatus.NOT_YET_AUTOMATED:
        return (
            f"Add `automation.checker_ids` for `{slug}` in global_philosophy_integration_matrix.json "
            "and implement a checker under scripts/philosophy_enforcement/checkers/."
        )
    if status == RowStatus.FAIL:
        return "Resolve confirmed violations, or update TRUTH docs + registry/config if the law or scope changed intentionally."
    if status == RowStatus.PARTIAL:
        return "Review heuristic hits; extend allowlists in scripts/philosophy_enforcement/config/ when benign."
    return "No automated issues; keep matrix JSON, configs, and ve_integration_schema in sync when changing labels or routes."


def _run_checker(repo: Path, cid: str) -> CheckerRun:
    fn = CHECKERS.get(cid)
    if fn is None:
        return CheckerRun(
            checker_id=cid,
            error=f"Unknown checker_id {cid!r} (not registered)",
        )
    return fn(repo)


def build_rows(repo: Path, registry: dict) -> list[PhilosophyRow]:
    pcm = philosophy_checker_map(registry)
    rows: list[PhilosophyRow] = []

    for p in registry.get("philosophies", []):
        pid = int(p["id"])
        slug = p.get("slug", "")
        name = p.get("name", "")
        cids = pcm.get(pid, [])

        if not cids:
            rows.append(
                PhilosophyRow(
                    philosophy_id=pid,
                    name=name,
                    slug=slug,
                    status=RowStatus.NOT_YET_AUTOMATED,
                    findings=[],
                    suggested_next_action=_suggested_action(RowStatus.NOT_YET_AUTOMATED, slug),
                )
            )
            continue

        all_findings: list[Finding] = []
        runs: list[CheckerRun] = []
        for cid in cids:
            run = _run_checker(repo, cid)
            runs.append(run)
            if run.error:
                all_findings.append(
                    Finding(
                        kind=FindingKind.HEURISTIC_SUSPICION,
                        message=f"Checker error: {run.error}",
                        location=f"checker:{cid}",
                        checker_id=cid,
                    )
                )
            all_findings.extend(run.findings)

        st = aggregate_status(all_findings)
        rows.append(
            PhilosophyRow(
                philosophy_id=pid,
                name=name,
                slug=slug,
                status=st,
                findings=all_findings,
                suggested_next_action=_suggested_action(st, slug),
                checker_runs=runs,
            )
        )
    rows.sort(key=lambda r: r.philosophy_id)
    return rows


def count_confirmed_violations(rows: list[PhilosophyRow]) -> int:
    return sum(
        1 for r in rows for f in r.findings if f.kind == FindingKind.CONFIRMED_VIOLATION
    )


def flatten_confirmed_findings(rows: list[PhilosophyRow]) -> list[dict]:
    """Structured confirmed findings for autonomous tooling (philosophy + checker + location)."""
    out: list[dict] = []
    for r in rows:
        for f in r.findings:
            if f.kind != FindingKind.CONFIRMED_VIOLATION:
                continue
            d = f.to_dict()
            d["philosophy_id"] = r.philosophy_id
            d["philosophy_slug"] = r.slug
            d["philosophy_name"] = r.name
            out.append(d)
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="Run philosophy enforcement checkers")
    parser.add_argument(
        "--repo",
        type=Path,
        default=_REPO,
        help="Repository root (default: auto-detected)",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=None,
        help="Override report directory (default: <repo>/reports/philosophy_enforcement)",
    )
    parser.add_argument(
        "--stdout",
        action="store_true",
        help="Print Markdown report to stdout as well as writing files",
    )
    args = parser.parse_args()
    repo = args.repo.resolve()

    try:
        program_state = load_program_state(repo)
    except ProgramStateError as e:
        print(str(e), file=sys.stderr)
        return 2

    load_all_checkers()
    registry = load_matrix_registry(repo)
    rows = build_rows(repo, registry)
    md_path, json_path = write_reports(rows, repo, args.out_dir, program_state=program_state)

    md = render_markdown(rows, repo, program_state=program_state)
    if args.stdout:
        print(md)
    else:
        print("Philosophy enforcement")
        print(f"  Repo:    {repo}")
        print(f"  Report:  {md_path}")
        print(f"  JSON:    {json_path}")
        summary = {s.value: sum(1 for r in rows if r.status == s) for s in RowStatus}
        print(f"  Summary: {summary}")

    if os.environ.get("PHILOSOPHY_ENFORCE_STRICT") == "1":
        if any(r.status == RowStatus.FAIL for r in rows):
            print("PHILOSOPHY_ENFORCE_STRICT: failing on confirmed violation(s).", file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
