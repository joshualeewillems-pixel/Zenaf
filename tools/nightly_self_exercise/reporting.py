from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class StepResult:
    name: str
    ok: bool
    duration_s: float
    classification: str  # pass | fail | skipped | known_gap
    detail: str = ""
    flaky: bool = False
    artifact_paths: list[str] = field(default_factory=list)
    slow_hint: bool = False
    metrics: dict[str, Any] = field(default_factory=dict)


def _failures(results: list[StepResult]) -> list[StepResult]:
    return [r for r in results if not r.ok and r.classification not in ("skipped", "known_gap")]


def build_digest(results: list[StepResult], meta: dict[str, Any]) -> dict[str, Any]:
    fails = _failures(results)
    flaky = [r for r in results if r.flaky]
    gaps = [r for r in results if r.classification == "known_gap"]
    slow = max(results, key=lambda r: r.duration_s) if results else None
    if fails:
        r0 = fails[0]
        inspect = (
            f"Open `{r0.artifact_paths[0]}`" if r0.artifact_paths else f"Step `{r0.name}` — {r0.detail[:160]}"
        )
    elif flaky:
        inspect = f"Re-run or inspect flaky step `{flaky[0].name}` (see detail below)."
    else:
        inspect = "No hard failures — skim `pytest.txt` / `api_smoke_checks.txt` / `cloud_budget.json` (if present)."
    return {
        "overall": "FAIL" if fails else "PASS",
        "profile": meta.get("profile", ""),
        "new_bugs": [r.name for r in fails],
        "flaky_steps": [r.name for r in flaky],
        "known_gap_steps": [r.name for r in gaps],
        "slowest_step": (slow.name, round(slow.duration_s, 2)) if slow else ("", 0),
        "first_place_to_inspect": inspect,
        "cloud_spent_est_usd": meta.get("cloud_spent_est_usd"),
        "cloud_calls": meta.get("cloud_external_calls"),
    }


def load_metrics_from_summary(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    rs = data.get("results") or []
    fail_n = sum(
        1
        for r in rs
        if not r.get("ok") and r.get("classification") not in ("skipped", "known_gap")
    )
    flaky_n = sum(1 for r in rs if r.get("flaky"))
    dur = sum(float(r.get("duration_s") or 0) for r in rs)
    mismatch = data.get("meta", {}).get("mismatch_count")
    return {
        "fail_count": fail_n,
        "flaky_count": flaky_n,
        "mismatch_count": mismatch,
        "total_duration_s": round(dur, 2),
        "run_dir": str(path.parent),
    }


def build_comparison(prev: dict[str, Any], cur_meta: dict[str, Any]) -> dict[str, Any] | None:
    if not prev:
        return None
    return {
        "previous_run_dir": prev.get("run_dir", ""),
        "delta_fail_count": cur_meta.get("fail_count", 0) - prev.get("fail_count", 0),
        "delta_flaky_count": cur_meta.get("flaky_count", 0) - prev.get("flaky_count", 0),
        "delta_mismatch_count": _delta_mismatch(cur_meta.get("mismatch_count"), prev.get("mismatch_count")),
        "delta_total_duration_s": round(
            float(cur_meta.get("total_duration_s", 0)) - float(prev.get("total_duration_s", 0)),
            2,
        ),
    }


def comparison_fields_from_run(results: list[StepResult], meta: dict[str, Any]) -> dict[str, Any]:
    fail_n = sum(
        1
        for r in results
        if not r.ok and r.classification not in ("skipped", "known_gap")
    )
    flaky_n = sum(1 for r in results if r.flaky)
    dur = round(sum(r.duration_s for r in results), 2)
    return {
        "fail_count": fail_n,
        "flaky_count": flaky_n,
        "mismatch_count": meta.get("mismatch_count"),
        "total_duration_s": dur,
        "run_dir": meta.get("out_dir", ""),
    }


def _delta_mismatch(cur: Any, prev: Any) -> str:
    if cur is None and prev is None:
        return "n/a"
    if cur is None or prev is None:
        return f"{cur} vs {prev}"
    try:
        return str(int(cur) - int(prev))
    except (TypeError, ValueError):
        return "n/a"


def write_report_md(
    out_dir: Path,
    results: list[StepResult],
    meta: dict[str, Any],
    *,
    digest: dict[str, Any] | None = None,
    comparison: dict[str, Any] | None = None,
) -> Path:
    """Single morning markdown artifact."""
    path = out_dir / "NIGHTLY_REPORT.md"
    lines: list[str] = []
    lines.append(f"# Nightly self-exercise — {meta.get('started_iso', '')}")
    lines.append("")
    d = digest or build_digest(results, meta)
    lines.append("## Morning digest")
    lines.append(f"- **Overall:** **{d['overall']}** (profile: `{d.get('profile') or meta.get('profile', '')}`)")
    lines.append(f"- **New bugs (hard failures):** {len(d['new_bugs'])} — {', '.join(d['new_bugs']) or 'none'}")
    lines.append(f"- **Flaky steps:** {', '.join(d['flaky_steps']) or 'none'}")
    lines.append(f"- **Known-gap steps:** {len(d['known_gap_steps'])} — {', '.join(d['known_gap_steps'][:12])}{' …' if len(d['known_gap_steps']) > 12 else ''}")
    ss, sv = d.get("slowest_step") or ("", 0)
    lines.append(f"- **Slowest step:** `{ss}` ({sv}s)")
    lines.append(f"- **First place to inspect:** {d['first_place_to_inspect']}")
    if d.get("cloud_spent_est_usd") is not None:
        lines.append(
            f"- **Cloud sample (est.):** ${d['cloud_spent_est_usd']} — {d.get('cloud_calls')} external calls logged"
        )
    lines.append("")
    if comparison:
        lines.append("## Run-to-run comparison")
        lines.append(f"- **Previous run:** `{comparison.get('previous_run_dir', '')}`")
        lines.append(f"- **Delta fail count:** {comparison.get('delta_fail_count')}")
        lines.append(f"- **Delta flaky count:** {comparison.get('delta_flaky_count')}")
        lines.append(f"- **Delta mismatch count:** {comparison.get('delta_mismatch_count')}")
        lines.append(f"- **Delta total duration (sum of steps):** {comparison.get('delta_total_duration_s')}s")
        lines.append("")
    lines.append("## Safety")
    lines.append(
        "- Read-only harness: no code rewrites, no schema changes, no mailbox mutation, no auto-fix commits.\n"
        "- Does not persist developmental guidance or profile interpretations.\n"
        "- Adversarial / council / LLM paths only exercise existing APIs and tools.\n"
    )
    lines.append("## Pass / fail summary")
    ok_n = sum(1 for r in results if r.ok)
    lines.append(f"- Steps: **{ok_n}/{len(results)}** passed")
    lines.append("")
    lines.append("| Step | Status | Class | s | Flaky? | Detail |")
    lines.append("|------|--------|-------|---|--------|--------|")
    for r in results:
        if r.classification == "skipped":
            st = "SKIP"
        elif r.classification == "known_gap":
            st = "GAP"
        else:
            st = "PASS" if r.ok else "FAIL"
        fl = "yes" if r.flaky else ""
        det = (r.detail or "").replace("|", "\\|").replace("\n", " ")[:120]
        lines.append(f"| {r.name} | {st} | {r.classification} | {r.duration_s:.2f} | {fl} | {det} |")
    lines.append("")
    lines.append("## Flaky vs repeatable")
    flaky = [r for r in results if r.flaky]
    if flaky:
        lines.append("Marked flaky (inconsistent across duplicate attempts in this run):")
        for r in flaky:
            lines.append(f"- **{r.name}**: {r.detail}")
    else:
        lines.append("- No flaky flags raised by this harness.")
    lines.append("")
    lines.append("## Known-gap vs new-bug")
    lines.append(
        "- **known_gap**: Missing credentials, LLM/stream fragility (concurrent council stress, sole `council_stream` smoke miss), "
        "Playwright not installed, export gate (`ATRIA_LEARNING_EXPORT_ENABLED`), etc.\n"
        "- **new-bug**: Unexpected 5xx, pytest regression, adversarial mismatch count increase — investigate.\n"
        "- **Table:** `GAP` = `known_gap` (informational; not counted as a hard failure in the digest).\n"
    )
    gaps = [r for r in results if r.classification == "known_gap"]
    bugs = [r for r in results if not r.ok and r.classification not in ("skipped", "known_gap")]
    lines.append(f"- Known-gap steps: {len(gaps)}")
    for r in gaps:
        lines.append(f"  - {r.name}: {r.detail}")
    lines.append(f"- Suspected new-bug failures: {len(bugs)}")
    for r in bugs:
        lines.append(f"  - **{r.name}**: {r.detail}")
    lines.append("")
    lines.append("## Slowest flows")
    slow = sorted(results, key=lambda x: -x.duration_s)[:8]
    for r in slow:
        flag = " (slow)" if r.slow_hint or r.duration_s > 120 else ""
        lines.append(f"- {r.name}: **{r.duration_s:.1f}s**{flag}")
    lines.append("")
    lines.append("## Artifacts / logs")
    lines.append(f"- Output directory: `{out_dir}`")
    lines.append(
        "- Playwright (when enabled): HTML report and failure screenshots under `e2e/nightly/playwright-report/` "
        "and `e2e/nightly/test-results/`."
    )
    for r in results:
        for ap in r.artifact_paths:
            lines.append(f"- `{ap}`")
    lines.append("")
    lines.append("## Meta")
    lines.append("```json")
    lines.append(json.dumps(meta, indent=2)[:8000])
    lines.append("```")
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def write_summary_json(out_dir: Path, results: list[StepResult], meta: dict[str, Any]) -> Path:
    path = out_dir / "summary.json"
    payload = {
        "meta": meta,
        "results": [
            {
                "name": r.name,
                "ok": r.ok,
                "duration_s": r.duration_s,
                "classification": r.classification,
                "detail": r.detail,
                "flaky": r.flaky,
                "artifact_paths": r.artifact_paths,
                "metrics": r.metrics,
            }
            for r in results
        ],
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def utc_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
