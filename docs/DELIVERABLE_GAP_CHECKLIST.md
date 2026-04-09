# Deliverable gap checklist

<!--
Status: Working backlog (not a release gate spec)
Last updated: 2026-03-27
-->

This document consolidates **partial implementations**, **integration gaps**, and **testing / go-to-market** work needed for Zenaf to function as a **reasonably solid, marketable** product. It merges the **conversation backlog**, **`docs/01_TRUTH/ACTIVE_VS_PLANNED.md`**, **`docs/01_TRUTH/CODEBASE_INVENTORY.md`**, **`README.md`**, and targeted code notes. It is **not** exhaustive file-by-file coverage.

**How to use:** Treat items as a prioritized backlog; link PRs/issues when closing gaps. Canonical “what exists vs planned” detail remains in **`ACTIVE_VS_PLANNED.md`**.

---

## A. Started or partial — system-wide integration still open

### Council / workspace AI

| Gap | Notes |
|-----|--------|
| **`seat_question` not in cockpit** | API and `run_council` / `run_council_stream` support optional `seat_question` (narrow seat prompt; full `question` drives synthesis). Frontend still sends a single `question` only. |
| **Council integrity calibration** | Streaming integrity + `failure_template` path exist; **heuristic tuning** was intentionally deferred. Stress scenarios (e.g. ambiguous PRIMARY / run1-style) can still **flake** when the model returns normal anchored synthesis instead of the stress outcome. |
| **Eval vs product policy** | Harness adjustments (e.g. run9 under local/Ollama) are **not** the same as a product promise of “fully grounded” council; strict cloud-only expectations need an explicit **eval profile** or policy if marketed. |
| **AI action trace parity** | Workspace `/run` / `/run/stream` emits traces but **no `AiActionResultPanel`**; **user outcomes** not fully wired. Evaluate-style flows: **apply/dismiss → trace** still open. See **`ACTIVE_VS_PLANNED.md`**. |
| **Idea “Clarify with AI”** | Stub (timed local fill); **no LLM**. |

### Interpretive axis → future artifact (explicitly deferred)

Do **not** implement persistence, schemas, or storage for this yet. When/if built later, a **versioned judgment-profile**-style artifact should likely store distilled tendencies, evidence refs, confidence bounds, revision history, explicit scope/context, and review state — **not** raw developmental-guidance wording. For now: keep **runtime structures interpretable** so they can transform into such an artifact later.

### Intake / mirror / policy

| Gap | Notes |
|-----|--------|
| **Mirror sync after poll** | `mirror_sync` / `set_sync_state` not called after poll; **`mailbox_action`** not written by current flows. See **`CODEBASE_INVENTORY.md`**. |
| **Tier B / C** | `get_item_with_content()` exists; **no API route or UI** consumes it. **Tier C** remains placeholder (`raw_content_ref`). |
| **Policy adoption** | Documented intent: council / File Steward use shared **`data_access`** for sensitive tiers; **only mirror** uses it today. |
| **External egress** | `request_access(..., Destination.EXTERNAL)` exists; **no real external** consumer path. |
| **Background poll** | On-demand only; **no scheduler**. |

### Other surfaces

| Gap | Notes |
|-----|--------|
| **File Steward plan UI** | “Execute moves” / “Save for later” still **TODO** (`App.tsx`). |
| **Perspectives** | “Chat with perspective” / “Use in Workspace” **placeholder** (`PerspectivesView.tsx`). |
| **Core profile** | “Reprocess with new influences” **not implemented** (`coreProfilePanels.tsx`). |
| **Meeting / Content / core reconcile** | **Legacy** vs shared trace substrate; migration **planned**. |

### Platform / architecture (documented as not built)

- **Shared artifact memory**, **node substrate** — see **`docs/01_TRUTH/SYSTEM_REFERENCE.md`**.
- **Profile versioning / distillation pipeline** — profiles in UI; server pipeline not implemented.

### Operational / data (thread reminder)

- **`intake_mirror.db`** (and VE DB) deserve **backup / version-history** discipline (e.g. OneDrive). An empty mirror recreate implies **re-sync** from mailbox for operational memory.

---

## B. Testing and quality

| Area | Need |
|------|------|
| **E2E / contract** | Smoke paths: auth (if shipped), **council stream** + integrity fields, vision-execution CRUD, intake poll + queue. |
| **`seat_question`** | Automated tests that **seat** prompts use `seat_question` and **synthesis** uses `question` (harness exercises this today; pytest would harden regressions). |
| **Council** | Teacher modes, wash, `routing_context` + anonymous Ollama fallback; document **acceptable mismatch budget** for adversarial batch under Ollama vs cloud. |
| **Frontend** | Integration tests for high-risk flows (council, VE focus rewrite, intake detail) where feasible. |
| **Concurrency** | WAL + `busy_timeout` help SQLite; **multi-worker** and **parallel long streams** need explicit stress if “team” use is claimed. |
| **Release gate** | Run **`tools/run_adversarial_stream_batch_tuned20.py`** (or successor) when changing council or integrity. |

---

## C. Training, ops, and marketable wrap (non-code)

| Item | Notes |
|------|--------|
| **Runbook** | Install, ports (**README** defaults **8010**; align with local overrides), Ollama vs OpenAI, **`ZENAF_SETTINGS_ENCRYPTION_KEY`**, DB file locations and backup. |
| **User-facing story** | What the product does/does not do: **local vs cloud**, integrity labels, **anonymous** limits (e.g. OpenAI key). |
| **Support playbook** | Mirror recovery, council fallback meta, known stubs. |
| **Security / compliance positioning** | README: **not production-hardened** by default; align marketing claims with cookie auth, CORS, and key handling. |
| **Commercial distribution** | If shipping binaries: dependency/licensing audit (npm/PyPI, LLM provider terms). |

---

## D. Source-of-truth pointers

| Doc | Role |
|-----|------|
| `docs/01_TRUTH/ACTIVE_VS_PLANNED.md` | Surfaces, flows, gaps, near-term targets |
| `docs/01_TRUTH/CODEBASE_INVENTORY.md` | Module/file inventory, mirror/poll caveats |
| `docs/01_TRUTH/SYSTEM_REFERENCE.md` | Philosophy, planned subsystems |
| `README.md` | Handoff, ports, “not production-hardened” |
| `tools/run_adversarial_stream_batch_tuned20.py` | Streaming council stress batch + harness notes |
| `docs/COUNCIL_INTEGRITY_ADVERSARIAL_EVAL_RUNS.md` | Manual integrity scenario reference |

---

## E. Maintaining this checklist

When a gap closes, **update this file** or **`ACTIVE_VS_PLANNED.md`** so they stay aligned. Prefer **one canonical sentence** in `ACTIVE_VS_PLANNED` for “product truth” and a **short pointer** here if the checklist grows.
