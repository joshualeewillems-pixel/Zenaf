#!/usr/bin/env python3
"""
Autonomous philosophy repair loop (local operator).

1. Run philosophy enforcement (same engine as run_all.py).
2. Collect confirmed violations only.
3. Pick highest-priority repairable checker with a registered handler (repair_registry.json + repairs.HANDLERS).
4. With --apply + Git: tag checkpoint, run handler, re-enforce + tests, commit or revert.

Default: --dry-run (no mutations, no Git tags).

See docs/01_TRUTH/AUTONOMOUS_REPAIR_POLICY.md
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from scripts.philosophy_enforcement.checkers import load_all_checkers  # noqa: E402
from scripts.philosophy_enforcement.program_state import ProgramStateError, load_program_state  # noqa: E402
from scripts.philosophy_enforcement.registry import load_matrix_registry  # noqa: E402
from scripts.philosophy_enforcement.repairs import get_handler  # noqa: E402
from scripts.philosophy_enforcement.repairs.models import RepairBatchResult  # noqa: E402
from scripts.philosophy_enforcement.run_all import (  # noqa: E402
    build_rows,
    count_confirmed_violations,
    flatten_confirmed_findings,
    write_reports,
)


def _load_repair_registry(repo: Path) -> dict:
    p = repo / "scripts" / "philosophy_enforcement" / "repair_registry.json"
    return json.loads(p.read_text(encoding="utf-8"))


def _git(repo: Path, *args: str, check: bool = False) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=str(repo),
        capture_output=True,
        text=True,
        timeout=180,
        check=check,
    )


def _git_ok(repo: Path) -> bool:
    try:
        r = _git(repo, "rev-parse", "--is-inside-work-tree")
    except FileNotFoundError:
        return False
    return r.returncode == 0 and r.stdout.strip() == "true"


def _working_tree_clean(repo: Path) -> bool:
    try:
        r = _git(repo, "status", "--porcelain")
    except FileNotFoundError:
        return False
    return r.returncode == 0 and not r.stdout.strip()


def _path_allowed(rel_posix: str, globs: list[str]) -> bool:
    p = Path(rel_posix)
    for g in globs:
        try:
            if p.match(g):
                return True
        except ValueError:
            continue
    return False


def _git_untracked_paths(repo: Path) -> list[str]:
    try:
        r = _git(repo, "status", "--porcelain", "-uall")
    except FileNotFoundError:
        return []
    if r.returncode != 0:
        return []
    out: list[str] = []
    for line in r.stdout.splitlines():
        if len(line) > 3 and line.startswith("?? "):
            out.append(line[3:].strip().replace("\\", "/"))
    return out


def _git_worktree_modified_paths(repo: Path) -> list[str]:
    """Paths with unstaged changes (working tree vs index)."""
    try:
        r = _git(repo, "diff", "--name-only")
    except FileNotFoundError:
        return []
    if r.returncode != 0:
        return []
    return [x.strip().replace("\\", "/") for x in r.stdout.splitlines() if x.strip()]


def _run_tests(repo: Path, argv: list[str]) -> tuple[bool, str]:
    if not argv:
        return True, "(no required_tests)"
    try:
        r = subprocess.run(argv, cwd=str(repo), capture_output=True, text=True, timeout=600)
    except FileNotFoundError as e:
        return False, f"test command not found: {e}"
    out = (r.stdout or "") + (r.stderr or "")
    return r.returncode == 0, out[-8000:] if len(out) > 8000 else out


def _write_auto_repair_report(
    repo: Path,
    payload: dict,
    markdown: str,
) -> tuple[Path, Path]:
    out_dir = repo / "reports" / "philosophy_enforcement"
    out_dir.mkdir(parents=True, exist_ok=True)
    jp = out_dir / "auto_repair_last.json"
    mp = out_dir / "auto_repair_last.md"
    jp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    mp.write_text(markdown, encoding="utf-8")
    return jp, mp


def main() -> int:
    parser = argparse.ArgumentParser(description="Autonomous philosophy repair loop")
    parser.add_argument("--repo", type=Path, default=_REPO, help="Repository root")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Run repair handler + Git checkpoint/revert (default: report-only dry run)",
    )
    parser.add_argument(
        "--no-git",
        action="store_true",
        help="With --apply: forbidden — apply requires Git. Without --apply: skip Git status hints in report only.",
    )
    parser.add_argument("--allow-dirty", action="store_true", help="Allow non-clean working tree with --apply")
    parser.add_argument("--max-iterations", type=int, default=1, help="Reserved for multi-iteration loops (currently 1)")
    parser.add_argument(
        "--write-enforcement-report",
        action="store_true",
        help="Also write reports/philosophy_enforcement/latest.{md,json}",
    )
    args = parser.parse_args()
    repo = args.repo.resolve()

    try:
        program_state = load_program_state(repo)
    except ProgramStateError as e:
        print(str(e), file=sys.stderr)
        return 2

    if args.apply and args.no_git:
        print("error: --apply cannot be used with --no-git (checkpoint/revert requires Git)", file=sys.stderr)
        return 2

    reg = _load_repair_registry(repo)
    ordered = sorted(reg.get("checkers", []), key=lambda x: int(x.get("repair_priority", 99)))

    load_all_checkers()
    matrix = load_matrix_registry(repo)
    rows = build_rows(repo, matrix)
    confirmed_before = count_confirmed_violations(rows)
    flat = flatten_confirmed_findings(rows)

    by_checker: dict[str, list[dict]] = defaultdict(list)
    for f in flat:
        cid = f.get("checker_id") or ""
        if cid:
            by_checker[cid].append(f)

    if args.write_enforcement_report:
        write_reports(rows, repo, program_state=program_state)

    repairable_candidate: dict | None = None
    for entry in ordered:
        cid = entry["checker_id"]
        if not entry.get("repairable"):
            continue
        if not by_checker.get(cid):
            continue
        repairable_candidate = entry
        break

    chosen: str | None = None
    chosen_cfg: dict | None = None
    if repairable_candidate and get_handler(repairable_candidate["checker_id"]):
        chosen = repairable_candidate["checker_id"]
        chosen_cfg = repairable_candidate

    iteration_log: list[dict] = []
    tag_name: str | None = None
    final_confirmed = confirmed_before
    outcome = "dry_run"
    handler_result: RepairBatchResult | None = None

    if args.apply:
        outcome = "no_applicable_handler"
        if not _git_ok(repo):
            outcome = "aborted_no_git_repo"
        elif not _working_tree_clean(repo) and not args.allow_dirty:
            outcome = "aborted_dirty_worktree"
        elif confirmed_before == 0:
            outcome = "no_confirmed_violations"
        elif not repairable_candidate:
            outcome = "violations_but_nothing_repairable"
        elif not get_handler(repairable_candidate["checker_id"]):
            outcome = "repairable_checker_but_no_handler"
        elif chosen and chosen_cfg:
            ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            tag_name = f"checkpoint/philosophy-{ts}"
            t = _git(repo, "tag", tag_name)
            if t.returncode != 0:
                outcome = "aborted_tag_failed"
                iteration_log.append({"tag": tag_name, "stderr": t.stderr})
                tag_name = None
            else:
                outcome = "handler_pending"

    if outcome == "handler_pending" and chosen and chosen_cfg and tag_name:
        fn = get_handler(chosen)
        assert fn is not None
        handler_crashed = False
        try:
            handler_result = fn(repo, by_checker[chosen], chosen_cfg)
        except Exception as e:
            handler_crashed = True
            iteration_log.append({"checker_id": chosen, "handler_exception": str(e)[:2000]})
            outcome = "handler_exception"
            try:
                _git(repo, "reset", "--hard", "HEAD")
                _git(repo, "tag", "-d", tag_name)
            except FileNotFoundError:
                pass

        if handler_crashed:
            pass
        elif not handler_result.applied:
            outcome = "handler_noop"
            iteration_log.append(
                {
                    "checker_id": chosen,
                    "handler_summary": handler_result.summary,
                    "applied": False,
                    "error": handler_result.error,
                }
            )
            _git(repo, "tag", "-d", tag_name)
        else:
            iteration_log.append(
                {
                    "checker_id": chosen,
                    "handler_summary": handler_result.summary,
                    "applied": True,
                    "touched_files": handler_result.touched_files,
                }
            )
            rels = [p.replace("\\", "/") for p in handler_result.touched_files]
            globs = chosen_cfg.get("allowed_file_globs") or []
            max_f = int(chosen_cfg.get("max_touched_files", 99))

            def _revert_wip() -> None:
                try:
                    _git(repo, "reset", "--hard", "HEAD")
                    _git(repo, "tag", "-d", tag_name)
                except FileNotFoundError:
                    pass

            post_handler_abort = False
            if len(rels) > max_f:
                outcome = "aborted_too_many_files"
                post_handler_abort = True
                _revert_wip()
            elif any(not _path_allowed(r, globs) for r in rels):
                outcome = "aborted_path_not_allowed"
                post_handler_abort = True
                _revert_wip()
            else:
                allow_new = bool(chosen_cfg.get("allow_new_files", False))
                untracked = _git_untracked_paths(repo)
                if untracked:
                    if not allow_new:
                        outcome = "aborted_unexpected_untracked"
                        iteration_log.append({"untracked": untracked})
                        post_handler_abort = True
                        _revert_wip()
                    else:
                        ug = chosen_cfg.get("allow_untracked_globs") or []
                        bad = [u for u in untracked if not any(Path(u).match(g) for g in ug)]
                        if bad:
                            outcome = "aborted_untracked_not_allowed"
                            iteration_log.append({"untracked_disallowed": bad})
                            post_handler_abort = True
                            _revert_wip()
                if not post_handler_abort:
                    modified = _git_worktree_modified_paths(repo)
                    if set(modified) != set(rels):
                        outcome = "aborted_diff_mismatch"
                        iteration_log.append({"modified_paths": modified, "expected": rels})
                        post_handler_abort = True
                        _revert_wip()

            if not post_handler_abort:
                ok_test, test_log = _run_tests(repo, chosen_cfg.get("required_tests") or [])
                rows_after = build_rows(repo, matrix)
                confirmed_after = count_confirmed_violations(rows_after)
                iteration_log.append(
                    {
                        "tests_ok": ok_test,
                        "test_log_tail": test_log,
                        "confirmed_after": confirmed_after,
                    }
                )
                worse = confirmed_after > confirmed_before
                if chosen_cfg.get("revert_on_worse", True) and (worse or not ok_test):
                    outcome = "reverted"
                    _revert_wip()
                    final_confirmed = confirmed_before
                elif confirmed_after >= confirmed_before:
                    outcome = "reverted_no_improvement"
                    _revert_wip()
                    final_confirmed = confirmed_before
                else:
                    msg = (
                        f"chore(philosophy-enforce): auto-repair {chosen}\n\n"
                        f"- confirmed_before: {confirmed_before}\n"
                        f"- confirmed_after: {confirmed_after}\n"
                        f"- policy: docs/01_TRUTH/AUTONOMOUS_REPAIR_POLICY.md\n"
                    )
                    add = _git(repo, "add", "--", *rels)
                    if add.returncode != 0:
                        outcome = "aborted_git_add_failed"
                        _revert_wip()
                    else:
                        cm = _git(repo, "commit", "-m", msg)
                        if cm.returncode != 0:
                            outcome = "aborted_commit_failed"
                            _revert_wip()
                        else:
                            outcome = "committed"
                            final_confirmed = confirmed_after

    payload = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "repo": str(repo),
        "dry_run": not args.apply,
        "apply": args.apply,
        "no_git": args.no_git,
        "max_iterations": args.max_iterations,
        "outcome": outcome,
        "checkpoint_tag": tag_name,
        "confirmed_violations_before": confirmed_before,
        "confirmed_violations_after": final_confirmed,
        "confirmed_findings_by_checker": {k: len(v) for k, v in by_checker.items()},
        "repairable_candidate_checker": repairable_candidate["checker_id"] if repairable_candidate else None,
        "chosen_checker": chosen,
        "handler_registered_for_chosen": bool(chosen and get_handler(chosen)),
        "iteration_log": iteration_log,
        "policy_doc": reg.get("policy_doc"),
        "git_repo": _git_ok(repo),
        "working_tree_clean": _working_tree_clean(repo) if _git_ok(repo) else None,
    }

    md_lines = [
        "# Auto-repair run",
        "",
        f"- UTC: `{payload['generated_at_utc']}`",
        f"- Repo: `{repo}`",
        f"- Outcome: **`{outcome}`**",
        f"- Confirmed violations (before → after): **{confirmed_before} → {final_confirmed}**",
        "",
        "## Summary",
        "",
        f"- Repairable candidate (first in priority): `{payload['repairable_candidate_checker']}`",
        f"- Chosen for apply (repairable + handler): `{chosen}`",
        f"- Handler registered for chosen: {payload['handler_registered_for_chosen']}",
        "",
        "## Findings by checker (confirmed count)",
        "",
    ]
    for k, v in sorted(by_checker.items(), key=lambda x: -len(x[1])):
        md_lines.append(f"- `{k}`: {len(v)}")
    md_lines.extend(
        [
            "",
            "## Notes",
            "",
            "Phase 0: all checkers default to `repairable: false` and no handlers are registered.",
            "Enable repairs by setting `repairable: true` and implementing `repairs.HANDLERS[checker_id]`.",
            "",
        ]
    )

    jp, mp = _write_auto_repair_report(repo, payload, "\n".join(md_lines) + "\n")
    print(f"Auto-repair report: {jp}")
    print(f"                    {mp}")
    print(f"Outcome: {outcome}")

    if not args.apply:
        print("(report-only; pass --apply to run handlers + Git checkpoint/revert)")

    rc = 0
    if args.apply and (outcome.startswith("aborted_") or outcome == "handler_exception"):
        rc = 1
    return rc


if __name__ == "__main__":
    sys.exit(main())
