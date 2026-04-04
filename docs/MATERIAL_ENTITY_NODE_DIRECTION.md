# Material Entity / Asset Roadmap (Vision Execution)

This note is **design guidance**. Do not implement all of this at once. Use it to preserve direction and make local choices that align with the intended system shape.

---

## Core direction

Assets are evolving toward a broader concept:

**Material entity node** = any non-human resource that participates in execution.

Examples:

- tools
- systems/software
- documents/templates
- equipment
- spaces
- supplies
- budget-like resources
- later: vendors/services

This is the **non-human capability/dependency layer** of the execution system.

**Execution ontology:**

- **work nodes** = ideas / initiatives / projects / tasks
- **human nodes** = persons
- **role nodes** = seats
- **material nodes** = assets

So:

- **Seats** answer **who is needed**
- **Material entities** answer **what is needed**
- **Work nodes** answer **what is being attempted**
- **People** answer **who can fill roles / steward resources**

**Always preserve these semantic distinctions:**

- `linked_to` = contextual association
- `required_by` = execution dependency
- `owned_by` / `stewarded_by` = control / access

Current backend already partially expresses these through:

- `linked_idea_ids`, `linked_initiative_ids`, `linked_project_ids`
- `required_assets` / `required_asset_ids` (on initiatives, projects, tasks)
- `owner_id`

Do not blur those concepts.

---

# NOW (short-term guidance)

**Goal:** Make assets feel operationally meaningful without schema rewrites.

## Priorities

1. **Improve asset UI clarity**
   - top summary strip
   - separate “Linked to” vs “Required by”
   - show human-readable titles instead of raw ids
   - derive simple summaries like:
     - `Unused asset`
     - `Linked for context`
     - `Required by active work`
     - `Supports active execution`

2. **Use existing loaded data to derive reverse usage**
   - at minimum: scan initiatives for `required_assets.includes(asset.id)`
   - if project/task required-asset data is already available in the frontend, include it too
   - keep this deterministic and presentation-oriented

3. **Preserve current storage model**
   - do not rewrite schema
   - do not build new link tables
   - do not build a generic graph

4. **Treat project/task required assets as real execution concepts**
   - even if not fully surfaced everywhere yet
   - avoid treating assets as merely “attachments”

## Short-term principle

Prefer:

- semantic clarity
- better display
- reverse usage visibility

Over:

- model expansion
- new abstractions

---

# NEXT (medium-term guidance)

**Goal:** Bring material entities into operational reasoning more directly.

## Priorities

1. **Expose asset requirements consistently across work nodes**
   - initiative required assets already visible
   - surface project/task required assets in the main execution UI when practical
   - keep distinction between: linked/contextual vs required/dependency

2. **Add backend/service helpers**
   - Examples: `get_asset_linked_usage(asset_id)`, `get_asset_required_usage(asset_id)`, `get_asset_operational_summary(asset_id)`
   - These do not need to change storage first; they can aggregate from existing records.

3. **Introduce lightweight derived operational states**
   - Examples: unused, linked only, required by draft work, required by active work, unavailable but required, potentially over-relied-on (later)
   - These can begin as service-layer or UI-layer derivations.

4. **Weave assets into radar more explicitly**
   - Future radar examples: active work missing required assets, unavailable required assets, underused valuable assets, assets required by multiple active work nodes.

5. **Keep meeting extraction / review / commit aligned**
   - Material entities as: mentioned resources, required dependencies, created systems/tools/docs, assigned/promised resources.

## Medium-term principle

Move from “asset records with links” toward “non-human resources with operational meaning”.

---

# LATER (long-term guidance)

**Goal:** Generalize assets into a broader material capability layer when the system is ready.

## Priorities

1. **Evolve “asset” toward broader material entity semantics** (without rushing into a full universal graph)
   - software systems, templates/docs, equipment, spaces, services/vendors, budget buckets / financial resources.

2. **Unify participation logic conceptually**
   - All major execution participants answer: what are you? what are you attached to? what depends on you? are you available? are you blocking something? who stewards you?

3. **Add richer dependency semantics later if needed**
   - Examples: required, helpful, optional, blocking if missing, substitute available. Do not add until existing semantics are consistently used.

4. **Potentially broaden from “assets tab” to “material capability layer”** only if the product benefits. Do not rename or re-architect prematurely.

## Long-term principle

Do not chase abstraction first. Earn it by preserving semantics, making operational use legible, and letting material capability flow through execution.

---

# Practical decision rule

When changing anything related to assets/material entities, ask:

1. Is this merely **linked/contextual**?
2. Is this **required to execute**?
3. Who **owns/stewards** it?
4. Is it **available right now**?
5. Is it **enabling** or **blocking** active work?

If the code/UI cannot answer those questions cleanly, improve that before adding new abstraction.

---

# Implementation boundary reminder

**Do NOT:**

- collapse everything into one universal node table yet
- build a full graph model yet
- add many subtypes just for elegance
- over-normalize before operational behavior is clear

**Do:**

- preserve semantics
- improve summaries
- expose reverse usage
- make material entities feel like first-class execution participants
