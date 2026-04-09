# Profile identity ontology (Zenaf)

This doc integrates product philosophy with enforcement in code. It is **not** a second “system core identity.”

## Layers

1. **System law** — Invariants (trace, privacy, schema, “one canonical user core row” for defaults). Does not speak as the user; constrains behavior.
2. **User canonical core** — One primary `core_profiles` row per signed-in user for meaning: evaluation, meeting extract defaults (authenticated), placement when `profile_id` is omitted. **User-controlled weights** (influences, settings) still modulate how much context applies where the UI exposes that.
3. **Legacy `core_profiles` rows** — Historical / non-primary data. Not deleted; **de-peered**: no new influence targets to non-canonical rows; graph nodes may carry `hierarchyHint: legacy_secondary_core`.
4. **System / built-in profiles (perspectives)** — Curated voices; may speak; must be **labeled** in UX/trace so they do not masquerade as the user. Influence rules may differ from user core (future tightening).

## Precedence (when unstated)

Law → user canonical core for “you” in defaults → explicit client `profile_id` / user weights where exposed → advisory system profiles (disclosed).

## Implementation touchpoints

- `canonical_core_profile_for_user` / `canonicalCoreProfileId` — default identity row.
- `GET /vision-execution/core-profiles` — each row includes `is_canonical`.
- `meeting_extract._resolve_profile_guidance` — authenticated + no `profile_id` uses canonical row text; template keys (e.g. `clinic_operations`) remain explicit overrides.
- Influences: `canonicalCoreProfileId` prop restricts **new** core-profile link targets to Brand core.

## What this does *not* do

- No schema deletion of extra rows; full PATCH/reconcile/conversation on legacy ids remain for admin/edit history.
- No claim that every model output is fully attributable (trace/UI labeling is incremental).
