"""
Shared taxonomy for the recognition lifecycle (emergence → interpretation → recognition → persistence).

Recognition sinks in Vision Execution:
- Typed **entities** (ideas, tasks, core_profiles, signals, …) in the main schema.
- Append-only **decisions** rows documenting provenance, identity shifts, or meaning-only insight.

Subsystems combine **entity and/or decision** depending on the kind of "being":
- Meeting extraction commit: entities + **decision** (provenance envelope).
- Council insight (optional): **decision only** (no new VE entity row).
- Core profile save: **entity** (PATCH row) + **decision** (identity-shift record).
- Intake graduate: **entity** (task) + **decision** (see intake bridge).
"""

# --- decision_type values (append-only decisions.decision_type) ---

DECISION_TYPE_MEETING_EXTRACTION_COMMIT = "meeting_extraction_commit"
DECISION_TYPE_COUNCIL_INSIGHT = "council_insight"
DECISION_TYPE_CORE_PROFILE_IDENTITY_SHIFT = "core_profile_identity_shift"
# Intake (existing)
DECISION_TYPE_INTAKE_GRADUATE_TASK = "intake_graduate_task"

# --- entity_type on decisions row (anchors the decision; not always a row in another table) ---

ENTITY_TYPE_MEETING_EXTRACTION_SESSION = "meeting_extraction"
ENTITY_TYPE_COUNCIL_INSIGHT = "council_insight"
ENTITY_TYPE_CORE_PROFILE = "core_profile"
