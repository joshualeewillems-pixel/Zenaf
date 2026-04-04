"""
HTTP client frontier (Philosophy #9).

Scans ``frontend/src/**/*.ts`` and ``*.tsx`` for **literal** absolute URLs passed directly to
``fetch(`` — i.e. ``fetch('http...`` / ``fetch(\"http...`` / ``fetch(`http...`` — which bypass the
designated relative bases (``VISION_EXECUTION_API``, ``API_BASE``, ``/api/...``, ``/studio/...``, etc.).

Does not flag ``fetch(\\`${API_BASE}/...\\`)`` (interpolated). Extend ``_PATH_ALLOWLIST`` if a vetted
client module must embed a full URL string.
"""
from __future__ import annotations

import re
from pathlib import Path

from ..models import CheckerRun, Finding, FindingKind
from . import register

_CHECKER_ID = "check_http_client_frontier"
_FE_SRC = Path("frontend/src")

# Suffixes of files that may intentionally contain raw absolute fetch URLs (e.g. codegen, rare).
_PATH_ALLOWLIST: frozenset[str] = frozenset()

_RAW_FETCH_HTTP = re.compile(
    r"fetch\s*\(\s*(['\"])https?://",
    re.IGNORECASE,
)
_RAW_FETCH_HTTP_TMPL = re.compile(
    r"fetch\s*\(\s*`https?://",
    re.IGNORECASE,
)


def _should_scan(path: Path) -> bool:
    if path.suffix not in (".ts", ".tsx"):
        return False
    name = path.name
    if ".test." in name or ".spec." in name:
        return False
    return True


@register("check_http_client_frontier")
def run(repo: Path) -> CheckerRun:
    out = CheckerRun(checker_id=_CHECKER_ID)
    root = repo / _FE_SRC
    if not root.is_dir():
        out.findings.append(
            Finding(
                kind=FindingKind.CONFIRMED_VIOLATION,
                message="frontend/src missing — cannot verify HTTP client frontier",
                location=str(_FE_SRC),
                checker_id=_CHECKER_ID,
            )
        )
        return out

    for fp in root.rglob("*"):
        if not fp.is_file() or not _should_scan(fp):
            continue
        rel = fp.relative_to(repo).as_posix()
        if rel in _PATH_ALLOWLIST:
            continue
        try:
            text = fp.read_text(encoding="utf-8")
        except OSError as e:
            out.findings.append(
                Finding(
                    kind=FindingKind.HEURISTIC_SUSPICION,
                    message=f"Could not read {rel}: {e}",
                    location=rel,
                    checker_id=_CHECKER_ID,
                )
            )
            continue
        for i, line in enumerate(text.splitlines(), start=1):
            if _RAW_FETCH_HTTP.search(line) or _RAW_FETCH_HTTP_TMPL.search(line):
                out.findings.append(
                    Finding(
                        kind=FindingKind.CONFIRMED_VIOLATION,
                        message=(
                            "Literal absolute URL in fetch() — use VISION_EXECUTION_API, API_BASE, "
                            "RUN_API_BASE, AUTH_BASE, or other proxied relative path (Philosophy #9)"
                        ),
                        location=f"{rel}:{i}",
                        detail=line.strip()[:220],
                        checker_id=_CHECKER_ID,
                    )
                )

    return out


def run_exploratory(repo: Path) -> CheckerRun:
    return run(repo)
