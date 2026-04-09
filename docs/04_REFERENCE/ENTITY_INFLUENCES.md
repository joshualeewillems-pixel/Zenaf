# Entity influences (Phase 1)

**Status:** UI + **localStorage** only. No API or DB fields yet.

## Purpose

Minimal directed edges between:

- **Core profiles** (identity)
- **Perspectives** (cognitive lenses; agent ids from `zenaf-perspective-agents` storage)
- **People** (execution / capacity actors)

Intended future use: AI behavior weighting, task routing hints, profile export / rental — **not** a full graph product.

**Product alignment:** The cockpit is moving toward **one canonical core profile** per workspace/person and **many perspectives** as lenses; **core_profile → core_profile** edges may be retired or hidden in UI when only one core exists. See **`docs/01_TRUTH/SYSTEM_REFERENCE.md`** §1.4a.

## Data shape

```ts
type InfluenceTargetKind = 'core_profile' | 'perspective' | 'person'
type InfluenceWeight = 'low' | 'medium' | 'high'

type InfluenceLink = {
  targetKind: InfluenceTargetKind
  targetId: string
  weight: InfluenceWeight
}
```

## Storage

- **Key:** `zenaf-entity-influences-v1`
- **Value:** JSON object map: `sourceKey → InfluenceLink[]`
- **Source key:** `` `${sourceKind}:${sourceId}` `` (e.g. `core_profile:abc`, `perspective:strategist`, `person:xyz`)

## UI

- **Perspectives** page (top nav): **Core profile** detail and **perspective** detail include **Influences** when `App` passes `influenceLinkLists` (core profiles + persons from the Vision Execution API). UI labels: **Core profile**, **Perspective**, **Person** (see `INFLUENCE_TARGET_KIND_LABEL` in `entityInfluences.ts`).
- **Team** tab (Vision → Execution): person detail includes the same section (core profile list loaded in the background for picklists).

## Conflicts / edge cases

- **Single lens store:** Perspective agents use `localStorage` key `zenaf-perspective-agents` (Perspectives page + Workspace Organizer council checkboxes).
- **Orphan targets:** If a linked entity is deleted server-side, the link row still shows until the user removes it (label may fall back to raw id).
- **Self-links:** Prevented in the add UI for same kind + id.
- **Cross-device:** localStorage only — not synced.

## Code

- `frontend/src/perspectives/entityInfluences.ts` — load/save helpers
- `frontend/src/perspectives/InfluencesLinksSection.tsx` — form UI
