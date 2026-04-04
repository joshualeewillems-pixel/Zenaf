# Mediation — operational design note

**Purpose:** Translate “mediation” into **observable system behavior** for prompts, response shapes, and review criteria. Not positioning language. Not a roadmap for new systems.

---

## 1. Core definition

### What mediation means **in this codebase**

**Mediation** = the product **does not only optimize for a single “right answer.”** It **surfaces multiple legitimate framings**, **makes tradeoffs and tensions explicit**, **grounds claims in supplied context**, and **leaves room for a human to commit** (approve, edit, defer, reject). The engine **structures disagreement and uncertainty** into **reviewable artifacts** instead of collapsing them into one authoritative narrative.

Operationally that implies:

- Outputs are often **multi-part** (see §4), not only `recommendation`.
- Where the system “decides” (e.g. intake lane, evaluation proposal), the **reasoning path should be inspectable** (signals, rationale fields, council seats, judgment chain) so a human can **mediate** between model output and ground truth.
- **Default LLM paths** (`/run`, council) and **user-scoped paths** (evaluate, settings-backed provider) share this contract at the **output/review** layer even when routing differs (`docs/01_TRUTH/CODEBASE_TRUTH_RULES.md`).

### What it is **not**

- Not **therapy**, coaching, or personality inference.
- Not a **single oracle** that replaces ownership.
- Not **consensus theater** (fake agreement) or **endless options** with no decision hook.
- Not a **new subsystem** — mediation is a **quality bar on existing surfaces** (prompts, schemas, UI copy, review checklists).

---

## 2. Primary behavioral lenses (5–7)

Use these as **checklist dimensions** when writing prompts or reviewing AI output — not as user-facing labels.

| Lens | Source tradition | Operational question for the model |
|------|------------------|-----------------------------------|
| **Multiple partial truths** | Conflict resolution | What are **2+ coherent readings** of the same facts? Where do they agree and disagree? |
| **Interests vs positions** | Negotiation / mediation | What **outcomes** might parties want under stated **constraints**, vs what they **said** literally? |
| **Readiness & stakes** | Human development (organizational) | What **decision stage** fits this artifact (explore / commit / escalate)? What **breaks** if we act too early? |
| **Load & chunking** | Cognitive psychology | What **3–7 chunks** of structure help a human decide without overload? |
| **Sensemaking under ambiguity** | Organizational sensemaking | What is **unknown**, **assumed**, and **worth verifying** next? |
| **Legitimate constraints** | Org / ops reality | What **capacity, policy, dependency, or time** limits apply **from context**, not invented? |
| **Procedural fairness** | Dispute systems | What **next step** respects an accountable human (owner, reviewer, operator)? |

---

## 3. Cross-feature implications

How mediation should **shape** outputs and decisions **in product areas** (behavioral intent, not implementation tasks).

| Area | Mediation-shaped behavior |
|------|---------------------------|
| **`/run` (File Steward modes)** | Surface **tradeoffs** (e.g. folder options with **why / risk / cost of being wrong**), not only a ranked list. Where uncertainty is high, **name it** and suggest **what evidence would reduce it** (e.g. scan another path, sample files). |
| **Council** | Treat seats as **partial perspectives**; synthesis should **attribute** tension between seats, not erase it. Prefer **structured per-seat output** + **synthesis that states disagreements** and a **single operational next step** when appropriate. |
| **Intake** | Lane / classification is a **proposal** with **signals and interpretation codes**; corrections are **first-class** (judgment chain). Mediation = **explainable routing** + **human override path**, not silent relabeling. |
| **Vision execution** | Ideas → initiatives → projects is **promotion with accountability**. Evaluation proposals are **drafts** until applied; **decisions** record snapshots. Mediation = **explicit recommendation + assumptions + risks + next step**, not only scores. |
| **Matching (entity / duplicate / link suggestions)** | Frame as **hypothesis**: match **confidence**, **what would falsify**, **merge vs link vs defer**. Avoid binary “this is the same” without **evidence tied to fields** the user can see. |
| **Radar** | Buckets and signals are **attention mediation**: **what needs a human now** vs **noise**. Copy should separate **fact** (e.g. overdue) from **interpretation** (e.g. capacity risk) where both exist. |
| **Settings** | Not a mediation surface. **Stores prefs and keys**; mediation applies to **features that consume LLM output**, not to where API keys live. |

---

## 4. Output contract implications

Beyond a flat **`recommendation`**, mediation-centered AI should **prefer** (when the feature allows) **typed or labeled sections** such as:

| Output type | Role |
|-------------|------|
| **Perspectives** | Named stances (e.g. strategist vs operator), each with **claim + dependency on context**. |
| **Tensions** | Explicit **A vs B** (or multi-way) tradeoff, not merged away. |
| **Needs** | **Missing info**, **clarifying questions**, or **dependencies** required to decide. |
| **Constraints** | **Hard limits** stated in or inferable from input (time, policy, capacity, scope) — **flag if inferred**. |
| **Proposed synthesis** | **One integrated view** that **does not pretend** all tensions vanished; states **what was prioritized and why**. |
| **Next step** | **One concrete action** + **owner type** (human / system) when relevant. |
| **Assumptions** | **Bullets**: what the model assumed **because it was not in context**. |

**Schema / prompt guidance:** Prefer **keys or headings** that map to the above over a single prose blob. For strict JSON features (evaluate, extract), **keep machine-readable keys** and map labels in UI. For council, **preserve seat boundaries** before synthesis.

---

## 5. Boundaries (stay operational)

**Must stay concrete:**

- **Anchors:** Every non-trivial claim should **trace to** supplied text, IDs, paths, fields, or explicitly labeled **assumption**.
- **Testability:** Reviewers can ask: “Could a second reader verify this from the artifact?” If no, mark as **assumption** or **hypothesis**.
- **No clinical or identity claims** about real people (no diagnoses, traits, “dysfunction”).
- **Decisions remain human-owned** where the product says so (Apply, PATCH queue, Promote, Approve). The model **proposes**; **storage and audit** reflect human commit where implemented.

**Reject vague therapy talk:**

- Ban filler: “hold space,” “journey,” “lean in,” “safe space” **unless** tied to a **specific workflow step** (e.g. “defer decision until owner confirms X”).
- Replace abstraction with **operational nouns**: *deadline, owner, dependency, scope, criterion, evidence, rollback*.

**Review standard (one line):**  
*If the output cannot be used to **act**, **audit**, or **disagree precisely**, it fails the mediation bar — regardless of tone.*

---

*This note informs prompts and review; it does not change routing, storage, or architecture by itself. Trunk/branch rules remain in `docs/01_TRUTH/CODEBASE_TRUTH_RULES.md`.*
