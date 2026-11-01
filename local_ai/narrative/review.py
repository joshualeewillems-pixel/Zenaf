"""Steward-proposal review items + verdicts (addendum §4.1).

The review layer's discipline, extended — not a parallel system.
Claim verdicts (agent routes) use the vocabulary accepted /
corrected / explained / rejected / unresolved, mutate a standing
record, and log a feedback signal. Steward review verdicts use the
same shape: accepted / rejected / unresolved, mutate the proposal
row through the store's existing transitions, and append to the
verdict log (the audit trail and the proposal-precision source).

Review surfaces (base plan §6.1 default — audit recommendation
(c)): queue cards for births and fittings, thread notes for
changes. Readings, as proposal items needing an explicit verdict
like births and fittings, surface as queue cards.

Verdict mapping (existing store transitions only, nothing new):

- birth (nascent thread, origin ``steward_proposal``):
  accept → ``active``; reject → ``archived`` (terminal; retired
  requires a retirement reason a verdict rejection does not
  supply); unresolved → no transition, verdict logged.
- reading (``proposed``, author ``steward``):
  accept → ``accept_reading`` (supersedes sibling proposals per
  existing behavior); reject → ``reject_reading``.
- change (``proposed``; changes are steward-recorded by
  construction, no author field): accept → ``confirmed``;
  reject → ``dismissed``.
- fitting (``proposed``/``offered``, ``proposed_by`` steward):
  accept → ``accepted``; reject → ``rejected``.
- revision (Phase 6 schedule version, ``in_review``):
  accept → ``accepted`` (prior accepted version, if any, becomes
  ``superseded``; the accepted version is the artifact's
  deliverable); reject → ``rejected`` (terminal; the row stays).
  Unresolved → no transition, version stays in review.
- oversight (Phase 7 oversight proposal, ``proposed``):
  accept → ``confirmed`` (a confirmed OBSERVATION — no thread,
  reading, or branch state changes, because oversight never
  commands); reject → ``dismissed``.
- correspondence (Phase 7 correspondence, ``proposed``):
  accept → ``user_accepted`` (the user alone accepts; seat
  responses never move this status); reject → ``rejected``.
- reconsideration (Phase 7 reading reconsideration, ``proposed``):
  accept → ``affirmed`` (the reading stays accepted and is
  open for revision; the reading row itself is never edited);
  reject → ``dismissed`` (candidacy cleared, reading stands).
  Unresolved → no transition for all three new kinds.

Durability note, stated honestly: a decided proposal never
reappears as pending — rejected/accepted statuses are terminal in
the store — and the verdict log is durable. What Phase 1 does NOT
do is write derivation dismissal memory: whether derivation
re-proposes equivalent content on re-analysis is governed
separately by ``is_dismissed`` rows, which review verdicts do not
create (a verdict is about a specific proposal; a dismissal is a
content-addressed signature). Wiring the two is a later-phase
decision, not something Phase 1 invents. The PR body flags this.

Point-in-time preservation (non-foreclosure, Phase 1 only):
this module implements NO snapshot capture and NO abstention
storage. What it preserves is the ABILITY to attach an
immutable, point-in-time evidence manifest to a proposal later,
without changing any Phase 1 contract:

* Proposals carry stable identities (store id) and creation
  timestamps, and their content — including their generation-
  time evidence_refs — is immutable. Evidence rows themselves
  are insert-only (only the entity_ref annotation is ever
  updated, and it records identity, not content), so a
  proposal's evidence_refs are the set available when it was
  generated, while those rows are retained.
* Timestamps + references alone do NOT reproduce what was
  seen: evidence rows cascade away when their thread is
  deleted. A future manifest must therefore store frozen
  evidence CONTENT, not references. The attachment point is
  the proposal's (item_kind, item_id) pair, which is stable
  and already the verdict log's key; manifest rows would be
  append-only (never updated — a correction is a new row)
  and would follow their proposal on deletion, exactly as
  verdict rows do (store.py delete_thread / clear cascades).
  Immutable here means unchanged while retained, NOT
  undeletable: deleting the proposal deletes its manifest.
* Verdicts remain separate from proposal content (the verdict
  log references proposals; it never embeds or edits them),
  so a manifest attached to a proposal stays readable
  regardless of later verdicts.
* Abstention needs no proposal: decline writes nothing in
  Phase 1, and non-proposal records already exist
  (assessments, flags, verdicts, dismissals), so a future
  abstention event can be its own record keyed by thread or
  assessment without ever becoming a narrative proposal —
  and it would never appear in this review surface unless
  explicitly wired.
* Deletion and consent revocation stay enforceable: verdict
  rows follow their items, assessments and flags follow
  their threads (delete_thread cascades; clear sweeps
  verdict rows for directly-deleted readings), and consent
  is re-validated on every coordination call, so no stored
  record grants future access.
"""

from __future__ import annotations

from dataclasses import dataclass

from .store import NarrativeStore

# Phase 6: schedule revisions are review items too — a version in
# review is a steward proposal awaiting a verdict, exactly like a
# birth, reading, change, or fitting. This is the schedule's
# review step running through the Phase 1 wiring, not a parallel
# system: revisions appear in GET /steward/review and take verdicts
# through the existing routes. No other Phase 1 semantics change.
# Phase 7: oversight proposals, correspondences, and reading
# reconsiderations route through the same machinery (store.py
# record_review_verdict's kind tuple must match ITEM_KINDS).
ITEM_KINDS: tuple[str, ...] = (
    "birth", "reading", "change", "fitting", "revision",
    "oversight", "correspondence", "reconsideration",
)
VERDICTS: tuple[str, ...] = ("accepted", "rejected", "unresolved")

#: Review surface per item kind (base plan §6.1 default).
SURFACE_BY_KIND: dict[str, str] = {
    "birth": "queue_card",
    "reading": "queue_card",
    "fitting": "queue_card",
    "change": "thread_note",
    "revision": "queue_card",
    "oversight": "queue_card",
    "correspondence": "queue_card",
    "reconsideration": "queue_card",
}


@dataclass(frozen=True)
class ReviewItem:
    """One steward proposal as a review item."""

    item_id: str  # "birth:<thread_id>" etc.
    item_kind: str
    thread_id: str
    surface: str  # queue_card | thread_note
    status: str
    title: str
    payload: dict


def _item_id(kind: str, row_id: str) -> str:
    return f"{kind}:{row_id}"


def _parse_item_id(item_id: str) -> tuple[str, str]:
    kind, sep, row_id = item_id.partition(":")
    if not sep or kind not in ITEM_KINDS or not row_id:
        raise ValueError(f"unknown review item: {item_id!r}")
    return kind, row_id


def pending_review_items(store: NarrativeStore, user_id: str) -> list[ReviewItem]:
    """All undecided steward proposals for a user, oldest first
    within each kind.

    Only steward proposals appear: births with origin
    ``steward_proposal``, readings authored by ``steward``,
    steward-recorded changes, and fittings proposed by
    ``steward``. User-declared threads and user/seat-authored
    readings never appear here — they are not steward proposals
    awaiting a verdict. Phase 7 kinds (oversight,
    correspondence, reconsideration) append after the
    thread-scoped items, oldest first within each kind.
    """
    items: list[ReviewItem] = []
    threads = store.threads_for(user_id, status="nascent", limit=None)
    for thread in threads:
        if thread.origin != "steward_proposal":
            continue
        items.append(
            ReviewItem(
                item_id=_item_id("birth", thread.id),
                item_kind="birth",
                thread_id=thread.id,
                surface=SURFACE_BY_KIND["birth"],
                status=thread.status,
                title=thread.title,
                payload={
                    "scope": thread.scope,
                    "origin": thread.origin,
                    "strand_weights": thread.strand_weights or {},
                },
            )
        )
    # All threads (not just nascent): a live thread can carry new
    # proposed readings, changes, and fittings.
    for thread in store.threads_for(user_id, limit=None):
        for reading in store.readings_for(
            user_id, thread.id, status="proposed"
        ):
            if reading.author != "steward":
                continue
            items.append(
                ReviewItem(
                    item_id=_item_id("reading", reading.id),
                    item_kind="reading",
                    thread_id=thread.id,
                    surface=SURFACE_BY_KIND["reading"],
                    status=reading.status,
                    title=thread.title,
                    payload={
                        "reading": reading.reading or {},
                        "scales": reading.scales or [],
                        "evidence_refs": reading.evidence_refs or [],
                    },
                )
            )
        for change in store.changes_for(user_id, thread.id):
            if change.status != "proposed":
                continue
            items.append(
                ReviewItem(
                    item_id=_item_id("change", change.id),
                    item_kind="change",
                    thread_id=thread.id,
                    surface=SURFACE_BY_KIND["change"],
                    status=change.status,
                    title=thread.title,
                    payload={
                        "kind": change.kind,
                        "prior_reading_id": change.prior_reading_id,
                        "new_reading_id": change.new_reading_id,
                        "evidence_refs": change.evidence_refs or [],
                        # Phase 3: retirement basis travels with
                        # the proposal so the verdict surface shows
                        # WHY the story is proposed to end.
                        "reason": change.reason,
                        "successor_thread_id": change.successor_thread_id,
                        "absence_window_days": change.absence_window_days,
                        "absence_last_evidence_at": (
                            change.absence_last_evidence_at
                        ),
                    },
                )
            )
        for fitting in store.fittings_for(user_id, thread.id):
            if fitting.status not in ("proposed", "offered"):
                continue
            if fitting.proposed_by != "steward":
                continue
            items.append(
                ReviewItem(
                    item_id=_item_id("fitting", fitting.id),
                    item_kind="fitting",
                    thread_id=thread.id,
                    surface=SURFACE_BY_KIND["fitting"],
                    status=fitting.status,
                    title=thread.title,
                    payload={
                        "lens_id": fitting.lens_id,
                        "proposed_by": fitting.proposed_by,
                        "evidence_refs": fitting.evidence_refs or [],
                    },
                )
            )
        # Phase 6: schedule revisions in review. Only versions
        # with status "in_review" are pending: a merely proposed
        # version has not entered the review step yet, and the
        # submit gate (store.submit_artifact_version_for_review)
        # is what moves it here. Accepted, rejected, and
        # superseded versions are terminal history, never pending.
        for artifact in store.artifacts_for(user_id, thread_id=thread.id):
            for version in store.artifact_versions(
                user_id, artifact.id
            ):
                if version.status != "in_review":
                    continue
                items.append(
                    ReviewItem(
                        item_id=_item_id("revision", version.id),
                        item_kind="revision",
                        thread_id=thread.id,
                        surface=SURFACE_BY_KIND["revision"],
                        status=version.status,
                        title=artifact.title,
                        payload={
                            "artifact_id": artifact.id,
                            "version_no": version.version_no,
                            "content": dict(version.content),
                            "evidence_refs": version.evidence_refs or [],
                            "reading_ids": version.reading_ids or [],
                            "lens_id": version.lens_id,
                            "created_by": version.created_by,
                            "involvement": {
                                "user_authored_units": (
                                    version.user_authored_units
                                ),
                                "user_edited_units": (
                                    version.user_edited_units
                                ),
                                "synthesized_units": (
                                    version.synthesized_units
                                ),
                                "user_share": version.user_share,
                            },
                        },
                    )
                )
    # Phase 7: oversight proposals, correspondences, and
    # reconsiderations are review items through this same
    # enumeration — no parallel surface. Oversight items are
    # thread-scoped; correspondences cite threads (listed
    # under their first cited thread for display; the item
    # itself carries all cited threads); reconsiderations
    # are thread-scoped via their reading's thread.
    for proposal in store.oversight_proposals_for(
        user_id, status="proposed"
    ):
        thread = store.get_thread(user_id, proposal.thread_id)
        items.append(
            ReviewItem(
                item_id=_item_id("oversight", proposal.id),
                item_kind="oversight",
                thread_id=proposal.thread_id,
                surface=SURFACE_BY_KIND["oversight"],
                status=proposal.status,
                title=thread.title if thread else "",
                payload={
                    "kind": proposal.kind,
                    "reason": proposal.reason,
                    "detail": dict(proposal.detail or {}),
                },
            )
        )
    for corr in store.correspondences_for(user_id, status="proposed"):
        first_thread = corr.thread_ids[0] if corr.thread_ids else ""
        thread = (
            store.get_thread(user_id, first_thread)
            if first_thread
            else None
        )
        items.append(
            ReviewItem(
                item_id=_item_id("correspondence", corr.id),
                item_kind="correspondence",
                thread_id=first_thread,
                surface=SURFACE_BY_KIND["correspondence"],
                status=corr.status,
                title=thread.title if thread else "",
                payload={
                    "thread_ids": list(corr.thread_ids or []),
                    "evidence_refs": list(corr.evidence_refs or []),
                    "structural_tension": corr.structural_tension,
                    "proposed_relationship": corr.proposed_relationship,
                    "candidate_metaphor": corr.candidate_metaphor,
                    "mapping": dict(corr.mapping or {}),
                    "limitations": corr.limitations,
                },
            )
        )
    for item_row in store.reconsiderations_for(
        user_id, status="proposed"
    ):
        thread = store.get_thread(user_id, item_row.thread_id)
        items.append(
            ReviewItem(
                item_id=_item_id("reconsideration", item_row.id),
                item_kind="reconsideration",
                thread_id=item_row.thread_id,
                surface=SURFACE_BY_KIND["reconsideration"],
                status=item_row.status,
                title=thread.title if thread else "",
                payload={
                    "reading_id": item_row.reading_id,
                    "reason": item_row.reason,
                },
            )
        )
    return items


def _find_pending(
    store: NarrativeStore, user_id: str, kind: str, row_id: str
) -> ReviewItem:
    """Locate one pending item, or raise ValueError."""
    for item in pending_review_items(store, user_id):
        if item.item_kind == kind and item.item_id == _item_id(kind, row_id):
            return item
    raise ValueError(f"no pending review item: {kind}:{row_id}")


def apply_verdict(
    store: NarrativeStore, user_id: str, item_id: str, verdict: str
) -> ReviewItem:
    """Apply one verdict to one pending steward proposal.

    Order: transition first (proposal state is authoritative),
    verdict log second (audit trail). A log failure surfaces as
    an error and never silently reverts state; the client re-lists
    to see the new state. Unresolved validates the item is pending
    and records the verdict without transitioning anything —
    explicit not-deciding, first-class.
    """
    if verdict not in VERDICTS:
        raise ValueError(f"unknown review verdict: {verdict!r}")
    kind, row_id = _parse_item_id(item_id)
    item = _find_pending(store, user_id, kind, row_id)
    if verdict == "accepted":
        if kind == "birth":
            store.set_thread_status(user_id, row_id, "active")
        elif kind == "reading":
            store.accept_reading(user_id, row_id)
        elif kind == "change":
            store.set_change_status(user_id, row_id, "confirmed")
            # Phase 3: accepting a retirement retires the thread
            # itself (status "retired", reason + successor from
            # the proposal). A retired thread keeps its evidence
            # and readings, leaves fast-path context (standing =
            # active/dormant only), and is never quietly revived.
            # No retired change can predate Phase 3 (no caller
            # recorded one), so a missing reason is a data error
            # and surfaces loudly instead of defaulting.
            change = next(
                (
                    row
                    for row in store.changes_for(
                        user_id, item.thread_id
                    )
                    if row.id == row_id
                ),
                None,
            )
            if change is not None and change.kind == "retired":
                if change.reason is None:
                    raise ValueError(
                        "retired change without a reason cannot "
                        "retire its thread"
                    )
                store.set_thread_status(
                    user_id,
                    item.thread_id,
                    "retired",
                    retirement_reason=change.reason,
                    successor_thread_id=change.successor_thread_id,
                )
        elif kind == "fitting":
            store.set_fitting_status(user_id, row_id, "accepted")
        elif kind == "revision":
            store.accept_artifact_version(user_id, row_id)
        elif kind == "oversight":
            # Confirmed observation only: no thread, reading,
            # or branch state changes, by construction — the
            # store has no transition for it. Oversight never
            # commands.
            store.set_oversight_status(user_id, row_id, "confirmed")
        elif kind == "correspondence":
            # The user alone accepts: seat responses never
            # move this status (three-layer framing, §3).
            store.set_correspondence_status(
                user_id, row_id, "user_accepted"
            )
        elif kind == "reconsideration":
            # Affirmed candidacy: the reading stays accepted
            # and untouched; only the candidacy moves.
            store.set_reconsideration_status(
                user_id, row_id, "affirmed"
            )
    elif verdict == "rejected":
        if kind == "birth":
            store.set_thread_status(user_id, row_id, "archived")
        elif kind == "reading":
            store.reject_reading(user_id, row_id)
        elif kind == "change":
            store.set_change_status(user_id, row_id, "dismissed")
        elif kind == "fitting":
            store.set_fitting_status(user_id, row_id, "rejected")
        elif kind == "revision":
            store.reject_artifact_version(user_id, row_id)
        elif kind == "oversight":
            store.set_oversight_status(user_id, row_id, "dismissed")
        elif kind == "correspondence":
            store.set_correspondence_status(user_id, row_id, "rejected")
        elif kind == "reconsideration":
            store.set_reconsideration_status(
                user_id, row_id, "dismissed"
            )
    store.record_review_verdict(user_id, kind, row_id, verdict)
    if verdict == "unresolved":
        return item
    # Decided items leave the pending list, so report the terminal
    # state instead of pretending the item is still pending.
    if kind == "birth":
        thread = store.get_thread(user_id, row_id)
        status = thread.status if thread else "unknown"
    elif kind == "reading":
        status = "accepted" if verdict == "accepted" else "rejected"
    elif kind == "change":
        status = "confirmed" if verdict == "accepted" else "dismissed"
    elif kind == "revision":
        status = "accepted" if verdict == "accepted" else "rejected"
    elif kind == "oversight":
        status = "confirmed" if verdict == "accepted" else "dismissed"
    elif kind == "correspondence":
        status = "user_accepted" if verdict == "accepted" else "rejected"
    elif kind == "reconsideration":
        status = "affirmed" if verdict == "accepted" else "dismissed"
    else:
        status = "accepted" if verdict == "accepted" else "rejected"
    return ReviewItem(
        item_id=item.item_id,
        item_kind=kind,
        thread_id=item.thread_id,
        surface=item.surface,
        status=status,
        title=item.title,
        payload=item.payload,
    )
