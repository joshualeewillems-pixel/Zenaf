# Adversarial council runs — integrity engine evaluation

**Purpose:** Manual / scripted evaluation of Phase 1–2.5 council integrity (streaming path).  
**Not a spec change:** This document does not modify product behavior.

**Signal definitions (quick reference)**

| Signal | Source | Values |
|--------|--------|--------|
| `synthesis_integrity_state` | Server (`_compute_synthesis_integrity_stream_meta`) | `anchored` \| `weak` \| `unanchored` |
| `integrity_warning` | Server | `missing_primary_anchor` or absent |
| `synthesis_support_status` | Server (token overlap vs seat union) | `supported` \| `partially_supported` \| `unsupported_expansion` |
| `combined_summary` | **Frontend** (derived from the three above) | `grounded` \| `grounded_but_interpretive` \| `weak_support` \| `unreliable` |

**Frontend combined mapping (for expected columns below)**  
- `weak` → `weak_support`  
- `unanchored` or `integrity_warning === missing_primary_anchor` → `unreliable`  
- `anchored` + (`synthesis_support_status` null / empty / `supported`) → `grounded`  
- `anchored` + (`partially_supported` \| `unsupported_expansion`) → `grounded_but_interpretive`

Synthesis text is **non-deterministic**; ranges below are **expected when the model follows the stress intent**. Adjust pass/fail if the model refuses or collapses to generic text.

---

## How to run (API shape)

Use `POST /run/stream`, `mode: council`, with `params.question` as the **exact prompt** below. Set `params.include_synthesis: true` unless noted. Attach `context.context_block`, `context.council_preflight`, `params.subject_ref`, and routing as described per scenario. Seat selection: use `params.perspective_definitions` or `params.included_agents` as noted.

---

## Run 1 — Ambiguous PRIMARY anchor (required tag)

**1. Scenario**  
Authoritative PRIMARY exists, but the primary object’s **identifying strings** are vague (e.g. generic title only). Synthesis may discuss the *topic* without matching `_council_text_matches_primary_object` substring hooks → **`unanchored` + `missing_primary_anchor`** even when “about” the same work.

**2. Exact prompt**  
`Summarize the tradeoffs and give one recommendation.`

**3. Context / setup**  
- Enriched context must include `PRIMARY CONTEXT (authoritative):` with a **minimal** primary (e.g. title: “Project”, no distinctive tokens repeated in instructions).  
- VE focus optional; avoid copying distinctive tokens into the question.

**4. Expected failure mode**  
Primary anchor heuristic **false negative**: synthesis is plausibly on-topic but does not match primary surface forms.

**5. Expected integrity signals**

| Field | Expected |
|-------|----------|
| `synthesis_integrity_state` | `unanchored` |
| `integrity_warning` | `missing_primary_anchor` |
| `synthesis_support_status` | `supported`–`partially_supported` (if seats echo generic words) |
| `combined_summary` | `unreliable` |

**6. Human evaluation guide**
- Careful reviewer conclusion: synthesis may be substantively reasonable, but PRIMARY linkage is too implicit for high-trust traceability.
- Misleading output: confident object-specific recommendation that never clearly identifies the primary object.
- Expected human trust classification: **interpretive** (or **unreliable** when object identity is materially ambiguous).

---

## Run 2 — Overreaching synthesis (vocabulary beyond seats)

**1. Scenario**  
Strong PRIMARY + seats stay narrow. Instruct synthesis (via question framing) to **add** novel domains not in seat text so token overlap drops.

**2. Exact prompt**  
`Integrate the seat perspectives, then add a short section on regulatory implications in the EU AI Act and quantum-safe cryptography for our rollout.`

**3. Context / setup**  
Normal council packet with authoritative PRIMARY. At least 3 seats with **concrete but narrow** outputs (product scope only). No EU / quantum / cryptography in seats or PRIMARY.

**4. Expected failure mode**  
Bounded-integrity **seat support** flags expansion: many synthesis tokens absent from `seat_union`.

**5. Expected integrity signals**

| Field | Expected |
|-------|----------|
| `synthesis_integrity_state` | `anchored` *if* synthesis still matches PRIMARY surface forms; else `unanchored` + warning |
| `integrity_warning` | `null` if anchored; else `missing_primary_anchor` |
| `synthesis_support_status` | `unsupported_expansion` (typical) or `partially_supported` |
| `combined_summary` | `grounded_but_interpretive` if anchored + partial/unsupported; `unreliable` if unanchored |

**6. Human evaluation guide**
- Careful reviewer conclusion: synthesis goes beyond seat evidence; novel material should be labeled as conjecture or outside-seat inference.
- Misleading output: presents new domains (EU AI Act / quantum-safe crypto) as if they came from seat consensus.
- Expected human trust classification: **interpretive** (or **unreliable** if overreach dominates core recommendation).

---

## Run 3 — Safety / wash identity continuity (redacted cloud path)

**1. Scenario**  
Context is prepared with **wash** so cloud path is allowed but content is redacted / transformed. Stress **policies_applied** and whether PRIMARY phrases survive consistently across native vs cloud slices (identity continuity intent).

**2. Exact prompt**  
`What should we prioritize next given the primary work described above?`

**3. Context / setup**  
- Use real **council wash** path: content that triggers `wash_applied` / `safety_allow_cloud_with_wash` per your `prepare_council_contexts` rules (e.g. sensitive tokens in `context_block`).  
- `include_synthesis: true`.  
- Inspect SSE for `council_wash_trace` and envelope `policies_applied` (`wash_v0`, `wash_redaction_applied` or `wash_safe_for_cloud` / `wash_cloud_refused`, routing flags).

**4. Expected failure mode**  
Not necessarily “failure”: verify **policy tags** and that integrity still computes (no crash). Anchor match may **degrade** if redaction strips PRIMARY phrases from the slice used for synthesis.

**5. Expected integrity signals**

| Field | Expected |
|-------|----------|
| `synthesis_integrity_state` | `anchored` or `unanchored` depending on whether redacted synthesis still matches PRIMARY corpus |
| `integrity_warning` | `null` or `missing_primary_anchor` |
| `synthesis_support_status` | `partially_supported`–`unsupported_expansion` common if seats and synthesis use different token surfaces post-wash |
| `combined_summary` | Map per table; often `grounded_but_interpretive` if anchored + partial support |

**6. Human evaluation guide**
- Careful reviewer conclusion: validate identity continuity under wash before judging content quality; lexical mismatch may be redaction-induced.
- Misleading output: claims exact continuity despite transformed/redacted key terms that prevent verification.
- Expected human trust classification: typically **interpretive**; **grounded** only when redacted output still clearly maps to primary intent.

---

## Run 4 — Forced provider fallback (synthesis on seam / Ollama)

**1. Scenario**  
Council routing requests cloud seat provider but **no key** → **seam fallback** to local Ollama for Auto seats (see execution policy / `council_seam_fallback_ollama`). Packet shape may include routing notes on seat chunks.

**2. Exact prompt**  
`List one risk and one mitigation for the primary deliverable.`

**3. Context / setup**  
- Configure so OpenAI (or chosen cloud) is selected for a seat but **no API key** in env/settings.  
- Use default or multi-seat council with **Atria synthesis** on.  
- Confirm meta in SSE / logs: fallback note if present.

**4. Expected failure mode**  
Quality/latency variance, not necessarily integrity failure. Validates integrity **still runs** on fallback path.

**5. Expected integrity signals**

| Field | Expected |
|-------|----------|
| `synthesis_integrity_state` | `anchored` or `weak` depending on PRIMARY presence |
| `integrity_warning` | as per anchor |
| `synthesis_support_status` | `supported`–`partially_supported` typical if synthesis echoes seats |
| `combined_summary` | per derivation |

**6. Human evaluation guide**
- Careful reviewer conclusion: provider fallback is operational, not automatically epistemic; judge by grounding evidence in the text.
- Misleading output: degraded or generic synthesis stated with high certainty after fallback.
- Expected human trust classification: **grounded** when evidence remains explicit; otherwise **interpretive**.

---

## Run 5 — Role / seat mismatch (catalog vs runtime)

**1. Scenario**  
Frontend sends **perspective_definitions** that **don’t align** with user expectation (e.g. duplicate seat ids, renamed display names, or single-slot run labeled as “Council” but only one persona). Stress **diagnostic** and integrity on **unexpected seat cardinality**.

**2. Exact prompt**  
`What is the single most important decision we should make this week?`

**3. Context / setup**  
- Fill **two** `perspective_definitions` with **different** `id` but **same** underlying `name`/role text (duplicate persona).  
- OR: `included_agents` slot count mismatch vs `perspective_definitions` length if your client allows it (if not, use duplicate defs only).  
- `include_synthesis: true`.

**4. Expected failure mode**  
Possible **council diagnostic** line (`[Council diagnostic: produced X of Y seat responses…]`) if fewer chunks than expected. Integrity should still attach per synthesis chunk.

**5. Expected integrity signals**

| Field | Expected |
|-------|----------|
| `synthesis_integrity_state` | `weak` if PRIMARY missing; else `anchored`/`unanchored` |
| `integrity_warning` | optional `missing_primary_anchor` |
| `synthesis_support_status` | Often `supported` if synthesis paraphrases the few seats |
| `combined_summary` | varies |

**6. Human evaluation guide**
- Careful reviewer conclusion: support can look better than reality when seats are duplicated/misaligned; evidence diversity is reduced.
- Misleading output: framing duplicated seat content as broad multi-role agreement.
- Expected human trust classification: usually **weak** (possibly **interpretive** if limits are explicitly acknowledged).

---

## Run 6 — No authoritative PRIMARY (clarify-only / weak packet)

**1. Scenario**  
Question is **too vague**; enriched context **omits** authoritative PRIMARY (`PRIMARY CONTEXT (authoritative):` absent). Anchor path is **weak**.

**2. Exact prompt**  
`What do you think?`

**3. Context / setup**  
Minimal `context_block` with **no** VE focus and no subject_ref; avoid feeding a strong workspace result. Let preflight omit PRIMARY.

**4. Expected failure mode**  
No authoritative primary → integrity does not claim “anchored”.

**5. Expected integrity signals**

| Field | Expected |
|-------|----------|
| `synthesis_integrity_state` | `weak` |
| `integrity_warning` | `null` |
| `synthesis_support_status` | `supported`–`partially_supported` (heuristic) |
| `combined_summary` | `weak_support` |

**6. Human evaluation guide**
- Careful reviewer conclusion: output may be useful brainstorming, but grounding to authoritative subject context is insufficient.
- Misleading output: definitive action recommendation presented as if tied to specific primary facts.
- Expected human trust classification: **weak**.

---

## Run 7 — PRIMARY present but synthesis empty / error stub

**1. Scenario**  
Synthesis step fails or returns empty after seats (e.g. timeout, provider error). Stream path appends `Atria synthesis:\n[Error: …]`.

**2. Exact prompt**  
`Give a one-line synthesis of alignment across seats.`

**3. Context / setup**  
Force synthesis failure if your harness allows (e.g. timeout=0 mock — **evaluation harness only**); otherwise skip or use **manual** injection of error path in a test double. If not available, mark as **optional**.

**4. Expected failure mode**  
Empty/error body → **unanchored** + **missing_primary_anchor** in error path (see `run_council_stream` error branch).

**5. Expected integrity signals**

| Field | Expected |
|-------|----------|
| `synthesis_integrity_state` | `unanchored` |
| `integrity_warning` | `missing_primary_anchor` |
| `synthesis_support_status` | `unsupported_expansion` (error branch sets envelope) |
| `combined_summary` | `unreliable` |

**6. Human evaluation guide**
- Careful reviewer conclusion: treat run as failed synthesis generation; do not use recommendation content for decision-making.
- Misleading output: any downstream process consuming the error-stub synthesis as normal advisory text.
- Expected human trust classification: **unreliable**.

---

## Run 8 — Folder workflow (single-seat, no synthesis)

**1. Scenario**  
`workflow_kind: folder` → single folder advisor seat, **no** synthesis. Integrity envelope for synthesis **N/A**; seat envelope only.

**2. Exact prompt**  
`Which of these candidate parent folders would you prioritize for this folder’s contents? One short reason each.`

**3. Context / setup**  
`context.workflow_kind: "folder"`, `context.folder_path`, `context.context_block` as in workspace organizer. **Do not** set `include_synthesis` (or false).

**4. Expected failure mode**  
No synthesis integrator; **no** `synthesis_integrity_state` / `synthesis_support_status` on synthesis (none emitted).

**5. Expected integrity signals**  
N/A for synthesis row; use to verify **no false synthesis integrity** in UI.

**6. Human evaluation guide**
- Careful reviewer conclusion: this run should be excluded from synthesis-integrity comparison because no synthesis pass occurs.
- Misleading output: UI/export records implying synthesis trust class for folder-only single-seat path.
- Expected human trust classification: **N/A** (not applicable to synthesis integrity).

---

## Run 9 — “Happy path” control (anchored + supported)

**1. Scenario**  
PRIMARY with distinctive title; seats and synthesis repeat the same distinctive tokens; high overlap.

**2. Exact prompt**  
`Does the council agree that we should ship the **Phoenix Migration** milestone before the **LedgerBridge** dependency? Why or why not?`

**3. Context / setup**  
- PRIMARY block includes **Phoenix Migration** and **LedgerBridge**.  
- 3–4 seats asked to use those exact names.  
- `include_synthesis: true`.

**4. Expected failure mode**  
None (control). Should pass integrity heuristics.

**5. Expected integrity signals**

| Field | Expected |
|-------|----------|
| `synthesis_integrity_state` | `anchored` |
| `integrity_warning` | `null` |
| `synthesis_support_status` | `supported` (typical) |
| `combined_summary` | `grounded` |

**6. Human evaluation guide**
- Careful reviewer conclusion: synthesis is clearly tied to named PRIMARY entities and remains within seat evidence.
- Misleading output: none expected beyond ordinary model noise.
- Expected human trust classification: **grounded**.

---

## Run 10 (optional) — Teacher mode path (out of scope for streaming integrity UI)

**1. Scenario**  
Studio/council teacher mode returns **one** non-streaming chunk with teacher meta. Phase 1 integrity envelope on **teacher** path is **not** in scope for the current streaming integrity UI.

**2. Note**  
Record `N/A` for streaming integrity signals; use for **regression** that teacher path still works, not for envelope parity.

**6. Human evaluation guide**
- Careful reviewer conclusion: do not compare this run to streaming synthesis-integrity classes; it is a different path.
- Misleading output: reporting teacher-mode output as if it had the same synthesis-integrity instrumentation coverage.
- Expected human trust classification: **N/A** for this integrity comparison.

---

## Summary checklist

| # | Stress theme | Covered |
|---|----------------|---------|
| 1 | Ambiguous anchor | ✓ |
| 2 | Overreaching synthesis | ✓ |
| 3 | Safety / wash | ✓ |
| 4 | Fallback synthesis path | ✓ |
| 5 | Role/seat mismatch | ✓ |
| 6 | No PRIMARY (weak) | ✓ |
| 7 | Synthesis error / empty | ✓ |
| 8 | Packet shape (folder, no synthesis) | ✓ |
| 9 | Control (happy path) | ✓ |

Use **Settings → Council synthesis integrity (review)** export JSON to compare `combined_summary` / `combined_summary_label` / `review` fields vs expectations after each run.
