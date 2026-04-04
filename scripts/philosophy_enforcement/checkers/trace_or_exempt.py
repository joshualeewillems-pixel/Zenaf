from __future__ import annotations

import importlib.util
from pathlib import Path

from ..models import CheckerRun, Finding, FindingKind
from . import register


def _load_charter_module(repo: Path):
    path = repo / "scripts" / "charter_enforcement_check.py"
    spec = importlib.util.spec_from_file_location("charter_enforcement_check", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load charter script at {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@register("trace_or_exempt")
def run(repo: Path) -> CheckerRun:
    out = CheckerRun(checker_id="trace_or_exempt")
    try:
        ch = _load_charter_module(repo)
        exempt = ch._load_exempt_ids()  # noqa: SLF001
        trace_findings = ch.check_trace_ve_routes(exempt)
        gateway = ch.check_run_gateway()
    except Exception as e:
        out.error = str(e)
        return out

    for f in trace_findings:
        kind = FindingKind.HEURISTIC_SUSPICION
        det = f.get("detail", "")
        led = f.get("ledger", "")
        if "gateway" not in led.lower() and "client-primary" not in det.lower():
            kind = FindingKind.CONFIRMED_VIOLATION
        out.findings.append(
            Finding(
                kind=kind,
                message=f.get("rule", "Trace / exempt"),
                location=f.get("where", ""),
                detail=det,
                checker_id="trace_or_exempt",
            )
        )

    for f in gateway:
        # Charter informational only: /run primary trace is client AiActionTrace (workspaceRunWithTrace).
        # Do not surface as philosophy partial — matrix row 1 already documents this split.
        led = (f.get("ledger") or "").lower()
        if "client-primary gateway" in led:
            continue
        out.findings.append(
            Finding(
                kind=FindingKind.HEURISTIC_SUSPICION,
                message=f.get("rule", "Run gateway"),
                location=f.get("where", ""),
                detail=f.get("detail", ""),
                checker_id="trace_or_exempt",
            )
        )

    return out
