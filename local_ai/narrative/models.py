"""Narrative state records (Narrative Steward S0).

Dataclasses for the Steward's store, following the fellowship
observations.py shape: frozen records, ``to_dict()`` for the wire,
storage concerns in store.py. The schema is audit Part II §2 **as
amended by Part IX** (Joshua, 2026-10-23 ~22:17 PT — ratified),
which supersedes wherever the two differ:

  * Scale and progression are distinct dimensions, and neither is a
    rigid, singular property of a thread.
  * A thread carries an OPTIONAL ``scope`` (nullable) — a broad
    situational label, nothing more.
  * A reading carries MULTIPLE interpretive scales (``scales``) plus
    a nullable ``primary_scale``. Scales are free labels, not rungs
    of a fixed hierarchy: the same experience may hold meaningful
    readings at several scales, and the store preserves that instead
    of resolving it.
  * A progression position is bound to a PARTICULAR lens (its phases
    are that lens's template) and may be ``unknown`` or
    ``inapplicable`` — both are first-class stored states, not
    missing data.
  * There is NO fixed scale hierarchy, no mandatory stage
    progression, no traversal anywhere in this package: these are
    records and their validation, not a map anyone must walk.

The involvement measure (Part VII) is likewise a record only: how
much of an artifact or a trained profile is the user's own authored
or edited work versus Zenaf-synthesized, stored so attribution and
incentive accounting can ever be honest. S0 stores the measure; it
computes nothing from it and shows it nowhere.

Part X (Joshua, 2026-10-23 ~22:32 PT — ratified) adds the recursive
structure: "progression is Mandelbrot at all scales." A life arc
contains smaller arcs, which contain smaller arcs, down to moments;
each arc has its own progression, and each may participate in
several larger arcs. So alongside the lens-bound reading positions
above, the schema carries:

  * **arc associations** — many-to-many links between threads
    (ThreadLink): a thread may nest inside several larger threads
    and contain several smaller ones. Optional, inert, unconsumed
    by any logic — no traversal, no recursion, no cycle machinery.
  * **a thread-local progression position** (nullable): the
    thread's own development at its own resolution, in the same
    lens-bound shape as a reading's. It coexists with readings'
    positions; neither replaces the other.

Scale remains what Part IX made it: the resolution at which an arc
is examined (thread ``scope`` + readings' ``scales``). Progression
is development at that resolution. Neither forces a universal
sequence — the fractal mathematics, if they ever come, are a later
phase's problem; S0's duty is a schema that will not prevent them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

#: Thread lifecycle (audit Part II §2). ``retired`` is the Continuity
#: domain's first-class ending — the story stopped fitting — kept
#: distinct from ``resolved`` (an ending inside the story).
THREAD_STATUSES: tuple[str, ...] = (
    "nascent", "active", "dormant", "resolved", "retired", "archived",
)

#: Mandatory reason when a thread is retired (audit Part II §5).
RETIREMENT_REASONS: tuple[str, ...] = (
    "completed", "abandoned", "outgrown", "reinterpreted",
)

#: Where a thread came from (audit Part II §2).
THREAD_ORIGINS: tuple[str, ...] = (
    "user_declared", "claim", "journal", "initiative", "steward_proposal",
)

#: Reading lifecycle: proposed readings become standing only by
#: acceptance; an accepted reading displaced by a newer accepted one
#: is superseded, never edited or deleted (both persist — doctrine
#: §6, disagreements preserved).
READING_STATUSES: tuple[str, ...] = (
    "proposed", "accepted", "superseded", "rejected",
)

#: "The story moved" vocabulary (audit Part II §2).
CHANGE_KINDS: tuple[str, ...] = (
    "opened", "extended", "contradicted", "milestone",
    "reopened", "resolved", "retired",
)

#: Change lifecycle: changes are proposals until the user confirms.
CHANGE_STATUSES: tuple[str, ...] = ("proposed", "confirmed", "dismissed")

#: Fitting lifecycle (audit Part II §4): a lens is proposed, offered,
#: and only ever *accepted* by user verdict; rejection is durable.
FITTING_STATUSES: tuple[str, ...] = (
    "proposed", "offered", "accepted", "rejected", "retired",
)

#: Who may propose a fitting (audit Part II §4: the steward, or the
#: user themselves — "read my year as a descent-and-return").
FITTING_PROPOSERS: tuple[str, ...] = ("steward", "user")

#: Involvement ledger subjects (Part VII §4): per artifact, per
#: trained profile.
INVOLVEMENT_SUBJECT_KINDS: tuple[str, ...] = ("artifact", "trained_profile")

#: The three states of a progression position (Part IX): a position
#: within a lens's phases, honestly unknown, or honestly
#: inapplicable — a lens (or progression itself) may simply not
#: apply to a reading.
PROGRESSION_STATES: tuple[str, ...] = ("positioned", "unknown", "inapplicable")

#: Arc association kinds (Part X). A link row is stored once, in
#: parent -> child direction; the SAME row is the child's "part_of"
#: view — direction carries the inverse, so the vocabulary needs
#: only the one kind today. The column exists so a later phase can
#: add kinds without a schema change; S0 defines no others.
THREAD_LINK_RELATIONS: tuple[str, ...] = ("contains",)

#: Observable kinds (steward increment C). An observable is a FACT
#: about recorded rows — never an interpretation, never a verdict:
#: it carries no status field, no author field, and no delivery
#: fields. Judgments are deferred with increment C's narrowed scope
#: (no judgment rows exist in C); when they return they are
#: ThreadReadings with author="steward" and a judgment_kind label,
#: not observables.
OBSERVABLE_KINDS: tuple[str, ...] = (
    "impression_unanswered",
    "correction_no_subsequent_activity",
    "thread_quiet",
    "divergent_reading_positions",
)


@dataclass(frozen=True)
class ProgressionPosition:
    """Where a reading sits inside one lens's progression template.

    Bound to a PARTICULAR lens: ``lens_id`` + ``phase`` are
    meaningful only together (the phase is a phase OF that lens),
    and only when ``state == "positioned"``. ``unknown`` (the
    reading takes no position yet) and ``inapplicable`` (progression
    under this lens does not apply to this material) are distinct,
    deliberate states — Part IX requires both to be representable,
    because collapsing them into null would let a later consumer
    mistake "does not apply" for "not yet assessed," and quietly
    assess it.
    """

    state: str = "unknown"
    lens_id: str | None = None
    phase: str | None = None

    @classmethod
    def unknown(cls) -> "ProgressionPosition":
        return cls(state="unknown")

    @classmethod
    def inapplicable(cls) -> "ProgressionPosition":
        return cls(state="inapplicable")

    @classmethod
    def positioned(cls, lens_id: str, phase: str) -> "ProgressionPosition":
        return cls(state="positioned", lens_id=lens_id, phase=phase)

    def to_dict(self) -> dict[str, Any]:
        return {"state": self.state, "lens_id": self.lens_id, "phase": self.phase}

    @classmethod
    def from_dict(cls, data: dict | None) -> "ProgressionPosition":
        if not data:
            return cls.unknown()
        return cls(
            state=str(data.get("state") or "unknown"),
            lens_id=data.get("lens_id"),
            phase=data.get("phase"),
        )


@dataclass(frozen=True)
class NarrativeThread:
    """One ongoing story the system keeps WITH the user, not about them.

    State only — facts, tensions, questions live on readings; the
    thread itself carries identity, lifecycle, and pointers. ``scope``
    is Part IX's optional broad label (e.g. "work", "family"): it may
    be absent, and nothing in the store treats it as a category the
    thread must obey. ``progression`` is Part X's thread-LOCAL
    progression position — this arc's own development at its own
    resolution, in the same lens-bound shape as a reading's. It is
    nullable (no local progression recorded is a normal state) and
    coexists with readings' positions: a reading's position says
    where an interpretation sits inside its lens; the thread's says
    where the arc itself stands. Neither replaces the other.
    """

    id: str
    user_id: str
    title: str = ""
    status: str = "nascent"
    retirement_reason: str | None = None
    successor_thread_id: str | None = None
    scope: str | None = None
    progression: ProgressionPosition | None = None
    strand_weights: dict[str, float] | None = None
    cast: list[dict[str, Any]] | None = None
    aspiration_refs: list[str] | None = None
    standing_reading_id: str | None = None
    lens_fitting_id: str | None = None
    origin: str = "user_declared"
    created_at: str = ""
    updated_at: str = ""
    last_change_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "user_id": self.user_id,
            "title": self.title,
            "status": self.status,
            "retirement_reason": self.retirement_reason,
            "successor_thread_id": self.successor_thread_id,
            "scope": self.scope,
            "progression": (
                self.progression.to_dict() if self.progression else None
            ),
            "strand_weights": self.strand_weights or {},
            "cast": self.cast or [],
            "aspiration_refs": self.aspiration_refs or [],
            "standing_reading_id": self.standing_reading_id,
            "lens_fitting_id": self.lens_fitting_id,
            "origin": self.origin,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "last_change_at": self.last_change_at,
        }


@dataclass(frozen=True)
class ThreadLink:
    """One arc association between two threads (Part X).

    Recursive narrative structure, stored flat: a link says the
    parent arc CONTAINS the child arc. The relation is many-to-many
    — a child may appear under several parents (it participates in
    several larger arcs) and a parent may contain many children —
    never a single-parent tree. Read from the child's side, the same
    row is its ``part_of`` view; direction carries the inverse, so
    only the one relation kind is stored.

    Links are optional and INERT in S0: nothing traverses them, no
    logic consumes them, and there is deliberately no cycle
    detection (the store refuses only the degenerate self-link).
    They exist so the schema will not prevent the recursive
    analysis a later phase may want.
    """

    id: str
    user_id: str
    parent_thread_id: str
    child_thread_id: str
    relation: str = "contains"
    note: str = ""
    created_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "user_id": self.user_id,
            "parent_thread_id": self.parent_thread_id,
            "child_thread_id": self.child_thread_id,
            "relation": self.relation,
            "note": self.note,
            "created_at": self.created_at,
        }


@dataclass(frozen=True)
class ThreadEvidence:
    """One evidence-tier record attached to a thread.

    Rows of this table are the ONLY things readings, changes, and
    fittings may cite: the store creates them exclusively through the
    tier-checked attach path (refs.require_evidence_tier), so a
    dramatization or an interpretation can never exist as a row here.
    ``note`` says why this evidence belongs to the thread — proposal
    text or the user's own note.
    """

    id: str
    thread_id: str
    ref_kind: str
    ref_id: str
    evidence_kind: str = "entity_ref"
    note: str = ""
    created_at: str = ""
    #: The "<type>:<id>" identity of the thing this record is about,
    #: when known (S1 derivation maintains it for evidence it
    #: attaches; rows from other writers carry NULL — honest
    #: unknown, never inferred). It is a derivation index, not a
    #: second identity: the row's identity stays (ref_kind, ref_id).
    entity_ref: str | None = None

    @property
    def key(self) -> tuple[str, str]:
        """Identity for dedupe / newness checks: same record, once."""
        return (self.ref_kind, self.ref_id)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "thread_id": self.thread_id,
            "ref_kind": self.ref_kind,
            "ref_id": self.ref_id,
            "evidence_kind": self.evidence_kind,
            "note": self.note,
            "created_at": self.created_at,
            "entity_ref": self.entity_ref,
        }


@dataclass(frozen=True)
class ThreadReading:
    """One attributable interpretation of a thread — versioned, never edited.

    ``reading`` is structured state, not prose: tensions, open
    questions, milestones, per-seat cast notes. ``scales`` +
    ``primary_scale`` and ``progression`` are Part IX's two distinct
    dimensions, stored per reading (interpretations sit at scales;
    threads as such do not). ``evidence_refs`` are thread_evidence
    row ids — REQUIRED non-empty, enforced by the store (audit
    invariant 1).
    """

    id: str
    thread_id: str
    author: str  # a seat id | "steward" | "user"
    reading: dict[str, Any] = field(default_factory=dict)
    scales: list[str] | None = None
    primary_scale: str | None = None
    progression: ProgressionPosition = field(
        default_factory=ProgressionPosition.unknown
    )
    evidence_refs: list[str] | None = None
    status: str = "proposed"
    created_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "thread_id": self.thread_id,
            "author": self.author,
            "reading": self.reading or {},
            "scales": self.scales or [],
            "primary_scale": self.primary_scale,
            "progression": self.progression.to_dict(),
            "evidence_refs": self.evidence_refs or [],
            "status": self.status,
            "created_at": self.created_at,
        }


@dataclass(frozen=True)
class ThreadChange:
    """One recognized movement in a thread's story.

    ``evidence_refs`` are thread_evidence row ids, and the store
    guarantees at least one of them was NEW to the thread when the
    change was recorded (audit invariant 2 — the anti-manufacture
    rule: the story may only be said to have moved when new evidence
    actually arrived).
    """

    id: str
    thread_id: str
    kind: str
    evidence_refs: list[str] | None = None
    prior_reading_id: str | None = None
    new_reading_id: str | None = None
    status: str = "proposed"
    created_at: str = ""
    #: Retirement reason, mandatory when kind == "retired" (Phase 3):
    #: one of RETIREMENT_REASONS. None for non-retirement changes.
    reason: str | None = None
    #: Successor thread id, mandatory when reason == "reinterpreted".
    #: The old thread's readings are preserved, never moved.
    successor_thread_id: str | None = None
    #: Outgrown-absence basis (Phase 3): the decay window in days
    #: over which no new evidence arrived. Only for
    #: retired/outgrown proposals, which cite a verified absence
    #: instead of new evidence (see store.record_change).
    absence_window_days: int | None = None
    #: Timestamp of the thread's most recent evidence row at the
    #: time the outgrown proposal was recorded. None otherwise.
    absence_last_evidence_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "thread_id": self.thread_id,
            "kind": self.kind,
            "evidence_refs": self.evidence_refs or [],
            "prior_reading_id": self.prior_reading_id,
            "new_reading_id": self.new_reading_id,
            "status": self.status,
            "created_at": self.created_at,
            "reason": self.reason,
            "successor_thread_id": self.successor_thread_id,
            "absence_window_days": self.absence_window_days,
            "absence_last_evidence_at": self.absence_last_evidence_at,
        }


@dataclass(frozen=True)
class LensFitting:
    """One lens proposed / offered / accepted / rejected for one thread.

    ``evidence_refs`` (thread_evidence row ids) are required — a
    fitting proposal must cite the evidence that suggested it
    (audit Part II §4). ``decided_at`` is set when the user accepts
    or rejects; rejection is durable data, not an obstacle the
    steward routes around.
    """

    id: str
    thread_id: str
    lens_id: str
    status: str = "proposed"
    evidence_refs: list[str] | None = None
    proposed_by: str = "steward"
    created_at: str = ""
    decided_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "thread_id": self.thread_id,
            "lens_id": self.lens_id,
            "status": self.status,
            "evidence_refs": self.evidence_refs or [],
            "proposed_by": self.proposed_by,
            "created_at": self.created_at,
            "decided_at": self.decided_at,
        }


@dataclass(frozen=True)
class InvolvementMeasure:
    """The involvement ledger record for one artifact or profile (Part VII §4).

    Units are deliberately uninterpreted counts (words, sentences,
    claims — the recording surface decides and says so in ``note``);
    what matters for attribution and incentive accounting is that
    authored, edited, and synthesized contributions are kept in
    separate columns from the first day, so no later phase has to
    reconstruct provenance it failed to store. S0 stores only.
    """

    id: str
    user_id: str
    subject_kind: str  # "artifact" | "trained_profile"
    subject_id: str
    user_authored_units: float = 0.0
    user_edited_units: float = 0.0
    synthesized_units: float = 0.0
    note: str = ""
    created_at: str = ""
    updated_at: str = ""

    @property
    def total_units(self) -> float:
        return (
            self.user_authored_units
            + self.user_edited_units
            + self.synthesized_units
        )

    @property
    def user_share(self) -> float | None:
        """The user's fraction of the whole — None when unmeasured.

        Edits count as the user's: an edit is authorship and
        correction in one act (Part VII §1).
        """
        total = self.total_units
        if total <= 0:
            return None
        return (self.user_authored_units + self.user_edited_units) / total

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "user_id": self.user_id,
            "subject_kind": self.subject_kind,
            "subject_id": self.subject_id,
            "user_authored_units": self.user_authored_units,
            "user_edited_units": self.user_edited_units,
            "synthesized_units": self.synthesized_units,
            "user_share": self.user_share,
            "note": self.note,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


#: What a dismissal dismissal-memory row can dismiss (S1, audit
#: Part II §5 birth durability + Part IV test S1-5): a proposed
#: thread birth, or a proposed extension (reading update + change)
#: for one thread. The signature is content-addressed (sorted
#: evidence keys, plus the thread id for extensions), so new
#: evidence produces a new signature and may be proposed again,
#: while the same evidence is never re-proposed after dismissal.
#: Increment B adds the offer kinds: for those rows the signature
#: column holds a semantic scoped key (inv:/subj:/class: grammar,
#: proposal §4), not a content signature — a declined offer, subject,
#: or class, not a declined evidence cluster. The two regimes are
#: consulted and cleared independently (proposal §5.4).
DISMISSAL_KINDS: tuple[str, ...] = (
    "thread_birth",
    "extension",
    "offer_invitation",
    "offer_subject",
    "offer_class",
)


@dataclass(frozen=True)
class StewardDismissal:
    """One remembered dismissal of a steward proposal (S1).

    Dismissal memory is what makes "decline" durable: derivation
    consults these rows before proposing, so a dismissed cluster is
    not re-proposed when the same evidence is re-analyzed. The row
    records the user's act, not a judgment about the evidence — a
    dismissal never deletes the thread, reading, or change it
    dismissed; those rows keep their own lifecycles.
    """

    id: str
    user_id: str
    kind: str  # one of DISMISSAL_KINDS
    signature: str
    created_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "user_id": self.user_id,
            "kind": self.kind,
            "signature": self.signature,
            "created_at": self.created_at,
        }


@dataclass(frozen=True)
class StewardObservable:
    """One steward observation: a FACT about recorded rows (C).

    Deliberately NOT a reading: no status (a fact is true or it
    is not — there is nothing to rule on), no author (facts have
    no author), no delivery fields (nothing here means delivered,
    seen, or invited). ``thread_id`` is NULL for meeting-scoped
    observations (O1), which carry their meeting identity in
    ``detail``. ``signal_key`` is the recompute identity: the
    natural key (scope + kind + identity fields) materialized so
    an upsert can preserve ``first_seen_at`` across passes.
    ``evidence_refs`` is non-empty by construction: thread_evidence
    row ids for thread-scoped rows; for O1 the meeting key (+ the
    filed claim id when one exists); for O3 the thread id itself
    (the thread row's clock IS the fact quiet observes — a thread
    with no evidence rows at all is still quiet by the rule).
    """

    id: str
    user_id: str
    thread_id: str | None
    kind: str  # one of OBSERVABLE_KINDS
    signal_key: str
    evidence_refs: list[str] = field(default_factory=list)
    detail: dict[str, Any] = field(default_factory=dict)
    first_seen_at: str = ""
    last_seen_at: str = ""
    created_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "user_id": self.user_id,
            "thread_id": self.thread_id,
            "kind": self.kind,
            "signal_key": self.signal_key,
            "evidence_refs": list(self.evidence_refs),
            "detail": dict(self.detail),
            "first_seen_at": self.first_seen_at,
            "last_seen_at": self.last_seen_at,
            "created_at": self.created_at,
        }


# -- Phase 1 (review wiring + branch contract) --------------------------------
# Additive records only. These rows are append-only by construction:
# assessments are never updated (a fresh assessment supersedes by
# recency, it does not rewrite history), flags never adjudicate
# themselves, and verdicts are a log, not a mutable status. The
# underlying proposal rows keep their own lifecycles in store.py.


@dataclass(frozen=True)
class RelevanceAssessment:
    """One deterministic relevance assessment (addendum I2).

    Records the inputs a coordination decision actually used, so the
    decision is inspectable after the fact: which branch, which
    thread/evidence, which rules fired, and the exact inputs they
    read. ``relevant`` is the decision; ``reasons`` names the rules
    that fired; ``inputs`` is the snapshot those rules read.
    """

    id: str
    user_id: str
    branch_id: str
    thread_id: str | None = None
    evidence_refs: list[str] | None = None
    relevant: bool = False
    reasons: list[str] | None = None
    inputs: dict[str, Any] | None = None
    created_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "user_id": self.user_id,
            "branch_id": self.branch_id,
            "thread_id": self.thread_id,
            "evidence_refs": self.evidence_refs or [],
            "relevant": self.relevant,
            "reasons": self.reasons or [],
            "inputs": self.inputs or {},
            "created_at": self.created_at,
        }


@dataclass(frozen=True)
class DiscrepancyFlag:
    """One flag-only discrepancy objection (addendum I5, §7(a)).

    A branch's inspectable objection to a steward relevance
    assessment. The flag preserves the assessment id (the original
    assessment row is append-only and never rewritten), the
    objecting branch, the objection text, and supporting evidence
    references. It changes no shared evidence, triggers no model
    generation, and initiates no adjudication: ``status`` stays
    ``open`` because there is no workflow that closes it in
    Phase 1 — a flag is an observation to preserve, not a ticket
    to resolve. Declining context is NOT a flag and creates no row.
    """

    id: str
    user_id: str
    assessment_id: str
    branch_id: str
    objection: str = ""
    evidence_refs: list[str] | None = None
    status: str = "open"
    created_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "user_id": self.user_id,
            "assessment_id": self.assessment_id,
            "branch_id": self.branch_id,
            "objection": self.objection,
            "evidence_refs": self.evidence_refs or [],
            "status": self.status,
            "created_at": self.created_at,
        }


@dataclass(frozen=True)
class ReviewVerdict:
    """One recorded review verdict (addendum §4.1).

    The audit trail for steward-proposal verdicts: which review
    item, which verdict, when. ``verdict`` is one of ``accepted``,
    ``rejected``, ``unresolved`` — the claim-verdict discipline's
    vocabulary, where unresolved is an explicit not-deciding,
    recorded rather than silently skipped. The verdict log is the
    source for the proposal-precision metric: precision counts
    review-layer verdicts only, never flags, disagreements, or
    cross-branch agreement, so it cannot reward convergence.
    """

    id: str
    user_id: str
    item_kind: str  # birth | reading | change | fitting | revision
    item_id: str
    verdict: str  # accepted | rejected | unresolved
    created_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "user_id": self.user_id,
            "item_kind": self.item_kind,
            "item_id": self.item_id,
            "verdict": self.verdict,
            "created_at": self.created_at,
        }


# -- Phase 6 (diffusion schedule, literal) ---------------------------------
# The schedule's records. Versions are append-only by construction:
# a rewrite inserts a new version row; no version row is ever
# updated, so every predecessor stays retrievable. A rejected
# version keeps its row with status "rejected" (durable rejection,
# §2 schedule) — the §6.7 default (do not record rejected OPTIONS)
# governs unproposed alternatives, which are never stored at all:
# each revision act records exactly one proposed version.


#: Artifact version lifecycle. One-way forward, enforced by the
#: store: proposed → in_review → accepted | rejected; accepted →
#: superseded (only by a later acceptance). No backward moves, no
#: resurrection of a rejected or superseded version.
ARTIFACT_VERSION_STATUSES: tuple[str, ...] = (
    "proposed",
    "in_review",
    "accepted",
    "rejected",
    "superseded",
)


@dataclass(frozen=True)
class StewardArtifact:
    """One steward-mediated artifact: a thread's accepted state
    rendered into a deliverable, via the §2 schedule.

    The artifact row itself carries identity only — title, thread,
    timestamps. Its CONTENT lives on versions: before any version
    is accepted there is no artifact content, only draft versions
    (proposed / in_review); after acceptance the accepted version
    is the deliverable. Status is derived from versions, never
    stored redundantly: "rendered" iff an accepted version exists,
    else "in_review" iff a version is in review, else "drafting".
    """

    id: str
    user_id: str
    thread_id: str
    title: str = ""
    created_at: str = ""
    updated_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "user_id": self.user_id,
            "thread_id": self.thread_id,
            "title": self.title,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


@dataclass(frozen=True)
class ArtifactVersion:
    """One version of a steward artifact — a WHOLE draft, never a patch.

    ``content`` is the complete draft at this version (telling,
    structure, whatever the caller renders); a rewrite replaces it
    wholesale, it never diffs against its predecessor. ``evidence_refs``
    are thread_evidence row ids the version cites — citations, never
    embedded evidence text: the pass never writes evidence rows, so
    Tier-E records are immutable by construction. ``reading_ids``
    are thread reading ids the version draws on; citing an accepted
    reading never mutates it — a change to accepted state goes
    through a new reading proposal, not through this row.
    Involvement is recorded per version, in the ledger's separate
    columns, so each rewrite's user vs synthesized split is
    assertable from the row itself.
    """

    id: str
    artifact_id: str
    user_id: str
    version_no: int
    content: dict[str, Any] = field(default_factory=dict)
    evidence_refs: list[str] | None = None
    reading_ids: list[str] | None = None
    lens_id: str | None = None
    status: str = "proposed"
    user_authored_units: float = 0.0
    user_edited_units: float = 0.0
    synthesized_units: float = 0.0
    created_by: str = "steward"
    created_at: str = ""

    @property
    def total_units(self) -> float:
        return (
            self.user_authored_units
            + self.user_edited_units
            + self.synthesized_units
        )

    @property
    def user_share(self) -> float | None:
        """The user's fraction of this version — None when unmeasured."""
        total = self.total_units
        if total <= 0:
            return None
        return (self.user_authored_units + self.user_edited_units) / total

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "artifact_id": self.artifact_id,
            "user_id": self.user_id,
            "version_no": self.version_no,
            "content": dict(self.content or {}),
            "evidence_refs": list(self.evidence_refs or []),
            "reading_ids": list(self.reading_ids or []),
            "lens_id": self.lens_id,
            "status": self.status,
            "user_authored_units": self.user_authored_units,
            "user_edited_units": self.user_edited_units,
            "synthesized_units": self.synthesized_units,
            "user_share": self.user_share,
            "created_by": self.created_by,
            "created_at": self.created_at,
        }
