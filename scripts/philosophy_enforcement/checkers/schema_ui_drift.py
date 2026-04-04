from __future__ import annotations

import json
from pathlib import Path

from ..models import CheckerRun, Finding, FindingKind
from . import register


def _config(repo: Path) -> dict:
    p = repo / "scripts" / "philosophy_enforcement" / "config" / "schema_ui_labels.json"
    return json.loads(p.read_text(encoding="utf-8"))


@register("schema_ui_drift")
def run(repo: Path) -> CheckerRun:
    out = CheckerRun(checker_id="schema_ui_drift")
    cfg = _config(repo)
    labels = cfg.get("labels_must_appear", [])
    anchors = cfg.get("ui_anchor_files", [])

    combined = ""
    missing_locations: list[str] = []
    for rel in anchors:
        fp = repo / rel
        if not fp.is_file():
            missing_locations.append(rel)
            continue
        combined += fp.read_text(encoding="utf-8")

    for rel in missing_locations:
        out.findings.append(
            Finding(
                kind=FindingKind.CONFIRMED_VIOLATION,
                message="UI anchor file missing for schema label contract",
                location=rel,
                detail=cfg.get("schema_source", ""),
                checker_id="schema_ui_drift",
            )
        )

    for label in labels:
        if label not in combined:
            out.findings.append(
                Finding(
                    kind=FindingKind.CONFIRMED_VIOLATION,
                    message=f'Canonical UI label not found in anchor file(s): "{label}"',
                    location=", ".join(anchors),
                    detail=f"Keep in sync with {cfg.get('schema_source', 've_integration_schema.py')}.",
                    checker_id="schema_ui_drift",
                )
            )

    for grp in cfg.get("label_any_of_groups", []):
        opts = grp.get("any_of") or []
        if not opts:
            continue
        if not any(o in combined for o in opts):
            out.findings.append(
                Finding(
                    kind=FindingKind.CONFIRMED_VIOLATION,
                    message=f'None of the equivalent UI labels present for group "{grp.get("id", "")}"',
                    location=", ".join(anchors),
                    detail=grp.get("note", "") or f"Expected one of: {opts!r}",
                    checker_id="schema_ui_drift",
                )
            )

    return out
