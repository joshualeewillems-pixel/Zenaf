"""
Product honesty (Wave 2B / Track A): scan cockpit TS/TSX for banned UI copy (phantom AI,
Tier B/C claims). Complements product_honesty_phantom (handler-body contract).

Exemption: line contains `product-honesty-exempt`.
"""
from __future__ import annotations

import json
import re
from fnmatch import fnmatch
from pathlib import Path

from ..models import CheckerRun, Finding, FindingKind
from . import register

_EXEMPT = "product-honesty-exempt"
_CONFIG = Path(__file__).resolve().parents[1] / "config" / "check_product_honesty.json"


def _iter_files(repo: Path, globs: list[str], ignore_globs: list[str]) -> list[Path]:
    hits: list[Path] = []
    for g in globs:
        for p in repo.glob(g):
            if not p.is_file():
                continue
            rel = p.relative_to(repo).as_posix()
            if any(fnmatch(rel, ig) for ig in ignore_globs):
                continue
            hits.append(p)
    return hits


def _kind(s: str) -> FindingKind:
    return (
        FindingKind.CONFIRMED_VIOLATION
        if s == "confirmed_violation"
        else FindingKind.HEURISTIC_SUSPICION
    )


@register("check_product_honesty")
def run(repo: Path) -> CheckerRun:
    out = CheckerRun(checker_id="check_product_honesty")
    if not _CONFIG.is_file():
        out.findings.append(
            Finding(
                kind=FindingKind.HEURISTIC_SUSPICION,
                message="check_product_honesty.json missing",
                location=str(_CONFIG.relative_to(repo)),
                checker_id="check_product_honesty",
            )
        )
        return out

    cfg = json.loads(_CONFIG.read_text(encoding="utf-8"))
    globs = cfg.get("scan_globs") or ["frontend/src/**/*.tsx"]
    ignore_globs = cfg.get("ignore_globs") or []

    for fp in _iter_files(repo, globs, ignore_globs):
        rel = fp.relative_to(repo).as_posix()
        try:
            lines = fp.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for i, line in enumerate(lines, 1):
            if _EXEMPT in line:
                continue
            for rule in cfg.get("literal_bans", []):
                sub = rule.get("substring") or ""
                if not sub or sub not in line:
                    continue
                out.findings.append(
                    Finding(
                        kind=_kind(rule.get("kind") or "heuristic_suspicion"),
                        message=rule.get("message") or f"Banned UI substring {sub!r}",
                        location=f"{rel}:{i}",
                        checker_id="check_product_honesty",
                    )
                )
            for rule in cfg.get("regex_bans", []):
                pat = rule.get("pattern") or ""
                if not pat:
                    continue
                try:
                    rx = re.compile(pat)
                except re.error:
                    continue
                if not rx.search(line):
                    continue
                out.findings.append(
                    Finding(
                        kind=_kind(rule.get("kind") or "heuristic_suspicion"),
                        message=rule.get("message") or f"Regex {pat!r} matched",
                        location=f"{rel}:{i}",
                        checker_id="check_product_honesty",
                    )
                )

    return out
