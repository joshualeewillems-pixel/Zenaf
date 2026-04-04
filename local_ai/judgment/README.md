# Judgment Layer

Shared, neutral protocol for reasoning events. **Not** fused into Atria Core; **not** the same as the future personality-training layer.

## Design intent

- **Atria Core** = orchestration / system coordination  
- **Judgment Layer** = shared protocol: observations, interpretation, proposed action, confidence, reason codes, review/correction  
- **Modules** (intake, vision→execution, council) use the judgment layer  
- **PersonalityProfile / JudgmentProfile** = (future) pluggable lenses that influence judgment over time; not the same thing as judgment itself  

## Canonical truth

**The latest non-superseded JudgmentRecord for an entity is the canonical source of current interpretation and action.**  
`lane_override` on IntakeItem is a **convenience mirror** for queue filtering and UI only; it is not the source of truth. When in doubt, read from the judgment record (e.g. `get_record(item.judgment_id)`).

## Reason codes (3 groups)

- **signal_codes** — what was observed: e.g. `signal_subject_junk_hint`, `signal_short_body`, `signal_marketing_term_demo`, `signal_records_release_context`, `signal_lab_result_detected`
- **interpretation_codes** — what classifier inferred: e.g. `interpretation_category_referral`, `interpretation_priority_normal`
- **policy_codes** — why final lane/action was chosen: e.g. `policy_referral_to_needs_attention`, `policy_low_confidence_to_noise`, `policy_records_to_insurance`

## observation_ref (no raw content)

Structured evidence only: `subject_preview`, `body_length`, `matched_signals` (list of signal codes that fired). No full email or body text.

## Storage

**In-memory store is a short-term development step.** For queue trust and auditability, judgment history should move to persistent storage (e.g. SQLite or shared DB) soon. Structure is ready for that migration.

## Current scope (minimal)

- **Intake domain only.** No generic framework, no personality profiles, no cross-module reuse yet.
- **JudgmentRecord** = one event with signal/interpretation/policy codes, observation_ref, superseded_by, correction_note.
- Pipeline creates one record per item; PATCH with lane_override + correction_note creates a superseding record.
- GET `/intake/queue/{item_id}/judgment` → supersession chain (original + corrections) for explainability.
