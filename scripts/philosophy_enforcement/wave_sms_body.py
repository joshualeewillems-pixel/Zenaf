#!/usr/bin/env python3
"""
Build human-readable SMS bodies from wave_exit_report.json (failure or success).

Used by GitHub Actions after wave_exit_gate.py; keep under ~1500 chars for SMS segments.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _short_ref(ref: str) -> str:
    r = (ref or "").strip()
    if r.startswith("refs/heads/"):
        return r[len("refs/heads/") :]
    return r or "unknown"


def suggested_action_for_failed(failed_id: str) -> str:
    if failed_id.startswith("pytest:"):
        return f"Run locally: python -m pytest {failed_id.split(':', 1)[1]} -vv"
    if failed_id.startswith("philosophy_"):
        return "Review reports/philosophy_enforcement/latest.json for that row; fix confirmed violations or matrix/checkers."
    return {
        "philosophy_enforcement": "Review reports/philosophy_enforcement/latest.json; fix confirmed violations or adjust matrix/checkers.",
        "phase_alignment": "Align docs/01_TRUTH/convergence_program_state.json active_phase with wave_registry exit.optional_phase_equals.",
        "branch_ref": "Use refs/heads/auto/wave-* or run with skip_branch_check on main.",
    }.get(
        failed_id,
        f"Inspect gate step {failed_id!r} in wave_exit_report.json and CI logs.",
    )


def format_failure_report(
    report: dict,
    *,
    repo: str,
    run_url: str,
    git_ref: str,
    sha: str,
) -> str:
    wave_id = str(report.get("wave_id") or "?")
    phase = report.get("phase")
    failed = report.get("failed_checks") or []
    block = str(report.get("block_type") or "hard")
    suggested = str(report.get("suggested_action") or "").strip()
    if not suggested and failed:
        suggested = suggested_action_for_failed(str(failed[0]))
    branch = str(report.get("branch") or _short_ref(git_ref))
    commit = str(report.get("commit") or (sha[:7] if sha else "?"))

    lines = [
        "Zenaf wave-autonomy",
        f"Wave: {wave_id}",
        f"Status: FAILED ({block})",
    ]
    if phase is not None:
        lines.append(f"Phase: {phase}")
    lines.append("")
    if failed:
        lines.append("Failed:")
        for f in failed[:8]:
            lines.append(f"- {f}")
    else:
        lines.append("Failed: (see report)")
    lines.extend(["", "Suggested:", suggested[:400]])
    lines.extend(["", f"Branch: {branch}", f"Commit: {commit}", f"Run: {run_url}", f"Repo: {repo}"])
    body = "\n".join(lines)
    return body[:1580]


def format_success_report(
    report: dict,
    *,
    repo: str,
    run_url: str,
    git_ref: str,
    sha: str,
) -> str:
    wave_id = str(report.get("wave_id") or "?")
    phase = report.get("phase")
    branch = str(report.get("branch") or _short_ref(git_ref))
    commit = str(report.get("commit") or (sha[:7] if sha else "?"))
    req = bool((report.get("promotion") or {}).get("requires_manual_flag", True))

    lines = [
        "Zenaf wave-autonomy",
        f"Wave: {wave_id}",
        "Status: OK (exit gate passed)",
    ]
    if phase is not None:
        lines.append(f"Phase: {phase}")
    lines.extend(["", f"Branch: {branch}", f"Commit: {commit}", f"Run: {run_url}"])
    if req:
        lines.extend(
            [
                "",
                "Awaiting promotion: update wave_registry current_wave_id (or workflow promote_next_wave) when ready.",
            ]
        )
    lines.append("")
    lines.append("(Reply handling not wired — use GitHub / local git.)")
    return "\n".join(lines)[:1580]


def main() -> int:
    p = argparse.ArgumentParser(description="Format SMS body from wave exit report")
    p.add_argument("--report", type=Path, required=True, help="Path to wave_exit_report.json")
    p.add_argument("--variant", choices=("failure", "success"), required=True)
    p.add_argument("--repo", default="", help="owner/repo")
    p.add_argument("--run-url", default="", help="Actions run URL")
    p.add_argument("--git-ref", default="", help="GITHUB_REF")
    p.add_argument("--sha", default="", help="GITHUB_SHA")
    args = p.parse_args()
    if not args.report.is_file():
        print(f"wave_sms_body: missing report {args.report}", file=sys.stderr)
        return 1
    try:
        report = json.loads(args.report.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        print(f"wave_sms_body: {e}", file=sys.stderr)
        return 1
    if args.variant == "failure":
        text = format_failure_report(
            report,
            repo=args.repo or "local",
            run_url=args.run_url or "(local)",
            git_ref=args.git_ref,
            sha=args.sha,
        )
    else:
        text = format_success_report(
            report,
            repo=args.repo or "local",
            run_url=args.run_url or "(local)",
            git_ref=args.git_ref,
            sha=args.sha,
        )
    sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
