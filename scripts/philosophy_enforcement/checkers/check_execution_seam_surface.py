"""
Execution seam (Phase 3 / objective 3C): structural gate that `seam_routing.apply_seam_routing`
remains the declared routing helper. Complements `execution_seam_bypasses` (get_default_provider
call-site scan + JSON structural checks).

Exemption: none — moving the seam requires CODEBASE_TRUTH_RULES + matrix update together.
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
