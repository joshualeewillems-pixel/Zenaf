from __future__ import annotations

import json
from pathlib import Path

from ..models import CheckerRun, Finding, FindingKind
from . import register


def _config(repo: Path) -> dict:
    p = repo / "scripts" / "philosophy_enforcement" / "config" / "execution_seam.json"
    return json.loads(p.read_text(encoding="utf-8"))


def _norm_rel(p: Path, repo: Path) -> str:
    return p.relative_to(repo).as_posix()


@register("execution_seam_bypasses")
def run(repo: Path) -> CheckerRun:
    out = CheckerRun(checker_id="execution_seam_bypasses")
    cfg = _config(repo)
    call_ok = cfg.get("get_default_provider_call_allowed_path_substrings", [])
    mention_ok = cfg.get("get_default_provider_string_mention_allowed_path_substrings", [])
    needle = "get_default_provider("

    for root_name in cfg.get("scan_roots", []):
        root = repo / root_name
        if not root.is_dir():
            continue
        globpat = cfg.get("scan_glob", "**/*.py")
        for fp in root.glob(globpat):
            if not fp.is_file():
                continue
            rel = _norm_rel(fp, repo)
            if any(s in rel for s in mention_ok):
                continue
            try:
                text = fp.read_text(encoding="utf-8")
            except OSError:
                continue
            if needle not in text:
                continue
            if any(s in rel for s in call_ok):
                for i, line in enumerate(text.splitlines(), 1):
                    if needle in line and "def get_default_provider" not in line:
                        out.findings.append(
                            Finding(
                                kind=FindingKind.CONFIRMED_VIOLATION,
                                message="Unexpected get_default_provider( usage in providers package",
                                location=f"{rel}:{i}",
                                detail="Matrix §7: new call sites require CODEBASE_TRUTH_RULES.md update.",
                                checker_id="execution_seam_bypasses",
                            )
                        )
                continue
            for i, line in enumerate(text.splitlines(), 1):
                if needle in line:
                    out.findings.append(
                        Finding(
                            kind=FindingKind.CONFIRMED_VIOLATION,
                            message="get_default_provider( call site outside allowed definition module",
                            location=f"{rel}:{i}",
                            detail="Prefer routed seam (_run_ve_llm_with_routing / apply_seam_routing / resolver).",
                            checker_id="execution_seam_bypasses",
                        )
                    )

    for chk in cfg.get("structural_checks", []):
        rel = chk["path"]
        fp = repo / rel
        if not fp.is_file():
            out.findings.append(
                Finding(
                    kind=FindingKind.CONFIRMED_VIOLATION,
                    message=f"Structural seam check — file missing: {rel}",
                    location=rel,
                    checker_id="execution_seam_bypasses",
                )
            )
            continue
        body = fp.read_text(encoding="utf-8")
        for sub in chk.get("must_contain_substrings", []):
            if sub not in body:
                out.findings.append(
                    Finding(
                        kind=FindingKind.CONFIRMED_VIOLATION,
                        message=f"Execution seam contract substring missing: {sub!r}",
                        location=rel,
                        detail=f"Check id: {chk.get('id', '')}",
                        checker_id="execution_seam_bypasses",
                    )
                )

    return out
