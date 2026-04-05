# Wave autonomy protocol (V1)

<!--
Status: Operational law for online wave-gated runners
Related: AUTONOMOUS_REPAIR_POLICY.md, convergence_program_state.json, wave_registry.json, wave_exit_gate.py
-->

## Purpose

Define how **repo-level autonomy** runs **online** in **discrete waves**, with:

- **One active autonomy workflow run** at a time (GitHub Actions `concurrency`).
- **No silent promotion** to the next wave: advancement requires **machine-checkable exit criteria** (`wave_exit_gate.py`) plus any **manual** promotion fields documented below.
- **Git as state + rollback spine**: branches, tags, artifacts—not a separate database.

This protocol is **Layer 1 (repo autonomy)** only. **Runtime / Zenaf behavior observation** (classification drift, trunk mismatch, list explosion) is **Layer 2** and **must not** drive repo commits or share the same auto-fix loop until explicitly chartered. **Escalation (SMS)** is **Layer 3** and fires only for **human-required** repo states listed below.

---

## Definitions

| Term | Meaning |
|------|---------|
| **Wave** | A named slice of convergence work with declared exit checks (enforcement + tests + optional phase alignment). |
| **Exit criteria** | Conditions `wave_exit_gate.py` evaluates; exit code `0` means the wave **passes the gate** for this run. |
| **Promotion** | Moving program focus to the **next** wave (e.g. editing `current_wave_id` in `wave_registry.json` and updating `convergence_program_state.json`). **Never** automatic inside the same job as the gate without a documented, reviewed workflow change. |
| **Checkpoint tag** | Lightweight Git tag for rollback, format: `checkpoint/wave-<wave_id>-<YYYYMMDDThhmmssZ>` (UTC), created only on **success** paths when the workflow has tag permissions. |

---

## Git spine

- **`main`**: protected; autonomous runners **do not** push directly to `main` in V1.
- **Work branches**: `auto/wave-<slug>` (e.g. `auto/wave-5-perimeter`) for autonomous commits when auto-repair is enabled (V1.5+).
- **Artifacts**: Each run uploads `wave_exit_report.json`, philosophy reports under `reports/philosophy_enforcement/`, and optional repair logs.
- **Summary commits**: Allowed only when changes strictly follow `AUTONOMOUS_REPAIR_POLICY.md` (improved confirmed count, tests pass, allowed globs). Default CI **does not** apply repair; see **V1.5** below.

Human narrative of what happened in a session may still be appended to `rogue_run_log.md` offline.

---

## Concurrency (one run at a time)

Workflow **`.github/workflows/wave-autonomy.yml`** uses:

- `concurrency.group: atria-wave-autonomy`
- `cancel-in-progress: false`

So a **second** scheduled or manual run **waits** for the first to finish instead of overlapping. Adjust only if you accept overlapping autonomy (not recommended).

---

## Machine-checkable gate

Canonical script: `scripts/philosophy_enforcement/wave_exit_gate.py`

Registry: `scripts/philosophy_enforcement/wave_registry.json`

For the active wave:

1. Optionally require `docs/01_TRUTH/convergence_program_state.json` → `active_phase` to equal `optional_phase_equals` (string). **Fails closed** on mismatch—prevents “green enforcement, wrong program phase.”
2. Run `run_all.py` with `PHILOSOPHY_ENFORCE_STRICT=1` when `exit.enforce_strict` is true (fail on any philosophy row `fail` / confirmed violations per runner).
3. Run each `pytest` target in `exit.pytest_targets` (repo-root relative paths).

The script writes **`wave_exit_report.json`** (summary JSON) for upload as a workflow artifact.

### Escalation fields (for SMS and humans)

The report includes (in addition to `steps`):

| Field | Role |
|-------|------|
| `ok` | Gate pass/fail |
| `wave_id` | Active wave |
| `phase` | `convergence_program_state.json` `active_phase` when readable |
| `failed_checks` | Stable ids: `phase_alignment`, `branch_ref`, `philosophy_enforcement` or per-row `philosophy_<id>_<slug>`, `pytest:<path>` |
| `block_type` | `hard` when failed, else `none` |
| `suggested_action` | One-line hint derived from the first failed check |
| `branch` / `commit` | From `GITHUB_REF` / `GITHUB_SHA` when set (CI) |
| `promotion` | Echo of registry `requires_manual_flag` + notes |

Formatter: `scripts/philosophy_enforcement/wave_sms_body.py` builds the Twilio body from this file.

---

## Promotion rule (no YOLO)

**There is no automatic promotion** when the gate turns green. Advance **`current_wave_id`** only through an **explicit human decision**:

1. **Manual edit:** PR or local commit updating `wave_registry.json` (and usually `convergence_program_state.json`), **after** `wave_exit_gate.py` exited `0` on the commit you trust.

2. **Optional workflow dispatch:** `promote_next_wave: true` runs `wave_promote.py`, which sets `current_wave_id` to the **next** entry in `waves[]` (ordered list) and **pushes** that commit. Use **only** when you intend that bump; if there is no next wave, the job **fails**. You may combine with `run_exit_gate: false` for a **promote-only** run (still human-triggered via dispatch).

Branch protection on `main` may block `git push` from `GITHUB_TOKEN`; adjust policy or use a PAT as needed.

---

## V1.5 — Optional `auto_repair --apply` in CI

[`AUTONOMOUS_REPAIR_POLICY.md`](AUTONOMOUS_REPAIR_POLICY.md) states that **default** CI must not run `auto_repair.py --apply`.

The wave workflow may expose **`workflow_dispatch` input `apply_repair`** (default `false`). When `true`:

- Run **only** on `refs/heads/auto/wave-*` (not on `main`).
- Invoke `python scripts/philosophy_enforcement/auto_repair.py --apply --write-enforcement-report` after the gate **or** in place of a second pass—operators must document the exact order in the workflow.

This is **opt-in** and requires secrets/permissions appropriate for pushing to the wave branch if you add push steps later.

---

## SMS (Twilio) — human-required only

Scripts: `scripts/philosophy_enforcement/notify_twilio_sms.py` (send), `scripts/philosophy_enforcement/wave_sms_body.py` (format from `wave_exit_report.json`).

1. **Failure:** On gate job failure, the workflow downloads the `wave-exit-report` artifact and sends an SMS with **wave id, failed_checks, suggested_action, branch, commit, run URL** (falls back to a short message if the report is missing).

2. **Success (opt-in):** Dispatch with **`notify_on_success: true`** sends a short “wave complete / awaiting promotion” message. **Scheduled runs** leave this off by default to avoid weekly noise.

3. **Safety / revert** (future): optional SMS when auto-repair reverts.

**Do not** SMS on heuristic/partial philosophy rows alone unless you extend this protocol.

Secrets (repository): `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_FROM_NUMBER`, `NOTIFY_TO_NUMBER` (E.164). If secrets are absent, the notify step **skips** without failing the workflow.

---

## Optional branch pattern

If a wave sets `exit.branch_ref_pattern` to a regex (e.g. `^refs/heads/auto/wave-`), the gate compares `GITHUB_REF` when set. Omit or `null` to skip (e.g. running gate on `main` for visibility).

---

## Deferred (explicit non-goals)

- Wiring **runtime behavior anomalies** into this workflow or into auto-repair.
- Twilio **reply** handling (1=review, 2=ignore).
- Cloudflare Workers / Pipedream orchestration until GitHub Actions is insufficient.

---

## Related files

| File | Role |
|------|------|
| [`AUTONOMOUS_REPAIR_POLICY.md`](AUTONOMOUS_REPAIR_POLICY.md) | Local vs CI repair bounds; checkpoint semantics |
| [`convergence_program_state.json`](convergence_program_state.json) | Program phase + objectives (cross-check optional) |
| [`global_philosophy_integration_matrix.json`](global_philosophy_integration_matrix.json) | Checker registry for `run_all.py` |
| `rogue_run_log.md` (repo root) | Optional human run narrative |
| `.github/workflows/wave-autonomy.yml` | Online runner (gate, optional notify, optional promote) |
| `scripts/philosophy_enforcement/wave_sms_body.py` | SMS body from `wave_exit_report.json` |
| `scripts/philosophy_enforcement/wave_promote.py` | Bump `current_wave_id` to next `waves[]` entry |
| `.github/workflows/philosophy-enforcement.yml` | PR/push enforcement (no wave gate) |
