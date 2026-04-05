#!/usr/bin/env python3
"""
Evaluate v0.1 arc heuristic against ARC-LAB synthetic fixtures.

Reads reports/arc_lab/manifest.json from scripts/seed_arc_lab_fixtures.py
and compares try_v01_friction_to_done outcomes to expected skips.

Exit 1 on mismatch (for CI). Exit 0 when all scenarios match.

This does NOT prove the product works for real users — only that the detector
matches the lab contract in docs/02_ACTIVE_DESIGN/ARC_DETECTION_FIXTURE_SPEC.md.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from local_ai.vision_execution import storage
from local_ai.vision_execution.detect_arcs import (
    collect_flow_readings_from_judgment_rows,
    try_v01_friction_to_done,
)

_MANIFEST = _REPO / "reports" / "arc_lab" / "manifest.json"

# scenario_key -> expected skip reason (None means heuristic should match / no skip)
EXPECTED: dict[str, str | None] = {
    "clean_hit": None,
    "insufficient_span": "insufficient_span",
    "unstable_after_completion": "unstable_after_completion",
    "rapid_false_positive_trap": "insufficient_span",
    "sparse_no_flow": "no_execution_flow_readings",
    "not_terminal": "not_terminal",
    "missing_pivot": "missing_pivot",
    "mixed_council_shape": None,
}


def main() -> int:
    if not _MANIFEST.is_file():
        print(f"missing manifest — run: python scripts/seed_arc_lab_fixtures.py\n  {_MANIFEST}")
        return 2
    manifest = json.loads(_MANIFEST.read_text(encoding="utf-8"))
    uid = manifest.get("user_id")
    if not uid:
        print("manifest missing user_id")
        return 2
    projects: dict[str, str] = manifest.get("projects") or {}
    storage.get_connection()

    failed = 0
    for key, pid in sorted(projects.items()):
        if key not in EXPECTED:
            print(f"skip unknown scenario key in manifest: {key}")
            continue
        row = storage.get_project(pid, uid)
        if not row:
            print(f"FAIL {key}: project {pid} missing")
            failed += 1
            continue
        jrows = storage.list_node_judgments_chronological(uid, "project", pid, limit=500)
        readings = collect_flow_readings_from_judgment_rows(jrows)
        skip, _payload = try_v01_friction_to_done(
            readings=readings,
            row_status=str(row.get("status") or ""),
            row_updated_at=str(row.get("updated_at") or "") or None,
        )
        exp_reason = EXPECTED[key]
        if exp_reason is None:
            ok = skip is None
            detail = f"skip={skip!r}" if not ok else "match"
        else:
            ok = skip == exp_reason
            detail = f"skip={skip!r} expected={exp_reason!r}"
        if not ok:
            print(f"FAIL {key}: {detail}")
            failed += 1
        else:
            print(f"OK   {key}: {detail}")

    if failed:
        print(f"\n{failed} scenario(s) failed")
        return 1
    print("\nAll lab scenarios passed (synthetic lane only).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
