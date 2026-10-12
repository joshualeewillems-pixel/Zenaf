# Identity License — Design

**Status:** Implemented (`local_ai/identity/`, `api/routes/identity_routes.py`)
**Date:** 2026-10-12

## The position

Data dignity, implemented instead of argued. Every doppelganger carries a
signed identity license declaring that all signals, profiles, snapshots, and
other data derived from the owner are the owner's exclusive property. Zenaf
is custodian, not owner. This is the load-bearing version of the consent
model the training-signal spec already demanded ("observation is consent-
gated, always") — now it gates the business model too.

## Re-anchoring

When a user imports their ChatGPT or Claude history, that data was extracted
elsewhere for someone else's benefit. The moment it enters Zenaf, the import
pipeline stamps the owner's `license_id` into the session's and every event's
provenance: it is **reclaimed** under the user's license. "Reclaim everything"
is a literal onboarding promise, enforced in code (`start_import` refuses to
run without an active license).

## Mechanics

- **License** (`IdentityLicense`): signed (HMAC-SHA256, key at
  `data/identity/.license_key`, 0600) declaration of rights + terms
  (`third_party_training: false`, `sale_of_data: false`,
  `rental_default: deny`, `data_residency: local`). Idempotent issuance.
- **Consent ledger** (`ScopeEvent`, append-only): `train:self` gates
  distillation; `rent:zone:*` / `rent:zone:<name>` will gate the rental
  layer; `export` and `delete:execute` cover takeout and deletion.
  Default-deny everywhere; every grant revocable; revocation is itself a
  ledger event.
- **Takeout** (`POST /identity/takeout`): one JSON bundle — signed license,
  full consent ledger, all approved training signals, import summaries.
  A right, not a privilege: no scope needed, license required.
- **Deletion** (`POST /identity/delete`, confirmation `"DELETE"` +
  `delete:execute` scope): removes uploads, the presence-ingest database,
  and the consent ledger; returns a signed `DeletionReceipt` with counts.
  What persists: the tombstoned license row and the receipt — proof the
  license existed and exactly what was removed. Everything else is gone.

## Composition

- **With ingest now:** license required at import; `train:self` required at
  distill; `license_id` in all provenance. API surfaces 409 (no license) and
  403 (scope denied) with instructions, not dead ends.
- **With rental later:** the rental layer will call `require_scope` /
  `check_scope` per invocation (`rent:zone:<name>`, falling back to
  `rent:zone:*`), meter usage against the license, and settle to the owner.
  The license is what makes "every cent flows to the owner" enforceable.

## Deliberately NOT built

- **PKI / cross-device identity.** HMAC with a local key is tamper-evidence,
  not identity proof to third parties. If the key file is lost, old
  signatures stop verifying — said out loud, not hidden.
- **Legal enforceability.** The license is a technical + product commitment.
  It does not pretend to be a contract.
- **Cross-user sharing.** No signal ever leaves the owner's store without
  an explicit, scoped grant. There is no "share" primitive yet on purpose.
