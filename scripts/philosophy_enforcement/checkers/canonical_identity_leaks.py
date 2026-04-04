from __future__ import annotations

import json
import re
from pathlib import Path

from ..models import CheckerRun, Finding, FindingKind
from . import register


def _config(repo: Path) -> dict:
    p = repo / "scripts" / "philosophy_enforcement" / "config" / "canonical_identity.json"
    return json.loads(p.read_text(encoding="utf-8"))


def _matches_any(rel: str, patterns: list[str]) -> bool:
    return any(p in rel.replace("\\", "/") for p in patterns)


@register("canonical_identity_leaks")
def run(repo: Path) -> CheckerRun:
    out = CheckerRun(checker_id="canonical_identity_leaks")
    cfg = _config(repo)
    rx = re.compile(cfg["forbidden_regex"])
    allowed = cfg.get("allowed_path_substrings", [])

    for g in cfg.get("scan_globs", []):
        for fp in repo.glob(g):
            if not fp.is_file():
                continue
            rel = fp.relative_to(repo).as_posix()
            if _matches_any(rel, allowed):
                continue
            try:
                text = fp.read_text(encoding="utf-8")
            except OSError:
                continue
            for i, line in enumerate(text.splitlines(), 1):
                if rx.search(line):
                    kind = (
                        FindingKind.CONFIRMED_VIOLATION
                        if cfg.get("finding_kind_confirmed") == "confirmed_violation"
                        else FindingKind.HEURISTIC_SUSPICION
                    )
                    out.findings.append(
                        Finding(
                            kind=kind,
                            message="Raw profiles[0] (or equivalent) outside canonical helper",
                            location=f"{rel}:{i}",
                            detail="Use canonicalCoreProfile.ts (or server equivalent) per matrix §6.",
                            checker_id="canonical_identity_leaks",
                        )
                    )
    return out
