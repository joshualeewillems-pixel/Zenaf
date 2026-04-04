"""
Operator / Studio boundaries (Phase 4 / Track A, Philosophy #15).

1. **Authorization:** ``api/routes/studio_routes.py`` — every ``@router`` handler block must use
   ``Depends(get_current_admin_user)``; the file must not use ``Depends(get_current_user)`` for route deps.

2. **Trace exemption contract:** ``docs/01_TRUTH/ai_trace_exemptions.json`` must declare at least one
   ``exempt_routes`` entry covering ``/studio``, with ``reason`` referencing ``studio_admin_surface``
   (ties operator trace carve-out to the stable exempt id from Phase 2).

3. **Client registry parity:** ``frontend/src/ai-actions/aiTraceExemptRegistry.ts`` must list exempt id
   ``studio_admin_surface`` (read-only scan; no edits to that file from this checker).

Does not execute the app. Does not modify ``api/`` or ``frontend/src/``.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from ..models import CheckerRun, Finding, FindingKind
from . import register

_CHECKER_ID = "check_operator_boundaries"
_STUDIO_REL = "api/routes/studio_routes.py"
_EXEMPTIONS_REL = "docs/01_TRUTH/ai_trace_exemptions.json"
_TS_REGISTRY_REL = "frontend/src/ai-actions/aiTraceExemptRegistry.ts"
_ROUTE_START = re.compile(r"^@router\.(get|post|put|patch|delete)\(", re.MULTILINE)
_STUDIO_ADMIN_ID = re.compile(r"id\s*:\s*['\"]studio_admin_surface['\"]")


def _scan_studio_router(repo: Path, out: CheckerRun) -> None:
    fp = repo / _STUDIO_REL
    if not fp.is_file():
        out.findings.append(
            Finding(
                kind=FindingKind.CONFIRMED_VIOLATION,
                message="studio_routes.py missing — cannot verify /studio admin authorization",
                location=_STUDIO_REL,
                checker_id=_CHECKER_ID,
            )
        )
        return
    text = fp.read_text(encoding="utf-8")
    if "get_current_admin_user" not in text:
        out.findings.append(
            Finding(
                kind=FindingKind.CONFIRMED_VIOLATION,
                message="Studio router must use get_current_admin_user for admin gate",
                location=_STUDIO_REL,
                checker_id=_CHECKER_ID,
            )
        )
        return
    if re.search(r"Depends\s*\(\s*get_current_user\s*\)", text):
        out.findings.append(
            Finding(
                kind=FindingKind.CONFIRMED_VIOLATION,
                message="Studio router must not use Depends(get_current_user) — use get_current_admin_user",
                location=_STUDIO_REL,
                checker_id=_CHECKER_ID,
            )
        )
    indices = [m.start() for m in _ROUTE_START.finditer(text)]
    if not indices:
        out.findings.append(
            Finding(
                kind=FindingKind.CONFIRMED_VIOLATION,
                message="No @router.* route decorators found in studio_routes.py",
                location=_STUDIO_REL,
                checker_id=_CHECKER_ID,
            )
        )
        return
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
                    checker_id=_CHECKER_ID,
                )
            )


def _scan_trace_exemptions_json(repo: Path, out: CheckerRun) -> None:
    fp = repo / _EXEMPTIONS_REL
    if not fp.is_file():
        out.findings.append(
            Finding(
                kind=FindingKind.CONFIRMED_VIOLATION,
                message="ai_trace_exemptions.json missing — cannot validate studio_admin_surface trace carve-out",
                location=_EXEMPTIONS_REL,
                checker_id=_CHECKER_ID,
            )
        )
        return
    try:
        data = json.loads(fp.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        out.findings.append(
            Finding(
                kind=FindingKind.CONFIRMED_VIOLATION,
                message=f"ai_trace_exemptions.json invalid JSON: {e}",
                location=_EXEMPTIONS_REL,
                checker_id=_CHECKER_ID,
            )
        )
        return
    routes = data.get("exempt_routes")
    if not isinstance(routes, list):
        out.findings.append(
            Finding(
                kind=FindingKind.CONFIRMED_VIOLATION,
                message="ai_trace_exemptions.json missing exempt_routes array",
                location=_EXEMPTIONS_REL,
                checker_id=_CHECKER_ID,
            )
        )
        return
    studio_entries: list[dict] = []
    for item in routes:
        if not isinstance(item, dict):
            continue
        pc = str(item.get("path_contains") or "")
        if "/studio" in pc:
            studio_entries.append(item)
    if not studio_entries:
        out.findings.append(
            Finding(
                kind=FindingKind.CONFIRMED_VIOLATION,
                message="exempt_routes must include a /studio path_contains entry (operator trace boundary per Philosophy #15)",
                location=_EXEMPTIONS_REL,
                checker_id=_CHECKER_ID,
            )
        )
        return
    id_needle = "studio_admin_surface"
    if not any(id_needle in str(e.get("reason") or "").lower() for e in studio_entries):
        out.findings.append(
            Finding(
                kind=FindingKind.CONFIRMED_VIOLATION,
                message=f"/studio exempt_routes entries must reference {id_needle!r} in reason (align with aiTraceExemptRegistry)",
                location=_EXEMPTIONS_REL,
                checker_id=_CHECKER_ID,
            )
        )


def _scan_ts_registry(repo: Path, out: CheckerRun) -> None:
    fp = repo / _TS_REGISTRY_REL
    if not fp.is_file():
        out.findings.append(
            Finding(
                kind=FindingKind.CONFIRMED_VIOLATION,
                message="aiTraceExemptRegistry.ts missing — studio_admin_surface exempt id must exist for charter §4.1",
                location=_TS_REGISTRY_REL,
                checker_id=_CHECKER_ID,
            )
        )
        return
    body = fp.read_text(encoding="utf-8")
    if not _STUDIO_ADMIN_ID.search(body):
        out.findings.append(
            Finding(
                kind=FindingKind.CONFIRMED_VIOLATION,
                message="aiTraceExemptRegistry.ts must declare exempt id 'studio_admin_surface' (Philosophy #15 / matrix)",
                location=_TS_REGISTRY_REL,
                checker_id=_CHECKER_ID,
            )
        )


@register("check_operator_boundaries")
def run(repo: Path) -> CheckerRun:
    out = CheckerRun(checker_id=_CHECKER_ID)
    _scan_studio_router(repo, out)
    _scan_trace_exemptions_json(repo, out)
    _scan_ts_registry(repo, out)
    return out


def run_exploratory(repo: Path) -> CheckerRun:
    return run(repo)
