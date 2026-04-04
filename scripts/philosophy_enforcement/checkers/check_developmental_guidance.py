"""
Developmental guidance boundary (Philosophy #12).

``developmental_guidance`` is a **council preflight** optional packet (hypothesis-level context).
It must not become a parallel channel into durable profile truth or unrelated API surfaces.

Scans ``local_ai/**/*.py`` and ``api/**/*.py`` (excluding ``tests/``, ``scripts/``) for the
identifier ``developmental_guidance``. Only these modules may reference it:

- ``local_ai/council_preflight.py`` — parse + enrich path
- ``local_ai/developmental_guidance.py`` — normalization + packet formatting
- ``local_ai/aspiration_layer.py`` — aspiration reasons only
"""
from __future__ import annotations

import re
from pathlib import Path

from ..models import CheckerRun, Finding, FindingKind
from . import register

_CHECKER_ID = "check_developmental_guidance"

_ALLOWED_SUFFIXES: frozenset[str] = frozenset(
    {
        "local_ai/council_preflight.py",
        "local_ai/developmental_guidance.py",
        "local_ai/aspiration_layer.py",
    }
)

_NEEDLE = re.compile(r"\bdevelopmental_guidance\b")


def _scan_tree(repo: Path, base: Path, out: CheckerRun) -> None:
    if not base.is_dir():
        return
    for path in base.rglob("*.py"):
        rel = path.relative_to(repo).as_posix()
        if rel.startswith("tests/") or rel.startswith("scripts/"):
            continue
        if rel in _ALLOWED_SUFFIXES:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
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
        if not _NEEDLE.search(text):
            continue
        for i, line in enumerate(text.splitlines(), start=1):
            if _NEEDLE.search(line) and not line.lstrip().startswith("#"):
                out.findings.append(
                    Finding(
                        kind=FindingKind.CONFIRMED_VIOLATION,
                        message=(
                            "developmental_guidance referenced outside allowed modules — keep guidance "
                            "on council_preflight / formatting / aspiration reasons only (Philosophy #12)"
                        ),
                        location=f"{rel}:{i}",
                        detail=line.strip()[:220],
                        checker_id=_CHECKER_ID,
                    )
                )
                break


@register("check_developmental_guidance")
def run(repo: Path) -> CheckerRun:
    out = CheckerRun(checker_id=_CHECKER_ID)
    _scan_tree(repo, repo / "local_ai", out)
    _scan_tree(repo, repo / "api", out)
    return out


def run_exploratory(repo: Path) -> CheckerRun:
    return run(repo)
