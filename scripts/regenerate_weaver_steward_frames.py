#!/usr/bin/env python3
"""Regenerate Weaver steward frame constants from the Phase 1 records JSON.

CANONICAL SOURCE (workspace-local, not in this repo):
    ~/workspace/your_files/zenaf-steward-consolidation-weaver-records.json
    (record set "weaver", version "weaver-records-v1").

local_ai/council/steward_records.py is GENERATED for the constants in
MANAGED below: never hand-edit those assignments. To change a frame:

  1. Edit the JSON value (the canonical source).
  2. Run this script: it rewrites only the MANAGED assignments, leaving
     every other line of steward_records.py byte-identical.
  3. Sync the rollback sources to the same values
     (local_ai/council/meetings.py CONDUCTOR_FIRST_MEETING and
     local_ai/conversation/encounter.py WEAVER_TURN_FRAME): when the
     steward flag is off (ZENAF_WEAVER_STEWARD=0) the meeting falls back
     to those sources, so a steward-only change would make rollback
     change behavior instead of restoring it.
  4. Run the steward parity + refinement tests (they assert the three
     sources agree).

The script self-verifies: it AST-parses the rewritten file and asserts
every MANAGED constant equals the JSON value before replacing the file.
--check verifies module == JSON for MANAGED without writing anything.
Only the standard library is used, so the script never imports the repo.

Managed constants that are NOT frame text (OBJECTIVES, capability
records, naming thresholds, ...) are intentionally untouched: they are
not rewritten by this script and must not be assumed in sync with the
JSON by it. The frame/script constants listed here are the complete set
this script owns.
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = REPO_ROOT / "local_ai" / "council" / "steward_records.py"
DEFAULT_JSON_PATH = (
    Path.home()
    / "workspace"
    / "your_files"
    / "zenaf-steward-consolidation-weaver-records.json"
)


def _managed_values(records: dict) -> dict[str, str | tuple[str, ...]]:
    """Frame/script constants owned by this script, read from the JSON."""
    rc = records["canonical"]["runtime_configuration"]
    script = rc["first_meeting_script"]["value"]
    wrap = rc["wrap_and_fallback_lines"]["value"]
    return {
        "TURN_FRAME": rc["turn_frame"]["value"],
        "SCRIPT_CHARACTER": script["character"],
        "SCRIPT_DEMEANOR": script["demeanor"],
        "SCRIPT_OPENING": tuple(script["opening"]),
        "SCRIPT_QUESTIONS": tuple(script["questions"]),
        "SCRIPT_ENCOUNTER_FRAME": script["encounter_frame"],
        "SCRIPT_READBACK_FRAME": script["readback_frame"],
        "SCRIPT_CORRECTION_FRAME": script["correction_frame"],
        "SCRIPT_READBACK_REPLY_FRAME": script["readback_reply_frame"],
        "SCRIPT_ORIENTATION_INTRO": tuple(script["orientation_intro"]),
        "SCRIPT_PULLED_ITEM_TEMPLATE": script["pulled_item_template"],
        "SCRIPT_PULLED_WHERE_TEMPLATE": script["pulled_where_template"],
        "SCRIPT_ORIENTATION": tuple(script["orientation"]),
        "SCRIPT_ORIENTATION_FRAME": script["orientation_frame"],
        "SCRIPT_ORIENTATION_FACTS": script["orientation_facts"],
        "SCRIPT_REVEAL": tuple(script["reveal"]),
        "WRAP_LINE": wrap["wrap"],
        "FALLBACK_LINE": wrap["fallback"],
    }


def _render(name: str, value: str | tuple[str, ...]) -> str:
    """One assignment line, double-quoted (json) string form."""
    if isinstance(value, str):
        return f"{name} = {json.dumps(value, ensure_ascii=False)}"
    if not value:
        return f"{name} = ()"
    inner = ", ".join(json.dumps(item, ensure_ascii=False) for item in value)
    return f"{name} = ({inner},)"


def _module_values(source: str, wanted: set[str]) -> dict[str, object]:
    """Constant values for top-level single-name assignments in source."""
    tree = ast.parse(source)
    found: dict[str, object] = {}
    for node in tree.body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if not isinstance(target, ast.Name) or target.id not in wanted:
            continue
        found[target.id] = ast.literal_eval(node.value)
    return found


def _rewrite(source: str, managed: dict[str, str | tuple[str, ...]]) -> tuple[str, list[str]]:
    """Replace MANAGED assignment lines whose VALUE differs from the JSON.

    Quote style alone is never a change: a constant whose value already
    matches the JSON keeps its existing line byte-identical, so a
    regeneration run touches only what actually changed.
    Returns (new_source, changed).
    """
    tree = ast.parse(source)
    spans: dict[str, tuple[int, int]] = {}
    for node in tree.body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if isinstance(target, ast.Name) and target.id in managed:
            assert node.end_lineno is not None and node.end_lineno == node.lineno, (
                f"{target.id} is not a single-line assignment; refusing to rewrite"
            )
            spans[target.id] = (node.lineno, node.end_lineno)
    missing = set(managed) - set(spans)
    assert not missing, f"assignments not found in module: {sorted(missing)}"
    current = _module_values(source, set(managed))
    lines = source.split("\n")
    changed: list[str] = []
    for name, value in managed.items():
        if current.get(name) == value:
            continue
        lineno, _ = spans[name]
        lines[lineno - 1] = _render(name, value)
        changed.append(name)
    return "\n".join(lines), changed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json-path", type=Path, default=DEFAULT_JSON_PATH,
                        help="Phase 1 records JSON (default: workspace copy)")
    parser.add_argument("--check", action="store_true",
                        help="verify module == JSON for MANAGED, write nothing")
    args = parser.parse_args(argv)
    if not args.json_path.exists():
        print(f"records JSON not found: {args.json_path}", file=sys.stderr)
        print("Pass --json-path to the workspace copy of the records JSON.",
              file=sys.stderr)
        return 2
    records = json.loads(args.json_path.read_text())
    managed = _managed_values(records)
    source = MODULE_PATH.read_text()
    current = _module_values(source, set(managed))
    if args.check:
        bad = [name for name, value in managed.items()
               if current.get(name) != value]
        if bad:
            print(f"MISMATCH (module != JSON): {', '.join(sorted(bad))}",
                  file=sys.stderr)
            return 1
        print(f"OK: {len(managed)} managed constants match the JSON.")
        return 0
    new_source, changed = _rewrite(source, managed)
    # Self-verify the rewritten text before it touches the module.
    rewritten = _module_values(new_source, set(managed))
    bad = [name for name, value in managed.items()
           if rewritten.get(name) != value]
    assert not bad, f"self-verification failed for: {bad}"
    if not changed:
        print("No changes: module already matches the JSON.")
        return 0
    fd, tmp = tempfile.mkstemp(dir=str(MODULE_PATH.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as handle:
            handle.write(new_source)
        os.replace(tmp, MODULE_PATH)
    except BaseException:
        os.unlink(tmp)
        raise
    for name in changed:
        value = managed[name]
        size = len(value) if isinstance(value, str) else sum(len(v) for v in value)
        print(f"regenerated {name} ({size} chars)")
    print(f"OK: {len(changed)} constant(s) regenerated, "
          f"{len(managed) - len(changed)} unchanged.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
