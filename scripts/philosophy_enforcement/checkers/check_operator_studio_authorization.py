"""
Operator / Studio surfaces (Phase 4 / Track A): ``/studio`` API routes must use
``Depends(get_current_admin_user)`` so operator tooling does not bypass admin authorization.

Structural scan of ``api/routes/studio_routes.py`` only; does not execute the app.
"""
from __future__ import annotations

import re
from pathlib import Path

from ..models import CheckerRun, Finding, FindingKind
from . import register

_STUDIO_REL = "api/routes/studio_routes.py"
_ROUTE_START = re.compile(r"^@router\.(get|post|put|patch|delete)\(", re.MULTILINE)


@register("check_operator_studio_authorization")
def run(repo: Path) -> CheckerRun:
    out = CheckerRun(checker_id="check_operator_studio_authorization")
    fp = repo / _STUDIO_REL
    if not fp.is_file():
        out.findings.append(
            Finding(
                kind=FindingKind.CONFIRMED_VIOLATION,
                message="studio_routes.py missing — cannot verify operator/studio auth surface",
                location=_STUDIO_REL,
                checker_id="check_operator_studio_authorization",
            )
        )
        return out
    text = fp.read_text(encoding="utf-8")
    if "get_current_admin_user" not in text:
        out.findings.append(
            Finding(
                kind=FindingKind.CONFIRMED_VIOLATION,
                message="studio routes must use get_current_admin_user for admin gate",
                location=_STUDIO_REL,
                checker_id="check_operator_studio_authorization",
            )
        )
        return out
    if re.search(r"Depends\s*\(\s*get_current_user\s*\)", text):
        out.findings.append(
            Finding(
                kind=FindingKind.CONFIRMED_VIOLATION,
                message="studio router must not use Depends(get_current_user) — use get_current_admin_user for /studio",
                location=_STUDIO_REL,
                checker_id="check_operator_studio_authorization",
            )
        )
    indices = [m.start() for m in _ROUTE_START.finditer(text)]
    if not indices:
        out.findings.append(
            Finding(
                kind=FindingKind.CONFIRMED_VIOLATION,
                message="No @router.* route decorators found in studio_routes.py",
                location=_STUDIO_REL,
                checker_id="check_operator_studio_authorization",
            )
        )
        return out
    for i, start in enumerate(indices):
        end = indices[i + 1] if i + 1 < len(indices) else len(text)
        block = text[start:end]
        if "Depends(get_current_admin_user)" not in block:
            route_line = block.split("\n", 1)[0].strip()
            out.findings.append(
                Finding(
                    kind=FindingKind.CONFIRMED_VIOLATION,
                    message="Studio route block missing Depends(get_current_admin_user)",
                    location=f"{_STUDIO_REL}:{text[:start].count(chr(10)) + 1}",
                    detail=route_line[:200],
                    checker_id="check_operator_studio_authorization",
                )
            )
    return out


def run_exploratory(repo: Path) -> CheckerRun:
    return run(repo)
