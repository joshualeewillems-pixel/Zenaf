"""Standing-permission capability registry (Slice 1, foundation).

This module is the permission framework's definition table, in the
``KNOWN_SCOPES`` pattern (``local_ai/identity/scopes.py``): capability
definitions live here as code; per-user stances live in the extended
permissions store (``local_ai/permissions/store.py``). Nothing in this
module reads a user row, touches the scope ledger, or calls a model —
it is definitions only, so the framework check stays a lookup.

Governing design: Rev2 (2026-11-04) as corrected by C1–C4, the
implementation clarification, the circle amendment, and the circle
corrections addendum. Architecture closed 2026-11-04; Slice 1 builds
only the foundation (registry + stance store + framework check +
flag migration).

R8 registration rule (Rev2 §2.7, normative): any future subsystem
that requests permission to observe, remember, interpret, or act MUST
register before it asks anything. Registration means: a capability
id; a covers statement in plain words; scope rows with reasons;
boundary neighbors (what it never authorizes); supported stances
(all three, or Just-do-it/Don't-do-it only where the output is
itself an ask, with that reason stated); a default stance with
justification; and exception membership. Registration is a DESIGN
ARTIFACT reviewed like any other design — not a runtime
self-declaration. There is deliberately NO ``register_capability()``
API: adding a capability means editing this module under review.
An unregistered capability fails closed at the framework check
(``framework.framework_check``, step 1): no asking, no capture, no
action.

R7 is RETIRED as a registry id (corrections C3): strand noting is a
scope-specific PRESENTATION of R1, not a second authority. R7 must
never be reused for another capability, and no entry here may claim
it. ``validate_registry()`` enforces that, and runs at import.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType

# --- Stances (Rev2 §1.4, systemwide names) --------------------------------

ASK_ME = "ask_me"
JUST_DO_IT = "just_do_it"
DONT_DO_IT = "dont_do_it"

STANCES = (ASK_ME, JUST_DO_IT, DONT_DO_IT)

#: Restrictiveness order for the most-restrictive join across scope
#: rows of ONE capability (Rev2 §2.1): a permissive row never
#: overrides a restrictive row. Unknown stance strings join as the
#: most restrictive value (fail closed); see framework.join.
_RESTRICTIVENESS = {DONT_DO_IT: 3, ASK_ME: 2, JUST_DO_IT: 1}

# --- C1.6: classes that NO contract may cover ------------------------------
# A consequential instance in one of these classes always requires
# per-transaction confirmation with its justification shown, even
# under Just do it (corrections C1.6, framework-check step 4 as
# amended by C1.8). Contract enforcement itself lands in Slice 6;
# Slice 1 lands the step-4 shape (see framework.AuthorizationContract).

NEVER_COVERABLE_CLASSES = (
    "new_third_party_grant",  # each new counterparty / access surface
    "unbounded_spend",  # any spend without an explicit amount cap + period
    "destructive_outside_policy",  # deletion/erasure outside a predefined policy
    "identity_changing_publication",  # a new profile version / identity statement
)

# --- Retired ids ------------------------------------------------------------

#: Registry ids that are retired and must never be reused (C3).
RETIRED_CAPABILITY_IDS = frozenset({"R7"})


@dataclass(frozen=True)
class ScopeRow:
    """One scope row of a capability: the unit a stance attaches to."""

    key: str
    label: str
    # kind: "strand" | "source" | "single" | "per_seat" | "per_commitment"
    kind: str


@dataclass(frozen=True)
class CapabilityEntry:
    """One registry entry. Complete only when every field is stated;
    an incomplete entry cannot be surfaced to users (Rev2 §2.7)."""

    id: str
    covers: str
    does_not_allow: str
    rows: tuple[ScopeRow, ...]
    # "enumerated" (rows listed above) or "per_commitment" (dynamic
    # rows, one per user-authorized commitment; any non-empty key).
    row_scheme: str
    supported_stances: tuple[str, ...]
    default_stance: str
    # Boundary neighbors: capabilities/classes this capability never
    # authorizes on its own (framework-check step 5).
    never_authorizes: tuple[str, ...]
    # C1.6 classes this capability's instances may fall in, if any.
    exception_classes: tuple[str, ...] = ()


def _strand_rows() -> tuple[ScopeRow, ...]:
    # R1 strand rows use the design's strand names (Heart, Hands,
    # Logic, Voice, Ear, Compass, Eye). Intake strand keys differ
    # (people, body, number, word, sound, self, image respectively);
    # reconciling registry rows with intake keys is noting work for
    # Slice 3, not foundation work — Slice 1 wires no noting.
    names = ("heart", "hands", "logic", "voice", "ear", "compass", "eye")
    return tuple(
        ScopeRow(key=f"strand:{name}", label=name.capitalize(), kind="strand")
        for name in names
    )


def _source_rows() -> tuple[ScopeRow, ...]:
    return (
        ScopeRow(
            key="source:strand_interviews",
            label="Strand interviews",
            kind="source",
        ),
        ScopeRow(
            key="source:general_conversation",
            label="General conversation",
            kind="source",
        ),
    )


_SEAT_ROWS = (
    # Row keys are archetype ids (the conversation store's seat key);
    # labels are the user-facing seat names (Rev2 §2.7 R4).
    ScopeRow(key="mentor", label="Gardener", kind="per_seat"),
    ScopeRow(key="champion", label="Firebrand", kind="per_seat"),
    ScopeRow(key="guardian", label="Bear", kind="per_seat"),
    ScopeRow(key="maverick", label="Fox", kind="per_seat"),
    ScopeRow(key="ambassador", label="Crane", kind="per_seat"),
    ScopeRow(key="conductor", label="Weaver", kind="per_seat"),
    ScopeRow(key="skeptic", label="Raven", kind="per_seat"),
)

_SINGLE_ROW = (ScopeRow(key="all", label="All", kind="single"),)

_CAPABILITIES: dict[str, CapabilityEntry] = {
    "R1": CapabilityEntry(
        id="R1",
        covers=(
            "Observe a candidate observation in conversation (a taste, "
            "a fact, a direction) and hold it as a pending note."
        ),
        does_not_allow=(
            "This never trains anything, never publishes anything, "
            "never shares anything outside your account, never spends "
            "money, and never executes anything. A note is a candidate "
            "record, never a training signal, until Review confirmation "
            "plus per-claim training approval."
        ),
        rows=_strand_rows() + _source_rows(),
        row_scheme="enumerated",
        supported_stances=STANCES,
        # Stated exception to the framework default (Rev2 §2.1/OQ5):
        # asking is not capturing — nothing is recorded without a yes.
        default_stance=ASK_ME,
        never_authorizes=(
            "train",
            "publish",
            "share",
            "spend",
            "execute",
        ),
    ),
    "R2": CapabilityEntry(
        id="R2",
        covers=(
            "Can Zenaf connect our talks into ongoing threads, note "
            "what they might mean, and keep those notes where you can "
            "review/delete them?"
        ),
        does_not_allow=(
            "This never trains anything, never publishes or shares "
            "anything outside your account, never spends money, never "
            "executes anything, and never distributes observations "
            "across branches (that is R3, a separate capability)."
        ),
        rows=_SINGLE_ROW,
        row_scheme="enumerated",
        supported_stances=STANCES,
        default_stance=DONT_DO_IT,
        never_authorizes=(
            "train",
            "publish",
            "share",
            "spend",
            "execute",
            "coordinate",
        ),
    ),
    "R3": CapabilityEntry(
        id="R3",
        covers=(
            "Distribute derived observations from one branch "
            "(conversation line) to another, so a pattern recognized "
            "in one place can inform another."
        ),
        does_not_allow=(
            "This never trains anything, never publishes or shares "
            "anything outside your account, never spends money, never "
            "executes anything — and never authorizes derivation "
            "itself. Coordination without derivation is empty, and "
            "derivation without coordination stays local."
        ),
        rows=_SINGLE_ROW,
        row_scheme="enumerated",
        supported_stances=STANCES,
        default_stance=DONT_DO_IT,
        never_authorizes=(
            "train",
            "publish",
            "share",
            "spend",
            "execute",
            "derive",
        ),
    ),
    "R4": CapabilityEntry(
        id="R4",
        covers=(
            "A seat lighting up with \"!\" — signaling it has "
            "something potentially worthwhile to bring to your "
            "attention in a conversation — and the invitation list "
            "entry behind it (seat, attributed reason, evidence)."
        ),
        does_not_allow=(
            "An invitation never joins, never switches conversations, "
            "never forces participation, never trains, never publishes, "
            "never shares, never spends, and never executes. Joining "
            "happens only on a sent turn to the invited seat."
        ),
        rows=_SEAT_ROWS,
        row_scheme="enumerated",
        # Ask me is not a distinct stance here: the invitation IS the
        # ask (Rev2 §2.7 R4). Just do it = surface; Don't do it =
        # suppress (suppression, not dismissal).
        supported_stances=(JUST_DO_IT, DONT_DO_IT),
        default_stance=JUST_DO_IT,
        never_authorizes=(
            "join",
            "navigate",
            "train",
            "publish",
            "share",
            "spend",
            "execute",
        ),
    ),
    "R5": CapabilityEntry(
        id="R5",
        covers=(
            "A seat offering a structured task proposal — title, "
            "parent, timeframe, due date, notes — as a proposal card "
            "in conversation, for the user to approve, edit, or "
            "decline. Surfacing the card is the capability; creating "
            "the task is NOT."
        ),
        does_not_allow=(
            "A proposal card authorizes nothing until the user "
            "approves it. This never creates tasks or commitments, "
            "never changes task state, never spends, never shares, "
            "never trains, and never publishes."
        ),
        rows=_SINGLE_ROW,
        row_scheme="enumerated",
        # Same reason as R4: the proposal card IS the ask.
        supported_stances=(JUST_DO_IT, DONT_DO_IT),
        default_stance=JUST_DO_IT,
        never_authorizes=(
            "create_task",
            "change_task_state",
            "spend",
            "share",
            "train",
            "publish",
        ),
        # No C1.6 membership claimed here: under C1, the never-
        # coverable classes are checked per INSTANCE at framework-
        # check step 4 (consequential_class), not per capability.
        # A proposal instance that itself attempted a C1.6 act
        # would confirm per transaction at that step regardless
        # of this entry's stance.
    ),
    "R6": CapabilityEntry(
        id="R6",
        covers=(
            "Follow-through nudges for tasks, aspirations, and "
            "commitments the user has explicitly asked Zenaf to keep "
            "after — the \"bug me until I do\" pattern, with a "
            "user-chosen cadence."
        ),
        does_not_allow=(
            "A reminder never becomes a new obligation, never creates "
            "a commitment, never changes a cadence unilaterally, "
            "never escalates frequency to overcome dismissal, never "
            "shares, never spends, never trains, and never publishes."
        ),
        rows=(),
        row_scheme="per_commitment",
        supported_stances=STANCES,
        default_stance=DONT_DO_IT,
        never_authorizes=(
            "create_commitment",
            "change_cadence",
            "escalate",
            "share",
            "spend",
            "train",
            "publish",
        ),
    ),
    # R7 deliberately absent: RETIRED (C3). It is a presentation of
    # R1 in the strand group, not a capability entry, and its id is
    # never reused.
    #
    # R8 is the registration RULE stated in this module's docstring,
    # not a capability entry: future subsystems register by editing
    # this module under design review, and unregistered capabilities
    # fail closed at the framework check.
}


def validate_registry() -> None:
    """Fail loudly if the registry is incomplete or reuses a retired id.

    Called at import so a broken registry cannot ship silently. This
    is the R8 fail-closed check at the definition layer; the
    framework check enforces the same rule per call for unknown ids.
    """
    seen_rows: dict[str, set[str]] = {}
    for capability_id, entry in _CAPABILITIES.items():
        if capability_id in RETIRED_CAPABILITY_IDS:
            raise ValueError(f"retired capability id reused: {capability_id}")
        if entry.id != capability_id:
            raise ValueError(f"registry key/id mismatch: {capability_id}")
        if not entry.covers.strip():
            raise ValueError(f"{capability_id}: covers statement missing")
        if not entry.does_not_allow.strip():
            raise ValueError(f"{capability_id}: 'does NOT allow' text missing")
        if entry.row_scheme not in ("enumerated", "per_commitment"):
            raise ValueError(f"{capability_id}: unknown row_scheme")
        if entry.row_scheme == "enumerated" and not entry.rows:
            raise ValueError(f"{capability_id}: enumerated capability has no rows")
        if entry.row_scheme == "per_commitment" and entry.rows:
            raise ValueError(f"{capability_id}: per-commitment capability lists rows")
        if not entry.supported_stances:
            raise ValueError(f"{capability_id}: no supported stances")
        for stance in entry.supported_stances:
            if stance not in STANCES:
                raise ValueError(f"{capability_id}: unknown stance {stance!r}")
        if entry.default_stance not in entry.supported_stances:
            raise ValueError(f"{capability_id}: default stance not supported")
        if not entry.never_authorizes:
            raise ValueError(f"{capability_id}: boundary neighbors unstated")
        for cls in entry.exception_classes:
            if cls not in NEVER_COVERABLE_CLASSES:
                raise ValueError(f"{capability_id}: unknown exception class {cls!r}")
        keys = seen_rows.setdefault(capability_id, set())
        for row in entry.rows:
            if row.key in keys:
                raise ValueError(f"{capability_id}: duplicate row key {row.key!r}")
            keys.add(row.key)
    if set(_CAPABILITIES) != {"R1", "R2", "R3", "R4", "R5", "R6"}:
        raise ValueError("registry must contain exactly R1–R6")


validate_registry()

#: The registry itself. Immutable by construction: runtime code cannot
#: add a capability (that would be runtime self-declaration, which
#: the R8 rule forbids). Any mutation attempt raises TypeError.
CAPABILITIES: MappingProxyType[str, CapabilityEntry] = MappingProxyType(
    _CAPABILITIES
)


def get_capability(capability_id: str | None) -> CapabilityEntry | None:
    """Return the registry entry, or None for unknown/retired ids.

    R7 returns None: retired, never reused, never an authority.
    """
    if not capability_id:
        return None
    return _CAPABILITIES.get(capability_id)


def is_registered(capability_id: str | None) -> bool:
    """True iff the id names a registered, stance-bearing capability."""
    return get_capability(capability_id) is not None


def is_valid_row(capability_id: str, row_key: str | None) -> bool:
    """True iff the row key is a row of the capability.

    Single-row capabilities accept ``"all"`` (or None, normalized to
    ``"all"`` by callers). Per-commitment capabilities (R6) accept
    any non-empty row key: each commitment is its own row.
    """
    entry = get_capability(capability_id)
    if entry is None:
        return False
    if entry.row_scheme == "per_commitment":
        return bool(row_key and str(row_key).strip())
    if row_key is None:
        row_key = "all"
    return any(row.key == row_key for row in entry.rows)


def row_keys(capability_id: str) -> tuple[str, ...]:
    """Enumerated row keys of a capability (empty for per-commitment)."""
    entry = get_capability(capability_id)
    if entry is None:
        return ()
    return tuple(row.key for row in entry.rows)
