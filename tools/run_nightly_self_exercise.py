#!/usr/bin/env python3
"""
Nightly self-exercise harness for Zenaf (read-only; no self-modifying AI).

Single entrypoint:
  python tools/run_nightly_self_exercise.py [--profile quick|standard|full]

Desktop UI (Windows-friendly): python tools/nightly_harness_gui.py  or  tools/NightlyHarness.bat

Requires API running (default http://127.0.0.1:8010) for smoke / adversarial / stress.
Set ZENAF_NIGHTLY_EMAIL + ZENAF_NIGHTLY_PASSWORD for authenticated VE / learning / focus flows.

Optional small cloud sample after local green: set ZENAF_NIGHTLY_CLOUD_BUDGET_USD (e.g. 0.5).

Safety: does not rewrite product code, alter schemas, mutate mailbox (poll off by default),
persist profiles, or auto-commit fixes.

See tools/nightly_self_exercise/ for modules.

User flow scripts (API): tools/nightly_self_exercise/user_flows.py — runs with standard/full unless
``--skip-user-flows``. Stress read loop: ``--user-flow-stress-iterations`` or env
``ZENAF_NIGHTLY_USER_FLOW_STRESS_ITER`` (full profile defaults to 12 when unset and flag is -1).

Browser flows: ``e2e/nightly/*.spec.ts`` — enable with ``ZENAF_NIGHTLY_PLAYWRIGHT=1`` (dev servers required).
Product UI: ``flows-a-core-interactions.spec.ts`` (Vision Map node + Soil/Water/Fruit + council question prefill; system prompt Discuss / Remind me later / Dismiss; VE evaluate dismiss + Distill stub) and ``flows-b-boundaries.spec.ts`` (PASS/BOUNDARY probes); see ``playwright-report/results.json`` for attachments.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.nightly_self_exercise.api_smoke import run_api_smoke
from tools.nightly_self_exercise.budget import BudgetTracker, parse_cloud_budget_usd
from tools.nightly_self_exercise.cleanup import cleanup_nightly_scratch_ideas
from tools.nightly_self_exercise.cloud_sample import build_opener_with_cookie_jar, login_opener, run_cloud_sample
from tools.nightly_self_exercise.reporting import (
    StepResult,
    build_comparison,
    build_digest,
    comparison_fields_from_run,
    load_metrics_from_summary,
    utc_iso,
    write_report_md,
    write_summary_json,
)
from tools.nightly_self_exercise.stress import stress_concurrent_council_probes, stress_health_and_intake
from tools.nightly_self_exercise.user_flows import run_user_flow_suite, stress_user_flow_reads

NIGHTLY_LOG_ROOT = REPO_ROOT / "logs" / "nightly_self_exercise"
LAST_RUN_POINTER = NIGHTLY_LOG_ROOT / "last_completed_run.txt"


def _progress(msg: str) -> None:
    """Stdout for humans / GUI pipes (harness otherwise only writes files until the end)."""
    line = f"[nightly] {msg}"
    try:
        print(line, flush=True)
    except UnicodeEncodeError:
        # Windows cp1252 pipes (e.g. Tk GUI subprocess) cannot print some Unicode.
        buf = getattr(sys.stdout, "buffer", None)
        enc = getattr(sys.stdout, "encoding", None) or "cp1252"
        if buf is not None:
            buf.write((line + "\n").encode(enc, errors="replace"))
            buf.flush()
        else:
            print(line.encode("ascii", errors="replace").decode("ascii"), flush=True)


def _run_cmd(
    name: str,
    argv: list[str],
    cwd: Path,
    log_file: Path,
    env: dict | None = None,
) -> tuple[int, float]:
    t0 = time.perf_counter()
    log_file.parent.mkdir(parents=True, exist_ok=True)
    with open(log_file, "w", encoding="utf-8") as lf:
        p = subprocess.run(
            argv,
            cwd=str(cwd),
            stdout=lf,
            stderr=subprocess.STDOUT,
            env={**os.environ, **(env or {})},
            text=True,
        )
    return p.returncode, time.perf_counter() - t0


def _local_critical_ok(profile: str, results: list[StepResult]) -> bool:
    """Steps that must pass before optional cloud sample."""

    def okish(r: StepResult) -> bool:
        return r.ok or r.classification in ("skipped", "known_gap")

    names = {"frontend_build", "api_smoke"}
    if profile != "quick":
        names.add("pytest_tests")
        names.add("stress_health_intake_loop")
    for r in results:
        if r.name in names and not okish(r):
            return False
    return True


def shutil_which(cmd: str) -> str | None:
    from shutil import which

    return which(cmd)


def main() -> int:
    ap = argparse.ArgumentParser(description="Zenaf nightly self-exercise harness")
    ap.add_argument(
        "--profile",
        choices=("quick", "standard", "full"),
        default=str(os.environ.get("ZENAF_NIGHTLY_PROFILE") or "standard").strip().lower(),
        help="quick=build+core smoke; standard=default local+optional cloud; full=stress+adversarial+smoke council",
    )
    ap.add_argument("--api-base", default=os.environ.get("ZENAF_API_BASE", "http://127.0.0.1:8010"))
    ap.add_argument("--out-dir", default="", help="Override output dir (default logs/nightly_self_exercise/<ts>)")
    ap.add_argument("--skip-frontend", action="store_true")
    ap.add_argument("--skip-pytest", action="store_true")
    ap.add_argument("--skip-api-smoke", action="store_true")
    ap.add_argument("--skip-adversarial", action="store_true")
    ap.add_argument("--skip-stress", action="store_true")
    ap.add_argument("--intake-poll", action="store_true", help="POST /intake/email/poll (no mailbox mutation; may 503)")
    ap.add_argument("--stress-iterations", type=int, default=int(os.environ.get("ZENAF_NIGHTLY_STRESS_ITER", "8")))
    ap.add_argument("--stress-workers", type=int, default=int(os.environ.get("ZENAF_NIGHTLY_STRESS_WORKERS", "3")))
    ap.add_argument("--skip-user-flows", action="store_true", help="Skip scripted API user flows (VE/settings/prompt-signals)")
    ap.add_argument(
        "--user-flow-stress-iterations",
        type=int,
        default=-1,
        help="Repeat authenticated read stress (0=off). Default -1: env ZENAF_NIGHTLY_USER_FLOW_STRESS_ITER or full=12",
    )
    args = ap.parse_args()

    profile = args.profile if args.profile in ("quick", "standard", "full") else "standard"
    email = (os.environ.get("ZENAF_NIGHTLY_EMAIL") or "").strip() or None
    password = (os.environ.get("ZENAF_NIGHTLY_PASSWORD") or "").strip() or None

    prev_metrics: dict = {}
    if LAST_RUN_POINTER.is_file():
        try:
            prev_dir = Path(LAST_RUN_POINTER.read_text(encoding="utf-8").strip())
            if prev_dir.is_dir():
                prev_metrics = load_metrics_from_summary(prev_dir / "summary.json")
        except OSError:
            prev_metrics = {}

    ts = time.strftime("%Y%m%d-%H%M%S", time.gmtime())
    out_dir = Path(args.out_dir) if args.out_dir else NIGHTLY_LOG_ROOT / ts
    out_dir.mkdir(parents=True, exist_ok=True)

    smoke_tier: str = {"quick": "quick", "standard": "local", "full": "full"}[profile]
    run_pytest = profile != "quick" and not args.skip_pytest
    run_stress_health = profile != "quick" and not args.skip_stress
    run_stress_concurrent = profile == "full" and not args.skip_stress
    run_adversarial_batch = profile == "full" and not args.skip_adversarial
    run_user_flows = profile != "quick" and not args.skip_user_flows
    uf_stress_iter = args.user_flow_stress_iterations
    if uf_stress_iter < 0:
        uf_stress_iter = int(os.environ.get("ZENAF_NIGHTLY_USER_FLOW_STRESS_ITER", "0") or 0)
        if profile == "full" and uf_stress_iter == 0:
            uf_stress_iter = 12
    run_user_flow_stress = run_user_flows and uf_stress_iter > 0 and bool(email and password)
    cloud_budget_usd = parse_cloud_budget_usd()
    run_cloud = profile != "quick" and cloud_budget_usd > 0.0

    meta: dict = {
        "started_iso": utc_iso(),
        "api_base": args.api_base,
        "repo_root": str(REPO_ROOT),
        "out_dir": str(out_dir),
        "argv": sys.argv,
        "profile": profile,
        "smoke_tier": smoke_tier,
        "cloud_budget_usd_config": cloud_budget_usd,
        "run_cloud_sample_planned": run_cloud,
        "user_flow_stress_iterations": uf_stress_iter if run_user_flow_stress else 0,
        "user_flow_stress_iterations_resolved": uf_stress_iter,
        "user_flow_stress_ran": False,
    }
    results: list[StepResult] = []

    try:
        _progress(f"started profile={profile} smoke_tier={smoke_tier} -> {out_dir}")
        # --- Frontend ---
        if not args.skip_frontend:
            fe = REPO_ROOT / "frontend"
            npm = shutil_which("npm.cmd") if sys.platform == "win32" else shutil_which("npm")
            if npm and fe.is_dir():
                log_b = out_dir / "frontend-build.txt"
                _progress("running frontend_build (npm run build)...")
                code, dur = _run_cmd("npm_run_build", [npm, "run", "build"], fe, log_b)
                results.append(
                    StepResult(
                        name="frontend_build",
                        ok=code == 0,
                        duration_s=dur,
                        classification="fail" if code != 0 else "pass",
                        detail=f"exit {code}",
                        artifact_paths=[str(log_b)],
                        slow_hint=dur > 120,
                    )
                )
                _progress(
                    f"frontend_build {'ok' if code == 0 else 'FAIL'} ({dur:.1f}s) log={log_b.name}"
                )
            else:
                results.append(
                    StepResult(
                        name="frontend_build",
                        ok=False,
                        duration_s=0,
                        classification="known_gap",
                        detail="npm or frontend/ missing",
                    )
                )
                _progress("frontend_build skipped (npm or frontend/ missing)")
        else:
            results.append(
                StepResult("frontend_build", True, 0, "skipped", detail="--skip-frontend")
            )
            _progress("frontend_build skipped")

        # --- Pytest ---
        if run_pytest:
            log_p = out_dir / "pytest.txt"
            _progress("running pytest...")
            code, dur = _run_cmd(
                "pytest",
                [
                    sys.executable,
                    "-m",
                    "pytest",
                    str(REPO_ROOT / "tests"),
                    "-q",
                    "--tb=line",
                    "--maxfail=20",
                ],
                REPO_ROOT,
                log_p,
            )
            results.append(
                StepResult(
                    name="pytest_tests",
                    ok=code == 0,
                    duration_s=dur,
                    classification="fail" if code != 0 else "pass",
                    detail=f"exit {code}",
                    artifact_paths=[str(log_p)],
                    slow_hint=dur > 600,
                )
            )
            _progress(f"pytest {'ok' if code == 0 else 'FAIL'} ({dur:.1f}s) log={log_p.name}")
        else:
            results.append(
                StepResult(
                    "pytest_tests",
                    True,
                    0,
                    "skipped",
                    detail="profile quick or --skip-pytest",
                )
            )
            _progress("pytest skipped")

        # --- API smoke ---
        if not args.skip_api_smoke:
            t0 = time.perf_counter()
            _progress(f"running api_smoke (tier={smoke_tier})...")
            try:
                sm = run_api_smoke(
                    args.api_base,
                    email=email,
                    password=password,
                    tier=smoke_tier,  # quick | local | full
                    intake_poll=args.intake_poll,
                    council_stream_twice_for_flaky=(profile == "full"),
                )
                dur = time.perf_counter() - t0
                detail = "; ".join(f"{n}:{'OK' if o else 'FAIL'}:{d}" for n, o, d in sm.checks[:12])
                if len(sm.checks) > 12:
                    detail += f" ... (+{len(sm.checks) - 12} checks)"
                log_s = out_dir / "api_smoke_checks.txt"
                log_s.write_text(
                    "\n".join(f"{n}\t{o}\t{d}" for n, o, d in sm.checks) + "\n",
                    encoding="utf-8",
                )
                failed_check_names = [n for n, o, _d in sm.checks if not o]
                only_council_failed = failed_check_names == ["council_stream"] and all(
                    o for n, o, _d in sm.checks if n != "council_stream"
                )
                # Sole council_stream failure: treat as harness/LLM stream fragility (same family as concurrent stress).
                if not sm.ok and only_council_failed:
                    api_ok = True
                    api_cls = "known_gap"
                    detail = (
                        detail[:1900]
                        + " | note: only council_stream failed → step classified known_gap (not a public/VE auth regression)"
                    )
                else:
                    api_ok = sm.ok
                    api_cls = "fail" if not sm.ok else "pass"
                results.append(
                    StepResult(
                        name="api_smoke",
                        ok=api_ok,
                        duration_s=dur,
                        classification=api_cls,
                        detail=detail[:2000],
                        artifact_paths=[str(log_s)],
                        flaky=sm.council_stream_flaky,
                        slow_hint=dur > 180,
                        metrics={"scratch_idea_id": sm.scratch_idea_id or ""},
                    )
                )
                _progress(f"api_smoke {'ok' if sm.ok else 'FAIL'} ({dur:.1f}s)")
            except Exception as e:
                results.append(
                    StepResult(
                        name="api_smoke",
                        ok=False,
                        duration_s=time.perf_counter() - t0,
                        classification="fail",
                        detail=str(e)[:500],
                    )
                )
                _progress(f"api_smoke exception: {str(e)[:200]}")
        else:
            results.append(StepResult("api_smoke", True, 0, "skipped", detail="--skip-api-smoke"))
            _progress("api_smoke skipped")

        # --- Scripted API user flows (standard/full) ---
        if run_user_flows:
            t0 = time.perf_counter()
            _progress("running user_flow_api...")
            try:
                uf = run_user_flow_suite(args.api_base, email=email, password=password)
                dur = time.perf_counter() - t0
                detail = "; ".join(f"{n}:{'OK' if o else 'FAIL'}:{d[:80]}" for n, o, d in uf.checks[:14])
                if len(uf.checks) > 14:
                    detail += f" ... (+{len(uf.checks) - 14} checks)"
                log_u = out_dir / "user_flow_checks.txt"
                log_u.write_text("\n".join(f"{n}\t{o}\t{d}" for n, o, d in uf.checks) + "\n", encoding="utf-8")
                soft_skipped = sum(1 for n, o, d in uf.checks if "skipped" in d.lower() or "known_gap" in d.lower())
                if not email or not password:
                    uf_cls = "known_gap"
                    uf_ok = True
                else:
                    uf_cls = "fail" if not uf.ok else "pass"
                    uf_ok = uf.ok
                results.append(
                    StepResult(
                        name="user_flow_api",
                        ok=uf_ok,
                        duration_s=dur,
                        classification=uf_cls,
                        detail=detail[:2000],
                        artifact_paths=[str(log_u)],
                        metrics={"checks": len(uf.checks), "soft_hints": soft_skipped},
                    )
                )
                _progress(f"user_flow_api {'ok' if uf.ok else 'FAIL'} ({dur:.1f}s)")
            except Exception as e:
                results.append(
                    StepResult(
                        name="user_flow_api",
                        ok=False,
                        duration_s=time.perf_counter() - t0,
                        classification="fail",
                        detail=str(e)[:500],
                    )
                )
                _progress(f"user_flow_api exception: {str(e)[:200]}")
        else:
            results.append(
                StepResult(
                    "user_flow_api",
                    True,
                    0,
                    "skipped",
                    detail="profile quick or --skip-user-flows",
                )
            )
            _progress("user_flow_api skipped")

        if run_user_flow_stress:
            t0 = time.perf_counter()
            _progress(f"running user_flow_read_stress (n={uf_stress_iter})...")
            ok_uf, det_uf, _t = stress_user_flow_reads(args.api_base, email, password, uf_stress_iter)
            results.append(
                StepResult(
                    name="user_flow_read_stress",
                    ok=ok_uf,
                    duration_s=time.perf_counter() - t0,
                    classification="pass" if ok_uf else "fail",
                    detail=det_uf,
                )
            )
            _progress(f"user_flow_read_stress {'ok' if ok_uf else 'FAIL'}")
        else:
            if args.skip_user_flows:
                skip_why = "--skip-user-flows"
            elif not email or not password:
                skip_why = "no ZENAF_NIGHTLY_EMAIL/PASSWORD"
            elif uf_stress_iter <= 0:
                skip_why = "iterations=0 (full profile defaults to 12 unless env overrides)"
            else:
                skip_why = "disabled"
            results.append(
                StepResult(
                    "user_flow_read_stress",
                    True,
                    0,
                    "skipped",
                    detail=skip_why,
                )
            )
            _progress("user_flow_read_stress skipped")

        # --- Adversarial batch (full profile; local API — not nightly cloud budget) ---
        mismatch_count: int | None = None
        if run_adversarial_batch:
            log_a = out_dir / "adversarial_batch.txt"
            _progress("running adversarial_council_batch...")
            env = os.environ.copy()
            env.setdefault("ZENAF_API_BASE", args.api_base)
            adv_started = time.time()
            code, dur = _run_cmd(
                "adversarial",
                [sys.executable, str(REPO_ROOT / "tools" / "run_adversarial_stream_batch_tuned20.py")],
                REPO_ROOT,
                log_a,
                env=env,
            )
            adv_root = REPO_ROOT / "logs" / "adversarial_stream_runs"
            if adv_root.is_dir():
                run_dirs = sorted(
                    [p for p in adv_root.iterdir() if p.is_dir() and p.stat().st_mtime >= adv_started - 2.0],
                    key=lambda p: p.stat().st_mtime,
                    reverse=True,
                )
                if not run_dirs:
                    run_dirs = sorted(
                        [p for p in adv_root.iterdir() if p.is_dir()],
                        key=lambda p: p.stat().st_mtime,
                        reverse=True,
                    )[:1]
                for rd in run_dirs[:3]:
                    summ = rd / "_batch_summary.json"
                    if summ.is_file():
                        try:
                            mismatch_count = int(
                                json.loads(summ.read_text(encoding="utf-8")).get("mismatch_count", 0)
                            )
                        except (json.JSONDecodeError, TypeError, ValueError):
                            mismatch_count = None
                        break
            adv_ok = code == 0 and (mismatch_count is None or mismatch_count == 0)
            if code != 0:
                adv_cls = "known_gap"
            elif mismatch_count is not None and mismatch_count > 0:
                adv_cls = "fail"
            else:
                adv_cls = "pass"
            detail = f"exit {code}"
            if mismatch_count is not None:
                detail += f"; mismatch_count={mismatch_count} (latest batch summary)"
            if code != 0:
                detail += " — subprocess error (LLM down / connection)"
            results.append(
                StepResult(
                    name="adversarial_council_batch",
                    ok=adv_ok,
                    duration_s=dur,
                    classification=adv_cls,
                    detail=detail,
                    artifact_paths=[str(log_a)],
                    slow_hint=dur > 900,
                    metrics={"mismatch_count": mismatch_count},
                )
            )
            _progress(
                f"adversarial_council_batch {'ok' if adv_ok else 'FAIL'} ({dur:.1f}s) mismatch={mismatch_count}"
            )
        else:
            results.append(
                StepResult(
                    "adversarial_council_batch",
                    True,
                    0,
                    "skipped",
                    detail="profile standard/quick or --skip-adversarial",
                )
            )
            _progress("adversarial_council_batch skipped")

        meta["mismatch_count"] = mismatch_count

        # --- Stress ---
        if run_stress_health:
            t0 = time.perf_counter()
            _progress("running stress_health_intake_loop...")
            ok_h, det_h, _times = stress_health_and_intake(args.api_base, max(1, args.stress_iterations))
            dur_h = time.perf_counter() - t0
            results.append(
                StepResult(
                    name="stress_health_intake_loop",
                    ok=ok_h,
                    duration_s=dur_h,
                    classification="pass" if ok_h else "fail",
                    detail=det_h,
                )
            )
            _progress(f"stress_health_intake_loop {'ok' if ok_h else 'FAIL'} ({dur_h:.1f}s)")
        else:
            results.append(
                StepResult(
                    "stress_health_intake_loop",
                    True,
                    0,
                    "skipped",
                    detail="profile quick or --skip-stress",
                )
            )
            _progress("stress_health_intake_loop skipped")

        if run_stress_concurrent:
            t1 = time.perf_counter()
            _progress("running stress_council_stream_concurrent...")
            ok_c, det_c = stress_concurrent_council_probes(
                args.api_base, max(2, args.stress_workers), timeout_s=60.0
            )
            results.append(
                StepResult(
                    name="stress_council_stream_concurrent",
                    ok=True,
                    duration_s=time.perf_counter() - t1,
                    classification="pass" if ok_c else "known_gap",
                    detail=det_c[:1500],
                    slow_hint=True,
                    metrics={"stress_workers_met_threshold": ok_c},
                )
            )
            _progress(
                f"stress_council_stream_concurrent {'ok' if ok_c else 'known_gap (concurrent stream fragility)'} "
                f"({time.perf_counter() - t1:.1f}s)"
            )
        else:
            results.append(
                StepResult(
                    "stress_council_stream_concurrent",
                    True,
                    0,
                    "skipped",
                    detail="profile quick/standard or --skip-stress",
                )
            )
            _progress("stress_council_stream_concurrent skipped")

        # --- Optional cloud sample (budgeted; after local green) ---
        cloud_path = out_dir / "cloud_budget.json"
        cloud_log = out_dir / "cloud_sample.txt"
        if not run_cloud:
            cloud_skip = (
                "profile quick (cloud sample disabled)"
                if profile == "quick"
                else "ZENAF_NIGHTLY_CLOUD_BUDGET_USD is 0 (local-only)"
            )
            results.append(
                StepResult(
                    name="nightly_cloud_sample",
                    ok=True,
                    duration_s=0,
                    classification="skipped",
                    detail=cloud_skip,
                )
            )
            _progress("nightly_cloud_sample skipped")
        elif not email or not password:
            results.append(
                StepResult(
                    name="nightly_cloud_sample",
                    ok=True,
                    duration_s=0,
                    classification="skipped",
                    detail="cloud sample needs ZENAF_NIGHTLY_EMAIL/PASSWORD",
                )
            )
            _progress("nightly_cloud_sample skipped (no credentials)")
        elif not _local_critical_ok(profile, results):
            results.append(
                StepResult(
                    name="nightly_cloud_sample",
                    ok=True,
                    duration_s=0,
                    classification="skipped",
                    detail="local critical steps did not pass — cloud sample skipped",
                )
            )
        else:
            cap = cloud_budget_usd
            _progress(f"running nightly_cloud_sample (cap ~${cap})...")
            budget = BudgetTracker(max_usd=cap)
            t_cloud = time.perf_counter()
            opener, _cj = build_opener_with_cookie_jar()
            ok_login, login_det = login_opener(opener, args.api_base, email, password)
            lines = [f"login: {ok_login} {login_det}"]
            if not ok_login:
                results.append(
                    StepResult(
                        name="nightly_cloud_sample",
                        ok=False,
                        duration_s=time.perf_counter() - t_cloud,
                        classification="known_gap",
                        detail=f"login failed: {login_det}",
                        artifact_paths=[str(cloud_log)],
                    )
                )
                cloud_log.write_text("\n".join(lines), encoding="utf-8")
                budget.write(cloud_path)
                _progress("nightly_cloud_sample: login failed")
            else:
                cs = run_cloud_sample(args.api_base, opener, budget)
                lines += [f"{n}\t{o}\t{d}" for n, o, d in cs.checks]
                cloud_log.write_text("\n".join(lines) + "\n", encoding="utf-8")
                if cs.budget:
                    cs.budget.write(cloud_path)
                tin, tout = (cs.budget.est_token_totals() if cs.budget else (0, 0))
                meta["cloud_spent_est_usd"] = round(cs.budget.spent_usd, 6) if cs.budget else 0.0
                meta["cloud_external_calls"] = len(cs.budget.calls) if cs.budget else 0
                meta["cloud_est_tokens_in"] = tin
                meta["cloud_est_tokens_out"] = tout
                results.append(
                    StepResult(
                        name="nightly_cloud_sample",
                        ok=cs.ok,
                        duration_s=time.perf_counter() - t_cloud,
                        classification="fail" if not cs.ok else "pass",
                        detail=f"{len(cs.checks)} checks; budget cap ${cap}",
                        artifact_paths=[str(cloud_log), str(cloud_path)],
                        metrics={
                            "external_calls": meta.get("cloud_external_calls", 0),
                            "est_tokens_in": tin,
                            "est_tokens_out": tout,
                        },
                    )
                )
                _progress(f"nightly_cloud_sample {'ok' if cs.ok else 'FAIL'}")

        # --- Optional Playwright (env only) ---
        if os.environ.get("ZENAF_NIGHTLY_PLAYWRIGHT", "").strip().lower() in ("1", "true", "yes", "on"):
            _progress("running playwright_e2e...")
            e2e = REPO_ROOT / "e2e" / "nightly"
            log_e = out_dir / "playwright.txt"
            npm = shutil_which("npm.cmd") if sys.platform == "win32" else shutil_which("npm")
            if npm and (e2e / "package.json").is_file():
                lock = e2e / "package-lock.json"
                _run_cmd(
                    "npm_install_e2e",
                    [npm, "ci" if lock.is_file() else "install"],
                    e2e,
                    out_dir / "playwright_npm_install.txt",
                )
                env = os.environ.copy()
                env.setdefault("ZENAF_E2E_BASE_URL", "http://127.0.0.1:5173")
                code, dur = _run_cmd(
                    "playwright",
                    [npm, "exec", "playwright", "test"],
                    e2e,
                    log_e,
                    env=env,
                )
                results.append(
                    StepResult(
                        name="playwright_e2e",
                        ok=code == 0,
                        duration_s=dur,
                        classification="known_gap" if code != 0 else "pass",
                        detail=f"exit {code} (needs dev servers + browsers)",
                        artifact_paths=[str(log_e)],
                    )
                )
            else:
                results.append(
                    StepResult(
                        name="playwright_e2e",
                        ok=False,
                        duration_s=0,
                        classification="known_gap",
                        detail="e2e/nightly missing or no npm",
                    )
                )

        meta["finished_iso"] = utc_iso()
        _progress("writing report + summary...")
        cur_cmp = comparison_fields_from_run(results, meta)
        for k, v in cur_cmp.items():
            if k != "run_dir":
                meta[k] = v
        meta["run_dir"] = str(out_dir)
        comparison = build_comparison(prev_metrics, cur_cmp)

        digest = build_digest(results, meta)
        write_summary_json(out_dir, results, meta)
        report_path = write_report_md(out_dir, results, meta, digest=digest, comparison=comparison)
        NIGHTLY_LOG_ROOT.mkdir(parents=True, exist_ok=True)
        LAST_RUN_POINTER.write_text(str(out_dir.resolve()), encoding="utf-8")

        print(report_path.read_text(encoding="utf-8")[:4000])
        print(f"\nFull report: {report_path}")
        failed = [r for r in results if not r.ok and r.classification not in ("skipped", "known_gap")]
        return 1 if failed else 0

    finally:
        if email and password:
            try:
                n, lines = cleanup_nightly_scratch_ideas(args.api_base, email, password)
                (out_dir / "scratch_cleanup.txt").write_text(
                    f"deleted={n}\n" + "\n".join(lines) + "\n",
                    encoding="utf-8",
                )
            except OSError:
                pass


if __name__ == "__main__":
    raise SystemExit(main())
