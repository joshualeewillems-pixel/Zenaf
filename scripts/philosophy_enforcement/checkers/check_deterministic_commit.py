"""
Deterministic commit / explicit payload (Wave 2D): integration_commit must keep the
[DRAFT_VALUE: …] contract; zenaf_tools call sites of infer_draft_value_from_context must
carry a nearby `deterministic-commit` audit marker (comment within preceding lines).

Exemption: not applicable — fix by adding the marker or removing the call.
"""
from __future__ import annotations

from pathlib import Path

from ..models import CheckerRun, Finding, FindingKind
from . import register

_IC_MARKERS = (
    "_DRAFT_VALUE_RE",
    "infer_draft_value_from_context",
    "extract_draft_value_for_pending",
)
_LOOKBACK = 16


@register("check_deterministic_commit")
def run(repo: Path) -> CheckerRun:
    out = CheckerRun(checker_id="check_deterministic_commit")
    ic = repo / "local_ai" / "integration_commit.py"
    if not ic.is_file():
        out.findings.append(
            Finding(
                kind=FindingKind.CONFIRMED_VIOLATION,
                message="integration_commit.py missing — explicit payload contract absent",
                location="local_ai/integration_commit.py",
                checker_id="check_deterministic_commit",
            )
        )
        return out
    ic_text = ic.read_text(encoding="utf-8")
    for sub in _IC_MARKERS:
        if sub not in ic_text:
            out.findings.append(
                Finding(
                    kind=FindingKind.CONFIRMED_VIOLATION,
                    message=f"integration_commit.py missing expected contract fragment {sub!r}",
                    location="local_ai/integration_commit.py",
                    checker_id="check_deterministic_commit",
                )
            )

    atools = repo / "local_ai" / "zenaf_tools.py"
    if not atools.is_file():
        return out
    lines = atools.read_text(encoding="utf-8").splitlines()
    for i, line in enumerate(lines):
        if "infer_draft_value_from_context(" not in line:
            continue
        pre = "\n".join(lines[max(0, i - _LOOKBACK) : i])
        if "deterministic-commit" in pre:
            continue
        out.findings.append(
            Finding(
                kind=FindingKind.CONFIRMED_VIOLATION,
                message="infer_draft_value_from_context( call without nearby deterministic-commit audit marker",
                location=f"local_ai/zenaf_tools.py:{i + 1}",
                detail="Prefer [DRAFT_VALUE: …] from the model; narrow fallback must be explicitly audited.",
                checker_id="check_deterministic_commit",
            )
        )

    return out
