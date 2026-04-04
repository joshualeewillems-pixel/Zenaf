"""
Mirror graph interpretation (Phase 3A / Track A): structural gates so staging rows are not
interpreted via ad-hoc row['interpretation'] assignment outside ``graph_interpretation.py``,
and required extract paths still wire ``interpret_against_graph``.

Does not modify product code. See config/check_mirror_interpretation.json.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from ..models import CheckerRun, Finding, FindingKind
from . import register


@register("check_mirror_interpretation")
def run(repo: Path) -> CheckerRun:
    out = CheckerRun(checker_id="check_mirror_interpretation")
    cfg_path = repo / "scripts" / "philosophy_enforcement" / "config" / "check_mirror_interpretation.json"
    if not cfg_path.is_file():
        out.findings.append(
            Finding(
                kind=FindingKind.CONFIRMED_VIOLATION,
                message="check_mirror_interpretation.json missing",
                location=str(cfg_path.relative_to(repo)),
                checker_id="check_mirror_interpretation",
            )
        )
        return out
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))

    canon = repo / (cfg.get("canonical_module") or "local_ai/vision_execution/graph_interpretation.py")
    if not canon.is_file():
        out.findings.append(
            Finding(
                kind=FindingKind.CONFIRMED_VIOLATION,
                message="Canonical graph_interpretation module missing",
                location=str(canon.relative_to(repo)),
                checker_id="check_mirror_interpretation",
            )
        )
        return out
    canon_body = canon.read_text(encoding="utf-8")
    needle = cfg.get("canonical_entrypoint_substring") or "def interpret_against_graph"
    if needle not in canon_body:
        out.findings.append(
            Finding(
                kind=FindingKind.CONFIRMED_VIOLATION,
                message=f"Canonical module missing entrypoint substring {needle!r}",
                location=str(canon.relative_to(repo)),
                checker_id="check_mirror_interpretation",
            )
        )

    for req in cfg.get("required_callers", []):
        rel = req.get("path") or ""
        sub = req.get("must_contain") or ""
        fp = repo / rel
        if not fp.is_file():
            out.findings.append(
                Finding(
                    kind=FindingKind.CONFIRMED_VIOLATION,
                    message=f"Required caller file missing: {req.get('reason', '')}",
                    location=rel,
                    checker_id="check_mirror_interpretation",
                )
            )
            continue
        body = fp.read_text(encoding="utf-8")
        if sub not in body:
            out.findings.append(
                Finding(
                    kind=FindingKind.CONFIRMED_VIOLATION,
                    message=f"Required wiring missing {sub!r} — {req.get('reason', '')}",
                    location=rel,
                    checker_id="check_mirror_interpretation",
                )
            )

    fb = cfg.get("forbidden_row_interpretation_assignment") or {}
    rx = re.compile(fb.get("pattern") or r'["\']interpretation["\']\s*\]\s*=')
    scan_roots = fb.get("scan_roots") or ["local_ai/vision_execution"]
    ignores = tuple(fb.get("ignore_path_substrings") or ["graph_interpretation.py", "/__pycache__/", "test_"])
    for root_name in scan_roots:
        root = repo / root_name
        if not root.is_dir():
            continue
        for fp in root.rglob("*.py"):
            rel = fp.relative_to(repo).as_posix()
            if any(ig in rel for ig in ignores):
                continue
            try:
                text = fp.read_text(encoding="utf-8")
            except OSError:
                continue
            for m in rx.finditer(text):
                line_no = text[: m.start()].count("\n") + 1
                out.findings.append(
                    Finding(
                        kind=FindingKind.CONFIRMED_VIOLATION,
                        message="Row interpretation assignment outside canonical graph_interpretation.py — use interpret_against_graph",
                        location=f"{rel}:{line_no}",
                        detail="Mirror graph: only graph_interpretation may attach row['interpretation'] with graph ops.",
                        checker_id="check_mirror_interpretation",
                    )
                )

    for h in cfg.get("heuristic_parallel_surfaces", []):
        rel = h.get("path") or ""
        fp = repo / rel
        if not fp.is_file():
            continue
        body = fp.read_text(encoding="utf-8")
        if_cont = h.get("if_contains") or ""
        unless = h.get("unless_contains") or ""
        if if_cont not in body:
            continue
        if unless and unless in body:
            continue
        out.findings.append(
            Finding(
                kind=FindingKind.HEURISTIC_SUSPICION,
                message=h.get("message") or "Parallel interpretation-shaped surface — review",
                location=rel,
                checker_id="check_mirror_interpretation",
            )
        )

    return out
