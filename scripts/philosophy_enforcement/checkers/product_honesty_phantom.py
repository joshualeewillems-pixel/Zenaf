from __future__ import annotations

import json
import re
from fnmatch import fnmatch
from pathlib import Path

from ..models import CheckerRun, Finding, FindingKind
from . import register


def _config_path(repo: Path) -> Path:
    return repo / "scripts" / "philosophy_enforcement" / "config" / "product_honesty.json"


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


@register("product_honesty_phantom")
def run(repo: Path) -> CheckerRun:
    out = CheckerRun(checker_id="product_honesty_phantom")
    cfg = json.loads(_config_path(repo).read_text(encoding="utf-8"))

    for chk in cfg.get("phantom_ui_checks", []):
        rel = chk["file"]
        fp = repo / rel
        if not fp.is_file():
            out.findings.append(
                Finding(
                    kind=FindingKind.HEURISTIC_SUSPICION,
                    message=f"Phantom check skipped — file missing: {rel}",
                    location=rel,
                    checker_id="product_honesty_phantom",
                )
            )
            continue
        text = fp.read_text(encoding="utf-8")
        label = chk["label_substring"]
        if label not in text:
            continue
        if chk.get("handler_name_substring") and chk["handler_name_substring"] not in text:
            continue
        hname = chk["handler_name_substring"]
        pos = text.find(f"const {hname}") if hname else -1
        if pos < 0:
            pos = text.find(hname) if hname else 0
        n = int(chk.get("body_scan_chars", 800))
        block = text[pos : pos + n] if pos >= 0 else text[:n]
        required = chk.get("if_label_present_then_body_must_contain_one_of") or []
        if any(s in block for s in required):
            continue
        kind = (
            FindingKind.CONFIRMED_VIOLATION
            if chk.get("kind_if_violation") == "confirmed_violation"
            else FindingKind.HEURISTIC_SUSPICION
        )
        out.findings.append(
            Finding(
                kind=kind,
                message=f'UI label "{label}" without API/network in handler body (phantom AI risk)',
                location=rel,
                detail="See charter_enforcement_check.check_phantom_clarify and ACTIVE_VS_PLANNED.md.",
                checker_id="product_honesty_phantom",
            )
        )

    for h in cfg.get("tier_contract_heuristics", []):
        rx = re.compile(h["regex"])
        cap = int(h.get("max_findings_per_rule", 40))
        n = 0
        for fp in _iter_files(repo, h.get("globs", []), h.get("ignore_globs", [])):
            if n >= cap:
                break
            try:
                t = fp.read_text(encoding="utf-8")
            except OSError:
                continue
            for i, line in enumerate(t.splitlines(), 1):
                if n >= cap:
                    break
                if rx.search(line):
                    rel = fp.relative_to(repo).as_posix()
                    out.findings.append(
                        Finding(
                            kind=FindingKind.HEURISTIC_SUSPICION,
                            message=f"Possible Tier B/C user-facing copy ({h['id']})",
                            location=f"{rel}:{i}",
                            detail=h.get("note", ""),
                            checker_id="product_honesty_phantom",
                        )
                    )
                    n += 1

    return out
