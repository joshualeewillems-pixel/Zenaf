#!/usr/bin/env python3
"""
Pass 2 council benchmark: local-model bake-off.

Compares council usefulness across candidate models × concurrency (1, 2).
Same 3-seat scenarios; metrics: useful_run, seats_ok, timeout, malformed, other_error, model_missing, avg_latency.
Recommendations: best default, best fast fallback, best specialist, not recommended.
Synthesis out of scope.

Edit CORE_MODEL_CANDIDATES and CONCURRENCY_LEVELS below to change the matrix.
Set ATRIA_COUNCIL_BENCHMARK_INCLUDE_CEILING=1 to add quality-ceiling model(s) (reported separately).

Run from repo root: python scripts/eval_council_pass2.py
"""

import os
import re
import sys
import time
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

INCLUDED_ROLES = ["strategist", "operator", "analyst"]
SEAT_HEADERS = ("Strategist:", "Operator:", "Analyst:")

# ---- Model matrix: edit here ----
# Core candidates (main benchmark)
CORE_MODEL_CANDIDATES = [
    "qwen3:8b",
    "deepseek-r1:8b",
    "qwen2:7b-instruct",
    "qwen2:1.5b-instruct",
]
# Concurrency levels to test
CONCURRENCY_LEVELS = (1, 2)
# Optional quality ceiling (only if ATRIA_COUNCIL_BENCHMARK_INCLUDE_CEILING=1)
CEILING_MODELS = ["qwen3:30b"]

# Error text that indicates model not installed (Ollama)
MODEL_NOT_FOUND_PATTERNS = re.compile(
    r"not found|404|model.*does not exist|unknown model|model not found|pull",
    re.IGNORECASE,
)

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

# Position values we treat as recognizable
POSITION_VALUES = re.compile(
    r"Position:\s*(proceed|pause|reject|revise)",
    re.IGNORECASE,
)
NEXT_STEP_PATTERN = re.compile(
    r"Next\s+step:\s*(.+)",
    re.IGNORECASE | re.DOTALL,
)
TIMEOUT_PATTERN = re.compile(r"timeout|timed\s+out", re.IGNORECASE)


def _split_seat_chunks(text: str) -> list[str]:
    """Split council output into per-seat chunks (exclude Atria synthesis)."""
    if not text or not text.strip():
        return []
    if "Atria synthesis:" in text:
        text = text[: text.index("Atria synthesis:")].strip()
    chunks = []
    for header in SEAT_HEADERS:
        idx = text.find(header)
        if idx < 0:
            continue
        start = idx
        end = len(text)
        for other in SEAT_HEADERS:
            if other == header:
                continue
            i2 = text.find(other, start + len(header))
            if 0 <= i2 < end:
                end = i2
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
    return chunks


def _classify_seat(chunk: str) -> tuple[str, bool, bool]:
    """(kind, has_position, has_next_step). kind: ok | timeout | malformed | other_error"""
    chunk_lower = chunk.lower()
    has_error = "[error:" in chunk_lower
    if has_error:
        if TIMEOUT_PATTERN.search(chunk):
            return ("timeout", False, False)
        return ("other_error", False, False)
    has_position = bool(POSITION_VALUES.search(chunk))
    next_match = NEXT_STEP_PATTERN.search(chunk)
    next_text = (next_match.group(1).strip() if next_match else "") or ""
    has_next_step = len(next_text) > 10 and not next_text.startswith("<")
    if has_position:
        return ("ok", True, has_next_step)
    return ("malformed", False, has_next_step)


def _is_model_not_found(error_text: str) -> bool:
    """True if error indicates the model is not installed."""
    if not error_text or not isinstance(error_text, str):
        return False
    return bool(MODEL_NOT_FOUND_PATTERNS.search(error_text))


def _run_one(
    question: str,
    context: str | None,
    workers_override: int,
    council_model_env: str | None,
) -> tuple[float, str, str | None]:
    """Run council once. Returns (latency_seconds, full_text, error_message_or_None)."""
    import local_ai.atria_tools as atria_tools

    atria_tools.COUNCIL_MAX_WORKERS_OVERRIDE = workers_override
    prev_model = os.environ.get("ATRIA_COUNCIL_MODEL")
    try:
        if council_model_env is not None:
            os.environ["ATRIA_COUNCIL_MODEL"] = council_model_env
        elif prev_model is not None:
            os.environ.pop("ATRIA_COUNCIL_MODEL", None)

        from local_ai.atria_tools import run_council

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
        text = text or ""
        if text.strip().startswith("Error:"):
            return elapsed, text, text.strip()
        return elapsed, text, None
    except Exception as e:
        err = str(e)
        return 0.0, "", err
    finally:
        atria_tools.COUNCIL_MAX_WORKERS_OVERRIDE = None
        if prev_model is not None:
            os.environ["ATRIA_COUNCIL_MODEL"] = prev_model
        else:
            os.environ.pop("ATRIA_COUNCIL_MODEL", None)


def _evaluate_run(text: str) -> dict:
    """Compute useful_run, seats_ok, timeout, malformed, other_error from full council text."""
    chunks = _split_seat_chunks(text)
    seats_ok = 0
    timeout_count = 0
    malformed_count = 0
    other_error_count = 0
    positions_count = 0
    next_steps_count = 0

    for chunk in chunks:
        kind, has_pos, has_next = _classify_seat(chunk)
        if kind == "ok":
            seats_ok += 1
            if has_pos:
                positions_count += 1
            if has_next:
                next_steps_count += 1
        elif kind == "timeout":
            timeout_count += 1
        elif kind == "malformed":
            malformed_count += 1
            if has_pos:
                positions_count += 1
            if has_next:
                next_steps_count += 1
        else:
            other_error_count += 1

    useful_run = positions_count >= 2 and next_steps_count >= 1
    return {
        "useful_run": useful_run,
        "seats_ok": seats_ok,
        "timeout": timeout_count,
        "malformed": malformed_count,
        "other_error": other_error_count,
        "positions_count": positions_count,
        "next_steps_count": next_steps_count,
    }


def _build_conditions() -> list[dict]:
    """Build (model, workers) conditions: core × concurrency, optionally ceiling × concurrency."""
    conditions = []
    for model in CORE_MODEL_CANDIDATES:
        for w in CONCURRENCY_LEVELS:
            conditions.append({"label": f"{model}, concurrency={w}", "model": model, "workers": w})
    if os.environ.get("ATRIA_COUNCIL_BENCHMARK_INCLUDE_CEILING", "").strip() == "1":
        for model in CEILING_MODELS:
            for w in CONCURRENCY_LEVELS:
                conditions.append(
                    {"label": f"{model} (ceiling), concurrency={w}", "model": model, "workers": w, "ceiling": True}
                )
    return conditions


def _recommendations(results: list[dict], include_ceiling: bool) -> dict:
    """Derive practical use-case fit from results."""
    # Exclude ceiling from "main" recommendations unless explicitly included
    main = [r for r in results if not r.get("ceiling") and r.get("model_missing", 0) == 0]
    all_valid = [r for r in results if r.get("model_missing", 0) == 0]

    best_default = None
    best_fast_fallback = None
    best_specialist = None
    not_recommended: list[str] = []

    if main:
        main.sort(key=lambda c: (-c["useful_runs"], -c["seats_ok"], c["avg_latency"]))
        best_default = main[0]["label"]

        fast_candidates = [c for c in main if c["useful_runs"] >= 2 or c["seats_ok"] >= 6]
        if fast_candidates:
            fast_candidates.sort(key=lambda c: c["avg_latency"])
            best_fast_fallback = fast_candidates[0]["label"]

        for c in main:
            if c["useful_runs"] == 0 and c["seats_ok"] < 3:
                not_recommended.append(c["label"])

    if include_ceiling and all_valid:
        ceiling_results = [r for r in all_valid if r.get("ceiling")]
        if ceiling_results:
            ceiling_results.sort(key=lambda c: (-c["useful_runs"], -c["seats_ok"]))
            best_specialist = ceiling_results[0]["label"]
    if best_specialist is None and main:
        main_by_quality = sorted(main, key=lambda c: (-c["useful_runs"], -c["seats_ok"]))
        if main_by_quality:
            best_specialist = main_by_quality[0]["label"]

    return {
        "best_default": best_default,
        "best_fast_fallback": best_fast_fallback,
        "best_specialist": best_specialist,
        "not_recommended": not_recommended,
    }


def main() -> None:
    conditions = _build_conditions()
    include_ceiling = any(c.get("ceiling") for c in conditions)

    print("Pass 2 council benchmark — local-model bake-off")
    print(f"Conditions: {len(conditions)} ({len(CORE_MODEL_CANDIDATES)} models × concurrency {CONCURRENCY_LEVELS})")
    if include_ceiling:
        print("Including quality-ceiling runs (reported separately)")
    print("Metrics: useful_run, seats_ok, timeout/malformed/other_error/model_missing, avg_latency")
    print("=" * 60)

    results_per_condition: list[dict] = []
    models_missing: set[str] = set()

    for cond in conditions:
        label = cond["label"]
        model = cond["model"]
        workers = cond["workers"]
        print(f"\n--- {label} ---")
        if model:
            os.environ["ATRIA_COUNCIL_MODEL"] = model
        else:
            os.environ.pop("ATRIA_COUNCIL_MODEL", None)

        latencies: list[float] = []
        useful_runs = 0
        total_ok = 0
        total_timeout = 0
        total_malformed = 0
        total_other = 0
        model_missing_runs = 0

        for s in SCENARIOS:
            print(f"  Scenario {s['id']}... ", end="", flush=True)
            try:
                elapsed, text, run_error = _run_one(
                    s["question"],
                    s.get("context"),
                    workers_override=workers,
                    council_model_env=model,
                )
            except Exception as e:
                print(f"Error: {e}")
                latencies.append(-1.0)
                total_other += 3
                continue

            if run_error and _is_model_not_found(run_error):
                model_missing_runs += 1
                models_missing.add(model or "default")
                print("model not installed")
                latencies.append(-1.0)
                continue

            if run_error:
                print(f"Run error: {run_error[:60]}...")
                latencies.append(elapsed)
                total_other += 3
                continue

            latencies.append(elapsed)
            ev = _evaluate_run(text)
            if ev["useful_run"]:
                useful_runs += 1
            total_ok += ev["seats_ok"]
            total_timeout += ev["timeout"]
            total_malformed += ev["malformed"]
            total_other += ev["other_error"]
            print(
                f"latency={elapsed:.1f}s ok={ev['seats_ok']} "
                f"(timeout={ev['timeout']} malformed={ev['malformed']} other={ev['other_error']}) "
                f"useful={ev['useful_run']}"
            )

        valid_lat = [l for l in latencies if l >= 0]
        avg_lat = sum(valid_lat) / len(valid_lat) if valid_lat else 0.0
        results_per_condition.append(
            {
                "label": label,
                "model": model,
                "workers": workers,
                "ceiling": cond.get("ceiling", False),
                "useful_runs": useful_runs,
                "seats_ok": total_ok,
                "timeout": total_timeout,
                "malformed": total_malformed,
                "other_error": total_other,
                "model_missing": model_missing_runs,
                "avg_latency": avg_lat,
                "latencies": latencies,
            }
        )
        print(
            f"  Summary: useful_runs={useful_runs} seats_ok={total_ok} "
            f"(timeout={total_timeout} malformed={total_malformed} other={total_other} missing={model_missing_runs}) "
            f"avg_latency={avg_lat:.1f}s"
        )

    # Main benchmark winner (exclude ceiling unless only candidates)
    main_results = [r for r in results_per_condition if not r.get("ceiling") and r.get("model_missing", 0) < 3]
    if not main_results:
        main_results = [r for r in results_per_condition if r.get("model_missing", 0) < 3]
    main_results.sort(key=lambda c: (-c["useful_runs"], -c["seats_ok"], c["avg_latency"]))
    winner = main_results[0] if main_results else results_per_condition[0]

    rec = _recommendations(results_per_condition, include_ceiling)

    print("\n" + "=" * 60)
    print("RESULTS TABLE")
    print("=" * 60)
    print(
        f"{'Condition':<45} {'Useful':<6} {'SeatsOK':<6} {'Timeout':<6} {'Malformed':<8} {'Other':<6} {'Missing':<6} {'AvgLat(s)':<8}"
    )
    print("-" * 98)
    for r in results_per_condition:
        print(
            f"{r['label']:<45} {r['useful_runs']:<6} {r['seats_ok']:<6} "
            f"{r['timeout']:<6} {r['malformed']:<8} {r['other_error']:<6} {r.get('model_missing', 0):<6} "
            f"{r['avg_latency']:.1f}"
        )
    print("=" * 60)
    print(f"Winner (useful_runs → seats_ok → latency): {winner['label']}")
    print(f"  useful_runs={winner['useful_runs']} seats_ok={winner['seats_ok']} avg_latency={winner['avg_latency']:.1f}s")

    if models_missing:
        print("\n--- Models not installed ---")
        for m in sorted(models_missing):
            if m and m != "default":
                print(f"  {m}: pull with  ollama pull {m}")

    print("\n--- Practical use-case fit ---")
    if rec["best_default"]:
        print(f"  Best default council model: {rec['best_default']}")
    if rec["best_fast_fallback"]:
        print(f"  Best fast fallback:         {rec['best_fast_fallback']}")
    if rec["best_specialist"]:
        print(f"  Best specialist / quality: {rec['best_specialist']}")
    if rec["not_recommended"]:
        print("  Not recommended for council:")
        for lbl in rec["not_recommended"]:
            print(f"    - {lbl}")


if __name__ == "__main__":
    main()
