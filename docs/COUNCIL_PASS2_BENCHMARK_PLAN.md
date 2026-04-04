# Council Pass 2 — Benchmark Plan (design only)

**Status:** Design / pre-implementation  
**Goal:** Compare inference-throughput options (concurrency + model choice) using the same 3-seat scenarios and Pass 1 packet, without widening architecture.

**Conclusion from Pass 1:** Bottleneck is inference throughput; prompt structure and timeouts are already bounded. Pass 2 tests whether lower concurrency or a smaller/faster model improves completion rate and latency.

---

## 1. Benchmark matrix

Same 3 scenarios as `scripts/eval_council_pass1.py` (Strategist, Operator, Analyst; same questions/context). Five conditions:

| Condition | Model | Concurrency | Purpose |
|-----------|--------|-------------|---------|
| **1** | Current (qwen3:8b) | 1 | Baseline: serial seats, no queue contention |
| **2** | Current (qwen3:8b) | 2 | Reduce contention vs current 3 |
| **3** | Current (qwen3:8b) | 3 | Current Pass 1 behavior (reference) |
| **4** | Smaller/faster council model | 1 | Fast model, serial |
| **5** | Smaller/faster council model | 2 | Fast model, light parallelism |

Each condition is run once per scenario (3 runs per condition, 15 runs total per benchmark pass). Optionally run each scenario 2× per condition and average to smooth variance.

---

## 2. Exact code/settings to parameterize

### 2.1 Concurrency

**Current:** `local_ai/atria_tools.py` uses `max_workers=min(3, len(tasks))` in four places (two in `run_council`, two in `run_council_stream`).

**Minimal change for benchmark only:** Introduce a single override used only when set.

- Add at module level in `local_ai/atria_tools.py`:
  - `COUNCIL_MAX_WORKERS_OVERRIDE: int | None = None`
- In all four `ThreadPoolExecutor` call sites, set:
  - `workers = COUNCIL_MAX_WORKERS_OVERRIDE if COUNCIL_MAX_WORKERS_OVERRIDE is not None else min(3, len(tasks))`
  - `with ThreadPoolExecutor(max_workers=workers) as executor: ...`

**Benchmark script:** Before calling `run_council`, set  
`local_ai.atria_tools.COUNCIL_MAX_WORKERS_OVERRIDE = 1` (or 2, 3). After the run (or at start of next condition), set back to `None` so normal behavior is unchanged.

No change to `run_council_stream` for the benchmark if we only use non-streaming `run_council` for eval (recommended: same as Pass 1).

### 2.2 Council model selection

**Current:** `local_ai/providers/__init__.py` — `get_council_provider()` returns `get_default_provider()` (reads `local_ai/config.py`: `OLLAMA_MODEL`, `MODEL_TIMEOUT`).

**Minimal change for benchmark only:** Allow one optional override so the benchmark can swap model without changing config or production defaults.

- **Option A (env var):** In `get_council_provider()`, if `os.environ.get("ATRIA_COUNCIL_MODEL")` is set, return `OllamaProvider(model=os.environ["ATRIA_COUNCIL_MODEL"], timeout=...)` (use existing `MODEL_TIMEOUT` or council timeout from config if present); otherwise return current behavior. Benchmark script sets `os.environ["ATRIA_COUNCIL_MODEL"] = "qwen2.5:3b"` before importing/calling council (and clears or unsets for “current” conditions).
- **Option B (override in atria_tools):** Benchmark script monkey-patches `local_ai.providers.get_council_provider` to return `OllamaProvider(model=benchmark_model)` for the duration of the run. No production code change; script is self-contained but fragile if import order or caching changes.

**Recommendation:** Option A (env var). One small, clear code path in `get_council_provider()`; benchmark script sets env per condition and runs the same `run_council()` path as production.

**Exact production change for Option A:**

- In `local_ai/providers/__init__.py`, in `get_council_provider()`:
  - `import os`
  - If `os.environ.get("ATRIA_COUNCIL_MODEL")`:
    - Return `OllamaProvider(model=os.environ["ATRIA_COUNCIL_MODEL"])` (timeout from config or default).
  - Else:
    - Return `get_default_provider()` as today.

**Benchmark script:**

- For conditions 1–3 (current model): do not set `ATRIA_COUNCIL_MODEL` (or set it to `qwen3:8b` if config might differ).
- For conditions 4–5: set `os.environ["ATRIA_COUNCIL_MODEL"] = "<chosen_smaller_model>"` before the run(s) for that condition.

### 2.3 Reuse of Pass 1 scenarios and roles

- Reuse `SCENARIOS` and `INCLUDED_ROLES` from `scripts/eval_council_pass1.py` (or import them from a small shared module so both scripts stay in sync).
- Same `run_council(..., included_roles=INCLUDED_ROLES, perspective_definitions=None, ...)` so backend uses built-in roles and same prompts as Pass 1.

### 2.4 Timeout

- Keep `COUNCIL_SEAT_TIMEOUT = 25` for all conditions so comparisons are fair (same timeout budget per seat).

---

## 3. Recommended smaller/faster council models to test

Candidates that are typically faster than qwen3:8b on the same hardware and can still follow structured output (Position / Primary reason / Main risk / Guardrail / Next step):

| Model (Ollama tag) | Notes |
|--------------------|--------|
| **qwen2.5:3b** | Same family as current; good instruction following; much faster than 8b. **Primary candidate.** |
| **phi3:mini** | ~3.8B; fast; decent structure. **Secondary candidate.** |
| **smollm2:1.7b** or **qwen2.5:1.5b** | Very fast; quality may drop; use if 3b still too slow. |

**Recommendation:** Run Pass 2 with **qwen2.5:3b** as the smaller council model for conditions 4 and 5. If results are promising, add a second smaller model (e.g. phi3:mini) in a follow-up run.

**Prerequisite:** Pull the chosen model in Ollama before the benchmark (e.g. `ollama pull qwen2.5:3b`).

---

## 4. Metrics and how to determine the winner

### 4.1 Collected per run (per scenario × condition)

- **Total latency (s):** Wall-clock time for `run_council(...)`.
- **Seats completed:** Count of seat blocks in the output that are not `[Error: ...]` or timeout. Max 3.
- **Synthesis ran:** Boolean (whether “Atria synthesis:” appears in output).
- **Output saved:** Full text for optional manual review (readability / decision usefulness).

### 4.2 Primary metric to determine the winner: **seats completed (and total latency as tiebreaker)**

- **Rationale:** Pass 1 showed that when seats time out, synthesis often doesn’t run and value drops. So the main goal is to maximize how often all 3 seats complete within the 25s timeout, then minimize latency.
- **Winner rule:** Prefer the condition with the **highest total seats completed** across the 3 scenarios (max 9). If tied, prefer the condition with **lowest average total latency** over the 3 runs.
- **Secondary:** If two conditions tie on seats completed and are close on latency, compare **readability** and **decision usefulness** on saved outputs (manual or simple heuristics, e.g. “has Position:” and “has Next step:” and no “[Error” in seat blocks).

### 4.3 Readability and decision usefulness

- **Readability:** Keep Pass 1 style: “structured (Position / Primary reason / Main risk / Guardrail / Next step) per seat.” For Pass 2, record whether each completed seat block contains the expected fields (e.g. regex or substring checks). Report % of completed seats that are “well-formed.”
- **Decision usefulness:** Subjective on a small sample: does the output give a clear position and next step? Optional: score 1–3 per scenario and average per condition. Not required for the primary winner; use to break ties or validate that the “winning” setup is still usable.

**Summary:** Primary = **seats completed** (then **total latency**). Readability and decision usefulness support the choice and help detect regressions (e.g. faster but useless output).

---

## 5. Benchmark script shape (no code yet)

- **File:** `scripts/eval_council_pass2.py`.
- **Input:** Same `SCENARIOS` and `INCLUDED_ROLES` as Pass 1 (import or copy).
- **Loop:** For each of the 5 conditions (model × concurrency), set override (env + `COUNCIL_MAX_WORKERS_OVERRIDE`), run 3 scenarios, record latency, seats completed, synthesis ran; optionally write outputs to a directory for review.
- **Output:** Table (condition × scenario) and summary: total seats completed and average latency per condition; recommend winner by the rule above.
- **No streaming:** Use `run_council` only (non-streaming) for reproducible timing.

---

## 6. Minimal production changes summary

| File | Change |
|------|--------|
| `local_ai/atria_tools.py` | Add `COUNCIL_MAX_WORKERS_OVERRIDE = None`. In all four `ThreadPoolExecutor` usages, use `workers = COUNCIL_MAX_WORKERS_OVERRIDE if COUNCIL_MAX_WORKERS_OVERRIDE is not None else min(3, len(tasks))`. |
| `local_ai/providers/__init__.py` | In `get_council_provider()`, if `os.environ.get("ATRIA_COUNCIL_MODEL")` set, return `OllamaProvider(model=...)`; else unchanged. |
| `scripts/eval_council_pass2.py` | New script: loop over 5 conditions × 3 scenarios, set env and override, call `run_council`, collect metrics, print table and winner. |

No change to prompt structure, timeout values, or streaming path for the benchmark itself. Overrides are used only when set (benchmark or future config); default behavior remains Pass 1 behavior.
