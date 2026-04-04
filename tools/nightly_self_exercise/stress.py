"""Repeat loops for timing variance (no product mutation beyond prior smoke)."""
from __future__ import annotations

import json
import statistics
import threading
import time
import urllib.request


def stress_health_and_intake(api_base: str, iterations: int) -> tuple[bool, str, list[float]]:
    base = api_base.rstrip("/")
    times: list[float] = []
    errors: list[str] = []
    for i in range(iterations):
        t0 = time.perf_counter()
        try:
            urllib.request.urlopen(f"{base}/health", timeout=15.0).read()
            urllib.request.urlopen(f"{base}/intake/queue?limit=3", timeout=20.0).read()
        except Exception as e:
            errors.append(f"iter{i}:{e}")
        times.append(time.perf_counter() - t0)
    ok = not errors
    summary = f"n={iterations} p50={statistics.median(times):.3f}s max={max(times):.3f}s"
    if errors:
        summary += " | " + "; ".join(errors[:5])
    return ok, summary, times


def stress_concurrent_council_probes(api_base: str, workers: int, timeout_s: float) -> tuple[bool, str]:
    """Fire parallel stream opens; each reads first chunk. May overload LLM — informational."""
    base = api_base.rstrip("/")
    results: list[tuple[bool, str]] = []

    def worker(idx: int) -> None:
        body = json.dumps(
            {
                "mode": "council",
                "params": {
                    "question": f"Nightly stress worker {idx}: reply OK",
                    "included_agents": ["strategist"],
                    "include_synthesis": True,
                },
                "context": {},
            }
        ).encode()
        req = urllib.request.Request(
            f"{base}/run/stream",
            data=body,
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout_s) as r:
                n = len(r.read(4096))
                results.append((True, f"w{idx} read {n}"))
        except Exception as e:
            results.append((False, f"w{idx} {e}"))

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(workers)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=timeout_s + 5.0)
    ok = sum(1 for o, _ in results if o) >= max(1, workers // 3)
    detail = " | ".join(m for _, m in results[:workers])
    return ok, detail
