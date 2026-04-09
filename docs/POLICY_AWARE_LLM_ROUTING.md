## Policy-Aware LLM Routing — Design Note

**Status:** Intent / architecture direction  
**Scope:** Future design for routing Zenaf requests to external LLM providers under explicit policy control.  
**Goal:** Treat external model usage as a **policy** problem (safety, compliance, contractual constraints), not just a provider integration, especially for PHI / HIPAA-adjacent workflows.

---

## 1. Context and intent

Zenaf is evolving toward a **bring-your-own LLM provider** model: customers may configure local models, hosted APIs, or third-party services for council and other reasoning tasks.

For **healthcare and adjacent domains**, simply redacting or de-identifying text before calling an external model is **not sufficient** to guarantee HIPAA compliance. Provider eligibility, contracts, data handling guarantees, and feature constraints all matter.

Therefore, Zenaf should:

- Treat LLM routing as a **policy decision** informed by configuration, contracts, and data sensitivity.  
- Make provider capabilities and restrictions **explicit**.  
- Ensure sensitive workflows can be constrained to **approved providers, modes, and tools**.  
- Produce **auditable logs** of how and why a given request was routed.

This note records the direction; it does **not** change current behavior.

---

## 2. Operating modes

Zenaf should eventually support at least three routing modes for reasoning workflows (including council):

### 2.1 PHI-safe mode

Intended for workflows that may contain PHI or similarly regulated data, under a customer’s HIPAA/BAA or equivalent contractual setup.

- **Only route** to providers/configurations explicitly marked as **PHI-eligible** under the customer’s contractual and technical setup.  
- **Disable** tools, plugins, or features that are not covered by the PHI-safe configuration (e.g. internet search, non-compliant vector stores, unsupported third-party APIs).  
- Enforce conservative defaults: no unapproved logging sinks, no shadow copies of prompts, no “experimental” providers.  
- Make routing decisions **inspectable**: an operator should be able to see which provider/model was used and why it was considered PHI-safe.

### 2.2 De-identified mode

Intended as a **risk-reduction** path for some workflows, but **not** as a compliance guarantee by itself.

- Run detection/minimization/redaction before external routing (e.g. PHI detectors, name scrubbers, ID masking).  
- Route to a broader set of providers than PHI-safe mode, but still under explicit policy (e.g. “de-identified research mode” providers).  
- Clearly label this mode in the UI and logs as **“de-identified risk reduction, not a compliance guarantee.”**  
- Retain enough structure (e.g. SubjectRef, decision context) to keep judgments meaningful while minimizing direct identifiers.

### 2.3 General mode

Intended for non-sensitive reasoning where PHI is not expected.

- Normal provider routing based on user or workspace defaults.  
- May use experimental providers, tools, and features that are **forbidden** in PHI-safe mode.  
- Still subject to high-level safety policies (e.g. rate limits, cost caps, content policies), but without PHI-specific constraints.

---

## 3. Architectural seam

At a high level, council and similar reasoning pipelines should pass through a **policy-aware routing seam**:

> council (or reasoning) request → **sensitivity classifier** → **policy gate** → **provider adapter**

- **Sensitivity classifier**  
  - Lightweight classifier (rules + optional ML) that tags a request as:  
    - `phi_expected`, `possibly_phi`, or `non_phi_expected`, and possibly a finer-grained label (e.g. “contains clinical notes”).  
  - May use context such as workspace type, subject/entity type (e.g. patient vs generic initiative), and module (Intake vs Content vs VE).

- **Policy gate**  
  - Takes:  
    - requested mode (PHI-safe, de-identified, general),  
    - sensitivity classification,  
    - workspace/org policy (including contracts and provider eligibility),  
    - provider capability declarations.  
  - Decides whether the request:  
    - can be routed externally,  
    - must be routed to a specific **PHI-eligible** provider,  
    - must be transformed first (de-identification),  
    - or must be **blocked** / downgraded (e.g. restrict to local/offline).

- **Provider adapter**  
  - Encapsulates how to call a given provider (Ollama, Azure OpenAI, Anthropic, etc.).  
  - Enforces the provider’s declared constraints (e.g. no PHI, restricted tools, logging behavior) and exposes a uniform interface to the rest of Zenaf.

This seam is intentionally simple to describe and can be inserted in front of council and other LLM-heavy flows without rewriting business logic.

---

## 4. Provider adapters: capabilities and restrictions

Provider adapters should **declare**, not hide, their capabilities and constraints. At minimum:

- **Capabilities**  
  - Supported task types (chat, completion, tool-calls, embeddings, etc.).  
  - Supported safety modes (e.g. PHI-eligible = true/false under a given configuration).  
  - Latency / cost hints (used for routing heuristics, not guarantees).

- **Restrictions**  
  - Whether the provider is contractually allowed to process PHI under the current deployment and keys.  
  - Any data residency constraints (e.g. must stay in-region).  
  - Logging / retention behavior (e.g. provider logs prompts for N days).  
  - Features that are disabled in PHI-safe mode (e.g. external tool plugins).

These declarations should be consumable by the policy gate so routing logic does not have to hard-code provider names or special-case every integration.

---

## 5. Policy layer responsibilities

The policy layer sits between **domain modules** (council, Content, Intake, VE) and **provider adapters**.

Responsibilities:

- **Mode enforcement**  
  - Determine which routing mode (PHI-safe, de-identified, general) applies to a given request.  
  - Enforce that PHI-safe mode only uses PHI-eligible providers and allowed tools.  
  - Reject or downgrade requests that violate policy (e.g. PHI in general mode with a non-eligible provider).

- **Routing decision**  
  - Choose the concrete provider/model based on:  
    - sensitivity classification,  
    - org-level configuration (allowed providers and keys),  
    - user or workspace preferences,  
    - performance/cost hints.  
  - Optionally apply transformations (e.g. de-identification) as part of the decision.

- **Auditability**  
  - Log for each routed request:  
    - timestamp and requesting module (e.g. council, Content, Intake),  
    - subject_ref / entity type where applicable,  
    - routing mode (PHI-safe / de-identified / general),  
    - sensitivity classification result,  
    - chosen provider/model and configuration id,  
    - policy decision (e.g. “allowed via PHI-safe provider X”, “blocked”, “downgraded to de-identified”).  
  - Make logs available for compliance review without leaking raw PHI beyond existing storage guarantees.

---

## 6. Council as a primary integration point

Council is a natural **first consumer** of the policy-aware routing layer:

- Council questions often touch **clinical decisions, capacity, risk, and outcomes**.  
- Council already has a structured output format and `SubjectRef`-like seams via the judgment substrate.  
- Council can be run in different modes (e.g. “clinical council” vs “strategy council”), which map cleanly onto routing modes.

Over time, the council invocation path could become:

1. Domain module builds a structured **council request** (question, subject_ref, context).  
2. Sensitivity classifier tags the request (e.g. `phi_expected`).  
3. Policy gate chooses PHI-safe, de-identified, or general routing and selects a compatible provider.  
4. Provider adapter executes the request under those constraints.  
5. Judgment substrate records the outputs along with routing metadata for audit.

The same seam can later be reused for other reasoning tools (Content generation, Transcript sorter analysis, VE consults).

---

## 7. Product / compliance framing

Key product and compliance points for future design:

- **Sanitization is helpful, not sufficient.**  
  - De-identification and redaction are useful tools but do **not** turn any provider into a HIPAA-compliant option.  
  - PHI-safe mode must rely on explicitly **approved** providers and configurations with contractual coverage, not just redaction.

- **Do not assume “user default LLM” is PHI-safe.**  
  - A user’s default provider (e.g. a personal OpenAI key) is **not** automatically acceptable for PHI workflows.  
  - PHI-safe routing should ignore or override user defaults that are not marked as eligible.

- **Policy-first, integration-second.**  
  - Provider integrations should be implemented with policy hooks from day one (capabilities, restrictions, logging), even if early deployments only use non-PHI general mode.  
  - This keeps the door open for regulated deployments without rewriting the routing layer.

---

## 8. Non-goals for now

- No immediate changes to the current council implementation or provider selection.  
- No full compliance engine or legal opinion encoded in code.  
- No automatic guarantee that de-identified mode satisfies HIPAA by itself.

This note is **architectural intent only**. It should guide future work on provider adapters, policy configuration, and council/LLM routing without constraining current development velocity.

