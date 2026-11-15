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
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from .models import DeletionReceipt
from .scopes import require_scope
from .service import _presence_data_dir, _receipt_payload, _wipe_presence
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
) -> DeletionReceipt:
    """Append one signed operation-record row (§9.4).

    The bound field set — covered_user, operation_id, erased_at,
    scope — sits inside the summary, inside the existing HMAC
    payload, so verification needs nothing but the row and the
    machine-local key. Rows are append-only; the latest row for an
    operation is its current state.
    """
    receipt = DeletionReceipt(
        receipt_id=f"opr-{uuid4().hex[:12]}",
        ts=datetime.now(timezone.utc),
        license_id=license_id,
        summary={
            "operation_id": operation_id,
            "op_status": status,
            "covered_user": covered_user,
            "erased_at": erased_at,
            "scope": "delete:execute",
            "stores": dict(stores),
            "counts": dict(counts),
        },
    )
    receipt.signature = sign_mapping(_receipt_payload(receipt))
    store.save_receipt(receipt)
    return receipt


def _user_receipt(
    store: IdentityStore,
    *,
    license_id: str,
    counts: dict[str, Any],
    stores: dict[str, str],
    coverage: str,
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
    elif lic is not None and lic.status == "terminated":
        if records.completed is not None:
            # Verified no-op: report the standing completion state
            # rather than pretending a second erasure occurred.
            return _user_receipt(
                identity_store,
                license_id=records.completed.license_id or license_id,
                counts=records.completed.counts,
                stores={name: "verified" for name in SCOPE_S_STORES},
                coverage=COVERAGE_STATEMENT,
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
        # tombstone (§9.4).
        operation_id = f"op-{uuid4().hex[:12]}"
        boundary = _utcnow()
        _save_operation_row(
            identity_store,
            license_id=license_id,
            operation_id=operation_id,
            status="opened",
            covered_user=user,
            erased_at=boundary,
            stores=stores_status,
            counts={},
        )

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
        erase_report = narrative_store.erase_user_material(
            user,
            erased_at=boundary,
            operation_id=operation_id,
            log_path=log_path,
        )
        counts["narrative_threads"] = erase_report["threads_deleted"]
        counts["narrative_rows"] = (
            erase_report["rows_deleted"] - erase_report["threads_deleted"]
        )
        stores_status["narrative"] = "deleted"
    except Exception as exc:  # noqa: BLE001
        failures["narrative"] = str(exc)
        stores_status["narrative"] = "incomplete"
    try:
        counts["observations"] = observation_store.delete_for_user(user)
        stores_status["observations"] = "deleted"
    except Exception as exc:  # noqa: BLE001
        failures["observations"] = str(exc)
        stores_status["observations"] = "incomplete"
    try:
        counts["scope_events"] = len(identity_store.list_scope_events())
        identity_store.clear_scope_events()
        if lic is not None:
            identity_store.terminate_license()
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
    )
    return _user_receipt(
        identity_store,
        license_id=license_id,
        counts=counts,
        stores=stores_status,
        coverage=_incomplete_coverage(unverified, verified_names),
    )
