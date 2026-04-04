"""
EXPLORATORY — NOT REGISTERED in global_philosophy_integration_matrix.json.

Structural smoke only: ``seam_routing`` module exists + ``apply_seam_routing`` defined.
Does **not** verify routed VE/run paths use the seam. Production gate remains
``execution_seam_bypasses``. Re-add ``@register`` only with path-level checks
(e.g. allowlisted files must call ``apply_seam_routing`` / ``_run_ve_llm_with_routing``).

Manual run::

    from pathlib import Path
    from scripts.philosophy_enforcement.checkers.check_execution_seam_surface import run_exploratory
    run_exploratory(Path("."))
"""
from __future__ import annotations

from pathlib import Path

from ..models import CheckerRun, Finding, FindingKind

_SEAM_REL = "local_ai/execution_policy/seam_routing.py"


def run_exploratory(repo: Path) -> CheckerRun:
    out = CheckerRun(checker_id="check_execution_seam_surface_exploratory")
    fp = repo / _SEAM_REL
    if not fp.is_file():
        out.findings.append(
            Finding(
                kind=FindingKind.CONFIRMED_VIOLATION,
                message="seam_routing module missing — execution seam contract broken",
                location=_SEAM_REL,
                checker_id="check_execution_seam_surface_exploratory",
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
                checker_id="check_execution_seam_surface_exploratory",
            )
        )
    return out
