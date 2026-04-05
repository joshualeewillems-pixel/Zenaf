#!/usr/bin/env python3
"""
Advance wave_registry.json current_wave_id to the next entry in waves[] (ordered list).

Does not modify convergence_program_state.json — human or follow-up commit should align phase.

Exit 0 on success; 1 if no next wave; 2 on IO/JSON errors.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
_REGISTRY_REL = Path("scripts") / "philosophy_enforcement" / "wave_registry.json"


def main() -> int:
    parser = argparse.ArgumentParser(description="Bump current_wave_id to next wave in registry")
    parser.add_argument("--repo", type=Path, default=_REPO, help="Repository root")
    parser.add_argument("--dry-run", action="store_true", help="Print next id only; do not write")
    args = parser.parse_args()
    repo = args.repo.resolve()
    path = repo / _REGISTRY_REL
    if not path.is_file():
        print(f"wave_promote: missing {path}", file=sys.stderr)
        return 2
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        print(f"wave_promote: {e}", file=sys.stderr)
        return 2
    waves = data.get("waves")
    if not isinstance(waves, list) or not waves:
        print("wave_promote: waves[] empty", file=sys.stderr)
        return 1
    ids = [w.get("id") for w in waves if isinstance(w, dict) and w.get("id")]
    cur = str(data.get("current_wave_id") or "").strip()
    if not cur:
        print("wave_promote: current_wave_id missing", file=sys.stderr)
        return 2
    try:
        idx = ids.index(cur)
    except ValueError:
        print(f"wave_promote: current_wave_id {cur!r} not in waves[]", file=sys.stderr)
        return 1
    if idx + 1 >= len(ids):
        print(
            f"wave_promote: no next wave after {cur!r} (append a wave in {_REGISTRY_REL.as_posix()})",
            file=sys.stderr,
        )
        return 1
    nxt = str(ids[idx + 1])
    print(json.dumps({"previous_wave_id": cur, "next_wave_id": nxt}))
    if args.dry_run:
        return 0
    data["current_wave_id"] = nxt
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
