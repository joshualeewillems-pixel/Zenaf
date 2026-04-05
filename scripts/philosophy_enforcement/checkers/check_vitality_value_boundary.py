"""
Vitality ≠ economic value + import firewall (Philosophy #16).

``node_vitality_scores`` (water/soil/fruit execution signals) must not leak into
Integration Artifact minting, ledgers, or tokenomics. Only the canonical VE
vitality writers may import ``compute_vitality_scores`` / ``node_vitality_scores``.

Law: ``docs/01_TRUTH/FRUIT_MINT_POLICY.md`` + ``TRUTH_CONVERGENCE.md`` locked row.

"No parallel ontologies" for this row: mint eligibility stays VE + judgment evidence
only; this checker enforces the **vitality coupling** slice (see matrix narrative).
"""
from __future__ import annotations

import re
from pathlib import Path

from ..models import CheckerRun, Finding, FindingKind
from . import register

_CHECKER_ID = "check_vitality_value_boundary"

# Only these paths may reference the vitality scoring module API (imports / compute_vitality_scores).
_ALLOWED_FILES: frozenset[str] = frozenset(
    {
        "local_ai/vision_execution/node_vitality_scores.py",
        "local_ai/vision_execution/storage.py",
        "tests/test_node_vitality_scores.py",
    }
)

# Match scoring entrypoints or submodule imports (not the string "node_vitality_scores.py" alone).
_PATTERN = re.compile(
    r"\b(compute_vitality_scores|from\s+local_ai\.vision_execution\.node_vitality_scores\s+import|"
    r"from\s+local_ai\.vision_execution\s+import\s+[^\n#]*\bnode_vitality_scores\b|"
    r"import\s+local_ai\.vision_execution\.node_vitality_scores\b)"
)


def _code_without_comment(line: str) -> str:
    return line.split("#", 1)[0]


def _scan_py_tree(repo: Path, base: Path, out: CheckerRun) -> None:
    if not base.is_dir():
        return
    for path in base.rglob("*.py"):
        rel = path.relative_to(repo).as_posix()
        if rel.startswith("scripts/"):
            continue
        if rel in _ALLOWED_FILES:
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
        for i, line in enumerate(text.splitlines(), start=1):
            code = _code_without_comment(line)
            if not _PATTERN.search(code):
                continue
            out.findings.append(
                Finding(
                    kind=FindingKind.CONFIRMED_VIOLATION,
                    message=(
                        "node_vitality_scores / compute_vitality_scores referenced outside allowlist — "
                        "vitality is not an economic/mint input (Philosophy #16; FRUIT_MINT_POLICY.md)"
                    ),
                    location=f"{rel}:{i}",
                    detail=line.strip()[:240],
                    checker_id=_CHECKER_ID,
                )
            )
            break


@register("check_vitality_value_boundary")
def run(repo: Path) -> CheckerRun:
    out = CheckerRun(checker_id=_CHECKER_ID)
    _scan_py_tree(repo, repo / "local_ai", out)
    _scan_py_tree(repo, repo / "api", out)
    _scan_py_tree(repo, repo / "tests", out)
    return out
