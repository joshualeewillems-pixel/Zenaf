# Arc detector lab — glossary, lanes, and fixture scenarios

<!--
Status: Active design (lab contract — not product truth about real users)
Last updated: 2026-04-04
Companion: `docs/01_TRUTH/FRUIT_MINT_POLICY.md`, `local_ai/vision_execution/detect_arcs.py`
Seeding: `scripts/seed_arc_lab_fixtures.py` — evaluation: `scripts/eval_arc_detector_lab.py`
-->

**Purpose:** Stable vocabulary and **synthetic** test scenarios for heuristic `v0.1_friction_to_done`. Synthetic timelines prove **detector mechanics**, not that real users “transformed.”

---

## Three lanes (do not mix invisibly)

| Lane | What it is | Truth value |
|------|------------|-------------|
| **Real** | Production telemetry from real accounts | Highest for product meaning; slow |
| **Synthetic** | Scripted `node_judgment_history` + VE rows under a **dedicated lab user** | Instrumentation / regression only |
| **Interpretive** | Human review of `arc_detection_candidates` (right / arguable / wrong) | Mints policy and UX |

**Rule:** Synthetic data must never be mistaken for entity truth about a real person. Lab projects use title prefix **`ARC-LAB:`** and user **`arc_lab_synthetic@local.zenaf`** (display name marks synthetic).

---

## Detector-layer glossary (tight)

| Term | Definition |
|------|------------|
| **friction-negative** | `execution_flow_reading` with `dimension=friction`, `impact=negative` (above confidence floor) on an **owned** VE subject — observable blockage signal in-system, not a clinical claim. |
| **pivot-positive** | Later reading on the **same** subject: `impact=positive`, or non-negative friction/clarity/capacity per v0.1 pivot rules — observable engagement shift. |
| **completion** | VE **terminal** status on the scanned row (`done` / `complete` / … — same word list as detector), not a feeling. |
| **stability** | Wall-clock **now** is at least **3 days** after inferred completion time; **no** strong friction-negative reading **after** completion timestamp. |
| **arc candidate** | Output of the heuristic + optional DB row in `arc_detection_candidates` — **system interpretation**, not proof of inner change. |

---

## Fixture scenarios (expected vs actual)

Run `python scripts/seed_arc_lab_fixtures.py` then `python scripts/eval_arc_detector_lab.py`.

| Scenario id | `ARC-LAB:` title suffix | Intended timeline (mechanical) | Expected `try_v01` outcome |
|-------------|-------------------------|--------------------------------|----------------------------|
| `clean_hit` | `clean_hit` | Friction → pivot ≥48h later → terminal `updated_at` ≥3d before *now*; no post-completion friction | **Match** (`skip` is `None`) |
| `insufficient_span` | `insufficient_span` | Friction and pivot ok order but completion &lt;48h after friction anchor | **`insufficient_span`** |
| `unstable_after_completion` | `unstable` | Strong friction-negative **after** `updated_at` completion | **`unstable_after_completion`** |
| `rapid_false_positive_trap` | `rapid` | Friction, pivot, “complete” within ~1h | **`insufficient_span`** (or stability if times align badly) |
| `sparse_no_flow` | `sparse` | No `execution_flow_reading` rows | **`no_execution_flow_readings`** |
| `not_terminal` | `not_terminal` | Good readings; project stays **Draft** | **`not_terminal`** |
| `missing_pivot` | `missing_pivot` | Only friction-negative; no pivot | **`missing_pivot`** |
| `mixed_council_shape` | `mixed` | Client friction + client positive + extra **neutral clarity** row (synthetic pointer, `activity_event` shape for lab only) | **Match** (neutral does not break v0.1 if ordering holds) |

**Why these:** They separate threshold bugs (span, stability) from instrumentation bugs (no readings) from “happy path.”

---

## What synthetic proof does **not** show

- It does **not** validate product copy, tree UI, or tokenomics.
- It does **not** substitute for a **real** timeline on a real account once `execution_flow_reading` production density improves.

---

## Commands

```bash
# One-time or after DB wipe (creates user + projects + backdated judgments)
python scripts/seed_arc_lab_fixtures.py

# Compare heuristic to expected skips / match
python scripts/eval_arc_detector_lab.py
```

Optional: `ARC_LAB_SEED_PASSWORD` env when creating the lab user (default is dev-only placeholder).

`reports/arc_lab/manifest.json` is written by the seed script (machine-specific ids) and is **gitignored**; regenerate after clone or DB reset.
