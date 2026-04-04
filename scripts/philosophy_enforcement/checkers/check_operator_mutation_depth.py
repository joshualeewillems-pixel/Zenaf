"""
Operator / Studio mutation depth (Phase 4 / 4C, Philosophy #15).

Flags raw ``.commit(`` calls in ``api/routes/studio_routes.py`` and admin routes in
``api/routes/auth_routes.py`` unless a nearby ``# operator-mutation-exempt`` comment documents
an intentional bypass of canonical structured mutation helpers (Phase 2D alignment).
"""
from __future__ import annotations

import re
from pathlib import Path

from ..models import CheckerRun, Finding, FindingKind
from . import register

_CHECKER_ID = "check_operator_mutation_depth"
_FILES = (
    "api/routes/studio_routes.py",
    "api/routes/auth_routes.py",
)
_COMMIT_RE = re.compile(r"\.commit\s*\(")
_ADMIN_DEP = re.compile(r"Depends\s*\(\s*get_current_admin_user\s*\)")
_EXEMPT_MARK = "operator-mutation-exempt"


def _code_before_comment(line: str) -> str:
    return line.split("#", 1)[0]


def _line_has_commit(line: str) -> bool:
    return bool(_COMMIT_RE.search(_code_before_comment(line)))


def _window_has_exempt(lines: list[str], idx: int) -> bool:
    lo = max(0, idx - 4)
    for j in range(lo, idx + 1):
        if _EXEMPT_MARK in lines[j]:
            return True
    return False


def _scan_file(repo: Path, rel: str, out: CheckerRun) -> None:
    fp = repo / rel
    if not fp.is_file():
        out.findings.append(
            Finding(
                kind=FindingKind.CONFIRMED_VIOLATION,
                message=f"Operator route file missing: {rel}",
                location=rel,
                checker_id=_CHECKER_ID,
            )
        )
        return
    raw_lines = fp.read_text(encoding="utf-8").splitlines()
    in_admin_route = False
    for i, line in enumerate(raw_lines):
        if "@router." in line:
            in_admin_route = False
        if _ADMIN_DEP.search(line):
            in_admin_route = True
        if rel.endswith("studio_routes.py"):
            scope = True
        else:
            scope = in_admin_route
        if not scope:
            continue
        if not _line_has_commit(line):
            continue
        if _window_has_exempt(raw_lines, i):
            continue
        lineno = i + 1
        out.findings.append(
            Finding(
                kind=FindingKind.CONFIRMED_VIOLATION,
                message=(
                    f"Raw database commit in operator surface — use canonical mutation helpers or add "
                    f"`# {_EXEMPT_MARK}` with architectural rationale (Phase 4C)"
                ),
                location=f"{rel}:{lineno}",
                detail=line.strip()[:240],
                checker_id=_CHECKER_ID,
            )
        )


@register("check_operator_mutation_depth")
def run(repo: Path) -> CheckerRun:
    out = CheckerRun(checker_id=_CHECKER_ID)
    for rel in _FILES:
        _scan_file(repo, rel, out)
    return out


def run_exploratory(repo: Path) -> CheckerRun:
    return run(repo)
