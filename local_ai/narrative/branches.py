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
