"""
Data access policy (Phase 3 / objective 3B): structural gate that the shared policy module
and `request_access` entrypoint remain present. Expand with route-level checks when Tier B/C
surfaces land.

Exemption: not used — relocate policy intentionally only with matrix + TRUTH_CONVERGENCE update.
"""
from __future__ import annotations

from pathlib import Path

from ..models import CheckerRun, Finding, FindingKind
from . import register

_POLICY_REL = "local_ai/policy/data_access.py"


@register("check_data_access_surface")
def run(repo: Path) -> CheckerRun:
    out = CheckerRun(checker_id="check_data_access_surface")
    fp = repo / _POLICY_REL
    if not fp.is_file():
        out.findings.append(
            Finding(
                kind=FindingKind.CONFIRMED_VIOLATION,
                message="data_access policy module missing — Tier B/C gate cannot be centralized",
                location=_POLICY_REL,
                checker_id="check_data_access_surface",
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
                checker_id="check_data_access_surface",
            )
        )
    return out
