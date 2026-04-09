# Vision Map `water_level` — stewardship vs execution shape

## Intent

`water_level` (`high` | `medium` | `low`) drives **coarse node surface wetness** on the Vision Map (see `map-water-*` in `frontend/src/vision-map/mapAesthetics.css`). It should reflect **whether work is stewarded *and* bounded in execution terms** — not only “someone is named.”

## Algorithm home

Implemented in **`frontend/src/vision-map/mapVitalForces.ts`** (`deriveWaterLevel`, `waterLevelFromVital`, `vitalFor*`).

## Rules (summary)

| Tier | Meaning |
|------|--------|
| **high** | Owner/assignee (or initiative seat assignment) **and** **execution shape complete** for that entity type. |
| **medium** | Owner/assignee **or** shape complete **or** entity touched within **14 days** (`updated_at`). |
| **low** | None of the above. |

## Execution shape by entity (current)

These fields are **filled** as follows before shape counts as complete:

### Initiative

- **Timeframe:** `estimated_timeframe_ai` non-trivial (trimmed length ≥ 3).
- **Seats:** If `seats.length > 0`, **every** seat has `assigned_person_id` set. If there are **no** seat rows, seat check passes (seats are optional until defined).

**Not yet in algorithm (follow-up):** rolling up **project** `start_date` / `end_date` / `estimated_weekly_hours` under the initiative would require passing project lists into `vitalForInitiative` from `liveProjection.ts` (or a server-computed flag).

### Project

- **Timeframe:** `start_date` and `end_date` both set.
- **Hours:** `estimated_weekly_hours` present and **> 0**.

### Task

- **Time / effort:** `due_date` set **or** `estimated_hours` **> 0** (assignee is already the “owner” signal).

### Idea

- **People + intent:** at least one `linked_people` entry **and** meaningful `desired_outcome` or `summary` (max length ≥ 20 chars).

## Related data (not map surface)

- **Triad / server `node_vitality`:** still computed elsewhere for soil/fruit and panels; **entity node wetness** uses **only** `water_level` on the payload (see prior change).
- **Edges:** `edgeWaterTone` still uses endpoint `water_level`; unchanged in this note.

## Future tie-ins

- Initiative **hours** via child projects’ `estimated_weekly_hours` or a dedicated initiative field.
- Stricter seat rules (e.g. `estimated_effort` per seat required).
- Alignment with **capacity** (`weekly_capacity_hours` vs active project hours) as a separate signal if product wants it.
