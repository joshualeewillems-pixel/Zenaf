# Vision Map & zen projection (current state and direction)

<!--
Status: Canonical (as-built for this slice)
Last updated: 2026-04-02
-->

This document describes the **Vision map** surface: a React Flow–based **live projection** of Vision Execution (VE) entities into a zen-garden metaphor (seeds, trees, branches, flowers, fruit), plus the **right-hand context panel** growth model. It complements **`VISION_EXECUTION_TABS_REFERENCE.md`** (operator tables) and **`SYSTEM_REFERENCE.md`** Part IV (platform-wide current state).

---

## 1. Where it lives in the product

- **Entry:** Operator mode → **Vision map** (or equivalent navigation that renders `VisionMapView`).
- **Data:** Same VE bundle as other views: `fetchVisionMapEntities()` + `fetchStudioCouncilRuns()` → `buildLiveVisionMapGraph(bundle, councilRuns)`.
- **Not** a separate backend: the map is a **read-only projection** over existing ideas, initiatives, projects, tasks, and synthetic **fruit** nodes (shipped project + `deliverables` text).

---

## 2. Where the system is today (implemented)

| Layer | Role |
|-------|------|
| **Graph build** | `liveProjection.ts` — positions, edges, `MapNodePayload` (growth, condition, water, council preview, summary lines). |
| **Visual ontology** | `ontology.ts` — `MapEntityKind`, `GrowthState`, `ConditionState`, `VeEntityType`, payload shape. |
| **Vitality / water** | `mapVitalForces.ts` — owner/assignee/seat heuristics → `water_level`; fertilizer pulse; used by nodes and edges. |
| **Focus** | `visionMapFocus.ts` — dim non-focused nodes when a selection is active. |
| **Nodes** | `EntityMapNode.tsx` — stone UI, condition/growth affordances. |
| **Edges** | `MapFlowEdge.tsx`, `mapEdgeVitality.ts`. |
| **Sand bed + rake** | `ZenSandCanvas.tsx` — dual canvas (bed + rake), **height-field** deformation in `sandHeightField.ts` (comb stamp, decay, non-destructive overlap rules); `MapSandRakeControls.tsx` (clear, rake toggle, fade preset). |
| **Context panel** | `MapChatShell.tsx` — council CTA, blockers/teacher sections, **growth triad** (`MapGrowthTriad.tsx` + `mapGrowthMetrics.ts`) derived from payload + bundle (no new API). |
| **Styling** | `mapAesthetics.css` — sand stack, graph chrome, nodes. |
| **Council bridge** | `mapCouncilActions.ts`, `councilCorrelation.ts` — anchor ref, prefilled questions, teacher copy. (Workspace council / Zenaf contract, timeouts, and **`[ID: …]`** / **`[DRAFT_VALUE]`** behavior: **`SYSTEM_REFERENCE.md`** §2.7 / §3.6, **`CODEBASE_TRUTH_RULES.md`** §9.) |
| **Developmental signals (→ council)** | `VisionMapView` optional **`onDevelopmentalSignalsChange`** — compact triad + missing-dimension snapshot for cockpit **`buildDevelopmentalGuidanceContext`** / `council_preflight.developmental_guidance` (platform doc: **`SYSTEM_REFERENCE.md`** §2.4, **Part IV**). |
| **Copy / badges** | `mapInterpretiveCopy.ts` — tension badges, interpretive summary (still in panel below triad). |

**Growth triad metrics (0–1), all client-side:**

- **Water** — `water_level`, `fertilizer_pulse`, council preview timestamps/text (`mapGrowthMetrics.ts` → `computeWaterLevel`).
- **Soil** — text depth on VE rows (brief, next step, risks, dependencies, deliverables, task criteria, etc.) (`computeSoilQuality`).
- **Fruit** — growth enum, done-like statuses, deliverables, task completion ratios by entity kind (`computeFruitProgress`).

---

## 3. Where it is going (direction, not committed roadmap)

| Direction | Notes |
|-----------|--------|
| **Richer signals** | Optional backend-derived scores later; today everything is explainable heuristics on existing columns. Triad already feeds **developmental guidance v1** for council (client-assembled); fuller cross-surface memory is not built. |
| **Radar / Signal integration** | Map could highlight or link Layer 1 signals for the selected ref; not wired yet. |
| **Subject/Node primitive** | Long-term platform direction (`SYSTEM_REFERENCE.md` §2.1); map would consume generic node refs when substrate exists. |
| **Sand / field** | Possible: higher-res field, contour rendering, or persistence of rake pattern per user (currently ephemeral, decay-only). |
| **Council** | “Ask council about this” opens workspace flow; deeper inline run history on the map is optional. |

---

## 4. Files that best represent this slice

Use these first when onboarding or debugging the Vision map:

| File | Why |
|------|-----|
| `frontend/src/vision-map/VisionMapView.tsx` | Shell: sand layer, ReactFlow, chat shell, data load. |
| `frontend/src/vision-map/liveProjection.ts` | **Source of truth** for graph topology and payload assembly. |
| `frontend/src/vision-map/ontology.ts` | Typed contract for node `data`. |
| `frontend/src/vision-map/mapGrowthMetrics.ts` | **Source of truth** for Water / Soil / Fruit 0–1 scores. |
| `frontend/src/vision-map/MapGrowthTriad.tsx` | Growth triad UI. |
| `frontend/src/vision-map/MapChatShell.tsx` | Panel composition and sections. |
| `frontend/src/vision-map/ZenSandCanvas.tsx` + `sandHeightField.ts` | Rake simulation and rendering. |
| `frontend/src/vision-map/mapVitalForces.ts` | Water tier inputs from VE rows. |
| `frontend/src/vision-map/mapAesthetics.css` | Layout/stacking (sand under graph, controls). |

Supporting: `EntityMapNode.tsx`, `MapFlowEdge.tsx`, `deriveVisualState.ts`, `blockersFromVe.ts`, `mapInterpretiveCopy.ts`, `MapSandRakeControls.tsx`.

---

## 5. Related docs

- **`docs/04_REFERENCE/VISION_EXECUTION_TABS_REFERENCE.md`** — VE tabs, fields, behavior (system of record).
- **`docs/01_TRUTH/SYSTEM_REFERENCE.md`** — Whole-platform intent and Part IV current state.
- **`docs/01_TRUTH/CODEBASE_INVENTORY.md`** — §8 Frontend + §10 VE backend.
- **`docs/01_TRUTH/ACTIVE_VS_PLANNED.md`** — Surfaces table (Vision map row).
