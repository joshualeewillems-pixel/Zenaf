# Multi-Instance Ollama Council Routing — Feasibility Assessment

**Status:** Design / investigation only (no implementation)  
**Goal:** Evaluate whether routing different council seats to different Ollama instances would meaningfully improve throughput, or add contention and complexity on current hardware.

---

## 1. Where provider routing would need to change

### 1.1 Current flow

- **`local_ai/atria_tools.py`**
  - `run_council` and `run_council_stream` each call `get_council_provider()` **once** at the start and receive a **single** provider instance.
  - That same provider is passed into every `_run_one_role(..., provider)` submitted to the `ThreadPoolExecutor` (four call sites: two in `run_council`, two in `run_council_stream`).
  - Synthesis uses the same provider: `provider.generate(synthesis_prompt, timeout=25)`.
  - So today: one provider → one base URL → one Ollama process; all seat requests and synthesis hit the same instance.

### 1.2 Changes required for multi-instance routing

| Location | Current behavior | Change needed for per-seat instances |
|----------|------------------|--------------------------------------|
| **`local_ai/providers/__init__.py`** | `get_council_provider()` returns a single provider. | Either (a) add something like `get_council_providers() -> list` that returns one provider per instance (e.g. one per URL), or (b) have `get_council_provider()` return a router object that implements `.generate(...)` and internally selects instance (e.g. round-robin). Callers would then need to support (a) or (b). |
| **`local_ai/atria_tools.py`** | Builds one `provider`, then `executor.submit(_run_one_role, idx, name, prompt, provider)` for every task. | **Option A (provider list):** Obtain a list of providers; for each task, pass `providers[seat_index % len(providers)]` into `_run_one_role`. So change from one shared `provider` to a per-task provider. Requires building the task list with an associated provider per task, or resolving provider by index at submit time. |
| **`local_ai/atria_tools.py`** | Synthesis uses `provider.generate(...)`. | Decide which instance runs synthesis: e.g. first instance, or a dedicated “synthesis” URL, or round-robin. Same provider interface; only which provider is chosen. |
| **`local_ai/config.py`** | Single `OLLAMA_URL`. | Add configuration for multiple council instances (see §3). |
| **`local_ai/providers/ollama.py`** | `OllamaProvider(base_url=..., model=..., timeout=...)`. | No change. Each instance is already a separate `OllamaProvider(base_url=url_i)`. |

**Summary:** The only behavioral change is **who provides the provider** (one vs many) and **what gets passed per seat**. All seat work already goes through `_run_one_role(..., provider)`; we only need to pass a different `provider` (different `base_url`) per seat when multiple instances are configured.

---

## 2. Whether the current provider abstraction supports per-seat instance selection

**Yes.** The contract is: “something with `.generate(prompt, timeout=...) -> str`.”

- **Per-seat selection with current abstraction:** Caller (e.g. `run_council`) can obtain a **list** of `OllamaProvider` instances (each with a different `base_url`). When submitting tasks, pass the provider for that seat: e.g. `provider_i = providers[i % len(providers)]` and `executor.submit(_run_one_role, idx, name, prompt, provider_i)`. `_run_one_role` already accepts a `provider` and calls `provider.generate(prompt, timeout=timeout)`; it does not care whether that provider points at instance A or B.
- **No change to `OllamaProvider` or to `_run_one_role`** is required for per-seat routing. Only the **call site** that builds the provider(s) and passes them into the executor must change (e.g. from one `provider` to a list and pick by index).
- **Synthesis:** Can keep using one provider (e.g. first in the list, or a dedicated “synthesis” instance). Still the same `.generate(...)` call.

So the abstraction already supports multiple instances; the missing piece is configuration and call-site logic to create and assign providers per seat.

---

## 3. Configuration shape

### 3.1 Minimal: multiple URLs for council only

Keep a single default `OLLAMA_URL` for non-council use. Add council-specific config:

- **List of URLs (simplest):**
  - `OLLAMA_COUNCIL_URLS: list[str] = ["http://localhost:11434/api/generate", "http://localhost:11435/api/generate"]`
  - If unset or empty, fall back to single provider from `get_council_provider()` as today (e.g. default URL).
  - Factory or helper builds `[OllamaProvider(base_url=u, model=..., timeout=...) for u in OLLAMA_COUNCIL_URLS]`.

### 3.2 Named / per-instance settings

If different instances might use different models or timeouts:

- **List of dicts:**
  - `OLLAMA_COUNCIL_INSTANCES = [{"url": "http://localhost:11434/api/generate", "model": "qwen3:8b"}, {"url": "http://localhost:11435/api/generate", "model": "qwen3:8b"}]`
  - Each entry yields one `OllamaProvider(**entry)`.

### 3.3 Single config source

- **Single URL:** `OLLAMA_COUNCIL_URL` (optional). If set, council uses it; else council uses default `OLLAMA_URL`. (No multi-instance.)
- **Multiple URLs:** `OLLAMA_COUNCIL_URLS` (optional). If set (list), council uses N providers; seats are assigned round-robin (or by index). If unset, use single default provider.

Recommendation: start with **`OLLAMA_COUNCIL_URLS`** as an optional list. If absent or empty, behavior stays “one provider” as today. No need for named providers unless we later need per-instance model or timeout.

---

## 4. Bottlenecks that would remain (or worsen) with multiple instances

### 4.1 Same machine, same GPU

- **Compute:** If one Ollama process is already saturating the GPU, adding a second process usually means two processes competing for the same GPU. Throughput may not improve and per-request latency can get worse (context switching, memory pressure).
- **Memory:** Typical Ollama deployment loads one model per process. Two instances ⇒ two model loads ⇒ roughly 2× VRAM or RAM for the model. On a single machine with limited RAM/VRAM, this can cause OOM or heavy swapping and hurt everyone.
- **Queueing:** Today, one process serializes requests in its own queue. With two processes on the same hardware, we parallelize at the process level but the hardware still does the work; we may just split the same total capacity across two queues and add overhead.

### 4.2 Same machine, multiple GPUs

- If the machine has **multiple GPUs** and we run one Ollama instance per GPU (each bound to a different GPU), we get true parallel compute. Then multi-instance routing can improve throughput, assuming we have at least as many instances as seats and the GPUs are not already saturated by other workloads.

### 4.3 Multiple machines

- If instances run on **different hosts** (e.g. two machines, each with its own Ollama), then we get real parallelism and no shared hardware contention. Routing seat 1 → host A and seat 2 → host B can improve throughput. Network latency and availability of the remote instance become the main concerns.

### 4.4 Synthesis

- Synthesis is a **single** call after seats complete. It does not benefit from “spreading across instances” for parallelism; it only needs one free instance. If that instance is one of the same council instances, it can still be delayed by other work on that instance (or by contention if everything is on one machine).

### 4.5 Summary of remaining bottlenecks

| Scenario | Bottlenecks that remain (or get worse) |
|----------|----------------------------------------|
| 1 machine, 1 GPU, 2+ Ollama instances | GPU and memory contention; possible 2× model memory; no real throughput gain, risk of worse latency. |
| 1 machine, 2+ GPUs, 1 Ollama per GPU | Less of a bottleneck; main limit is total GPU capacity and how many seats we run at once. |
| 2+ machines, 1 Ollama per machine | No shared-hardware bottleneck; network and instance availability matter. |
| Any | Synthesis is still one sequential call; its latency is unchanged or can worsen if the chosen instance is busy. |

---

## 5. Recommendation: when multi-instance is beneficial, neutral, or harmful

### 5.1 Beneficial

- **Multiple GPUs on one machine:** Run one Ollama instance per GPU, bind each to a different GPU; route council seats across instances (e.g. by index). Likely to improve throughput vs a single process.
- **Multiple machines:** Each machine runs its own Ollama; council seats are routed to different machines. Clear win for throughput if the machines are not already overloaded.
- **Single machine but proven queue serialization:** If profiling shows that a **single** Ollama process is serializing requests and underusing the GPU (e.g. idle time between requests), and running a **second** process has been measured to increase total throughput without hurting latency, then two instances on the same host can be beneficial. This is environment-specific and should be validated with benchmarks.

### 5.2 Neutral

- **Single machine, single GPU, two instances:** May behave similarly to today if the GPU was not saturated and the OS schedules the two processes without much contention. Could slightly improve or slightly worsen; only measurement (and possibly different concurrency settings) will tell. Not recommended without testing.

### 5.3 Harmful

- **Single machine, limited RAM/VRAM, multiple instances:** Risk of OOM or swapping when each instance loads its own copy of the model. Can severely degrade latency and reliability.
- **Single GPU, multiple instances:** High risk of contention and worse per-request latency; little or no gain in throughput. Generally not recommended.
- **Operational complexity:** Multiple instances mean more to deploy, monitor, and debug (which instance failed, which URL to check). If throughput gain is small or zero, the added complexity is harmful.

---

## 6. Summary

| Question | Answer |
|----------|--------|
| Where would provider routing change? | `get_council_provider()` (or new `get_council_providers()`), config (add `OLLAMA_COUNCIL_URLS` or equivalent), and the four executor call sites in `atria_tools.py` that today pass a single `provider` — they would pass a provider per seat (e.g. by index from a list). Synthesis would use one chosen provider. |
| Does the current abstraction support per-seat selection? | Yes. `_run_one_role` already takes a `provider` and calls `provider.generate(...)`. Passing a different `OllamaProvider(base_url=...)` per seat is enough; no protocol change. |
| What configuration shape? | Optional `OLLAMA_COUNCIL_URLS: list[str]` (or list of dicts with `url`/`model`/`timeout`). If unset or empty, keep current single-provider behavior. |
| What bottlenecks remain? | Same machine + same GPU: contention and 2× model memory; often no gain. Synthesis remains one call. Multiple GPUs or multiple machines are where multi-instance helps. |
| When beneficial / neutral / harmful? | **Beneficial:** Multiple GPUs or multiple machines. **Neutral:** Single GPU, two instances, with measurement. **Harmful:** Single machine with limited memory, or single GPU with multiple instances without evidence of gain. |

**Practical recommendation:** Do not implement multi-instance routing on the assumption it will help on “current hardware” (typically one machine, one GPU). First validate with Pass 2–style benchmarks (e.g. smaller model, concurrency 1 vs 2). If the bottleneck remains and the deployment has (or will have) multiple GPUs or multiple machines, then multi-instance Ollama routing is a reasonable next step and the current provider abstraction can support it with the changes above.
