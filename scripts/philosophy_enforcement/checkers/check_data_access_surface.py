"""
EXPLORATORY — NOT REGISTERED in global_philosophy_integration_matrix.json.

Structural smoke only: policy module exists + ``request_access`` symbol present.
Does **not** enforce “reads go through data_access” (path-level). Re-add ``@register``
only after implementing real gates (e.g. covered modules must import/call policy or
carry ``data-access-policy-exempt`` with inventory justification).

Manual run::

    from pathlib import Path
    from scripts.philosophy_enforcement.checkers.check_data_access_surface import run_exploratory
    run_exploratory(Path("."))
"""
from __future__ import annotations

from pathlib import Path

from ..models import CheckerRun, Finding, FindingKind

_POLICY_REL = "local_ai/policy/data_access.py"


def run_exploratory(repo: Path) -> CheckerRun:
    out = CheckerRun(checker_id="check_data_access_surface_exploratory")
    fp = repo / _POLICY_REL
    if not fp.is_file():
        out.findings.append(
            Finding(
                kind=FindingKind.CONFIRMED_VIOLATION,
                message="data_access policy module missing — Tier B/C gate cannot be centralized",
                location=_POLICY_REL,
                checker_id="check_data_access_surface_exploratory",
            )
        )
        return out
    body = fp.read_text(encoding="utf-8")
    if "def request_access(" not in body:
        out.findings.append(
            Finding(
                kind=FindingKind.CONFIRMED_VIOLATION,
                message="data_access.py missing def request_access( — policy choke point broken",
                location=_POLICY_REL,
                checker_id="check_data_access_surface_exploratory",
            )
        )
    return out
