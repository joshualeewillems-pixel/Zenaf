"""Steward evidence access, Phase 1 — narrowed shared retrieval plumbing.

Plan: implementation-plan revision 2, section 3. This module contains
exactly three things and nothing else:

1. A provenance-only envelope (rev2 section 0.2): a plain data shape
   carrying original evidence with its source, speaker, timestamp,
   form, and durability. It carries no semantic-category field, no
   significance field, no recognition field, and no interpretation
   field. Constructing an envelope never writes anything.
2. Safe ownership enforcement (rev2 section 0.5): a row-wise guard
   that returns a decision row only when its owner matches the
   requesting user, and otherwise returns a refusal carrying no
   content from the row. The guard is per-row by design, so a future
   caller can apply it to every row of a list result; there is no
   emit-then-filter path.
3. Explicit unavailable-source behavior (rev2 section 0.3, narrowed):
   a minimal durability determination over a citation. Live
   re-fetch under the requesting user's scope first; else consult
   ONLY the consuming phase's named carrier, supplied as a
   parameter; else UNAVAILABLE (id plus the fact of loss, no
   content). The generic multi-carrier classifier from the original
   plan is cut: this module hardcodes no carrier set and never
   consults a carrier beyond the one it is given, and it never scans
   a corpus or invents content.

Deliberate non-imports: this module imports no conversation store,
no VE store, no narrative module, and no model or provider code.
Live re-fetch and carrier lookup are caller-supplied callables, so
Phase 1 adds no read invocation, no call site, and no new coupling
to any store. Scope enforcement for a live re-fetch lives with the
caller that supplies the fetch (Phase 2 pairs it with the guard
below); the determination itself never touches a store directly,
so it cannot bypass scope. A fetch returning None means "no live
row"; any string, including an empty one, means "live row present".

No consumers exist in this phase. Nothing in this module derives,
interprets, categorizes, attaches, writes, or calls a model.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass

__all__ = [
    "CarrierRef",
    "DurabilityOutcome",
    "EvidenceEnvelope",
    "OwnershipRefusal",
    "determine_durability",
    "guard_row",
    "guard_rows",
]

# Durability states (rev2 section 0.3). RETRIEVABLE: the live source
# row was re-fetched by id, under the requesting user's scope, at read
# time. QUOTED: no live row was verified, but a frozen copy survives
# in the one named carrier the caller supplied, presented as a quote
# with that carrier identified. UNAVAILABLE: neither a live row nor a
# frozen quote was located; only the id and the fact of loss may be
# presented, never content.
DURABILITIES = ("RETRIEVABLE", "QUOTED", "UNAVAILABLE")

# Envelope forms (rev2 section 0.2). "verbatim": the content is the
# source row's own text. "quoted": the content is a frozen quote
# carried by a named carrier, presented as a quote.
FORMS = ("verbatim", "quoted")


@dataclass(frozen=True)
class EvidenceEnvelope:
    """Provenance-only carrier for retrieved evidence (rev2 0.2).

    Fields, exactly: source_system, source_ids, speaker_or_author,
    timestamp, form, durability, content, stored_type_text,
    about_target. ``content`` is present for RETRIEVABLE and QUOTED
    and absent (None) for UNAVAILABLE; construction enforces that.
    ``stored_type_text`` is decision records only: it holds the
    record's stored type string quoted verbatim as stored data, and
    is None for non-decision sources. It is data, never a category
    assigned by this module. ``about_target`` is a decision
    about-target, or a conversation id.
    """

    source_system: str
    source_ids: tuple[str, ...]
    speaker_or_author: str
    timestamp: str
    form: str
    durability: str
    content: str | None
    stored_type_text: str | None
    about_target: str

    def __post_init__(self) -> None:
        if self.form not in FORMS:
            raise ValueError(f"unknown envelope form: {self.form!r}")
        if self.durability not in DURABILITIES:
            raise ValueError(f"unknown durability: {self.durability!r}")
        if self.durability == "UNAVAILABLE" and self.content is not None:
            raise ValueError("UNAVAILABLE envelope must not carry content")
        if not isinstance(self.source_ids, tuple):
            object.__setattr__(self, "source_ids", tuple(self.source_ids))


@dataclass(frozen=True)
class CarrierRef:
    """One named frozen-quote carrier a caller permits consulting.

    ``kind`` names the carrier type (Phase 3's set names only
    "evidence_note"); ``ref_id`` identifies the single carrier
    record (e.g. a note id). The determination consults exactly
    this carrier and no other.
    """

    kind: str
    ref_id: str


@dataclass(frozen=True)
class DurabilityOutcome:
    """Result of the minimal durability determination (rev2 0.3).

    ``carrier`` identifies the carrier for QUOTED outcomes and is
    None otherwise. ``content`` is the live row's text for
    RETRIEVABLE, the frozen quote for QUOTED, and None for
    UNAVAILABLE. A future caller builds an EvidenceEnvelope from
    this outcome plus the passage's speaker, timestamp, and form;
    the determination itself assigns no further meaning.
    """

    durability: str
    source_ids: tuple[str, ...]
    carrier: CarrierRef | None
    content: str | None

    def __post_init__(self) -> None:
        if self.durability not in DURABILITIES:
            raise ValueError(f"unknown durability: {self.durability!r}")
        if self.durability == "UNAVAILABLE" and self.content is not None:
            raise ValueError("UNAVAILABLE outcome must not carry content")
        if self.durability == "QUOTED" and self.carrier is None:
            raise ValueError("QUOTED outcome must identify its carrier")
        if not isinstance(self.source_ids, tuple):
            object.__setattr__(self, "source_ids", tuple(self.source_ids))


@dataclass(frozen=True)
class OwnershipRefusal:
    """Content-free refusal from the ownership guard (rev2 0.5).

    Deliberately fieldless: a refusal carries nothing from the
    refused row — no id, no snippet, no about-target, no owner.
    Its bare presence is the whole signal: ownership was not
    established for that row under the requesting user.
    """


def guard_row(
    row: Mapping[str, object], requesting_user_id: str
) -> Mapping[str, object] | OwnershipRefusal:
    """Return ``row`` unchanged iff its owner is the requester.

    Fail-closed: a row with no ``user_id``, or an empty requesting
    user id, never establishes ownership and is refused. The
    returned row on success is the same object, unmodified; the
    refusal on failure carries no row content by construction.
    """
    if not requesting_user_id:
        return OwnershipRefusal()
    owner = row.get("user_id")
    if owner is not None and owner == requesting_user_id:
        return row
    return OwnershipRefusal()


def guard_rows(
    rows: Sequence[Mapping[str, object]], requesting_user_id: str
) -> list[Mapping[str, object] | OwnershipRefusal]:
    """Apply :func:`guard_row` to every row, preserving positions.

    Per-row enforcement is the point: a list result (the flagged
    list_decisions enumeration hazard) must have its guard tested
    on every row, not just on a single get. Passing rows come back
    unchanged; each refused row becomes a content-free refusal in
    its own position. Nothing from a refused row appears anywhere
    in the output, so there is no emit-then-filter path.
    """
    return [guard_row(row, requesting_user_id) for row in rows]


def determine_durability(
    *,
    source_ids: Sequence[str],
    live_fetch: Callable[[], str | None],
    carrier_lookup: Callable[[CarrierRef], str | None] | None = None,
    carrier_ref: CarrierRef | None = None,
) -> DurabilityOutcome:
    """Minimal durability determination over one citation (rev2 0.3).

    Order is fixed: (1) live re-fetch under the requesting user's
    scope, via the caller-supplied ``live_fetch`` — a string result
    means the live row exists and the outcome is RETRIEVABLE, and
    no carrier is consulted at all. (2) Else, only if the caller
    supplied BOTH a ``carrier_lookup`` and the single ``carrier_ref``
    it permits consulting, call the lookup exactly once with exactly
    that ref — a string result means QUOTED with that carrier
    identified. (3) Else UNAVAILABLE: the ids plus the fact of loss,
    no content. A half-supplied carrier (lookup without ref, or ref
    without lookup) is not consulted at all: an unnamed carrier is
    not a carrier this determination may use. Nothing here scans a
    corpus, enumerates carriers, or invents content.
    """
    ids = tuple(source_ids)
    live = live_fetch()
    if live is not None:
        return DurabilityOutcome(
            durability="RETRIEVABLE", source_ids=ids, carrier=None, content=live
        )
    if carrier_lookup is not None and carrier_ref is not None:
        quote = carrier_lookup(carrier_ref)
        if quote is not None:
            return DurabilityOutcome(
                durability="QUOTED",
                source_ids=ids,
                carrier=carrier_ref,
                content=quote,
            )
    return DurabilityOutcome(
        durability="UNAVAILABLE", source_ids=ids, carrier=None, content=None
    )
