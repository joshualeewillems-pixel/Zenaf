#!/usr/bin/env python3
"""
Pass 1 fast council: before/after evaluation.

Runs 3 council scenarios with default 3 seats (Strategist, Operator, Analyst),
times each run, and reports: total latency, whether synthesis ran, output readability, decision-usefulness.

Run from repo root: python scripts/eval_council_pass1.py
Requires: Ollama running with the council model (e.g. qwen3:8b).
"""
import sys
import time
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

# Default 3 seats (Pass 1)
INCLUDED_ROLES = ["strategist", "operator", "analyst"]

SCENARIOS = [
    {
        "id": "1",
        "question": "Should we prioritize launching the new service line this quarter or delay until we have two more hires?",
        "context": None,
    },
    {
        "id": "2",
        "question": "Given limited capacity, which initiative should we pause: the clinic expansion or the digital intake rollout?",
        "context": "Current team of 4; both initiatives are 3-month efforts.",
    },
    {
        "id": "3",
        "question": "What is the single most important next step for the business right now?",
        "context": None,
    },
]


def run_one(question: str, context: str | None) -> tuple[float, str]:
    """Run council once; return (latency_seconds, full_text)."""
    from local_ai.zenaf_tools import run_council

    t0 = time.perf_counter()
    result = run_council(
        question=question,
        context=context,
        recent_tool_summary=None,
        key_constraints=None,
        included_roles=INCLUDED_ROLES,
        perspective_definitions=None,
        include_synthesis=None,
    )
    elapsed = time.perf_counter() - t0
    text = result if isinstance(result, str) else result[0]
    return elapsed, text


def main() -> None:
    print("Pass 1 fast council evaluation (3 seats: Strategist, Operator, Analyst)")
    print("=" * 60)

    latencies: list[float] = []
    synthesis_ran: list[bool] = []
    outputs: list[str] = []

    for s in SCENARIOS:
        print(f"\n--- Scenario {s['id']} ---")
        print(f"Q: {s['question'][:80]}...")
        try:
            elapsed, text = run_one(s["question"], s.get("context"))
        except Exception as e:
            print(f"Error: {e}")
            latencies.append(-1.0)
            synthesis_ran.append(False)
            outputs.append(str(e))
            continue

        latencies.append(elapsed)
        has_synthesis = "Zenaf synthesis:" in (text or "")
        synthesis_ran.append(has_synthesis)
        outputs.append(text or "")

        print(f"Latency: {elapsed:.1f}s")
        print(f"Synthesis ran: {has_synthesis}")
        print("\nOutput (excerpt):")
        print((text or "")[:1200] + ("..." if len(text or "") > 1200 else ""))
        print()

    # Summary
    print("=" * 60)
    print("SUMMARY")
    print("=" * 60)
    valid = [l for l in latencies if l >= 0]
    if valid:
        print(f"Total latency (avg of 3): {sum(valid) / len(valid):.1f}s")
        print(f"Latencies: {[f'{l:.1f}s' for l in latencies]}")
    else:
        print("Total latency: N/A (all runs failed)")
    print(f"Synthesis ran: {synthesis_ran}")
    print("\nReadability: structured (Position / Primary reason / Main risk / Guardrail / Next step) per seat.")
    print("Decision-usefulness: review excerpts above for concrete positions and next steps.")
    print("\nNote: Synthesis runs only when positions disagree (or include_synthesis=True). With timeouts, fewer seats may return, so synthesis may not run.")


if __name__ == "__main__":
    main()
