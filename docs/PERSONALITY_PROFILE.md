# Personality Profile — Design Note

**Status:** Implemented (Phase 1 — the user-defined side; see `local_ai/personality/`)  
**Scope:** Formalize Zenaf’s implicit personality layer into a structured, versioned cognitive profile that can be deployed as a “seat at the table” in councils and workspaces.  
**Goal:** Distill a user’s cognitive style into an interpretable, governable, portable, and marketable profile — without uncontrolled self-training, hidden memory blobs, or raw-data exposure.

---

## 1. Definitions

Three concepts must stay clearly separated:

| Term | Definition |
|------|-------------|
| **Person** | The real human who is the source of behavior and signals. A person is the identity behind the keyboard (or future auth principal). Person data is out of scope for this note except as the *source* from which a profile is distilled. |
| **Profile** | A structured, versioned cognitive model distilled from a person. It is a snapshot of voice, reasoning style, decision heuristics, domain map, constraints, and curated examples — not raw activity logs. A profile has a unique id and version history; updates are explicit and human-approved. |
| **Seat** | A runtime instance of a profile loaded into a council or workspace. A seat binds a profile (and optionally a version) to a context with permissions, memory lens, domain scope, and mode (advisory vs active). One profile can have many seats (e.g. “Phil’s seat” in Council, “Phil’s seat” in Content workspace). |

**Summary:** Person → source of truth. Profile → packaged, versioned cognitive model. Seat → deployed profile in a specific context with policy and scope.

---

## 2. Profile schema

A profile is a first-class object with at least the following dimensions. All are optional at creation; they are filled or refined through the distillation pipeline and explicit edits.

| Dimension | Purpose | Example / shape |
|-----------|---------|------------------|
| **Voice profile** | Tone, register, vocabulary preferences, “how this person sounds” in text or briefs. | Free text + optional structured tags (e.g. “concise”, “direct”, “avoids jargon”). |
| **Reasoning profile** | How this person tends to reason: evidence-first, analogy-driven, principle-led, etc. | Short descriptors + optional ordering (e.g. “prefer trade-off framing before recommending”). |
| **Decision heuristics** | Reusable rules or patterns this person applies when choosing (e.g. “default to reversible decisions”, “kill criteria before scale”). | List of short, human-readable heuristics; can reference red-lines. |
| **Domain map** | Areas where this person has strong views or expertise vs. areas where they defer. | Map or list: domain label → strength/role (e.g. “product: lead”, “legal: defer”). |
| **Constraint / red-line profile** | Non-negotiables, hard boundaries, and “never do” rules. | List of constraints; each can have a short rationale; used to filter or warn in councils and content. |
| **Curated example fragments** | Short, sanitized examples of preferred phrasing, decisions, or reasoning — for few-shot use in generation or council prompts. | List of { context, fragment, optional tag }; no PII or raw logs; user-curated or proposed then accepted. |
| **Version metadata** | When this version was created, from what signals (optional high-level labels), and who approved. | `version_id`, `created_at`, `source_summary` (e.g. “transcript + VE decisions”), `approved_by` (person or “user”). |

#### Decision Fingerprint

A profile should capture not only tone and reasoning traits but also a **distilled pattern of decision-making behavior**. This “decision fingerprint” helps the seat behave consistently with how the person tends to choose, not just how they speak or reason in the abstract.

Example fields (all optional, human-readable or ordinal where possible):

| Field | Purpose |
|-------|---------|
| **risk_bias** | Tendency toward risk-seeking vs. risk-averse (e.g. “reversible first”, “default no”). |
| **exploration_vs_exploitation** | Preference for trying new options vs. refining known ones. |
| **time_horizon** | Typical horizon for decisions (short-term vs. long-term). |
| **evidence_preference** | How much evidence is preferred before deciding (e.g. “one strong signal”, “aggregate first”). |
| **decision_style** | e.g. “decide fast, iterate” vs. “align then commit”. |
| **conflict_style** | How disagreements or trade-offs are handled (e.g. “explicit trade-off”, “defer to owner”). |
| **failure_tolerance** | Attitude toward failure and iteration (e.g. “fail fast”, “minimize downside”). |

The fingerprint is **derived from signals** such as Vision Execution decisions (approvals, kills, priority overrides), transcript sorter interactions (what was promoted or dismissed), and content choices (what was kept vs. regenerated). As with other profile dimensions, updates are proposed and accepted, not applied silently.

**Persistence:** Profiles are stored as versioned documents. Each version is immutable; “current” is a pointer to the latest published version. Edits produce a new version; the pipeline proposes diffs, not silent overwrites.

---

## 3. Distillation pipeline

The system must **propose** structured profile updates for human review. It must **not** silently mutate the profile or run continuous self-training without consent.

**Thin pipeline stages:**

| Stage | Responsibility |
|-------|----------------|
| **1. Collect signals from modules** | Modules (transcript sorter, content choices, VE decisions, intake corrections, folder sorting, inbox cleanup, prompt/output edits) emit *anonymized or summarized* signals (e.g. “user preferred X over Y”, “user edited prompt to add Z”) into a staging area. No raw private data is stored in the profile; signals are ephemeral or short-lived for derivation only. |
| **2. Derive candidate traits/updates** | A batch or on-demand job runs over recent signals and produces *candidate* additions or edits to the profile (e.g. “suggest adding heuristic: prefer reversible decisions”, “suggest voice tag: concise”). Output is a **proposed diff**, not a direct write. |
| **3. Propose structured profile updates** | The system presents the proposed diff to the user: “We suggest adding these heuristics / voice tags / constraints. Accept, edit, or reject.” Optionally, the user can trigger “derive from last N decisions” manually. |
| **4. Human accepts / edits / rejects** | The person (or delegated approver) accepts, edits, or rejects each proposed change. Rejected items are discarded; no silent persistence. |
| **5. Publish profile version** | On accept, a **new version** of the profile is created with the approved changes. Version metadata records the publish event. The “current” pointer advances only after this step. |

**Important:**  
- **No uncontrolled continuous self-training.** Updates are always proposed and explicitly approved.  
- **No silent mutation.** The profile only changes when the user (or delegated flow) publishes a new version.  
- **Structured updates only.** The system distills *structured* fields (heuristics, tags, constraints, example fragments), not a giant embedding or opaque blob.

---

## 4. Distillation reports

To keep profile evolution transparent and prevent silent personality drift, the system can produce a lightweight artifact called a **Profile Distillation Report** for each run of the distillation pipeline (or each user-triggered “derive and propose” action).

A report records:

| Field | Purpose |
|-------|---------|
| **source signals analyzed** | High-level summary of which signals were used (e.g. “last 30 VE decisions”, “transcript sorter promotions in March”), without storing raw data. |
| **candidate trait updates** | The proposed diff: suggested new or changed heuristics, voice tags, decision fingerprint fields, constraints, etc. |
| **accepted updates** | Which of the candidates the user accepted (or accepted after edit). |
| **rejected updates** | Which candidates were explicitly rejected, so the system does not re-propose them inappropriately. |
| **timestamp and profile version change** | When the report was generated and which profile version resulted (e.g. “v3 → v4”). |

Reports provide **transparency**: the person can see what was analyzed and what changed. They also **prevent silent drift**: every version change is tied to an explicit accept/reject step and, optionally, to a report. No hidden mutation of the profile without a corresponding report and version bump.

---

## 5. Signal sources

Signals are inputs to the distillation pipeline. They should be **summarized or behavioral**, not raw PII or full content. Possible sources:

| Source | What is captured (conceptual) | Use in derivation |
|--------|-------------------------------|-------------------|
| **Transcript sorter** | Which topics/user segments the user marked substantive; which candidate tasks they promoted or dismissed. | Reasoning preferences; prioritization style; domain emphasis. |
| **Content choices** | Which briefs, tones, and edits the user made in the Content tab; which outputs they kept vs. regenerated. | Voice profile; constraint/red-line hints; domain map. |
| **Vision Execution decisions** | Status changes, approvals, kills, priority overrides on initiatives/projects/tasks. | Decision heuristics; kill criteria; constraint profile. |
| **Intake corrections** | How the user corrected or reclassified intake items (email/fax). | Domain map; decision boundaries; red-lines. |
| **Folder sorting** | Choices in Workspace Organizer: accepted vs. rejected recommendations; manual overrides; “use as focus”. | Reasoning and prioritization; preference for structure. |
| **Inbox cleanup** | Archive, assign, or dismiss actions; patterns in what is kept vs. hidden. | Heuristics; attention/priority signals. |
| **Prompt/output edits** | When the user edits a council question or an AI output before using it (e.g. adding context, shortening). | Voice profile; reasoning profile; example fragments (if user explicitly allows). |

**Principle:** Signals feed **candidate** profile updates. They are not stored as a giant “memory blob” in the profile; they are used to derive structured traits, then the proposal is shown and the user decides. Raw logs stay in their modules or in bounded, purpose-limited storage — not in the profile object itself.

---

## 6. Runtime seat model

Three concepts keep identity and execution contexts from becoming entangled:

| Concept | Definition |
|--------|------------|
| **Profile** | The **static cognitive model**: versioned snapshot of voice, reasoning, decision fingerprint, heuristics, constraints, domain map, examples. It does not “run”; it is data. |
| **Seat** | A **scoped instance** of a profile in a context (council, Content workspace, etc.) with permissions, memory lens, domain scope, and mode (advisory vs active). The seat is the binding of profile + version + policy. |
| **Runtime agent** | An **active LLM session** that is “operating” the seat: it receives context, applies the profile’s traits, and produces output or recommendations. The runtime agent is ephemeral (per run or per session); the seat and profile persist. |

**Chain:** `profile_id` → `seat_instance` → `runtime_agent_session`. A given profile can have many seats (e.g. one in Council, one in Content). A given seat can spawn many runtime agent sessions over time. The separation ensures that (1) the identity model (profile) stays static until the user publishes a new version, (2) where and how that identity is used (seat) is governed by policy and scope, and (3) the actual execution (runtime agent) is a transient session that does not mutate the profile or the seat.

| Field | Purpose |
|-------|---------|
| **profile_id** | Which profile this seat uses. |
| **version** | Optional. Specific profile version, or “latest”. Enables reproducibility (e.g. “Council run with Phil v2”). |
| **capability policy** | What this seat is allowed to do: e.g. “advisory only”, “can suggest tasks”, “can propose content”. Encoded as a simple policy label or small set of flags. |
| **access tier** | Optional. For multi-tenant or marketplace: e.g. “owner”, “editor”, “viewer”. Affects what the seat can read/write in the context. |
| **memory lens** | Optional. What past context this seat can see: e.g. “last 5 council runs”, “current brief only”, “no history”. Prevents unbounded “giant memory”; scope is explicit. |
| **domain scope** | Optional. Restrict this seat to certain domains (from the profile’s domain map). E.g. “product and strategy only”; “no legal”. |
| **advisory vs active mode** | **Advisory:** seat contributes perspective/recommendations but does not perform actions (e.g. create tasks, send). **Active:** seat can trigger actions within the capability policy. Default for human-owned seats can be advisory in sensitive contexts. |

**Example:** “Phil’s seat” in Council: profile_id = Phil’s profile, version = latest, capability = full, access = owner, memory lens = last 3 council threads, domain scope = all, mode = advisory (Phil still clicks Run; the seat doesn’t auto-execute).

---

## 7. Marketplace framing

A profile can be **shared or sold as a seat** without exposing raw private data.

**The product is not raw user data or conversation logs.** The marketable artifact is **Profile → licensed seat.** Profiles are distilled cognitive models with versioning and provenance. Seats are permissioned runtime instances of those profiles that can participate in councils, advisory contexts, or workflow systems. The buyer receives a seat (profile + version + policy + scope) that runs in their environment; they do not receive the underlying signals, logs, or identity data.

- **Profile = packaged cognitive model.** What is shared or sold is the *structured* profile: voice, reasoning, decision fingerprint, heuristics, domain map, constraints, and curated example fragments. Not activity logs, not transcripts, not raw decisions.
- **No raw-data resale.** The marketplace does not sell “Phil’s inbox” or “Phil’s decision log.” It sells “Phil’s profile” (or a derivative seat) as a cognitive model that can be loaded as a seat in another user’s council or workspace.
- **Versioning and provenance.** Buyers or collaborators get a specific profile version with clear provenance (e.g. “v3, published 2025-03”). They do not get access to the underlying signal history or person identity unless explicitly agreed.
- **Seat as product.** The sellable/shareable unit can be “a seat” (profile + version + policy + scope). The seat runs in the consumer’s environment; the profile content is the product, not the person’s live data.

This keeps the layer **interpretable** (you can inspect what’s in the profile), **governable** (the person controls what gets published and shared), **portable** (profile can move across instances), and **marketable** (packaged model, not raw data).

---

## 8. Scope constraints

- **No uncontrolled continuous self-training.** The system proposes structured updates; a human (or explicit delegated flow) accepts, edits, or rejects. The profile does not change without a publish step.  
- **No silent self-training.** All profile evolution is explicit and versioned; no hidden mutation.  
- **No giant hidden memory blob.** Memory is scoped via the seat’s “memory lens” and optional bounded context. The profile itself is structured fields and curated fragments, not an opaque embedding or unbounded log.  
- **No hidden personality embeddings.** Profile dimensions (voice, reasoning, decision fingerprint, heuristics, constraints, domain map, examples) are human-readable and editable. Derivation can use ML to propose updates, but the stored artifact is interpretable and governable.  
- **No direct raw-data resale.** Marketplace and sharing deal in packaged profiles and seats, not raw activity logs, transcripts, or PII.

**Goal:** Make this layer **interpretable**, **governable**, **portable**, and **marketable** — so Zenaf can offer a “seat at the table” for a user’s cognitive style without becoming an uncontrolled or opaque personality engine.
