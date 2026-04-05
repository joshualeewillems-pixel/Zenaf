# Autonomous repair policy

<!--
Status: Canonical (operating constraints for local automation)
Companion: repair_registry.json, scripts/philosophy_enforcement/auto_repair.py
-->

**Purpose:** Define what an **autonomous philosophy repair loop** may do in this repo, when it must stop, and how rollback must behave—so automation is a **bounded operator**, not uncontrolled mutation.

**Non-goals:** Product redesign, prompt/ontology changes, or “fixing” heuristics without human review.

---

## Law stack (inputs)

Automation reads truth from (in order of specificity):

1. `ATRIA_SYSTEM_CHARTER.md`
2. `TRUTH_CONVERGENCE.md`
3. `GLOBAL_PHILOSOPHY_INTEGRATION_MATRIX.md` + `global_philosophy_integration_matrix.json`
4. `repair_registry.json` (what may be auto-repaired)
5. This policy (how the loop behaves)

---

## What autonomous repair **may** change

Only when **all** are true:

- A **confirmed** violation from a registered checker (`kind == confirmed_violation` in enforcement JSON).
- The checker is marked `repairable: true` in `repair_registry.json`.
- A **registered repair handler** exists in code for that checker (see `scripts/philosophy_enforcement/repairs/`).
- Every touched path matches an **allowed file glob** for that checker.
- The number of touched files ≤ `max_touched_files` for that checker.

Allowed edit **types** (when a handler declares them):

- **config** — JSON/TS registry rows, philosophy config under `scripts/philosophy_enforcement/config/`
- **docs** — TRUTH docs only if explicitly allowed by the checker entry (default: not allowed)
- **route_trace** — in-body trace/exempt wiring patterns **only** where a codified handler implements them (Phase 1+; not implied by `repairable: true` alone)

---

## What autonomous repair **must not** change

- Heuristic-only findings (`heuristic_suspicion`) — no auto-fix.
- Philosophies with no checker or `not-yet-automated` rows — no inventing fixes.
- Broad refactors, dependency upgrades, or unrelated formatting.
- Charter/matrix semantics (unless human updates law and registry in the same change).
- Meeting extraction semantics, scoring, weighting, or council prompts.
- Anything outside `allowed_file_globs` for the active checker.
- **New files** unless the checker entry sets `allow_new_files: true` and any created paths match `allow_untracked_globs`.

---

## Filesystem hygiene (post-handler)

After a handler runs and before tests/commit, `auto_repair.py` enforces:

1. **Untracked files:** If `allow_new_files` is false (default), any `git status` untracked path (`??`) → **revert** (handler must not drop stray files).
2. If `allow_new_files` is true, every untracked path must match at least one `allow_untracked_globs` pattern; otherwise **revert**.
3. **Diff truth:** `git diff --name-only` (working tree vs index) must equal exactly the handler’s `touched_files` set; otherwise **revert** (detects extra edits or no-op lies).

This limits residue when `git reset --hard` runs (tracked files only).

---

## Success criteria

A repair **iteration** succeeds only if:

1. **Enforcement:** Count of **confirmed** violations is **strictly lower** than before the iteration (for the scoped checker or globally—see `revert_scope` in registry; default: global confirmed count).
2. **Tests:** Every command in `required_tests` for that checker exits 0 (if the list is non-empty).
3. **Scope:** Touched files ⊆ allowed globs and ≤ `max_touched_files`.

If `repairable: false` or no handler: the loop **reports only** (dry-run or “no handler”).

---

## Stop conditions (must halt)

The runner **stops** (no further iterations) when:

- Working tree is dirty and `--allow-dirty` was not passed.
- Git is unavailable and `--no-git` was not passed (checkpoint/revert disabled → refuse `--apply`).
- No confirmed violations remain **or** no repairable checker has violations + handler.
- An iteration would touch zero files but claims success (handler bug).
- Touched files exceed `max_touched_files` or fail glob validation.
- **Confidence drop:** enforcement confirmed count **increases** after a repair attempt (`revert_on_worse: true`).
- Required tests fail.
- `--max-iterations` reached.

---

## Checkpoint and revert (Git as rollback spine)

**Local Git is mandatory for `--apply`** unless `--no-git` is set (then only enforcement + report; no writes that need revert).

1. **Before** applying patches: require a **clean** `git status` (or `--allow-dirty` with explicit acknowledgment in the report).
2. Create an annotated or lightweight tag: `checkpoint/philosophy-<UTC-timestamp>` at current `HEAD` (e.g. `checkpoint/philosophy-20260403T211800Z`).
3. Apply handler changes **only** in the working tree (no commit until validation passes).
4. Re-run enforcement + required tests.
5. **If improved:** `git add` only allowed paths, then `git commit` with a structured message (see below).
6. **If worse or tests fail:** `git reset --hard HEAD` and `git clean -fd` **only if** the repair did not create commits; if intermediate commits were made, `git reset --hard <checkpoint-tag>` (Phase 2—v1 avoids mid-run commits).

**Branches:** Prefer `auto/philosophy-enforcement` (or topic branches) for autonomous work; do not push to `main` from the script. Opening/updating a PR is human or CI follow-up.

---

## Commit message format

```
chore(philosophy-enforce): auto-repair <checker_id>

- confirmed_before: N
- confirmed_after: M
- policy: docs/01_TRUTH/AUTONOMOUS_REPAIR_POLICY.md
```

---

## Auto-repair phases (rollout)

| Phase | Scope |
|-------|--------|
| **0** | Runner: enforce → report → Git tag → no codified handlers (`repairable: false` default). |
| **1** | **One** repairable checker at a time; first handler: `trace_exempt_registry_sync` — append missing exempt ids to `aiTraceExemptRegistry.ts` when a route already declares `# charter-trace-exempt:<id>` but the id is absent from the registry (honors the route’s stated intent; human still reviews reason text). |
| **2** | Optional codified route/trace templates **only** where `repair_registry` + handler agree. |

**Current:** `trace_or_exempt` is `repairable: true` with the registry-sync handler only; all other checkers remain `repairable: false`.

---

## CI vs local

- **Local:** `auto_repair.py` may use `--apply` with Git checkpoints.
- **CI:** Run philosophy enforcement + tests; **upload reports**; **do not** run `--apply` in the default workflow (no self-modifying CI without separate policy).
- **Wave autonomy (online):** `.github/workflows/wave-autonomy.yml` is the gated runner; see [`wave_autonomy_protocol.md`](wave_autonomy_protocol.md). **`apply_repair` is default `false`** on `workflow_dispatch`. When set `true`, the workflow runs `--apply` **only** on `refs/heads/auto/wave-*` (not on `main`). Scheduled runs never enable `apply_repair`. This is **V1.5**—keep the default PR/push workflow (`.github/workflows/philosophy-enforcement.yml`) without `--apply`.

---

## Related files

| File | Role |
|------|------|
| [`wave_autonomy_protocol.md`](wave_autonomy_protocol.md) | Online wave gates, concurrency, SMS triggers, promotion rules |
| `scripts/philosophy_enforcement/wave_registry.json` | Current wave id + exit criteria for `wave_exit_gate.py` |
| `scripts/philosophy_enforcement/wave_exit_gate.py` | Machine-checkable wave exit (strict enforcement + pytest + optional phase) |
| `scripts/philosophy_enforcement/repair_registry.json` | Per-checker repair eligibility and caps |
| `scripts/philosophy_enforcement/auto_repair.py` | Loop orchestration |
| `scripts/philosophy_enforcement/repairs/` | Handler implementations |
| `reports/philosophy_enforcement/` | Enforcement + auto-repair run artifacts |
