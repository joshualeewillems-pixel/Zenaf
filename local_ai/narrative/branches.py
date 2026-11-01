"""Phase 1 branch contract + registry (addendum §2).

A branch is a conditioner and a view over shared steward state, not
a copy, not a fork, not a second store. The contract types below are
data, not behavior: they name what each branch may do (observation,
interpretation, coordination), what it is conditioned on, and
whether its branch status is confirmed, candidate, or undecided.
Nothing here wires a seat, generates text, or moves state — Phase 1
proves the contract with fixtures; seat integration is Phase 2.

Seat naming: branch ids use archetype ids (the stable code
vocabulary); display names are the character names, which unlock
seat by seat. The mapping is grounded in
``local_ai/conversation/encounter.py`` ``_SEAT_CHARACTER_NAMES``
(mentor=Gardener, champion=Firebrand, guardian=Bear, maverick=Fox,
ambassador=Crane, conductor=Weaver, skeptic=Raven).
"""

from __future__ import annotations

from dataclasses import dataclass

#: Capability vocabulary (addendum §2). Coordination is a
#: first-class capability: a contract with only observation and
#: interpretation is read-plus-emit-only, which FAILS Phase 1
#: acceptance. Any branch contracted for coordination is still
#: gated per preparation by consent + relevance (coordination.py);
#: the contract names the capability, it never pre-authorizes it.
CAPABILITIES: tuple[str, ...] = ("observation", "interpretation", "coordination")

#: Branch kinds. ``reading_surface`` entries are NOT branches: they
#: display branch and steward state and hold no narrative state of
#: their own (reconciled architecture §1).
BRANCH_KINDS: tuple[str, ...] = (
    "seat",
    "progression",
    "dramatization",
    "candidate",
    "reading_surface",
)

#: Registry statuses (base plan Phase 1 acceptance).
BRANCH_STATUSES: tuple[str, ...] = ("confirmed", "candidate", "undecided")

#: Display name per archetype id (encounter.py ground truth).
SEAT_DISPLAY_NAMES: dict[str, str] = {
    "mentor": "Gardener",
    "champion": "Firebrand",
    "guardian": "Bear",
    "maverick": "Fox",
    "ambassador": "Crane",
    "conductor": "Weaver",
    "skeptic": "Raven",
}


@dataclass(frozen=True)
class BranchContract:
    """One branch's contract with the steward layer.

    ``capabilities`` names what the branch is contracted for — not
    what is pre-authorized. Coordination capability is always
    exercised through per-preparation consent + relevance gates.
    ``tier_constraint`` records evidence-tier limits (journal is
    Tier-D only: its artifacts can never be cited as evidence).
    """

    branch_id: str
    display_name: str
    kind: str
    capabilities: tuple[str, ...]
    status: str
    conditioning_sources: tuple[str, ...]
    notes: str = ""
    tier_constraint: str | None = None
    #: Phase 7 decision recorded for this branch. Every registered
    #: branch carries one: confirmed branches record their
    #: confirmation; candidate branches record the Phase 7
    #: disposition (sibling / deferred / confirmed). An empty
    #: decision means the registry is INCOMPLETE — see
    #: :func:`registry_audit`, which refuses that state.
    decision: str = ""

    def __post_init__(self) -> None:
        if self.kind not in BRANCH_KINDS:
            raise ValueError(f"unknown branch kind: {self.kind!r}")
        if self.status not in BRANCH_STATUSES:
            raise ValueError(f"unknown branch status: {self.status!r}")
        for capability in self.capabilities:
            if capability not in CAPABILITIES:
                raise ValueError(f"unknown branch capability: {capability!r}")
        if self.kind == "reading_surface" and self.capabilities:
            raise ValueError(
                "a reading surface holds no narrative state and "
                f"contracts no capabilities: {self.branch_id!r}"
            )


def _seat_contract(archetype_id: str) -> BranchContract:
    return BranchContract(
        branch_id=f"seat:{archetype_id}",
        display_name=SEAT_DISPLAY_NAMES[archetype_id],
        kind="seat",
        capabilities=("observation", "interpretation", "coordination"),
        status="confirmed",
        conditioning_sources=(
            "local_ai/council/jurisdictions.py SeatJurisdiction "
            "(focus, periphery, conflicts, register)",
            "personal profile where the mirror applies",
        ),
        decision="Phase 7: confirmed branch — seat voice branch "
        "under the amended branch contract (addendum §2).",
    )


#: The seven seats — voice branches, all confirmed.
SEAT_BRANCHES: tuple[BranchContract, ...] = tuple(
    _seat_contract(archetype_id)
    for archetype_id in (
        "mentor",
        "champion",
        "guardian",
        "maverick",
        "ambassador",
        "conductor",
        "skeptic",
    )
)

VISION_EXECUTION_BRANCH = BranchContract(
    branch_id="vision_execution",
    display_name="Vision Execution",
    kind="progression",
    capabilities=("observation", "coordination"),
    status="confirmed",
    conditioning_sources=(
        "task/initiative completions",
        "commitment status flips (milestone/change evidence)",
    ),
    notes="Does not author narrative interpretations; its completions "
    "and flips are milestone/change evidence.",
    decision="Phase 7: confirmed branch — progression branch under "
    "the amended branch contract (addendum §2).",
)

JOURNAL_BRANCH = BranchContract(
    branch_id="journal",
    display_name="Journal",
    kind="dramatization",
    capabilities=("coordination",),
    status="confirmed",
    conditioning_sources=("thread state reads for framing",),
    notes="Reads thread state for framing only; its artifacts can "
    "never be cited as evidence.",
    tier_constraint="Tier-D only",
    decision="Phase 7: confirmed branch — dramatization branch, "
    "Tier-D only, under the amended branch contract (addendum §2).",
)

BUILD_COUNCIL_BRANCH = BranchContract(
    branch_id="build_council",
    display_name="Build Council",
    kind="candidate",
    capabilities=("observation", "interpretation"),
    status="candidate",
    conditioning_sources=(
        "record contract: declarations, exposure, standing, validation "
        "(self-contained)",
    ),
    notes="CANDIDATE branch, decision in Phase 7. Default: sibling "
    "record referenced by the steward, not subsumed. Coordination "
    "is NOT contracted until branch-read is proven safe against "
    "the record contract — its absence here is deliberate.",
    decision="Phase 7: SIBLING, not a branch (base plan §6.2 "
    "default, applied). The build-council record — declarations, "
    "exposure, standing, validation — is self-contained and is "
    "referenced by the steward, never subsumed: no steward code "
    "reads or writes build-council records, and branch-read "
    "safety against the record contract was not proven in this "
    "phase. Coordination stays uncontracted. Revisiting the "
    "decision requires a branch-read safety proof, not a "
    "registry edit alone.",
)

GARDEN_BRANCH = BranchContract(
    branch_id="garden",
    display_name="Garden",
    kind="candidate",
    capabilities=(),
    status="candidate",
    conditioning_sources=(),
    notes="CANDIDATE branch; its backend progression store was not "
    "located in the audit pass (only a frontend test reference was "
    "found). Phase 7 locates it or defers the branch explicitly. "
    "Do not invent a garden store before then.",
    decision="Phase 7: DEFERRED EXPLICITLY (base plan §6.4 "
    "default, applied). No backend garden progression store was "
    "located in the codebase (no Python module owns garden "
    "progression state); the branch is not activated and no "
    "store was invented for it. Activating it requires locating "
    "or building that store first.",
)

#: Every §1 branch (reading surfaces excluded).
BRANCHES: tuple[BranchContract, ...] = (
    *SEAT_BRANCHES,
    VISION_EXECUTION_BRANCH,
    JOURNAL_BRANCH,
    BUILD_COUNCIL_BRANCH,
    GARDEN_BRANCH,
)

#: Reading surfaces over branches — not branches themselves.
READING_SURFACES: tuple[BranchContract, ...] = (
    BranchContract(
        branch_id="today",
        display_name="Today",
        kind="reading_surface",
        capabilities=(),
        status="confirmed",
        conditioning_sources=(
            "branch state and steward state (display only)",
        ),
        notes="Holds no narrative state of its own.",
        decision="Phase 7: reading surface, not a branch — "
        "displays branch and steward state, holds none.",
    ),
    BranchContract(
        branch_id="review",
        display_name="Review",
        kind="reading_surface",
        capabilities=(),
        status="confirmed",
        conditioning_sources=(
            "branch state and steward state (display only)",
        ),
        notes="Holds no narrative state of its own.",
        decision="Phase 7: reading surface, not a branch — "
        "the verdict surface for steward proposals.",
    ),
)


def branch_registry() -> dict[str, BranchContract]:
    """All registered branches by id (reading surfaces excluded)."""
    return {contract.branch_id: contract for contract in BRANCHES}


def get_branch(branch_id: str) -> BranchContract | None:
    """One branch contract, or None for unknown ids."""
    return branch_registry().get(branch_id)


def coordination_capable_branches() -> list[BranchContract]:
    """Branches contracted for coordination (capability, not authorization)."""
    return [c for c in BRANCHES if "coordination" in c.capabilities]


#: Phase 7 conditioning audit: for each branch and each Phase 6
#: schedule step, the conditioner — whose conditioning governs
#: that step for that branch. This table is DATA, not behavior:
#: it names the same conditioners the implemented wiring already
#: enforces (schedule.py step docstrings), so the audit can be
#: spot-checked against code instead of asserted from prose.
#:
#: - draft: the thread's jurisdiction registry routes the draft
#:   (seats), or the branch's own progression evidence (vision
#:   execution). Journal never conditions evidence (Tier-D
#:   framing only); the sibling record and the deferred branch
#:   condition nothing.
#: - revision: approved evidence (Tier-E refs) + accepted readings,
#:   within the branch's jurisdiction where the branch has one.
#: - review: the user verdict, for every branch alike — authority
#:   resides with the user alone (addendum §0).
#: - artifact: the accepted version + involvement ledger, for
#:   branches that render artifacts; nothing for the rest.
_CONDITIONER_BY_STEP: dict[str, dict[str, str]] = {
    "seat": {
        "draft": "seat jurisdiction registry (SeatJurisdiction: "
        "focus, periphery, conflicts, register) + evidence gate",
        "revision": "approved evidence (Tier-E refs) + accepted "
        "readings, within the seat's jurisdiction",
        "review": "user verdict (review layer)",
        "artifact": "accepted version + involvement ledger",
    },
    "progression": {
        "draft": "task/initiative completions + commitment status "
        "flips (milestone/change evidence)",
        "revision": "approved evidence (Tier-E refs) + accepted readings",
        "review": "user verdict (review layer)",
        "artifact": "accepted version + involvement ledger",
    },
    "dramatization": {
        "draft": "none — Tier-D framing only; journal never "
        "conditions evidence",
        "revision": "none — Tier-D framing only; journal never "
        "conditions evidence",
        "review": "user verdict (review layer)",
        "artifact": "none — Tier-D dramatization surface only",
    },
}

#: Schedule steps (Phase 6), shared with schedule.SCHEDULE_STEPS
#: without importing it (branches.py must stay behavior-free).
AUDIT_SCHEDULE_STEPS: tuple[str, ...] = (
    "draft", "revision", "review", "artifact",
)


def conditioning_audit() -> list[dict]:
    """One row per branch per schedule step: its conditioner.

    Sibling and deferred branches condition nothing at any step —
    that absence is the recorded decision, not a gap. Reading
    surfaces are included with conditioner "none" and a note:
    they display state and hold none of their own.
    """
    rows: list[dict] = []
    for contract in (*BRANCHES, *READING_SURFACES):
        if contract.kind == "reading_surface":
            for step in AUDIT_SCHEDULE_STEPS:
                rows.append({
                    "branch_id": contract.branch_id,
                    "step": step,
                    "conditioner": "none — reading surface; displays "
                    "branch and steward state, holds none",
                    "decision": contract.decision,
                })
            continue
        if contract.branch_id == "build_council":
            for step in AUDIT_SCHEDULE_STEPS:
                rows.append({
                    "branch_id": contract.branch_id,
                    "step": step,
                    "conditioner": "none — sibling record; the "
                    "steward references it, never conditions it",
                    "decision": contract.decision,
                })
            continue
        if contract.branch_id == "garden":
            for step in AUDIT_SCHEDULE_STEPS:
                rows.append({
                    "branch_id": contract.branch_id,
                    "step": step,
                    "conditioner": "none — deferred branch; no "
                    "store, no conditioning",
                    "decision": contract.decision,
                })
            continue
        per_step = _CONDITIONER_BY_STEP[contract.kind]
        for step in AUDIT_SCHEDULE_STEPS:
            rows.append({
                "branch_id": contract.branch_id,
                "step": step,
                "conditioner": per_step[step],
                "decision": contract.decision,
            })
    return rows


def registry_audit() -> dict:
    """Registry completeness (Phase 7 acceptance): every branch
    registered with its conditioning contract and a recorded
    decision; every branch's conditioning sources named (or an
    explicit decision explaining their absence, as for garden).

    Returns the audit table plus a completeness verdict. An
    empty decision anywhere, or a confirmed branch with no
    conditioning sources, makes the registry INCOMPLETE — the
    function reports it instead of raising, so a test (or a
    future phase) can see exactly which branch is undecided.
    """
    entries: list[dict] = []
    incomplete: list[str] = []
    for contract in BRANCHES:
        entry = {
            "branch_id": contract.branch_id,
            "display_name": contract.display_name,
            "kind": contract.kind,
            "capabilities": list(contract.capabilities),
            "status": contract.status,
            "conditioning_sources": list(contract.conditioning_sources),
            "decision": contract.decision,
            "tier_constraint": contract.tier_constraint,
        }
        entries.append(entry)
        if not contract.decision:
            incomplete.append(
                f"{contract.branch_id}: no decision recorded"
            )
        if contract.status == "confirmed" and not contract.conditioning_sources:
            incomplete.append(
                f"{contract.branch_id}: confirmed but no "
                "conditioning sources named"
            )
    return {
        "complete": not incomplete,
        "incomplete_reasons": incomplete,
        "branches": entries,
        "reading_surfaces": [
            {
                "branch_id": c.branch_id,
                "display_name": c.display_name,
                "decision": c.decision,
            }
            for c in READING_SURFACES
        ],
        "conditioning_audit": conditioning_audit(),
    }
