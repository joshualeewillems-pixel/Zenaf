"""
Small debug helper for extract_meeting.

Usage (from repo root):
  python tools/debug_extract_meeting.py
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
  sys.path.insert(0, str(ROOT))

from local_ai.vision_execution.meeting_extract import extract_meeting  # type: ignore


def main() -> None:
  fixtures = ROOT / "tests" / "fixtures"
  path = fixtures / "healing_haven_transcript_snippet.txt"
  if not path.exists():
    print(f"Transcript fixture not found at {path}")
    return

  text = path.read_text(encoding="utf-8")
  print(f"Loaded transcript snippet: {len(text)} chars")

  t0 = time.time()
  out = extract_meeting(text, context=None)
  elapsed = time.time() - t0
  print(f"extract_meeting completed in {elapsed:.2f}s")

  if not isinstance(out, dict):
    print(f"Unexpected output type: {type(out)}")
    return

  print(f"Top-level keys: {sorted(out.keys())}")

  def count(key: str) -> int:
    v = out.get(key)
    return len(v) if isinstance(v, list) else 0

  print(f"initiatives: {count('initiatives')}")
  print(f"projects: {count('projects')}")
  print(f"tasks: {count('tasks')}")
  print(f"assets: {count('assets')}")
  print(f"peopleReferences: {count('peopleReferences')}")
  print(f"signals: {count('signals')}")


if __name__ == "__main__":
  main()

