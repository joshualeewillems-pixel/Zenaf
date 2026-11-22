"""Organic currency for narrative readings (Story-First Phase 1A).

Currency is a PURE DERIVATION over existing records — thread,
readings, change records — computed at render time. It is never
stored, never verdicted, and this module writes nothing and calls
no model: its only inputs are the records it is handed.

The contract (design Rev 5 §1 + Rev 6 §1): a reading's stored
status records verdict history only. Whether a reading is CURRENT
— part of the card's living field — or HISTORY is derived:

- A reading named as ``prior_reading_id`` in a change with a
  non-null ``new_reading_id`` is organically superseded: the
  Steward's own revision act retired it, whatever its stored
  status still says (normally ``proposed`` — no verdict writer
  is ever invoked for organic revision).
- Stored ``superseded`` / ``rejected`` readings are history.
- Every other reading (``proposed`` / ``accepted``, not
  organically superseded) is live and sits in the current field.

Labels describe, never rank. A reading may carry several:

- ``superseded`` — retired by a successor (organically, or by
  stored status); ``rejected`` — stored status rejected.
- ``weakened`` — a ``contradicted`` change names it as prior
  with NO successor: the contradiction stands unresolved.
- ``recurring`` — an ``extended`` change names it as prior WITH
  a successor, and the extension supplied genuinely new support:
  the successor's support accounting (payload key ``support``)
  records at least one ``additional`` item; when no accounting
  is present, the fallback is mechanical — the change cites
  evidence refs the prior reading did not cite. (The label
  describes the prior reading's lineage event: its theme
  recurred and was extended on new support.)
- ``competing`` — another live reading on the same thread has
  no change-lineage relation to it: competitors, not versions.
- ``emerging`` — live, named by no change record, and either
  the thread's only live reading or its newest.
- ``dormant`` — the thread's own status is dormant (added to
  every reading on the thread, current and history alike).

Independent support (Rev 6 §2) is classified by
``classify_support`` over fields the record already carries —
``(ref_kind, ref_id)`` identity, ``entity_ref``, timestamps, and
caller-supplied cohesion pairs. Cohesion testifies only AGAINST
independence (a cohesive same-entity citation is a probable
retelling); its absence proves nothing — without a positive
occasion marker, a novel citation is ``undetermined``, never
``additional``.
"""

from __future__ import annotations

from dataclasses import dataclass

from .models import (
    NarrativeThread,
    ThreadChange,
    ThreadEvidence,
    ThreadReading,
)

PLACEMENT_CURRENT = "current"
PLACEMENT_HISTORY = "history"

_HISTORY_STATUSES = ("superseded", "rejected")

#: Canonical label order for deterministic rendering.
_LABEL_ORDER = (
    "superseded",
    "rejected",
    "weakened",
    "recurring",
    "competing",
    "emerging",
    "dormant",
)

#: The four support classes (Rev 6 §2), in payload order.
SUPPORT_CLASSES = (
    "duplicate",
    "probable_retelling",
    "additional",
    "undetermined",
)


@dataclass(frozen=True)
class ReadingCurrency:
    """One reading's derived currency: placement + condition labels."""

    placement: str  # PLACEMENT_CURRENT | PLACEMENT_HISTORY
    labels: tuple[str, ...] = ()

    def to_dict(self) -> dict:
        return {"placement": self.placement, "labels": list(self.labels)}


def _extension_has_new_support(
    change: ThreadChange,
    prior: ThreadReading,
    successor: ThreadReading | None,
) -> bool:
    """Did this extension rest on genuinely new support?

    The successor's support accounting is authoritative when
    present; only in its absence does the mechanical fallback
    apply (the change cites refs the prior reading never cited).
    """
    support = None
    if successor is not None and isinstance(successor.reading, dict):
        support = successor.reading.get("support")
    if isinstance(support, dict):
        return bool(support.get("additional"))
    prior_refs = set(prior.evidence_refs or [])
    return any(
        ref not in prior_refs for ref in (change.evidence_refs or [])
    )


def derive_currency(
    thread: NarrativeThread,
    readings: list[ThreadReading],
    changes: list[ThreadChange],
) -> dict[str, ReadingCurrency]:
    """Derive placement + labels for every reading of one thread.

    Pure: no store access, no writes, no generation. ``readings``
    and ``changes`` are the thread's full record (any status);
    consumers that hold only a subset still get correct placement
    for the readings they hold, because organic supersession is
    determined by the change records alone.
    """
    readings = list(readings)
    by_id = {reading.id: reading for reading in readings}

    superseded_ids: set[str] = set()
    named_prior: dict[str, list[ThreadChange]] = {}
    named_any: set[str] = set()
    linked_pairs: set[frozenset] = set()
    for change in changes:
        prior_id = change.prior_reading_id
        new_id = change.new_reading_id
        if prior_id:
            named_any.add(prior_id)
            named_prior.setdefault(prior_id, []).append(change)
            if new_id:
                superseded_ids.add(prior_id)
                linked_pairs.add(frozenset((prior_id, new_id)))
        if new_id:
            named_any.add(new_id)

    live = [
        reading
        for reading in readings
        if reading.status not in _HISTORY_STATUSES
        and reading.id not in superseded_ids
    ]
    newest_live_id = None
    if live:
        newest_live_id = max(
            live, key=lambda r: (r.created_at or "", r.id)
        ).id

    result: dict[str, ReadingCurrency] = {}
    for reading in readings:
        labels: set[str] = set()
        if reading.status in _HISTORY_STATUSES or reading.id in superseded_ids:
            placement = PLACEMENT_HISTORY
            if reading.id in superseded_ids or reading.status == "superseded":
                labels.add("superseded")
            if reading.status == "rejected":
                labels.add("rejected")
        else:
            placement = PLACEMENT_CURRENT

        for change in named_prior.get(reading.id, []):
            if change.kind == "contradicted" and not change.new_reading_id:
                if placement == PLACEMENT_CURRENT:
                    labels.add("weakened")
            elif change.kind == "extended" and change.new_reading_id:
                successor = by_id.get(change.new_reading_id)
                if _extension_has_new_support(change, reading, successor):
                    labels.add("recurring")

        if placement == PLACEMENT_CURRENT:
            for other in live:
                if other.id == reading.id:
                    continue
                if frozenset((reading.id, other.id)) not in linked_pairs:
                    labels.add("competing")
                    break
            if reading.id not in named_any and (
                len(live) == 1 or reading.id == newest_live_id
            ):
                labels.add("emerging")

        if thread is not None and thread.status == "dormant":
            labels.add("dormant")

        result[reading.id] = ReadingCurrency(
            placement=placement,
            labels=tuple(
                label for label in _LABEL_ORDER if label in labels
            ),
        )
    return result


def _date_part(value: str | None) -> str | None:
    """The calendar date (YYYY-MM-DD) of an ISO timestamp, or None."""
    if not value:
        return None
    text = str(value).strip()
    if len(text) < 10:
        return None
    date = text[:10]
    if date[4] != "-" or date[7] != "-":
        return None
    if not (date[:4] + date[5:7] + date[8:]).isdigit():
        return None
    return date


def classify_support(
    lineage_cited: set[tuple[str, str]],
    prior_evidence_rows: list[ThreadEvidence],
    new_evidence_rows: list[ThreadEvidence],
    cohesion_pairs=frozenset(),
) -> dict[str, list[str]]:
    """Classify each newly cited evidence row (Rev 6 §2).

    ``lineage_cited`` is the set of ``(ref_kind, ref_id)`` the
    reading's lineage already cites. ``prior_evidence_rows`` are
    the evidence rows behind those citations; ``new_evidence_rows``
    are the rows a revision newly cites. ``cohesion_pairs`` holds
    pairs of evidence row ids (frozensets or 2-tuples) that
    derivation found cohesive.

    Returns ``{duplicate, probable_retelling, additional,
    undetermined}`` — lists of NEW row ids, in input order. Only
    ``additional`` corroborates; the other three classes are
    recorded and visible and corroborate nothing.
    """
    lineage = set(lineage_cited or ())
    priors = list(prior_evidence_rows or ())
    pairs: set[frozenset] = set()
    for pair in cohesion_pairs or ():
        ids = frozenset(pair)
        if len(ids) == 2:
            pairs.add(ids)

    prior_entities = {row.entity_ref for row in priors if row.entity_ref}
    prior_kinds = {row.ref_kind for row in priors}
    prior_dates = [_date_part(row.created_at) for row in priors]

    out: dict[str, list[str]] = {name: [] for name in SUPPORT_CLASSES}
    for row in new_evidence_rows or ():
        # (a) The same source record, cited again — exact.
        if (row.ref_kind, row.ref_id) in lineage:
            out["duplicate"].append(row.id)
            continue
        # (b) Probable retelling: same subject identity AND a
        # cohesion link to a prior row. Cohesion argues against
        # independence; it can never argue for it.
        if row.entity_ref and row.entity_ref in prior_entities:
            if any(
                frozenset((row.id, prior.id)) in pairs for prior in priors
            ):
                out["probable_retelling"].append(row.id)
                continue
        # (c) Genuinely additional — a POSITIVE occasion marker is
        # required, and markers need prior rows to compare against.
        # Absence of cohesion is never a marker.
        additional = False
        if priors:
            date = _date_part(row.created_at)
            if (
                date is not None
                and all(d is not None for d in prior_dates)
                and date not in prior_dates
            ):
                additional = True
            elif (
                row.entity_ref
                and all(p.entity_ref is not None for p in priors)
                and row.entity_ref not in prior_entities
            ):
                additional = True
            elif row.ref_kind not in prior_kinds:
                additional = True
        if additional:
            out["additional"].append(row.id)
            continue
        # (d) The record cannot distinguish — uncertainty preserved.
        out["undetermined"].append(row.id)
    return out


def support_block(
    lineage_cited: set[tuple[str, str]],
    prior_evidence_rows: list[ThreadEvidence],
    new_evidence_rows: list[ThreadEvidence],
    cohesion_pairs=frozenset(),
) -> dict[str, list[str]]:
    """The support-accounting block for a revision reading's payload.

    Same shape ``classify_support`` returns — ``{duplicate,
    probable_retelling, additional, undetermined}`` of evidence
    row ids — embedded under the reading payload's ``support``
    key at recognition time (Rev 6 §2: one payload convention,
    no new table, no persisted groups).
    """
    return classify_support(
        lineage_cited,
        prior_evidence_rows,
        new_evidence_rows,
        cohesion_pairs=cohesion_pairs,
    )
