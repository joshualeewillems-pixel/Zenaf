"""Steward D2: the wired Scope S erasure flow (packet §§8.2/9.1/9.4/9.5).

This is the operation behind ``POST /identity/delete`` when it is
invoked by an authenticated session (service.delete_all's wired
path). It is wiring, not a new subsystem: it composes the existing
identity store + signing, the narrative store's erase operation,
and the fellowship observations store, under the completion
protocol the packet specifies:

- §9.1 owner resolution runs first, before any destructive step:
  the session user must equal the bootstrapped owner row's id.
  Enumeration is used only as coverage verification inside the
  resolved scope; uniqueness in a store is never evidence of
  ownership.
- Step 0: a signed operation record in the existing
  deletion_receipts table fixes the boundary T before the first
  tombstone (§9.4, bound field set per Revision 4).
- A barrier-integrity pre-step reconciles the two tombstones
  against the record (missing barriers written at the record's T;
  a divergent tombstone rewritten to the record's T and reported).
- Per-store steps in fixed order — presence, narrative,
  observations, identity — then per-store verification by
  independent recount AND a full-set provenance audit of the
  survivors (§9.5), with a bounded mop-up loop, then VACUUM.
- The receipt is composed LAST, from the recounts — never from a
  preview. Partial failure yields exactly one signed incomplete
  receipt (a per-store status line, no completion language), and
  the operation resumes under its original boundary on a later
  authenticated invocation: the verified record substitutes for
  the scope grant the original run consumed (§9.1 Rev 3).

Gate B Increment 1 (the non-destructive protocol foundation)
layers the joint-erasure protocol onto this flow for its current
four-store set only — no provenance or pipeline deletion is
activated anywhere:

- Fresh operations open under the distinct ``delete:execute/1.1``
  token (the legacy token is preserved for historical records;
  the generalized reader in narrative/eligibility.py binds both
  generations and fails closed on any token/version/store-set
  disagreement).
- A no-writes classification phase captures each store's target
  enumeration under a bracketed source fingerprint, persists it
  as a signed work row in ``erasure_operation_work``, and binds
  its hash in a signed ``classified`` row — persist and bind in
  one identity-store transaction (FPC §1).
- Execution is gated, not observational: the fingerprint is
  re-verified before the ``executing`` row and again inside each
  store's caller-owned ``BEGIN IMMEDIATE`` boundary
  (local_ai/identity/boundary.py), whose rollback-only semantics
  make a swallowed mid-step failure refuse the whole step. The
  one deliberate behavior change is the narrative step's failure
  atomicity (footprint §3.5): a mid-step failure now rolls the
  step back instead of leaving partial progress durable.
- Completion seals in one transaction (completion row + work-row
  destruction); receipts speak the coverage bound in the record,
  rendered by id from COVERAGE_STATEMENTS after hash
  verification. Legacy records carry no bindings and gain none;
  their replays are labelled reproductions (FPC §7).
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from .boundary import BoundaryRefused, StoreBoundary
from .models import DeletionReceipt
from .scopes import require_scope
from .service import (
    _presence_census,
    _presence_data_dir,
    _receipt_payload,
    _wipe_presence,
)
from .service import verify_license
from .signing import sign_mapping
from .store import IdentityStore

logger = logging.getLogger(__name__)

#: The §8.5 post-build coverage statement (with §9.5's amendment:
#: "verified by recount and by a provenance check of the records
#: that remain"). This text is the receipt's coverage and the
#: delete route's description — the same words in both places.
COVERAGE_STATEMENT = (
    "Erased: your narrative record (threads, readings, evidence, "
    "interpretations, and derived relationships held by the narrative "
    "steward) and your fellowship observations, verified by recount "
    "and by a provenance check of the records that remain. "
    "A content-free marker remains so the erased material cannot be "
    "silently re-derived from older records. Not erased by this "
    "action: the activity log's contents (under separate review), "
    "your conversations, meetings, projects, and claims, and "
    "anything held in backups or snapshots, which this action "
    "cannot reach. Material you create after this erasure is new "
    "and is not covered by it."
)

#: The stores Scope S covers, in the protocol's fixed step order.
SCOPE_S_STORES: tuple[str, ...] = (
    "presence",
    "narrative",
    "observations",
    "identity",
)

#: The coverage statement registry (amendment §4; Gate B
#: Increment 1 §3.6): coverage id → the exact statement text.
#: Append-only — entries are never edited in place; a wording
#: change is a new id, approved as ruled text. ``coverage/1`` is
#: the landed four-store statement, preserved verbatim: the
#: COVERAGE_STATEMENT constant IS this entry.
COVERAGE_STATEMENTS: dict[str, str] = {
    "coverage/1": COVERAGE_STATEMENT,
}

#: The coverage id every four-store operation binds.
COVERAGE_ID = "coverage/1"

#: Protocol generation for new four-store operations (footprint
#: §3.5, founder's compatibility correction 2026-11-15): a distinct
#: versioned token over the SAME four-store manifest. The landed
#: ``delete:execute`` token is preserved for historical records
#: only; a legacy binary refuses a ``delete:execute/1.1`` operation
#: as an unbound token (conflict, zero writes) instead of resuming
#: it without its classification, work record, and transaction
#: requirements. The grant scope in scopes.py is unchanged — the
#: token is the operation record's binding, not the grant.
OPERATION_TOKEN = "delete:execute/1.1"
OPERATION_SCOPE_VERSION = "1.1"
LEGACY_OPERATION_TOKEN = "delete:execute"

#: The label a legacy (pre-registry) operation's replay carries
#: (FPC §7): its coverage text is reproduced from the preserved
#: registry entry, labelled as reproduced — no binding is claimed
#: for a record that contains none.
LEGACY_REPLAY_LABEL = (
    "Coverage reproduced from the registry's preserved "
    "coverage/1 text: this operation predates coverage binding, "
    "and its record contains no bound statement."
)

#: Bounded mop-up: recount → audit deletes ineligible survivors →
#: recount again, at most this many passes (§8.3).
_MAX_VERIFICATION_PASSES = 3


class ErasureRefused(Exception):
    """The wired flow refused before deleting anything.

    Raised for §9.1 resolution failures and the fail-closed states
    (license absent or not active-and-verifying, a standing record
    that fails verification, a terminated license with neither a
    standing record nor a completion receipt, a tombstone standing
    with no operation record). Nothing has been deleted when this
    propagates; the route maps it to 403.
    """


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _default_owner_resolver() -> str | None:
    """The bootstrapped owner row's id (vision_execution storage).

    Called through the module attribute so tests monkeypatch it
    exactly as the build-room gate's tests do.
    """
    from local_ai.vision_execution import storage as ve_storage

    return ve_storage.get_owner_user_id()


def _save_operation_row(
    store: IdentityStore,
    *,
    license_id: str,
    operation_id: str,
    status: str,
    covered_user: str,
    erased_at: str,
    stores: dict[str, str],
    counts: dict[str, Any],
    scope_token: str = LEGACY_OPERATION_TOKEN,
    scope_version: str | None = None,
    coverage_id: str | None = None,
    coverage_sha256: str | None = None,
    source_fingerprint: dict[str, Any] | None = None,
    classification_sha256: str | None = None,
) -> DeletionReceipt:
    """Append one signed operation-record row (§9.4).

    The bound field set — covered_user, operation_id, erased_at,
    scope — sits inside the summary, inside the existing HMAC
    payload, so verification needs nothing but the row and the
    machine-local key. Rows are append-only; the latest row for an
    operation is its current state.

    Gate B Increment 1: new-generation rows additionally bind the
    protocol generation (``scope_token`` + ``scope_version``), the
    coverage binding (``coverage_id`` + ``coverage_sha256``), the
    per-store ``source_fingerprint``, and — once classification
    has run — the ``classification_sha256``, all inside the same
    signed summary. Legacy rows bind none of these (the defaults
    reproduce the landed field set exactly): no binding is
    invented for a historical record (FPC §7).
    """
    summary: dict[str, Any] = {
        "operation_id": operation_id,
        "op_status": status,
        "covered_user": covered_user,
        "erased_at": erased_at,
        "scope": scope_token,
        "stores": dict(stores),
        "counts": dict(counts),
    }
    if scope_version is not None:
        summary["scope_version"] = scope_version
    if coverage_id is not None:
        summary["coverage_id"] = coverage_id
    if coverage_sha256 is not None:
        summary["coverage_sha256"] = coverage_sha256
    if source_fingerprint is not None:
        summary["source_fingerprint"] = dict(source_fingerprint)
    if classification_sha256 is not None:
        summary["classification_sha256"] = classification_sha256
    receipt = DeletionReceipt(
        receipt_id=f"opr-{uuid4().hex[:12]}",
        ts=datetime.now(timezone.utc),
        license_id=license_id,
        summary=summary,
    )
    receipt.signature = sign_mapping(_receipt_payload(receipt))
    store.save_receipt(receipt)
    return receipt


def _coverage_binding() -> tuple[str, str]:
    """The (coverage_id, coverage_sha256) a fresh operation binds:
    the registry's current four-store text, hashed over its exact
    UTF-8 bytes (amendment §4.2)."""
    text = COVERAGE_STATEMENTS[COVERAGE_ID]
    return COVERAGE_ID, hashlib.sha256(text.encode("utf-8")).hexdigest()


def _user_receipt(
    store: IdentityStore,
    *,
    license_id: str,
    counts: dict[str, Any],
    stores: dict[str, str],
    coverage: str,
    extra: dict[str, Any] | None = None,
) -> DeletionReceipt:
    """Compose + save + sign a user-facing receipt.

    Counts, per-store status lines, and the coverage statement
    only — never the covered user's id, never an erased-content
    identifier (§4 discipline, test 12 as amended by Rev 4).
    """
    summary: dict[str, Any] = {
        key: value
        for key, value in counts.items()
        if isinstance(value, int)
    }
    summary["stores"] = dict(stores)
    summary["coverage"] = coverage
    if extra:
        summary.update(extra)
    receipt = DeletionReceipt(
        receipt_id=f"del-{uuid4().hex[:12]}",
        ts=datetime.now(timezone.utc),
        license_id=license_id,
        summary=summary,
    )
    receipt.signature = sign_mapping(_receipt_payload(receipt))
    store.save_receipt(receipt)
    return receipt


def _incomplete_coverage(unverified: list[str], verified: list[str]) -> str:
    """The incomplete attempt's coverage statement (§8.2): says
    the erasure is incomplete and names the unverified stores —
    store names and counts only, no completion language."""
    verified_text = ", ".join(verified) if verified else "none"
    return (
        "This erasure is INCOMPLETE. Verified as erased: "
        f"{verified_text}. Not verified as erased: "
        f"{', '.join(unverified)}. Nothing in this receipt claims "
        "those stores were deleted. The operation can be resumed by "
        "invoking deletion again — it continues under its original "
        "boundary and never widens. Not erased by this action in "
        "any case: the activity log's contents (under separate "
        "review), your conversations, meetings, projects, and "
        "claims, and anything held in backups or snapshots, which "
        "this action cannot reach."
    )


# ---------------------------------------------------------------------------
# Classification phase (Gate B Increment 1: amendment §1, FPC §1,
# closure note §1, closure correction §1)
# ---------------------------------------------------------------------------


def _fingerprint_portion(payload: Any) -> str:
    """One store's source-fingerprint portion: SHA-256 over the
    canonical serialization of exactly what that store's
    classifier reads (FPC §1)."""
    canonical = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), default=str
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _store_readset(
    name: str,
    user: str,
    *,
    identity_store: IdentityStore,
    narrative_store: Any,
    observation_store: Any,
    presence_store: Any,
    presence_upload_root: Path | None,
    presence_db_path: Path | None,
) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, Any]]:
    """One landed store's classifier read set: (entries, counts,
    fingerprint payload). READ-ONLY — the target enumeration the
    store's delete path already computes, captured before deleting
    (amendment §1.1). Every landed disposition is ``erase``: the
    landed steps are deterministic on (covered user, boundary),
    and the classification is their captured enumeration, not a
    second decider (footprint §3.5)."""
    if name == "presence":
        db_path = (
            Path(presence_db_path)
            if presence_db_path
            else _presence_data_dir() / "signals.db"
        )
        if presence_store is None and not db_path.exists():
            # The wiped state (or never-imported): counting must
            # not resurrect the signals database by constructing
            # a store on its path.
            counts = {
                "import_sessions": 0,
                "presence_events": 0,
                "training_signals": 0,
            }
        else:
            counts = _presence_census(
                presence_store=presence_store,
                presence_upload_root=presence_upload_root,
                presence_db_path=presence_db_path,
            )
        return [], counts, {"counts": counts}
    if name == "narrative":
        threads = narrative_store.threads_for(user, limit=None)
        recount = narrative_store.erasure_recount(user)
        entries = [
            {
                "id": thread.id,
                "kind": "thread",
                "disposition": "erase",
                "group": "",
            }
            for thread in threads
        ]
        payload = {
            "threads": sorted(thread.id for thread in threads),
            "recount": recount,
        }
        return entries, recount, payload
    if name == "observations":
        rows = observation_store.list_for_user(user)
        entries = [
            {
                "id": row.id,
                "kind": "observation",
                "disposition": "erase",
                "group": "",
            }
            for row in rows
        ]
        return (
            entries,
            {"observations": len(rows)},
            {"observations": sorted(row.id for row in rows)},
        )
    if name == "identity":
        events = identity_store.list_scope_events()
        lic = identity_store.get_license()
        entries = [
            {
                "id": event.event_id,
                "kind": "scope_event",
                "disposition": "erase",
                "group": "",
            }
            for event in events
        ]
        if lic is not None:
            entries.append(
                {
                    "id": lic.license_id,
                    "kind": "license",
                    "disposition": "erase",
                    "group": "",
                }
            )
        payload = {
            "scope_events": sorted(event.event_id for event in events),
            "license": (
                [lic.license_id, lic.status] if lic is not None else None
            ),
        }
        return entries, {"scope_events": len(events)}, payload
    raise ValueError(f"unknown Scope S store {name!r}")


def _capture_classification(
    user: str, **readset: Any
) -> tuple[dict[str, Any], dict[str, str]]:
    """Capture the union classification + per-store fingerprint
    over the four landed stores. No writes to any store."""
    classification: dict[str, Any] = {}
    fingerprint: dict[str, str] = {}
    for name in SCOPE_S_STORES:
        entries, counts, payload = _store_readset(name, user, **readset)
        classification[name] = {"entries": entries, "counts": counts}
        fingerprint[name] = _fingerprint_portion(payload)
    return classification, fingerprint


def _compute_fingerprint(user: str, **readset: Any) -> dict[str, str]:
    """The per-store source fingerprint over current state."""
    return _capture_classification(user, **readset)[1]


def _classification_sha256(classification: dict[str, Any]) -> str:
    canonical = json.dumps(
        classification, sort_keys=True, separators=(",", ":"), default=str
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _run_classification_phase(
    *,
    identity_store: IdentityStore,
    license_id: str,
    operation_id: str,
    covered_user: str,
    erased_at: str,
    stores_status: dict[str, str],
    bound_fingerprint: dict[str, str],
    binding: dict[str, Any],
    readset: dict[str, Any],
) -> str:
    """The no-writes classification phase, bracketed (closure
    note §1): the fingerprint is recomputed and required to equal
    the opening row's bound value before capture, over the
    captured state, and again after capture — a classification is
    bound only when its source state is proven unchanged across
    the whole capture window. Any mismatch discards the
    classification unbound (nothing persists), leaves the
    operation opened-unclassified, and raises ErasureRefused
    before any destructive step exists.

    On success the signed work row and the signed ``classified``
    row are persisted in ONE identity-store transaction
    (persist→bind, FPC §1): no interleaving is observable.
    Returns the classification hash.
    """
    pre = _compute_fingerprint(covered_user, **readset)
    if pre != bound_fingerprint:
        raise ErasureRefused(
            "Deletion refused: the source state no longer matches "
            "the fingerprint the operation record binds, so "
            "classification cannot be captured under its "
            "authorization. Nothing was deleted; the operation "
            "remains opened and unclassified."
        )
    classification, mid = _capture_classification(covered_user, **readset)
    post = _compute_fingerprint(covered_user, **readset)
    if mid != bound_fingerprint or post != bound_fingerprint:
        raise ErasureRefused(
            "Deletion refused: the source state changed during "
            "classification capture, so the classification was "
            "discarded unbound. Nothing was deleted; the operation "
            "remains opened and unclassified."
        )
    classification_sha = _classification_sha256(classification)
    payload: dict[str, Any] = {
        "operation_id": operation_id,
        "classification": classification,
        "scrub_set": [],
        "classification_sha256": classification_sha,
        "created_at": _utcnow(),
        "sealed_at": None,
    }
    signature = sign_mapping(payload)
    with StoreBoundary(
        identity_store.boundary_state, identity_store._conn
    ):
        identity_store.save_operation_work(
            operation_id, payload, signature
        )
        _save_operation_row(
            identity_store,
            license_id=license_id,
            operation_id=operation_id,
            status="classified",
            covered_user=covered_user,
            erased_at=erased_at,
            stores=stores_status,
            counts={},
            classification_sha256=classification_sha,
            **binding,
        )
    return classification_sha


def _already_executed(
    name: str, user: str, readset: dict[str, Any]
) -> bool:
    """True when the store already stands fully executed under
    this operation (its classified target set recounts to zero) —
    the resume shape. Under the boundary a store's step is never
    partially durable, so executed-or-untouched is exhaustive."""
    _entries, counts, payload = _store_readset(name, user, **readset)
    if name == "presence":
        return (
            counts.get("import_sessions", 1) == 0
            and counts.get("presence_events", 1) == 0
            and counts.get("training_signals", 1) == 0
        )
    if name == "narrative":
        return counts.get("total", 1) == 0
    if name == "observations":
        return counts.get("observations", 1) == 0
    if name == "identity":
        lic = payload.get("license")
        return (
            counts.get("scope_events", 1) == 0
            and lic is not None
            and lic[1] == "terminated"
        )
    return False


def _store_gate(
    name: str,
    user: str,
    *,
    bound_portion: str,
    readset: dict[str, Any],
) -> bool:
    """The per-store execution gate (closure correction §1),
    evaluated inside the store's boundary transaction: the
    store's fingerprint portion must still equal the bound
    portion — the classified read set untouched — OR the store
    must already stand fully executed under this operation
    (recount zero), which is the resume shape: under the boundary
    a store's step is never partially durable, so a changed read
    set with a nonzero recount is a change the classification
    never authorized, and the step refuses before deleting."""
    _entries, _counts, payload = _store_readset(name, user, **readset)
    if _fingerprint_portion(payload) == bound_portion:
        return True
    return _already_executed(name, user, readset)


def run_erasure_flow(
    *,
    requesting_user_id: str,
    identity_store: IdentityStore,
    narrative_store: Any = None,
    observation_store: Any = None,
    presence_store: Any = None,
    presence_upload_root: Path | None = None,
    presence_db_path: Path | None = None,
    owner_resolver: Any = None,
    log_path: Path | str | None = None,
) -> DeletionReceipt:
    """Run the wired Scope S erasure for the resolved owner.

    The caller (service.delete_all) has already verified the typed
    confirmation. Returns the user-facing receipt — complete,
    incomplete, or the standing-completion no-op report. Raises
    ErasureRefused (nothing deleted) for the §9.1 fail-closed
    states, and ScopeDenied for a fresh operation without the
    delete:execute grant.
    """
    from local_ai.narrative.eligibility import (
        ProvenanceResolver,
        audit_narrative_store,
        audit_observation_store,
        read_operation_records,
        render_bound_coverage,
    )

    # -- §9.1 resolution: first, before any destructive step. ------
    resolver_fn = owner_resolver or _default_owner_resolver
    owner_id = resolver_fn()
    if not owner_id or requesting_user_id != owner_id:
        raise ErasureRefused(
            "Deletion refused: the authenticated session does not "
            "resolve to this installation's owner record, so no "
            "deletion scope can be established. Nothing was deleted."
        )
    user = owner_id

    if narrative_store is None:
        from local_ai.narrative.store import NarrativeStore

        narrative_store = NarrativeStore()
    if observation_store is None:
        from local_ai.fellowship.observations import ObservationStore

        observation_store = ObservationStore()

    records = read_operation_records(identity_store, user)
    if records.conflict:
        raise ErasureRefused(
            f"Deletion refused: {records.conflict}. Nothing was deleted."
        )
    lic = identity_store.get_license()
    license_id = lic.license_id if lic is not None else "none"

    stores_status: dict[str, str] = {
        name: "not-attempted" for name in SCOPE_S_STORES
    }
    counts: dict[str, Any] = {}

    # Gate B Increment 1: generation + lifecycle tracking. A
    # standing record's token fixes its operation's generation for
    # the operation's whole life; fresh operations are
    # new-generation. ``binding`` carries the _save_operation_row
    # kwargs every later row of a new-generation operation binds;
    # for a legacy operation it stays empty and every row keeps
    # the landed field set exactly.
    new_generation = True
    binding: dict[str, Any] = {}
    bound_fingerprint: dict[str, str] = {}
    classification_sha: str | None = None
    latest_status = ""
    readset: dict[str, Any] = dict(
        identity_store=identity_store,
        narrative_store=narrative_store,
        observation_store=observation_store,
        presence_store=presence_store,
        presence_upload_root=presence_upload_root,
        presence_db_path=presence_db_path,
    )

    if records.standing is not None:
        # Continuation / authenticated resume (§9.1 Rev 3): the
        # standing verified record governs — original boundary,
        # original covered user, original scope. The record's
        # signature verification (read_operation_records) replaces
        # the scope re-check: the original run consumed the grant
        # when it cleared the ledger, and the resume does not
        # re-draw on it. The license is never resurrected.
        operation_id = records.standing.operation_id
        boundary = records.standing.erased_at
        license_id = records.standing.license_id or license_id
        standing = records.standing
        latest_status = standing.status
        if standing.scope == OPERATION_TOKEN:
            # New-generation resume: lifecycle-aware (FPC §1).
            bound_fingerprint = dict(standing.source_fingerprint)
            if not bound_fingerprint:
                raise ErasureRefused(
                    "Deletion refused: the standing operation "
                    "record binds no source fingerprint, so its "
                    "classification cannot be governed. Nothing "
                    "was deleted."
                )
            binding = dict(
                scope_token=OPERATION_TOKEN,
                scope_version=OPERATION_SCOPE_VERSION,
                coverage_id=standing.coverage_id,
                coverage_sha256=standing.coverage_sha256,
                source_fingerprint=bound_fingerprint,
            )
            work_present = identity_store.has_operation_work(operation_id)
            lifecycle = standing.derive_lifecycle(work_present)
            if lifecycle == "opened-unclassified":
                if work_present:
                    # Unbound work row — the staged-write form of
                    # a crash at the persist→bind seam: discard it
                    # and reclassify under the fingerprint rule
                    # (FPC §1). Nothing was ever executed from it.
                    identity_store.delete_operation_work(operation_id)
                classification_sha = _run_classification_phase(
                    identity_store=identity_store,
                    license_id=license_id,
                    operation_id=operation_id,
                    covered_user=user,
                    erased_at=boundary,
                    stores_status=stores_status,
                    bound_fingerprint=bound_fingerprint,
                    binding=binding,
                    readset=readset,
                )
                latest_status = "classified"
            elif lifecycle in ("classified", "executing"):
                # Execute only against a verified work row
                # (amendment §1.3): signature-verified on load and
                # hash-equal to the signed classified row's bound
                # hash. Missing or unverifiable → conflict,
                # nothing deleted, never recomputed.
                payload, verified = identity_store.load_operation_work(
                    operation_id
                )
                if (
                    not verified
                    or payload is None
                    or payload.get("classification_sha256")
                    != standing.classification_sha256
                ):
                    raise ErasureRefused(
                        "Deletion refused: the standing operation's "
                        "classification work row is missing or does "
                        "not verify against its signed record, so "
                        "execution cannot proceed from it. Nothing "
                        "was deleted."
                    )
                classification_sha = standing.classification_sha256
            else:  # pragma: no cover — standing implies the above
                raise ErasureRefused(
                    f"Deletion refused: the standing operation's "
                    f"lifecycle state ({lifecycle}) cannot resume. "
                    "Nothing was deleted."
                )
        else:
            # Legacy generation: resume under landed behavior —
            # no classification is invented for it (FPC §7).
            new_generation = False
    elif lic is not None and lic.status == "terminated":
        if records.completed is not None:
            # Verified no-op: report the standing completion state
            # rather than pretending a second erasure occurred.
            completed = records.completed
            # T-X23 invariant: a work row standing beside a
            # completed record (the staged-write seal seam) is
            # destroyed on sight. Under this build's
            # one-transaction seal the state is unrepresentable;
            # the cleanup is kept as the invariant's enforcement.
            if identity_store.has_operation_work(completed.operation_id):
                identity_store.delete_operation_work(completed.operation_id)
            if completed.coverage_id is not None:
                # New-generation completion: speak its bound
                # coverage, rendered by id after hash verification.
                rendered = render_bound_coverage(
                    completed.coverage_id, completed.coverage_sha256
                )
                if rendered is None:
                    raise ErasureRefused(
                        "Deletion refused: the completed operation's "
                        "coverage binding does not verify against "
                        "the registry, so no coverage language can "
                        "be issued for it. Nothing was deleted."
                    )
                return _user_receipt(
                    identity_store,
                    license_id=completed.license_id or license_id,
                    counts=completed.counts,
                    stores={name: "verified" for name in SCOPE_S_STORES},
                    coverage=rendered,
                )
            # Legacy completion: the coverage text is reproduced
            # from the preserved registry entry, LABELLED as
            # reproduced — the record contains no bound statement
            # and none is claimed for it (FPC §7).
            return _user_receipt(
                identity_store,
                license_id=completed.license_id or license_id,
                counts=completed.counts,
                stores={name: "verified" for name in SCOPE_S_STORES},
                coverage=COVERAGE_STATEMENT,
                extra={"coverage_note": LEGACY_REPLAY_LABEL},
            )
        raise ErasureRefused(
            "Deletion refused: the license is terminated but neither "
            "an operation record nor a completion receipt stands — "
            "a state this protocol cannot produce. Nothing was deleted."
        )
    else:
        # Fresh operation: license active-and-verifying + the live
        # delete:execute grant are both required (§9.1).
        if (
            lic is None
            or lic.status != "active"
            or not verify_license(store=identity_store)
        ):
            raise ErasureRefused(
                "Deletion refused: there is no active, "
                "signature-verifying identity license. Nothing was "
                "deleted."
            )
        require_scope("delete:execute", store=identity_store)
        # A tombstone standing with no operation record is an
        # anomaly this protocol cannot produce (the record is
        # written before either tombstone): fail closed rather
        # than silently override an existing barrier.
        for store_obj, name in (
            (narrative_store, "narrative"),
            (observation_store, "observations"),
        ):
            if store_obj.get_erasure_tombstone(user) is not None:
                raise ErasureRefused(
                    f"Deletion refused: an erasure tombstone stands "
                    f"in the {name} store with no operation record. "
                    "Nothing was deleted."
                )
        # Step 0: the operation record fixes T before the first
        # tombstone (§9.4). Gate B Increment 1: a fresh operation
        # is new-generation — the per-store source fingerprint is
        # computed first (read-only) and bound into the signed
        # opening row together with the generation token and the
        # coverage binding; the classification phase follows
        # immediately, before any barrier or content step.
        operation_id = f"op-{uuid4().hex[:12]}"
        boundary = _utcnow()
        bound_fingerprint = _compute_fingerprint(user, **readset)
        cov_id, cov_sha = _coverage_binding()
        binding = dict(
            scope_token=OPERATION_TOKEN,
            scope_version=OPERATION_SCOPE_VERSION,
            coverage_id=cov_id,
            coverage_sha256=cov_sha,
            source_fingerprint=bound_fingerprint,
        )
        _save_operation_row(
            identity_store,
            license_id=license_id,
            operation_id=operation_id,
            status="opened",
            covered_user=user,
            erased_at=boundary,
            stores=stores_status,
            counts={},
            **binding,
        )
        classification_sha = _run_classification_phase(
            identity_store=identity_store,
            license_id=license_id,
            operation_id=operation_id,
            covered_user=user,
            erased_at=boundary,
            stores_status=stores_status,
            bound_fingerprint=bound_fingerprint,
            binding=binding,
            readset=readset,
        )
        latest_status = "classified"

    # -- Execution gate + executing row (new-generation only). ----
    # Classification is not a purely observational safeguard
    # (founder's Gate B condition; closure note §1): before the
    # `executing` row is appended — the last moment before
    # destructive execution is possible — every store whose step
    # has not already executed must still match its bound
    # fingerprint portion. A mismatch refuses here, with zero
    # destructive writes anywhere; the operation stays classified
    # and its exits are resume (state settled) or abandonment.
    if new_generation:
        current = _compute_fingerprint(user, **readset)
        for name in SCOPE_S_STORES:
            if current.get(name) != bound_fingerprint.get(
                name
            ) and not _already_executed(name, user, readset):
                raise ErasureRefused(
                    f"Deletion refused: the {name} store's state "
                    "no longer matches the fingerprint the "
                    "operation's classification binds, and the "
                    "store does not stand executed under this "
                    "operation. Execution is refused before any "
                    "destructive step; the operation remains "
                    "classified. Nothing was deleted."
                )
        if latest_status != "executing":
            _save_operation_row(
                identity_store,
                license_id=license_id,
                operation_id=operation_id,
                status="executing",
                covered_user=user,
                erased_at=boundary,
                stores=stores_status,
                counts={},
                classification_sha256=classification_sha,
                **binding,
            )
            latest_status = "executing"

    def _refusal_recorder(store_name: str):
        """Four-gap §1(d): a boundary refusal is recorded in the
        identity store AFTER the rollback completes — never inside
        the boundary that failed — with that store's standing
        refused."""

        def record(reason: str) -> None:
            logger.warning(
                "erasure %s: %s step refused at its boundary: %s",
                operation_id,
                store_name,
                reason,
            )
            try:
                refused = dict(stores_status)
                refused[store_name] = "refused"
                _save_operation_row(
                    identity_store,
                    license_id=license_id,
                    operation_id=operation_id,
                    status="incomplete",
                    covered_user=user,
                    erased_at=boundary,
                    stores=refused,
                    counts={"boundary_refusal": store_name},
                    classification_sha256=classification_sha,
                    **binding,
                )
            except Exception:  # noqa: BLE001 — never mask the refusal
                logger.exception(
                    "erasure %s: boundary refusal for %s could not "
                    "be recorded",
                    operation_id,
                    store_name,
                )

        return record

    # -- Barrier-integrity pre-step (§9.4): reconcile the barriers
    # against the record before the content steps. Missing barriers
    # are written at the record's T; a divergent tombstone is
    # rewritten to the record's T and the discrepancy reported (in
    # the operation rows and as a count on the receipt — a
    # timestamp is never chosen here, only copied from the record).
    discrepancies: list[str] = []
    for store_obj, name in (
        (narrative_store, "narrative"),
        (observation_store, "observations"),
    ):
        tomb = store_obj.get_erasure_tombstone(user)
        if tomb is None:
            store_obj.write_erasure_tombstone(user, boundary, operation_id)
        elif tomb["erased_at"] != boundary:
            store_obj.rewrite_erasure_tombstone(user, boundary, operation_id)
            discrepancies.append(name)
    if discrepancies:
        counts["barrier_discrepancies"] = len(discrepancies)
        logger.warning(
            "erasure %s: tombstone(s) %s disagreed with the signed "
            "operation record and were reconciled to its boundary %s",
            operation_id,
            ", ".join(discrepancies),
            boundary,
        )

    # -- Per-store steps, fixed order (§8.2 step 3). ---------------
    failures: dict[str, str] = {}
    try:
        counts.update(
            _wipe_presence(
                presence_store=presence_store,
                presence_upload_root=presence_upload_root,
                presence_db_path=presence_db_path,
            )
        )
        stores_status["presence"] = "deleted"
    except Exception as exc:  # noqa: BLE001 — recorded, not hidden
        failures["presence"] = str(exc)
        stores_status["presence"] = "incomplete"
    try:
        # Caller-owned boundary (four-gap §1; closure correction
        # §1): the gate check, the destructive step, and the
        # step's own recount run inside one BEGIN IMMEDIATE
        # transaction on the narrative store's file. This is the
        # footprint §3.5 named exception: the step's internal
        # per-thread commits are suppressed into the boundary, so
        # a mid-step failure now rolls the whole step back instead
        # of leaving partial progress durable; final states,
        # dispositions, counts, and receipts are unchanged.
        with StoreBoundary(
            narrative_store.boundary_state,
            narrative_store._conn,
            gate=(
                (
                    lambda: _store_gate(
                        "narrative",
                        user,
                        bound_portion=bound_fingerprint.get(
                            "narrative", ""
                        ),
                        readset=readset,
                    )
                )
                if new_generation
                else None
            ),
            on_refusal=_refusal_recorder("narrative"),
        ) as narrative_boundary:
            erase_report = narrative_store.erase_user_material(
                user,
                erased_at=boundary,
                operation_id=operation_id,
                log_path=log_path,
            )
            narrative_boundary.assert_intact()
        counts["narrative_threads"] = erase_report["threads_deleted"]
        counts["narrative_rows"] = (
            erase_report["rows_deleted"] - erase_report["threads_deleted"]
        )
        stores_status["narrative"] = "deleted"
    except Exception as exc:  # noqa: BLE001
        failures["narrative"] = str(exc)
        stores_status["narrative"] = "incomplete"
    try:
        with StoreBoundary(
            observation_store.boundary_state,
            observation_store._conn,
            gate=(
                (
                    lambda: _store_gate(
                        "observations",
                        user,
                        bound_portion=bound_fingerprint.get(
                            "observations", ""
                        ),
                        readset=readset,
                    )
                )
                if new_generation
                else None
            ),
            on_refusal=_refusal_recorder("observations"),
        ) as observations_boundary:
            deleted_observations = observation_store.delete_for_user(user)
            if observation_store.count_for_user(user) != 0:
                observation_store.boundary_state.mark_rollback_only(
                    "observations recount inside the boundary is "
                    "not zero after delete_for_user"
                )
            observations_boundary.assert_intact()
        counts["observations"] = deleted_observations
        stores_status["observations"] = "deleted"
    except Exception as exc:  # noqa: BLE001
        failures["observations"] = str(exc)
        stores_status["observations"] = "incomplete"
    try:
        with StoreBoundary(
            identity_store.boundary_state,
            identity_store._conn,
            gate=(
                (
                    lambda: _store_gate(
                        "identity",
                        user,
                        bound_portion=bound_fingerprint.get(
                            "identity", ""
                        ),
                        readset=readset,
                    )
                )
                if new_generation
                else None
            ),
            on_refusal=_refusal_recorder("identity"),
        ) as identity_boundary:
            n_scope_events = len(identity_store.list_scope_events())
            identity_store.clear_scope_events()
            identity_boundary.assert_intact()
            if lic is not None:
                identity_store.terminate_license()
        counts["scope_events"] = n_scope_events
        stores_status["identity"] = "deleted"
    except Exception as exc:  # noqa: BLE001
        failures["identity"] = str(exc)
        stores_status["identity"] = "incomplete"

    # -- Verification (§8.2 step 4 + §9.5): independent recount AND
    # a full-set provenance audit of the survivors, with the
    # bounded mop-up loop. Receipts are composed from these
    # numbers, never from the steps' own reports alone.
    # Meeting rows for culmination provenance (§9.3): the flow is
    # outside the narrative package, so it may read the meeting
    # store; any failure leaves meeting origins unresolvable,
    # which fails closed in the audit.
    meeting_rows = None
    try:
        from local_ai.conversation.meeting import MeetingStore

        meeting_store = MeetingStore()
        try:
            meeting_rows = meeting_store.meetings_for(user)
        finally:
            meeting_store.close()
    except Exception:  # noqa: BLE001 — fail closed, recorded below
        logger.warning(
            "erasure %s: meeting rows unavailable for the provenance "
            "audit; meeting origins will fail closed",
            operation_id,
        )
    resolver = ProvenanceResolver(
        user,
        boundary,
        narrative_store=narrative_store,
        observation_store=observation_store,
        log_path=log_path,
        meeting_rows=meeting_rows,
    )
    if stores_status["presence"] == "deleted":
        pdata = _presence_data_dir()
        db_path = (
            Path(presence_db_path) if presence_db_path else pdata / "signals.db"
        )
        upload_root = (
            Path(presence_upload_root)
            if presence_upload_root
            else pdata / "uploads"
        )
        if not db_path.exists() and not upload_root.exists():
            stores_status["presence"] = "verified"
        else:
            stores_status["presence"] = "incomplete"
            failures.setdefault(
                "presence", "presence files remain after deletion"
            )
    if stores_status["narrative"] == "deleted":
        audit: dict[str, Any] = {"checked": 0, "removed": 0, "failures": []}
        verified = False
        for _ in range(_MAX_VERIFICATION_PASSES):
            audit = audit_narrative_store(narrative_store, user, resolver)
            recount = narrative_store.erasure_recount(user)
            if recount["total"] == 0 and not audit["failures"]:
                verified = True
                break
            if audit["removed"] == 0:
                break
        counts["narrative_audit_checked"] = audit["checked"]
        counts["narrative_audit_removed"] = audit["removed"]
        if verified:
            stores_status["narrative"] = "verified"
        else:
            stores_status["narrative"] = "incomplete"
            failures.setdefault(
                "narrative",
                "recount/provenance audit did not converge to zero",
            )
    if stores_status["observations"] == "deleted":
        audit_o: dict[str, Any] = {"checked": 0, "removed": 0, "failures": []}
        verified = False
        for _ in range(_MAX_VERIFICATION_PASSES):
            audit_o = audit_observation_store(
                observation_store, user, resolver
            )
            remaining = observation_store.count_for_user(user)
            if remaining == 0 and not audit_o["failures"]:
                verified = True
                break
            if audit_o["removed"] == 0:
                break
        counts["observations_audit_checked"] = audit_o["checked"]
        counts["observations_audit_removed"] = audit_o["removed"]
        if verified:
            stores_status["observations"] = "verified"
        else:
            stores_status["observations"] = "incomplete"
            failures.setdefault(
                "observations",
                "recount/provenance audit did not converge to zero",
            )
    if stores_status["identity"] == "deleted":
        lic_after = identity_store.get_license()
        if not identity_store.list_scope_events() and (
            lic_after is None or lic_after.status == "terminated"
        ):
            stores_status["identity"] = "verified"
        else:
            stores_status["identity"] = "incomplete"
            failures.setdefault(
                "identity", "ledger not empty or license not terminated"
            )

    # -- VACUUM (§8.2 step 5): file hygiene for this store's file.
    for store_obj, name in (
        (narrative_store, "narrative"),
        (observation_store, "observations"),
    ):
        try:
            store_obj.vacuum()
        except Exception as exc:  # noqa: BLE001
            if stores_status[name] == "verified":
                stores_status[name] = "incomplete"
            failures.setdefault(name, f"VACUUM failed: {exc}")

    # -- Receipts (§8.2 step 6): composed last, from the recounts.
    complete = all(
        stores_status[name] == "verified" for name in SCOPE_S_STORES
    )
    if failures:
        logger.warning(
            "erasure %s store failures: %s", operation_id, failures
        )
    if complete:
        narrative_store.set_erasure_tombstone_counts(user, counts)
        observation_store.set_erasure_tombstone_counts(user, counts)
        if new_generation:
            # Seal (FPC §1): the completion row — binding the
            # classification hash and the per-class counts — and
            # the work row's destruction commit in ONE
            # identity-store transaction. A seal failure leaves
            # the operation open and resumable (the incomplete
            # path below), never half-sealed.
            try:
                with StoreBoundary(
                    identity_store.boundary_state, identity_store._conn
                ):
                    _save_operation_row(
                        identity_store,
                        license_id=license_id,
                        operation_id=operation_id,
                        status="completed",
                        covered_user=user,
                        erased_at=boundary,
                        stores=stores_status,
                        counts=counts,
                        classification_sha256=classification_sha,
                        **binding,
                    )
                    identity_store.delete_operation_work(operation_id)
            except Exception as exc:  # noqa: BLE001 — resumable
                logger.warning(
                    "erasure %s: sealing failed (%s); the operation "
                    "remains open and resumable",
                    operation_id,
                    exc,
                )
                complete = False
                failures["identity"] = f"sealing failed: {exc}"
                stores_status["identity"] = "incomplete"
            if complete:
                # Speak the bound coverage, rendered by id after
                # hash verification (amendment §4). A binding that
                # does not verify fails closed: counts still
                # report, no coverage language is issued, and the
                # receipt carries the failure as its reason.
                rendered = render_bound_coverage(
                    binding.get("coverage_id"),
                    binding.get("coverage_sha256"),
                )
                if rendered is None:
                    return _user_receipt(
                        identity_store,
                        license_id=license_id,
                        counts=counts,
                        stores=stores_status,
                        coverage=_incomplete_coverage(
                            ["the coverage statement binding"],
                            list(SCOPE_S_STORES),
                        ),
                    )
                return _user_receipt(
                    identity_store,
                    license_id=license_id,
                    counts=counts,
                    stores=stores_status,
                    coverage=rendered,
                )
        else:
            _save_operation_row(
                identity_store,
                license_id=license_id,
                operation_id=operation_id,
                status="completed",
                covered_user=user,
                erased_at=boundary,
                stores=stores_status,
                counts=counts,
            )
            return _user_receipt(
                identity_store,
                license_id=license_id,
                counts=counts,
                stores=stores_status,
                coverage=COVERAGE_STATEMENT,
            )
    unverified = [
        name for name in SCOPE_S_STORES if stores_status[name] != "verified"
    ]
    verified_names = [
        name for name in SCOPE_S_STORES if stores_status[name] == "verified"
    ]
    _save_operation_row(
        identity_store,
        license_id=license_id,
        operation_id=operation_id,
        status="incomplete",
        covered_user=user,
        erased_at=boundary,
        stores=stores_status,
        counts=counts,
        classification_sha256=classification_sha,
        **binding,
    )
    return _user_receipt(
        identity_store,
        license_id=license_id,
        counts=counts,
        stores=stores_status,
        coverage=_incomplete_coverage(unverified, verified_names),
    )


def abandon_operation(
    *,
    requesting_user_id: str,
    identity_store: IdentityStore,
    owner_resolver: Any = None,
) -> DeletionReceipt:
    """Abandon the standing new-generation operation (FPC §1).

    Abandonment exists only from the pre-execution states —
    opened-unclassified and classified: no content store has been
    touched in either, or can have been. The signed ``abandoned``
    row (binding the classification hash if one existed, counts
    zero) and the work row's destruction commit in ONE
    identity-store transaction. From ``executing`` abandonment
    does not exist: the only exits are completion or the
    incomplete-receipt/resume path. The covered user alone may
    abandon, under the same §9.1 owner resolution as the flow.
    Returns the abandoned row.
    """
    resolver_fn = owner_resolver or _default_owner_resolver
    owner_id = resolver_fn()
    if not owner_id or requesting_user_id != owner_id:
        raise ErasureRefused(
            "Abandonment refused: the authenticated session does "
            "not resolve to this installation's owner record. "
            "Nothing was changed."
        )
    from local_ai.narrative.eligibility import read_operation_records

    records = read_operation_records(identity_store, owner_id)
    if records.conflict:
        raise ErasureRefused(
            f"Abandonment refused: {records.conflict}. "
            "Nothing was changed."
        )
    standing = records.standing
    if standing is None:
        raise ErasureRefused(
            "Abandonment refused: no operation stands open for "
            "the covered user. Nothing was changed."
        )
    if standing.scope != OPERATION_TOKEN:
        raise ErasureRefused(
            "Abandonment refused: the standing operation is a "
            "legacy-generation record; abandonment is a "
            "new-protocol act and no binding is invented for it. "
            "Nothing was changed."
        )
    work_present = identity_store.has_operation_work(standing.operation_id)
    lifecycle = standing.derive_lifecycle(work_present)
    if lifecycle not in ("opened-unclassified", "classified"):
        raise ErasureRefused(
            f"Abandonment refused: the standing operation is "
            f"{lifecycle}; abandonment exists only before "
            "execution begins. Nothing was changed."
        )
    binding = dict(
        scope_token=OPERATION_TOKEN,
        scope_version=OPERATION_SCOPE_VERSION,
        coverage_id=standing.coverage_id,
        coverage_sha256=standing.coverage_sha256,
        source_fingerprint=dict(standing.source_fingerprint),
    )
    with StoreBoundary(
        identity_store.boundary_state, identity_store._conn
    ):
        row = _save_operation_row(
            identity_store,
            license_id=standing.license_id or "none",
            operation_id=standing.operation_id,
            status="abandoned",
            covered_user=owner_id,
            erased_at=standing.erased_at,
            stores={name: "not-attempted" for name in SCOPE_S_STORES},
            counts={},
            classification_sha256=standing.classification_sha256,
            **binding,
        )
        identity_store.delete_operation_work(standing.operation_id)
    return row
