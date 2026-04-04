"""
Execution seam (Phase 3C / Track A): structural gate that ``seam_routing.apply_seam_routing`` exists.
Complements ``execution_seam_bypasses`` (get_default_provider scan + JSON structural checks).

Does not modify product code.
"""
from __future__ import annotations

from pathlib import Path

from ..models import CheckerRun, Finding, FindingKind
from . import register

_SEAM_REL = "local_ai/execution_policy/seam_routing.py"


@register("check_execution_seam_surface")
def run(repo: Path) -> CheckerRun:
    out = CheckerRun(checker_id="check_execution_seam_surface")
    fp = repo / _SEAM_REL
    if not fp.is_file():
        out.findings.append(
            Finding(
                kind=FindingKind.CONFIRMED_VIOLATION,
                message="seam_routing module missing — execution seam contract broken",
                location=_SEAM_REL,
                checker_id="check_execution_seam_surface",
            )
        )
        return out
    body = fp.read_text(encoding="utf-8")
    if "def apply_seam_routing(" not in body:
        out.findings.append(
            Finding(
                kind=FindingKind.CONFIRMED_VIOLATION,
                message="seam_routing.py missing apply_seam_routing — VE/run routing helper absent",
                location=_SEAM_REL,
                checker_id="check_execution_seam_surface",
            )
        )
    return out


def run_exploratory(repo: Path) -> CheckerRun:
    """Alias for manual invocation; same as matrix-gated ``run``."""
    return run(repo)
