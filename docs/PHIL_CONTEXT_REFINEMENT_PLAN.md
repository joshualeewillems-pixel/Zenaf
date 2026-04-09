# Phil Context Refinement — Truth Hierarchy Repositioning

**Status:** Proposal (no implementation yet)  
**Goal:** Treat Phil-derived content as **operator priority / preference weighting** in fast council, not as global task truth or broad philosophical framing for every seat.

---

## 1. Current usage (audit)

| Location | What happens |
|----------|--------------|
| **`local_ai/context/phil_context.py`** | Single function `load_phil_context()` reads `phil_brand_brief.md`, looks for first of `## Council context`, `## Phil Context`, `## Distilled`, else start of file; returns up to 300 words. One global cache. |
| **`local_ai/context/phil_brand_brief.md`** | Contains a short "## Council context" block: Mission, Strength, Common bottleneck, Best intervention, Tone. Already somewhat operational but labeled as generic "Phil Context". |
| **`local_ai/zenaf_tools.py` → `build_council_decision_packet()`** | Unconditionally appends `Phil Context:\n{_truncate(phil, MAX_PHIL_CONTEXT_CHARS)}` (300 chars) to the **shared packet** sent to **every** council seat. No distinction by seat or by purpose. |

**Problem:** The same block is presented to every seat as "Phil Context", which reads like global task truth or worldview. The content (bottleneck, intervention, tone) is really **operator preference / priority** and should be framed and scoped as such.

---

## 2. Conceptual split

| Concept | Purpose | Length | When to use |
|--------|---------|--------|-------------|
| **Operator priority (priority profile)** | What the operator is optimizing for; preferred tradeoffs; practical constraints/aversions. | Short (e.g. 100–150 words or ~200 chars in packet). | Fast council: small weighting block so seats can align with operator preferences without treating them as task truth. Optionally emphasize for Brand/Integration seats. |
| **Philosophical orientation** | Mission, worldview, values language. | Can be longer (e.g. up to 300 words). | **Not** default for fast council. Reserved for: synthesis step (optional), governance-heavy runs, or general assistant / cockpit alignment when we want mission framing. |

---

## 3. Smallest safe patch plan

### 3.1 Split the loader (`local_ai/context/phil_context.py`)

- **Add** `load_operator_priority() -> str`:
  - Look for sections in this order: `## Operator priority`, `## Priority profile`, `## Council context` (backward compatible with current brief).
  - Return content of first match, capped at a **small** word limit (e.g. **120 words**). This keeps it clearly a “weighting hint,” not an essay.
  - Cache separately from philosophical orientation (e.g. `_cache_priority: str | None`, `_cache_philosophy: str | None`).

- **Add** `load_philosophical_orientation() -> str`:
  - Look for sections: `## Philosophical orientation`, `## Mission & worldview`, `## Phil Context`, `## Distilled`.
  - Return content capped at existing 300 words. For use only where we explicitly want mission/worldview (synthesis, governance, general assistant).
  - Cache separately.

- **Keep** `load_phil_context() -> str` for backward compatibility:
  - Implement as “return `load_operator_priority()`” so any existing or future callers get the short priority block by default. Optionally add a deprecation comment that call sites should use `load_operator_priority()` or `load_philosophical_orientation()` explicitly.

No change to file path or filename; still `phil_brand_brief.md`.

### 3.2 Council packet: use priority only, relabel (`local_ai/zenaf_tools.py`)

- In **`build_council_decision_packet()`**:
  - **Remove** the current “Phil Context” block (the one that calls `load_phil_context()` and appends `Phil Context:\n...`).
  - **Add** a block that:
    - Calls `load_operator_priority()` (from `context.phil_context`).
    - If non-empty, appends with label **`Operator priority:`** (or **`Priority weighting:`**), e.g.  
      `Operator priority:\n{_truncate(priority, MAX_OPERATOR_PRIORITY_CHARS)}`.
  - Introduce a **small** cap for this block only, e.g. **`MAX_OPERATOR_PRIORITY_CHARS = 220`** (so it stays clearly below “task context” in both length and framing). Remove or repurpose `MAX_PHIL_CONTEXT_CHARS` for this call site so the default council packet never includes the long philosophical block.

- **Do not** inject `load_philosophical_orientation()` into the default council packet or into every seat. No change to synthesis or other paths in this minimal patch unless we explicitly add an optional synthesis-only use (see below).

### 3.3 Brief structure (`local_ai/context/phil_brand_brief.md`)

- **Rename or duplicate** the current “## Council context” section to **`## Operator priority`** (or keep “## Council context” so the loader still finds it as fallback for operator priority). Content should stay short and practical:
  - What we optimize for
  - Preferred tradeoffs
  - Practical constraints / aversions
  - (Optional) one line on tone/collaboration if it affects choices)

- **Add** a section **`## Philosophical orientation`** (or **`## Mission & worldview`**):
  - Mission, worldview, values language.
  - Used only by `load_philosophical_orientation()`; not included in default council packet.

If we keep “## Council context” as the fallback source for operator priority, we can leave the current content there and add “## Philosophical orientation” below it; no need to remove content, only to clarify which section is which.

### 3.4 Where each loader is used (after patch)

| Loader | Use |
|--------|-----|
| **`load_operator_priority()`** | **Fast council:** single “Operator priority:” block in `build_council_decision_packet()`, capped at ~220 chars. Optional future: pass only to Brand (or Brand + Integration) seat when we have seat-specific packet building. |
| **`load_philosophical_orientation()`** | **Not** in default council seats. **Reserved for:** (1) optional synthesis step (e.g. one-line “mission alignment” hint when building synthesis prompt), (2) governance-oriented or “full council” modes if we add them, (3) general assistant / cockpit system prompt when we want mission framing. No new injection in this minimal patch beyond defining the loader and documenting intent. |
| **`load_phil_context()`** | Becomes a thin wrapper returning `load_operator_priority()` so behavior is “priority only” by default; call sites that currently expect “Phil context” get the short priority block. |

### 3.5 What is removed from default council prompt assembly

- **Removed:** The label **“Phil Context”** and the injection of the full 300-word-style block into the shared packet for every seat.
- **Removed:** Any implication that the brief is “global task truth” or “philosophical framing for every seat.” The new “Operator priority:” block is explicitly a preference/weighting hint.
- **Unchanged:** Task context, question, recent tool summary, key constraints, and per-seat system prompts. Only the Phil-derived block is replaced and relabeled; no other truth sources are changed.

---

## 4. Summary table

| Item | Current | After refinement |
|------|--------|-------------------|
| **Loader** | Single `load_phil_context()` (up to 300 words from Council context / Phil Context / start). | `load_operator_priority()` (short, ~120 words, from Operator priority / Priority profile / Council context); `load_philosophical_orientation()` (up to 300 words, from Philosophical orientation / Mission & worldview / Phil Context); `load_phil_context()` = `load_operator_priority()` for compatibility. |
| **Council packet** | “Phil Context:” + truncated 300 chars to every seat. | “Operator priority:” + truncated ~220 chars to every seat (from `load_operator_priority()`). No philosophical block in default packet. |
| **Brief file** | One section “## Council context”. | “## Operator priority” (or keep “## Council context” as fallback) + “## Philosophical orientation” for mission/worldview. |
| **Philosophical orientation** | Not separated. | Loaded only by `load_philosophical_orientation()`; used only for synthesis/governance/general assistant when we add those call sites. |

---

## 5. Implementation order

1. **`phil_context.py`**: Add `load_operator_priority()` and `load_philosophical_orientation()` with separate caches and section logic; make `load_phil_context()` return `load_operator_priority()`.
2. **`phil_brand_brief.md`**: Add `## Operator priority` (or keep `## Council context` as fallback) and `## Philosophical orientation`; keep content short under Operator priority.
3. **`zenaf_tools.py`**: In `build_council_decision_packet()`, replace Phil Context block with Operator priority block (new label, `MAX_OPERATOR_PRIORITY_CHARS`, call `load_operator_priority()`).
4. **Optional later:** Use `load_philosophical_orientation()` in synthesis prompt or general assistant when we want mission alignment.

This keeps the operator-priority shortcut, repositions it in the truth hierarchy (preference/weighting, not task truth or global philosophy), and reserves longer philosophical content for contexts where it is explicitly needed.
