"""
Phase 1 repair: charter-trace-exempt:<id> declared on a VE route but missing from aiTraceExemptRegistry.ts.

Only touches the registry file. Does not add server traces or remove route comments.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .models import RepairBatchResult

REGISTRY_REL = "frontend/src/ai-actions/aiTraceExemptRegistry.ts"

_DETAIL_RE = re.compile(
    r"charter-trace-exempt:\s*([a-z0-9_]+)\s+not\s+in\s+aiTraceExemptRegistry",
    re.IGNORECASE,
)
_EXISTING_ID_RE = re.compile(r"id:\s*'([^']+)'")


def _collect_missing_ids(findings: list[dict[str, Any]]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for f in findings:
        if (f.get("checker_id") or "") != "trace_or_exempt":
            continue
        det = f.get("detail") or ""
        m = _DETAIL_RE.search(det)
        if not m:
            continue
        eid = m.group(1).strip().lower()
        if eid and eid not in seen:
            seen.add(eid)
            ordered.append(eid)
    return ordered


def repair_trace_exempt_registry_gaps(
    repo: Path,
    findings: list[dict[str, Any]],
    checker_config: dict[str, Any],
) -> RepairBatchResult:
    del checker_config  # bounds enforced by auto_repair.py

    missing = _collect_missing_ids(findings)
    if not missing:
        return RepairBatchResult(
            applied=False,
            touched_files=[],
            summary="No charter-trace-exempt registry gap findings for this checker run.",
        )

    path = repo / REGISTRY_REL
    if not path.is_file():
        return RepairBatchResult(
            applied=False,
            touched_files=[],
            summary="Registry file missing",
            error=str(path),
        )

    text = path.read_text(encoding="utf-8")
    existing = {m.group(1).strip().lower() for m in _EXISTING_ID_RE.finditer(text)}
    to_add = [i for i in missing if i not in existing]
    if not to_add:
        return RepairBatchResult(
            applied=False,
            touched_files=[],
            summary="All cited exempt ids already present in registry (idempotent).",
        )

    anchor = re.search(r"\]\s*\r?\n\s*\r?\nexport function aiTraceExemptIds", text)
    if not anchor:
        return RepairBatchResult(
            applied=False,
            touched_files=[],
            summary="Could not find AI_ACTION_TRACE_EXEMPTS array closing anchor",
            error="parse_error",
        )
    insert_at = anchor.start()

    blocks = []
    for eid in to_add:
        blocks.append(
            "  {\n"
            f"    id: '{eid}',\n"
            "    reason:\n"
            "      'Declared via # charter-trace-exempt on a Vision Execution route; "
            "entry added by philosophy auto-repair — confirm scope with ZENAF_SYSTEM_CHARTER §4 "
            "and GLOBAL_PHILOSOPHY_INTEGRATION_MATRIX.',\n"
            "  },\n"
        )
    new_text = text[:insert_at] + "".join(blocks) + text[insert_at:]
    path.write_text(new_text, encoding="utf-8")

    return RepairBatchResult(
        applied=True,
        touched_files=[REGISTRY_REL],
        summary=f"Appended exempt id(s) to registry: {', '.join(to_add)}",
    )
