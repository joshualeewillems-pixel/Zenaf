#!/usr/bin/env python3
"""
Machine-checkable exit gate for the active wave (see wave_registry.json + wave_autonomy_protocol.md).

1. Optional: convergence_program_state.json active_phase must match wave.exit.optional_phase_equals.
2. Optional: GITHUB_REF must match wave.exit.branch_ref_pattern (regex).
3. run_all.py with PHILOSOPHY_ENFORCE_STRICT=1 when enforce_strict is true.
4. pytest for each path in wave.exit.pytest_targets.

Writes wave_exit_report.json and prints a one-line JSON summary to stdout.
Exit 0 iff all steps pass; 1 on gate failure; 2 on configuration error.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
_REGISTRY_REL = Path("scripts") / "philosophy_enforcement" / "wave_registry.json"
_STATE_REL = Path("docs") / "01_TRUTH" / "convergence_program_state.json"
_RUN_ALL = Path("scripts") / "philosophy_enforcement" / "run_all.py"
_LATEST_JSON = Path("reports") / "philosophy_enforcement" / "latest.json"


def _load_registry(repo: Path) -> dict:
    p = repo / _REGISTRY_REL
    if not p.is_file():
        raise FileNotFoundError(str(p))
    return json.loads(p.read_text(encoding="utf-8"))


def _wave_by_id(registry: dict, wave_id: str) -> dict | None:
    for w in registry.get("waves") or []:
        if isinstance(w, dict) and w.get("id") == wave_id:
            return w
    return None


def _append_step(steps: list[dict], name: str, ok: bool, detail: str | None = None) -> None:
    row: dict = {"name": name, "ok": ok}
    if detail:
        row["detail"] = detail[:2000]
    steps.append(row)


def _read_active_phase(repo: Path) -> str | None:
    sp = repo / _STATE_REL
    if not sp.is_file():
        return None
    try:
        st = json.loads(sp.read_text(encoding="utf-8"))
        p = str(st.get("active_phase") or "").strip()
        return p if p else None
    except (OSError, json.JSONDecodeError):
        return None


def _failed_philosophy_ids(repo: Path) -> list[str]:
    p = repo / _LATEST_JSON
    if not p.is_file():
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    out: list[str] = []
    for row in data.get("rows") or []:
        if not isinstance(row, dict):
            continue
        if row.get("status") != "fail":
            continue
        pid = row.get("philosophy_id")
        slug = row.get("slug") or "unknown"
        if pid is not None:
            out.append(f"philosophy_{int(pid)}_{slug}")
    return out


def _suggested_action(failed_checks: list[str]) -> str:
    if not failed_checks:
        return ""
    first = failed_checks[0]
    if first.startswith("pytest:"):
        return f"Run pytest locally: python -m pytest {first.split(':', 1)[1]} -vv"
    if first.startswith("philosophy_"):
        return "Review reports/philosophy_enforcement/latest.json for failing philosophy rows; fix confirmed violations or adjust checkers/matrix."
    return {
        "phase_alignment": "Align docs/01_TRUTH/convergence_program_state.json active_phase with this wave's optional_phase_equals.",
        "branch_ref": "Use a matching refs/heads/auto/wave-* branch or run with skip_branch_check on main.",
        "philosophy_enforcement": "Review reports/philosophy_enforcement/latest.json; address strict-mode failures.",
    }.get(first, f"Inspect failed check {first!r} in wave_exit_report.json and CI logs.")


def _build_escalation_report(
    *,
    repo: Path,
    wave: dict,
    wave_id: str,
    steps: list[dict],
    all_ok: bool,
) -> dict:
    failed_steps = [s for s in steps if not s.get("ok")]
    failed_checks: list[str] = [str(s.get("name") or "unknown") for s in failed_steps]

    # Replace coarse philosophy_enforcement with per-philosophy ids when latest.json available
    if "philosophy_enforcement" in failed_checks:
        granular = _failed_philosophy_ids(repo)
        if granular:
            failed_checks = [c for c in failed_checks if c != "philosophy_enforcement"] + granular

    phase = _read_active_phase(repo)
    ref = (os.environ.get("GITHUB_REF") or "").strip()
    branch = ref[11:] if ref.startswith("refs/heads/") else (ref or None)
    sha = (os.environ.get("GITHUB_SHA") or "").strip()

    block_type = "none" if all_ok else "hard"
    promo = wave.get("promotion") if isinstance(wave.get("promotion"), dict) else {}

    return {
        "wave_id": wave_id,
        "ok": all_ok,
        "phase": phase,
        "failed_checks": failed_checks,
        "block_type": block_type,
        "suggested_action": _suggested_action(failed_checks) if not all_ok else "",
        "branch": branch,
        "commit": sha[:40] if sha else None,
        "promotion": {
            "requires_manual_flag": bool(promo.get("requires_manual_flag", True)),
            "notes": promo.get("notes"),
        },
        "timestamp_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "steps": steps,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Wave exit gate (enforcement + tests + optional phase/branch checks)")
    parser.add_argument("--repo", type=Path, default=_REPO, help="Repository root")
    parser.add_argument("--wave-id", type=str, default=None, help="Override registry current_wave_id")
    parser.add_argument(
        "--report-out",
        type=Path,
        default=None,
        help="Write JSON report (default: <repo>/wave_exit_report.json)",
    )
    parser.add_argument(
        "--skip-branch-check",
        action="store_true",
        help="Ignore branch_ref_pattern even if set (for local runs on main)",
    )
    args = parser.parse_args()
    repo = args.repo.resolve()
    report_path = args.report_out or (repo / "wave_exit_report.json")
    steps: list[dict] = []
    wave_id: str | None = None

    try:
        registry = _load_registry(repo)
    except (OSError, json.JSONDecodeError, FileNotFoundError) as e:
        print(json.dumps({"ok": False, "error": f"registry: {e}"}), file=sys.stderr)
        return 2

    wave_id = (args.wave_id or registry.get("current_wave_id") or "").strip()
    if not wave_id:
        print(json.dumps({"ok": False, "error": "current_wave_id missing"}), file=sys.stderr)
        return 2

    wave = _wave_by_id(registry, wave_id)
    if not wave:
        print(json.dumps({"ok": False, "error": f"unknown wave_id: {wave_id}"}), file=sys.stderr)
        return 2

    exit_cfg = wave.get("exit") or {}
    if not isinstance(exit_cfg, dict):
        exit_cfg = {}

    # Optional phase alignment
    phase_need = exit_cfg.get("optional_phase_equals")
    if phase_need is not None and str(phase_need).strip() != "":
        sp = repo / _STATE_REL
        if not sp.is_file():
            _append_step(steps, "phase_alignment", False, f"missing { _STATE_REL.as_posix() }")
        else:
            try:
                st = json.loads(sp.read_text(encoding="utf-8"))
                active = str(st.get("active_phase") or "").strip()
                need = str(phase_need).strip()
                match = active == need
                _append_step(
                    steps,
                    "phase_alignment",
                    match,
                    f"active_phase={active!r} expected {need!r}" if not match else None,
                )
            except (OSError, json.JSONDecodeError) as e:
                _append_step(steps, "phase_alignment", False, str(e))
    else:
        _append_step(steps, "phase_alignment", True, "skipped (optional_phase_equals not set)")

    # Optional branch ref (CI)
    pat = exit_cfg.get("branch_ref_pattern")
    if not args.skip_branch_check and pat is not None and str(pat).strip():
        ref = (os.environ.get("GITHUB_REF") or "").strip()
        if not ref:
            _append_step(steps, "branch_ref", True, "skipped (GITHUB_REF unset)")
        else:
            try:
                ok = bool(re.match(str(pat), ref))
                _append_step(
                    steps,
                    "branch_ref",
                    ok,
                    f"GITHUB_REF={ref!r} vs pattern {pat!r}" if not ok else None,
                )
            except re.error as e:
                _append_step(steps, "branch_ref", False, f"invalid regex: {e}")
    else:
        _append_step(steps, "branch_ref", True, "skipped")

    # Philosophy enforcement
    env = os.environ.copy()
    enforce_strict = bool(exit_cfg.get("enforce_strict", True))
    if enforce_strict:
        env["PHILOSOPHY_ENFORCE_STRICT"] = "1"
    else:
        env.pop("PHILOSOPHY_ENFORCE_STRICT", None)

    run_all_py = repo / _RUN_ALL
    if not run_all_py.is_file():
        _append_step(steps, "philosophy_enforcement", False, f"missing {_RUN_ALL.as_posix()}")
    else:
        r = subprocess.run(
            [sys.executable, str(run_all_py)],
            cwd=str(repo),
            env=env,
            capture_output=True,
            text=True,
            timeout=600,
        )
        ok = r.returncode == 0
        tail = (r.stderr or r.stdout or "")[-1500:]
        _append_step(steps, "philosophy_enforcement", ok, None if ok else tail.strip())

    # Pytest targets
    targets = exit_cfg.get("pytest_targets") or []
    if not isinstance(targets, list):
        targets = []
    for rel in targets:
        rel_s = str(rel).strip()
        if not rel_s:
            continue
        tp = repo / rel_s
        if not tp.is_file():
            _append_step(steps, f"pytest:{rel_s}", False, "path not found")
            continue
        r = subprocess.run(
            [sys.executable, "-m", "pytest", rel_s, "-q", "--tb=no"],
            cwd=str(repo),
            capture_output=True,
            text=True,
            timeout=600,
        )
        ok = r.returncode == 0
        tail = (r.stderr or r.stdout or "")[-1500:]
        _append_step(steps, f"pytest:{rel_s}", ok, None if ok else tail.strip())

    all_ok = all(s.get("ok") for s in steps)
    report = _build_escalation_report(
        repo=repo,
        wave=wave,
        wave_id=wave_id,
        steps=steps,
        all_ok=all_ok,
    )
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({"ok": all_ok, "wave_id": wave_id, "report": str(report_path.relative_to(repo))}))
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
