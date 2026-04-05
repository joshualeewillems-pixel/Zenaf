# Fruit / Integration Artifact — Mint Policy

<!--
Status: Canonical (policy — implementation gated)
Last updated: 2026-04-04
Companion: economic layer plan (`.cursor/plans/fruit_tokenomics_assessment_*.plan.md`), `CODEBASE_TRUTH_RULES.md`, `coordination_signals.py`
-->

**Purpose:** Lock **what may become a minted Integration Artifact** (public-facing name may differ from vitality “fruit”) and **what the system is allowed to claim**. This document is **law for product honesty** until superseded by charter/truth convergence update.

**Scope:** Policy law per [TRUTH_CONVERGENCE.md](TRUTH_CONVERGENCE.md) (locked row: Integration Artifact mint policy). Schema and UI may lag; shipped behavior and copy must not contradict this document.

---

## 1. The core axiom

**Value thesis:** Do not pay for effort, attention, or raw expression. Economic recognition attaches only to **integration that is structurally evidenced in Vision & Execution (VE)** and (when activated) to **downstream reuse signals** that remain **honestly non-causal**.

**Vitality Fruit ≠ Economic Fruit:** VE `node_vitality` water/soil/fruit scores measure **local execution health**. They **must not** drive minting or payout math.

### The truth constraint — boundary of interpretation

**Integration Artifacts are interpretations over VE evidence, not objective measures of personal development.** The system must **not** claim or imply that an artifact represents true inner transformation. At most it certifies: **a verifiable, coordination-shaped arc** (or re-ignition lineage) **within the system’s trace**, under the mint gates below.

This humility is the main defense against becoming a **delusional oracle**: we measure **coordination artifacts**, not human souls.

---

## 2. What gets minted — three layers (structurally bound)

Every minted artifact is a **structurally bound** compression of three distinct layers (terminology may vary in UI):

| Layer | Meaning |
|--------|---------|
| **Arc structure** | The finite pattern the **system** may propose from VE + judgment evidence (e.g. chronological footprint, friction readings, completion, stability window). Same structural unit can appear across users; **no** parallel clinical ontology. |
| **Stylization** | How the user **dresses** the arc (mythic, clinical, mundane, etc.). Denomination for legibility; **does not** replace proof requirements. |
| **Provenance** | The **irreducible trace** tied to this user’s entities and judgment history: what rows, what times, what pointers. **Provenance tier** may increase on **re-ignition** (deeper spiral) with explicit lineage to prior mints. |

**Product honesty — no false cryptography:** Do **not** describe this binding as “cryptographic” unless the implementation actually uses hashes committed to a Merkle tree (or equivalent). Until then use **“structurally bound”** or **“evidence-bound.”**

---

## 3. Proof of work — system detection (soft certainty)

**Artifacts cannot be manually generated or self-reported from scratch.** Self-report and stylization **co-author** the artifact but **do not** satisfy proof alone.

A **candidate** arc may be proposed when the system detects a **chronological footprint** along the lines of:

\[
T_{\text{avoid}} \rightarrow T_{\text{eng}} \rightarrow T_{\text{complete}} \rightarrow W_{\text{stability}}
\]

using **existing** evidence types (e.g. `execution_flow_reading` judgments on `node_judgment_history`, VE entity `status` / timestamps, optional `activity.log` corroboration). Parameters \(C_{\text{friction}}\), \(W_{\min\text{-}span}\), \(W_{\text{stability}}\) are policy-tuned, **not** user-visible as exact thresholds (see §7).

**Detection produces a candidate, not a guarantee.** Minting requires **both**:

1. **System evidence** meeting the gated footprint (and any tier-specific depth rules), and  
2. **User synthesis** (explicit integration / share step in product — ceremony TBD in implementation).

---

## 4. Co-authorship minting ceremony (division of labor)

**System detects → user synthesizes → system binds.**

- The system proposes **candidates** from trace.  
- The user supplies **meaning** (stylization, narrative compression, consent to share policy).  
- The system **binds** the mint to **SubjectRef + judgment/VE pointers** and lineage fields — **structurally bound**, not inferred from chat alone.

---

## 5. Downstream value — correlation, not causation

When an artifact **assists** another user in navigating friction — measured by **probabilistic downstream utility signals** in the **receiver’s** VE trace — the originating artifact may **accrue** tokenomic weight.

**Explicit law:** The system tracks **correlation and reuse patterns**, not **definitive causation**. Copy must never imply that User A *caused* User B’s outcome; at most that engagement **preceded** measurable receiver-side signals per policy.

---

## 6. No parallel ontologies

Flow signals, developmental hypotheses, and mint eligibility are **interpretations of VE state and append-only judgments**, not a second source of entity truth. Confirmed writes remain **explicit payload** per existing commit rules.

---

## 7. UX and incentive hygiene

- **Serendipity:** The minting moment should feel **noticed**, not **scored**.  
- **Goodhart:** Visible progress bars toward exact numeric thresholds create a **Skinner box**. Obscurity of precise gates is **load-bearing** (reduces direct optimization; does not remove all gaming).  
- **Decay and re-ignition:** If regression-shaped signals recur (ontology-pure: e.g. similarity + friction telemetry), prior glow may **dim**; **re-mint at higher provenance tier** is allowed when a **new** pass satisfies gates, carrying **lineage** (spiral, not amnesia). Cooldowns/anti-spam TBD in implementation.

---

## 8. Stress test — three failure scenarios (pre-code)

If this policy is sound, it must **gracefully** address the following. **Responses below are architectural intent**, not shipped behavior.

### Scenario 1 — The productivity farmer (gaming)

**Setup:** A user learns the rough shape \(T_{\text{avoid}} \to T_{\text{complete}}\), creates **mundane** tasks (e.g. “Do laundry”), waits, logs **one** friction checkpoint, completes, and tries to **harvest** tree fruits.

**Test:** How does the system avoid filling the tree with **garbage** without judging the “worthiness” of the user’s goals?

**Policy response (non-moral):**

- **Graph and depth gates:** Tie **tier** (or eligibility) to **structural** features that trivial loops lack — e.g. mint **only** from entities that sit under a **non-trivial** initiative/project graph, minimum **checkpoint count** or **pointer-kind diversity** (client trace vs council stream), minimum \(W_{\min\text{-}span}\) and **stability** requirements.  
- **Rate limits:** Cap mints per user per window regardless of task count.  
- **Stylization does not expand proof:** Mythic copy **cannot** substitute for missing judgment footprint.  
- **Honest labeling:** Low-tier or no mint for **thin** graphs is framed as **insufficient structural evidence**, not “your goal is shallow.”

### Scenario 2 — The sincere delusion (spiritual bypassing)

**Setup:** A large initiative (“Resolve childhood trauma”), one strong session, catharsis, **one** positive checkpoint, immediately marked **Done**, plus a sweeping mythic narrative.

**Test:** The user **sincerely** believes completion; the **trace** is tiny.

**Policy response:**

- **Narrative is not proof:** User synthesis **cannot** mint without **system** footprint meeting **minimum depth** and **\(W_{\text{stability}}\)**. A single spike **fails** the chronological/stability contract.  
- **Tier cap:** Stylization tier **≤** evidence tier; no “ultimate dragon” **mint** without proportional **append-only** evidence (readings, time spread, completion semantics).  
- **Product copy:** Refusal is **evidence incomplete / stability not met**, not “you didn’t really heal.”

### Scenario 3 — The silent integration (edge-case success)

**Setup:** Real friction on a project (\(T_{\text{avoid}}\)), user **leaves** Atria for weeks, does real-world work, returns and marks the task **Done**. **No** intermediate \(T_{\text{eng}}\) `execution_flow_reading` rows.

**Test:** Does the system **miss** a real arc?

**Policy response (honesty first):**

- **v0 footprint:** Yes — a strict \(T_{\text{avoid}} \to T_{\text{eng}} \to \cdots\) detector **can false-negative** when checkpoints are sparse.  
- **Mitigations (implementation backlog):** Alternate **evidence paths** — e.g. **long-gap + terminal state + activity.log** completion event, **retroactive** council checkpoint, or a **human review / appeal** lane for practitioner deployments.  
- **Product honesty:** The system should **not** pretend it saw what happened offline; it should either **relax gates in defined cases** with explicit rules or **acknowledge** the miss.

---

## 9. Preconditions before implementation

1. **Measure** real `execution_flow_reading` density for live sessions (arc detector needs rows).  
2. Lock **minimum evidence tables** and **tier rules** in this doc or `TRUTH_CONVERGENCE.md`.  
3. No mint UI that exposes exact numeric thresholds (§7).  
4. **Automation:** Philosophy matrix row **#16** + `check_vitality_value_boundary` in `scripts/philosophy_enforcement/` — mint/ledger code must not import `node_vitality_scores` / `compute_vitality_scores` (allowlist only `storage.py` vitality upsert, the scores module itself, and `tests/test_node_vitality_scores.py`).  
5. **Lab table:** `arc_detection_candidates` in `local_ai/vision_execution/schema.sql` stores heuristic **proposals** only (`python -m local_ai.vision_execution.detect_arcs`); not mint evidence until policy graduates this path.

---

## References (code / schema)

- `local_ai/vision_execution/coordination_signals.py` — `execution_flow_reading` choke point  
- `local_ai/vision_execution/storage.py` — `node_judgment_history`, VE entities  
- `local_ai/activity.py` — `ActivityEvent` types (optional corroboration)  
- `local_ai/integration_commit.py` — affirmation pattern for explicit writes  

---

**Deferred trajectory (not active work):** [TOKENOMICS_DIRECTION_NOTE.md](TOKENOMICS_DIRECTION_NOTE.md) — tokenomics frozen as a defined future layer; activation conditions, constraints, and “do not build” directive until evidence and charter layers are ready.
