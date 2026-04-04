"""
Run extract_meeting on Meeting 2.txt twice: default preset vs fast_local (UI-style).

Usage (repo root):
  python tools/compare_meeting2_extract_presets.py

Requires local LLM (e.g. Ollama) configured like production. Prints JSON with
evidence_extraction_trace_summary from each run.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

MEETING_PATH = Path(r"c:\Users\philc\OneDrive\Desktop\Meeting 2.txt")


def main() -> int:
    if not MEETING_PATH.is_file():
        print(f"Missing fixture: {MEETING_PATH}", file=sys.stderr)
        return 2

    from local_ai.vision_execution.meeting_extract import extract_meeting

    text = MEETING_PATH.read_text(encoding="utf-8", errors="replace")

    results: list[dict] = []
    for preset in ("default", "fast_local"):
        out = extract_meeting(
            text,
            context=None,
            return_diagnostics=True,
            evidence_extraction_preset=preset,  # type: ignore[arg-type]
            skip_harvest=True,
        )
        ev = (out.get("_diagnostics") or {}).get("evidence") or {}
        trace = ev.get("evidence_extraction_trace_summary") or {}
        results.append(
            {
                "preset": preset,
                "candidate_count": len(out.get("candidates") or []),
                "error": out.get("error"),
                "message": out.get("message"),
                "execution_blocked": out.get("execution_blocked"),
                "evidence_extraction_trace_summary": trace,
            }
        )

    print(json.dumps({"meeting_file": str(MEETING_PATH), "runs": results}, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
