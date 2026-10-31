"""Correction input path (Increment E, accepted schema contract §6 + §1.6).

Pure stdlib; no imports from meeting.py or transjective_record.py, so
this module cannot mutate the record it reads and cannot fork
validation logic: the validator remains the independent check, and
these functions only construct records the validator accepts (or
refuse to construct them).

Design rules (contract §6/§1.6 + plan Increment E):

- Corrections are NOT from models mid-meeting. This module is the
  defined input path for authorized convener tooling and explicit
  user corrections only. There is no model-facing surface here.
- Every correction carries original_value, corrected_value,
  author_or_process, reason, superseded_record, and reconciles when
  superseding a non-head. Missing elements are refused at
  construction (ValueError) and fail E11 under the validator.
- Provenance is DISTINCT and never blended: author_or_process is
  exactly "convener-tooling" or "user", set only via the two named
  entry points (or the general function, which enforces membership).
  There is no default and no free-text provenance: a caller that
  does not choose explicitly does not get a correction.
- User-as-corrector is NOT the E7 user ban. E7 restricts disposition
  EVENT authorizers (§4.2); correction authorship (§1.6/§6 plus the
  decided correction authority) explicitly includes explicit user
  corrections. The validator imposes no authorizer restriction on
  corrections, and this module does not invent one.
- Append-only, single-successor: functions return a NEW record dict
  with an extended corrections list; the input record and its
  existing entries are never mutated. superseded_record is always
  the current head (or the chain origin for a reconciliation),
  resolved by replaying the validator's chain rules — callers never
  hand-compute heads, so a stale snapshot cannot silently become a
  new head: it becomes a competing correction the validator rejects
  (E11) unless reconciled.
- Reconciliation: a correction superseding a non-head cites the
  chain ORIGIN with reconciles = {heads (including the current
  head), resolver, reason}. The tooling validates this against the
  record as it stands; a stale reconciliation (heads missing the
  current head) is refused rather than silently accepted. A
  reconciliation supplied for a chain with no head yet is refused:
  there is nothing to reconcile.
- Value semantics are caller-defined: the contract defines the
  fields, not the value type. The tooling guarantees presence, chain
  position, provenance, and immutability — not value interpretation.
  original_value is the value as first recorded, as supplied by the
  caller; the tooling does not derive or reinterpret it.
- Persistence is the caller's job: this module operates on record
  dicts (the validate_contract_record input shape). No storage
  write path is invented here; a caller that owns a stored capture
  persists the returned record's corrections list through its own
  channel. A correction-id-citing reconciliation remains
  validator-accepted for hand-built records, but the tooling only
  constructs origin-citing reconciliations, which always suffice to
  advance a chain head.
"""

from __future__ import annotations

__all__ = [
    "PROVENANCE_CONVENER",
    "PROVENANCE_USER",
    "PROVENANCE_VALUES",
    "apply_correction",
    "apply_convener_correction",
    "apply_user_correction",
    "correction_chain",
    "resolve_head",
]

PROVENANCE_CONVENER = "convener-tooling"
PROVENANCE_USER = "user"
PROVENANCE_VALUES = frozenset({PROVENANCE_CONVENER, PROVENANCE_USER})

_CORRECTION_FIELDS = (
    "original_value",
    "corrected_value",
    "author_or_process",
    "reason",
    "superseded_record",
)


def _id_sets(record: dict) -> set[str]:
    """Ids the validator accepts as correction targets.

    Mirrors the validator's existence sets: claim ids, proposal ids,
    event ids, and disagreement ids. Correction ids are handled
    separately via the chain maps.
    """
    ids: set[str] = set()
    for claim in record.get("claims") or []:
        if isinstance(claim, dict) and claim.get("id"):
            ids.add(claim["id"])
    for proposal in record.get("proposals") or []:
        if isinstance(proposal, dict) and proposal.get("id"):
            ids.add(proposal["id"])
    for event in record.get("events") or []:
        if isinstance(event, dict) and event.get("event_id"):
            ids.add(event["event_id"])
    for disagreement in record.get("disagreements") or []:
        if isinstance(disagreement, dict) and disagreement.get("id"):
            ids.add(disagreement["id"])
    return ids


def _replay(corrections: list, existing_ids: set[str]):
    """Replay the validator's chain rules over a corrections list.

    Returns (chain_of, head_of): chain_of maps each accepted
    correction id to its chain origin; head_of maps each origin to
    its current head correction id. Structurally invalid
    corrections (missing fields) and chain-invalid corrections
    (nonexistent target, non-head citation without valid
    reconciliation) are skipped exactly as the validator skips
    them (``continue``): they never advance a head. This function
    is a read-only mirror, not a second validator: the validator
    remains the authority, and any divergence between this replay
    and the validator is a bug to be reported, not resolved here.
    """
    chain_of: dict[str, str] = {}
    head_of: dict[str, str] = {}
    accepted: set[str] = set()
    for corr in corrections:
        if not isinstance(corr, dict):
            continue
        cid = corr.get("id")
        if not cid:
            continue
        if any(corr.get(f) is None for f in _CORRECTION_FIELDS):
            continue
        sup = corr.get("superseded_record", "")
        if sup in accepted:
            chain = chain_of[sup]
            if head_of.get(chain) != sup:
                rec = corr.get("reconciles") or {}
                heads = rec.get("heads") if isinstance(rec, dict) else None
                if (
                    not heads
                    or head_of.get(chain) not in (heads or [])
                    or not rec.get("resolver")
                    or not rec.get("reason")
                ):
                    continue
                head_of[chain] = cid
            else:
                head_of[chain] = cid
            chain_of[cid] = chain
        elif sup in existing_ids:
            if sup in head_of:
                rec = corr.get("reconciles") or {}
                heads = rec.get("heads") if isinstance(rec, dict) else None
                if (
                    not heads
                    or head_of.get(sup) not in (heads or [])
                    or not rec.get("resolver")
                    or not rec.get("reason")
                ):
                    continue
                chain_of[cid] = sup
                head_of[sup] = cid
            else:
                chain_of[cid] = sup
                head_of[sup] = cid
        else:
            continue
        accepted.add(cid)
    return chain_of, head_of


def _chain_origin(record: dict, target_id: str) -> str:
    """Resolve a target id to its chain origin, or refuse."""
    corrections = record.get("corrections") or []
    chain_of, _ = _replay(corrections, _id_sets(record))
    if target_id in chain_of:
        return chain_of[target_id]
    if target_id in _id_sets(record):
        return target_id
    raise ValueError(f"unknown correction target: {target_id!r}")


def resolve_head(record: dict, target_id: str) -> str:
    """Current head of a target's correction chain.

    Returns the latest accepted correction id for the chain, or
    the target id itself when the chain has no corrections yet.
    Raises ValueError for an unknown target.
    """
    origin = _chain_origin(record, target_id)
    _, head_of = _replay(record.get("corrections") or [], _id_sets(record))
    return head_of.get(origin, origin)


def correction_chain(record: dict, target_id: str) -> list[dict]:
    """Accepted corrections of a target's chain, in chain order.

    Invalid corrections are excluded, exactly as the validator
    excludes them from head advancement. The origin record itself
    is not included; it lives in the record's claims/proposals.
    Raises ValueError for an unknown target.
    """
    origin = _chain_origin(record, target_id)
    corrections = record.get("corrections") or []
    chain_of, _ = _replay(corrections, _id_sets(record))
    return [
        corr
        for corr in corrections
        if isinstance(corr, dict) and chain_of.get(corr.get("id")) == origin
    ]


def apply_correction(
    record: dict,
    *,
    target_id: str,
    original_value,
    corrected_value,
    author_or_process: str,
    reason: str,
    correction_id: str | None = None,
    reconciles: dict | None = None,
) -> dict:
    """Append one CorrectionEvent to a record; return a NEW record.

    ``target_id`` is the record being corrected (a claim, proposal,
    event, disagreement, or prior correction id); the chain origin
    is resolved from it. ``superseded_record`` is always computed,
    never caller-supplied: the current head, or the chain origin
    for a reconciliation. The input record is never mutated.

    Raises ValueError for: an unknown target; any missing element
    (original_value, corrected_value, author_or_process, reason);
    provenance outside {"convener-tooling", "user"}; a duplicate
    correction id; a reconciliation that is malformed, stale
    (heads missing the current head), or supplied for a chain with
    no head yet.
    """
    if not target_id:
        raise ValueError("correction target_id must be non-empty")
    missing = [
        name
        for name, value in (
            ("original_value", original_value),
            ("corrected_value", corrected_value),
            ("author_or_process", author_or_process),
            ("reason", reason),
        )
        if value is None
    ]
    if missing:
        raise ValueError(f"correction missing elements: {missing}")
    if author_or_process not in PROVENANCE_VALUES:
        raise ValueError(
            f"author_or_process must be exactly 'convener-tooling' or "
            f"'user', not {author_or_process!r}"
        )
    corrections = list(record.get("corrections") or [])
    origin = _chain_origin(record, target_id)
    _, head_of = _replay(corrections, _id_sets(record))
    head = head_of.get(origin, origin)
    if reconciles is not None:
        if origin not in head_of:
            raise ValueError(
                "reconciliation supplied but chain has no head yet: "
                "there is nothing to reconcile"
            )
        if not isinstance(reconciles, dict):
            raise ValueError("reconciles must be a dict")
        heads = reconciles.get("heads")
        resolver = reconciles.get("resolver")
        rreason = reconciles.get("reason")
        if (
            not isinstance(heads, list)
            or not heads
            or head not in heads
            or not resolver
            or not rreason
        ):
            raise ValueError(
                "invalid reconciliation: heads must be a non-empty "
                "list including the current head, plus resolver and "
                "reason"
            )
        sup = origin
    else:
        sup = head
    existing_corr_ids = {
        c.get("id")
        for c in corrections
        if isinstance(c, dict) and c.get("id")
    }
    if correction_id is None:
        n = len(corrections) + 1
        while f"correction:{n}" in existing_corr_ids:
            n += 1
        correction_id = f"correction:{n}"
    elif correction_id in existing_corr_ids:
        raise ValueError(f"duplicate correction id: {correction_id!r}")
    corr: dict = {
        "id": correction_id,
        "original_value": original_value,
        "corrected_value": corrected_value,
        "author_or_process": author_or_process,
        "reason": reason,
        "superseded_record": sup,
    }
    if reconciles is not None:
        corr["reconciles"] = {
            "heads": list(reconciles["heads"]),
            "resolver": reconciles["resolver"],
            "reason": reconciles["reason"],
        }
    new_record = dict(record)
    new_record["corrections"] = corrections + [corr]
    return new_record


def apply_convener_correction(
    record: dict,
    *,
    target_id: str,
    original_value,
    corrected_value,
    reason: str,
    correction_id: str | None = None,
    reconciles: dict | None = None,
) -> dict:
    """Append a convener-tooling correction (provenance pinned)."""
    return apply_correction(
        record,
        target_id=target_id,
        original_value=original_value,
        corrected_value=corrected_value,
        author_or_process=PROVENANCE_CONVENER,
        reason=reason,
        correction_id=correction_id,
        reconciles=reconciles,
    )


def apply_user_correction(
    record: dict,
    *,
    target_id: str,
    original_value,
    corrected_value,
    reason: str,
    correction_id: str | None = None,
    reconciles: dict | None = None,
) -> dict:
    """Append an explicit user correction (provenance pinned)."""
    return apply_correction(
        record,
        target_id=target_id,
        original_value=original_value,
        corrected_value=corrected_value,
        author_or_process=PROVENANCE_USER,
        reason=reason,
        correction_id=correction_id,
        reconciles=reconciles,
    )
