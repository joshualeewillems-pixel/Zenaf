"""Diffusion schedule, literal (Phase 6, reconciled architecture §2).

Diffusion here is PROCESS architecture, not a model class: no
diffusion language model is imported, called, or swapped in
anywhere in this module. What is made literal is the schedule,
the global revision, and the visible resolution.

The schedule, as a reusable pass, over one steward artifact:

1. **Draft** — :func:`start_draft`: a low-resolution proposal,
   evidence-cited, landing as ``proposed``, never active. The
   Draft conditioner is enforced: at least one evidence citation
   is required (zero candidates means no draft), and citations
   must belong to the thread.
2. **Revision** — :func:`propose_revision`: slow-path refinement
   against the FULL current evidence/reading state (omitted
   citations default to the thread's current evidence + accepted
   readings). A rewrite replaces the draft wholesale — versions
   store complete content, never patches — and is itself only
   ``proposed``. Competing readings are preserved (the pass cites
   readings, never mutates them); contradictions are linked, not
   overwritten; accepted readings are never rewritten without a
   new reading proposal. Tier-E evidence is immutable here: the
   pass never writes evidence rows, so verbatim words can only
   be cited, never rewritten.
3. **Review** — :func:`submit_for_review` + the review layer
   (review.apply_verdict, item kind ``revision``): accept, reject
   (durably), or unresolved (explicit not-deciding, stays in
   review). A rejected version never silently reactivates, and
   unproposed alternatives are never stored (§6.7 default).
4. **Artifact** — :func:`render`: the accepted version rendered
   into a deliverable carrying its tier, lens, and involvement.
   Rendering is a pure read: with no accepted version there is
   nothing to render, so an unaccepted revision can never become
   standing state through this function.

Approval gates are load-bearing, not ceremonial: every transition
is enforced in the store (one-way version statuses), and every
gate refusal raises instead of advancing state.

Resolution rendering (:func:`resolution_for_thread`,
:func:`resolution_for_artifact`) carries the two I4 axes
separately — epistemic (approval, standing reading, fitted lens)
and developmental (thread status, change recency) — and never a
single "resolved" bit. Approval density is counts, never a
finished-ness score. Blend appears at most once, under
``provenance``, labeled "provenance: user-sourced vs base-model
fill — not resolution, not fidelity"; it is never resolution and
never fidelity (§2, §6.10 default).

First adopter: the narrative artifact path — steward readings
into artifact drafts. The build-council path is explicitly NOT
touched: it has its own interim/final validation schedule, and
nothing in this module reads or writes build-council records.
"""

from __future__ import annotations

from .models import ArtifactVersion, StewardArtifact
from .store import NarrativeStore

#: The four schedule steps, in order. A run's current step is
#: derived from version state (see :func:`step_of_artifact`),
#: never stored redundantly.
SCHEDULE_STEPS: tuple[str, ...] = ("draft", "revision", "review", "artifact")

#: Blend's only label, verbatim from the §6.10 default. Any display
#: that presents blend without this label, or as resolution, is a
#: mislabeling bug.
BLEND_LABEL = (
    "provenance: user-sourced vs base-model fill — "
    "not resolution, not fidelity"
)


# -- Schedule steps -----------------------------------------------------------


def start_draft(
    store: NarrativeStore,
    user_id: str,
    thread_id: str,
    *,
    title: str = "",
    content: dict | None = None,
    evidence_refs: list[str] | None = None,
    reading_ids: list[str] | None = None,
    lens_id: str | None = None,
    involvement: dict | None = None,
    created_by: str = "steward",
) -> tuple[StewardArtifact, ArtifactVersion]:
    """Schedule step 1 (Draft): artifact row + version 1, proposed.

    Conditioners: the thread's jurisdiction registry routes the
    draft (the thread's own cast/scope), and the deterministic
    prefilter is the evidence gate — at least one citation, all
    belonging to the thread, or the draft refuses to start.
    Nothing here generates prose: ``content`` is caller-supplied
    (a seat's existing generation, or fixture content in tests);
    the schedule is the gate/version/provenance machinery around
    it, not a prose generator.
    """
    return store.create_artifact(
        user_id,
        thread_id,
        title=title,
        content=content if content is not None else {},
        evidence_refs=evidence_refs or [],
        reading_ids=reading_ids or [],
        lens_id=lens_id,
        involvement=involvement,
        created_by=created_by,
    )


def propose_revision(
    store: NarrativeStore,
    user_id: str,
    artifact_id: str,
    *,
    content: dict | None = None,
    evidence_refs: list[str] | None = None,
    reading_ids: list[str] | None = None,
    lens_id: str | None = None,
    involvement: dict | None = None,
    created_by: str = "steward",
) -> ArtifactVersion:
    """Schedule step 2 (Revision): global rewrite, versioned, proposed.

    Conditioners: approved evidence (Tier-E refs) + accepted
    readings — omitted citations default to the thread's current
    evidence and accepted readings, so the rewrite reconsiders
    the whole constellation. The pass itself proposes; acceptance
    is a user verdict at step 3. A revision that auto-applied
    would be a fabrication machine, not a denoising step, and no
    path here applies one.
    """
    return store.propose_artifact_revision(
        user_id,
        artifact_id,
        content=content if content is not None else {},
        evidence_refs=evidence_refs,
        reading_ids=reading_ids,
        lens_id=lens_id,
        involvement=involvement,
        created_by=created_by,
    )


def submit_for_review(
    store: NarrativeStore, user_id: str, version_id: str
) -> ArtifactVersion:
    """Schedule step 3 entry: proposed → in_review, or a loud refusal.

    Only an in-review version is a pending review item; this gate
    is what makes a version verdictable. Submitting an already
    reviewed, rejected, or superseded version raises and changes
    nothing.
    """
    return store.submit_artifact_version_for_review(user_id, version_id)


def render(
    store: NarrativeStore, user_id: str, artifact_id: str
) -> dict | None:
    """Schedule step 4 (Artifact): the accepted version, or None.

    None is the honest answer before acceptance: there is no
    deliverable yet, only draft versions. Rendering never creates
    standing state — it reads the accepted version.
    """
    return store.render_artifact(user_id, artifact_id)


def propose_reconsideration(
    store: NarrativeStore,
    user_id: str,
    reading_id: str,
    reason: str = "",
):
    """State-revision pass entry (I3): candidate status for a
    previously accepted interpretation, through the schedule's
    proposal → offer → verdict discipline.

    This is the schedule's review step applied to state
    rather than to an artifact draft: the candidacy is a
    review item (kind ``reconsideration``); the reading row
    itself is never mutated — its status stays ``accepted``
    and its content and evidence_refs are byte-identical
    before and after. What the verdict decides is the
    candidacy (affirmed: open for revision; dismissed:
    stands as before). Reaffirm / revise / retire are the
    downstream outcomes: a new reading proposal that
    supersedes this one is the revise path; a retirement
    change is the retire path; an affirmed candidacy with
    no new proposal is, at close, the reaffirm path.
    """
    return store.propose_reading_reconsideration(
        user_id, reading_id, reason
    )


def thread_status_display(
    store: NarrativeStore,
    user_id: str,
    thread_id: str,
) -> dict:
    """A thread's status with BOTH I4 axes visible (Phase 7).

    Developmental axis: the thread's lifecycle status,
    retirement reason/successor, latest confirmed change.
    Epistemic axis: standing-reading presence + status,
    approval counts, fitted lens (the thread's ACCEPTED
    fitting only — never a lens canon pick, never a draft's
    claimed lens). Reconsideration candidacies on the
    thread's readings are listed separately: a candidate
    reading is still accepted, and the display must not
    confuse candidacy with revision.

    There is deliberately no ``resolved`` key anywhere in
    this dict: no single bit may conflate the axes, and
    approval density is counts, never a finished-ness score.
    """
    resolution = resolution_for_thread(store, user_id, thread_id)
    reconsiderations = [
        {
            "id": item.id,
            "reading_id": item.reading_id,
            "status": item.status,
            "reason": item.reason,
        }
        for item in store.reconsiderations_for(user_id)
        if item.thread_id == thread_id
    ]
    return {
        "thread_id": thread_id,
        "developmental": resolution["developmental"],
        "epistemic": resolution["epistemic"],
        "involvement": resolution["involvement"],
        "provenance": resolution["provenance"],
        "reconsiderations": reconsiderations,
    }


def step_of_artifact(
    store: NarrativeStore, user_id: str, artifact_id: str
) -> str:
    """A run's current schedule step, derived from version state."""
    status = store.artifact_status(user_id, artifact_id)
    if status == "rendered":
        return "artifact"
    if status == "in_review":
        return "review"
    versions = store.artifact_versions(user_id, artifact_id)
    if any(v.version_no > 1 for v in versions):
        return "revision"
    return "draft"


# -- Resolution rendering -----------------------------------------------------


def _count_by_status(rows: list, key: str = "status") -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        status = getattr(row, key, None) or row.to_dict().get(key)
        counts[str(status)] = counts.get(str(status), 0) + 1
    return counts


def _accepted_fitting(store: NarrativeStore, user_id: str, thread_id: str):
    fitted = [
        f
        for f in store.fittings_for(user_id, thread_id)
        if f.status == "accepted"
    ]
    if not fitted:
        return None
    fit = fitted[-1]
    return {
        "lens_id": fit.lens_id,
        "proposed_by": fit.proposed_by,
        "decided_at": fit.decided_at,
    }


def _provenance_blend(user_share: float | None) -> dict | None:
    """Blend, at most once, labeled, never as resolution.

    Returns None when unmeasured (no involvement) — an absent
    blend is honest; a zero or invented blend would not be.
    """
    if user_share is None:
        return None
    return {
        "blend": {
            "user_sourced": user_share,
            "base_model_fill": 1 - user_share,
            "label": BLEND_LABEL,
        }
    }


def resolution_for_thread(
    store: NarrativeStore, user_id: str, thread_id: str
) -> dict:
    """A thread's resolution state, both I4 axes, from store state.

    Epistemic axis: approval counts (never a finished-ness
    score), standing-reading presence + status, fitted lens +
    by whose proposal. Developmental axis: thread status,
    retirement reason/successor, latest confirmed change, last
    change clock. Involvement aggregates the thread's artifacts'
    ledger measures. Blend appears only under ``provenance``,
    labeled, or not at all. There is deliberately no ``resolved``
    key anywhere in this dict.
    """
    thread = store.get_thread(user_id, thread_id)
    if thread is None:
        raise ValueError(f"unknown thread: {thread_id!r}")
    readings = store.readings_for(user_id, thread_id)
    changes = store.changes_for(user_id, thread_id)
    confirmed = [c for c in changes if c.status == "confirmed"]
    latest = confirmed[-1] if confirmed else None
    standing = None
    if thread.standing_reading_id is not None:
        for reading in readings:
            if reading.id == thread.standing_reading_id:
                standing = {
                    "id": reading.id,
                    "status": reading.status,
                }
                break
        if standing is None:
            standing = {"id": thread.standing_reading_id, "status": "unknown"}
    artifacts = store.artifacts_for(user_id, thread_id=thread_id)
    revision_counts: dict[str, int] = {}
    authored = edited = synthesized = 0.0
    for artifact in artifacts:
        for version in store.artifact_versions(user_id, artifact.id):
            revision_counts[version.status] = (
                revision_counts.get(version.status, 0) + 1
            )
        measure = store.involvement_for(user_id, "artifact", artifact.id)
        if measure is not None:
            authored += measure.user_authored_units
            edited += measure.user_edited_units
            synthesized += measure.synthesized_units
    total = authored + edited + synthesized
    user_share = (authored + edited) / total if total > 0 else None
    return {
        "thread_id": thread.id,
        "title": thread.title,
        "epistemic": {
            "approval": {
                "readings": _count_by_status(readings),
                "changes": _count_by_status(changes),
                "fittings": _count_by_status(
                    store.fittings_for(user_id, thread_id)
                ),
                "revisions": revision_counts,
            },
            "standing_reading": standing,
            "lens": _accepted_fitting(store, user_id, thread_id),
        },
        "developmental": {
            "status": thread.status,
            "retirement_reason": thread.retirement_reason,
            "successor_thread_id": thread.successor_thread_id,
            "latest_confirmed_change": (
                {"kind": latest.kind, "created_at": latest.created_at}
                if latest is not None
                else None
            ),
            "last_change_at": thread.last_change_at,
        },
        "involvement": {
            "user_authored_units": authored,
            "user_edited_units": edited,
            "synthesized_units": synthesized,
            "user_share": user_share,
        },
        "provenance": _provenance_blend(user_share),
    }


def resolution_for_artifact(
    store: NarrativeStore, user_id: str, artifact_id: str
) -> dict:
    """One artifact's resolution state: step, approval, involvement, lens.

    The approval state is the current version's status (proposed /
    in_review / accepted / rejected / superseded) plus the latest
    verdict on the rendered version, when one exists. Involvement
    is the rendered version's split when rendered, else the
    latest version's. The lens is the thread's accepted fitting —
    a draft's claimed lens_id never counts as fitted. Blend only
    under ``provenance``, labeled, or absent when unmeasured.
    """
    artifact = store.get_artifact(user_id, artifact_id)
    if artifact is None:
        raise ValueError(f"unknown artifact: {artifact_id!r}")
    versions = store.artifact_versions(user_id, artifact_id)
    if not versions:
        raise ValueError(f"artifact has no versions: {artifact_id!r}")
    accepted = [v for v in versions if v.status == "accepted"]
    current = accepted[-1] if accepted else versions[-1]
    verdict = None
    for row in store.verdicts_for(user_id, item_kind="revision"):
        if row.item_id == current.id:
            verdict = row.verdict
    return {
        "artifact_id": artifact.id,
        "thread_id": artifact.thread_id,
        "title": artifact.title,
        "step": step_of_artifact(store, user_id, artifact_id),
        "version_no": current.version_no,
        "approval": {
            "version_status": current.status,
            "verdict": verdict,
        },
        "involvement": {
            "user_authored_units": current.user_authored_units,
            "user_edited_units": current.user_edited_units,
            "synthesized_units": current.synthesized_units,
            "user_share": current.user_share,
        },
        "lens": _accepted_fitting(store, user_id, artifact.thread_id),
        "draft_lens_id": current.lens_id,
        "provenance": _provenance_blend(current.user_share),
    }
