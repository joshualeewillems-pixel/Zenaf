"""Exposure capture at generation time (Increment B, accepted schema
contract §5, Joshua 2026-10-30).

Pure stdlib; no imports from meeting.py, so this module cannot mutate
the record it reads. It answers one question per generation: what did
this model actually see, as proven by the exact provider-bound payload?

Design rules (contract §5 + verdict constraint):

- The payload object actually sent is the single source of truth. The
  visible-claim list is DERIVED from that payload, never assembled
  independently — a hash plus a separately assembled list is dishonest
  if the two can diverge.
- Visibility requires identifiable claim CONTENT presented as an
  available council claim — not a bare identifier occurrence. Only
  lines in the claim-presentation structure count: the registry block
  the runner inserted (``ClaimRegistry.render()`` output: a header
  line plus one ``C{id} [participant, status]: text`` line per
  claim). A claim id merely MENTIONED in packet prose, instructions,
  telemetry, or another claim's text is NOT visibility, and the
  extractor never scans the payload for bare ids.
- The extractor parses ONLY the supplied registry block and verifies
  the block occurs verbatim in the payload. Packet text that happens
  to contain registry-shaped lines never counts, because it was not
  the runner-inserted block. (Residual edge, documented: spans are
  anchored to the FIRST byte-identical occurrence of the block in
  the payload. If packet text contained a byte-identical copy of the
  block before the runner-inserted one, spans would point at the
  earlier copy — but the visible IDS would be identical, since the
  block content is identical, so validation outcomes are unaffected.)
- The exact payload is preserved by hash AND by retrievable copy:
  ``capture_exposure`` returns the hash; the runner stores the full
  payload text in the meeting's ``payload_evidence`` store keyed by
  that hash (see artifact wiring). Hash-only would make the
  presented-vs-mentioned distinction unauditable after the fact, so
  hash-only is not an acceptable record on its own.
- Transformations are recorded, not assumed away. The current engine
  never truncates (over-window generations are refused, never
  silently truncated), so the runner passes an empty transformation
  list today — but the record shape supports truncation drops, and a
  transformation claiming a drop MUST agree with the block (dropped
  ids absent from visible ids), else capture fails loudly.
- Failure honesty: when capture is impossible, :func:`unknown_exposure`
  records unknown evidence with a reason — never a reconstructed
  visible list. ``temporarily_unavailable`` evidence warns at interim
  validation and errors at final validation (contract §5 escalation);
  ``absent`` evidence always errors (E12).
- Evidence vocabulary follows the existing validator
  (``transjective_record``): a successful capture records evidence
  ``present`` — the value the validator's E3 visibility check engages
  on. A hand-built record carrying some other evidence label with a
  visible list would skip E3 under the validator as written; that is
  a pre-existing validator property, not something this module
  changes, and native captures never hit it because they emit
  ``present``.
"""

from __future__ import annotations

import hashlib
import re

__all__ = [
    "REGISTRY_HEADER",
    "capture_exposure",
    "extract_presented_claims",
    "truncation_record",
    "unknown_exposure",
]

REGISTRY_HEADER = "Claim registry (meeting-local IDs):"

# One registry line: C{id} [participant, status]: text — anchored at
# line start, so text-internal mentions never create presented claims.
_REGISTRY_LINE_RE = re.compile(r"^C(\d+) \[(.*), ([^\]]+)\]: ")

_CAPTURE_METHOD = "send-time payload capture"


def _line_offsets(block: str) -> list[tuple[int, int]]:
    """(start, end) offsets of each line in ``block`` (no newline in
    the spans themselves)."""
    offsets: list[tuple[int, int]] = []
    pos = 0
    for line in block.split("\n"):
        offsets.append((pos, pos + len(line)))
        pos += len(line) + 1
    return offsets


def extract_presented_claims(
    registry_block: str,
    *,
    base_offset: int = 0,
    base_line: int = 0,
) -> list[dict]:
    """Parse a registry block into presented claims, in order.

    ``registry_block`` must be exactly a ``ClaimRegistry.render()``
    output: the header line, then one registry line per claim. Any
    non-empty line that is not the header or a registry line raises
    ``ValueError`` — a malformed block fails loudly, never silently
    yields a partial visible set. Duplicate claim ids also raise.
    Each result carries the claim id, participant, status, section
    (``claim_registry``), and the span (offsets + 1-based line number
    in the full payload, via ``base_offset`` / ``base_line``).
    """
    lines = registry_block.split("\n")
    # Tolerate trailing blank lines only; anything else must match.
    while lines and lines[-1].strip() == "":
        lines.pop()
    if not lines or lines[0].strip() != REGISTRY_HEADER:
        raise ValueError("registry block does not start with the registry header")
    offsets = _line_offsets("\n".join(lines))
    presented: list[dict] = []
    seen: set[str] = set()
    for i, line in enumerate(lines[1:], start=1):
        if line.strip() == "":
            raise ValueError("blank line inside registry block")
        m = _REGISTRY_LINE_RE.match(line)
        if m is None:
            raise ValueError(f"line is not a registry line: {line[:80]!r}")
        cid = f"C{m.group(1)}"
        if cid in seen:
            raise ValueError(f"duplicate claim id in registry block: {cid}")
        seen.add(cid)
        start, end = offsets[i]
        presented.append(
            {
                "claim_id": cid,
                "participant": m.group(2),
                "status": m.group(3),
                "section": "claim_registry",
                "start_offset": base_offset + start,
                "end_offset": base_offset + end,
                "line": base_line + i + 1,
            }
        )
    return presented


def truncation_record(
    dropped_claim_ids: list[str],
    *,
    policy: str,
    order: str = "registry order",
) -> dict:
    """One context-window transformation record: claims dropped from
    the presented block, in order, under a named window policy."""
    return {
        "kind": "truncated",
        "dropped_claim_ids": list(dropped_claim_ids),
        "policy": policy,
        "order": order,
    }


def capture_exposure(
    payload: str,
    registry_block: str,
    *,
    window_id: str,
    transformations: list[dict] | None = None,
    capture_method: str = _CAPTURE_METHOD,
) -> dict:
    """Capture an exposure record from the exact payload sent.

    ``payload`` is the finalized provider-bound prompt string (after
    per-seat extras, after all assembly). ``registry_block`` is the
    exact registry render inserted into that payload ("" when the
    prompt presents no claims, e.g. opening phase). The block must
    occur verbatim in the payload, else ``ValueError`` — the record
    never asserts visibility it cannot locate. ``transformations``
    lists context-window transformation records; every dropped id
    must be absent from the visible ids, else ``ValueError``.

    Returns the exposure_ref dict attached to claims generated from
    this payload: payload hash + retrievable payload reference,
    window identity, transformations, visible ids + spans, evidence
    ``available``, and the capture method. The full payload text
    itself lives in the meeting's ``payload_evidence`` store keyed by
    ``payload_hash`` (the runner maintains it); this record alone
    carries the hash, never the text, so per-claim records stay small
    while the payload stays retrievable.
    """
    transformations = list(transformations or [])
    for tr in transformations:
        if not isinstance(tr, dict) or not isinstance(
            tr.get("dropped_claim_ids"), list
        ):
            raise ValueError("transformation record missing dropped_claim_ids list")
    if registry_block:
        offset = payload.find(registry_block)
        if offset < 0:
            raise ValueError("registry block not present in payload")
        base_line = payload[:offset].count("\n")
        presented = extract_presented_claims(
            registry_block, base_offset=offset, base_line=base_line
        )
    else:
        presented = []
    visible_ids = [p["claim_id"] for p in presented]
    for tr in transformations:
        dropped = set(tr.get("dropped_claim_ids") or [])
        if dropped & set(visible_ids):
            raise ValueError(
                "transformation claims a drop that is still visible: "
                f"{sorted(dropped & set(visible_ids))}"
            )
    payload_hash = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return {
        "payload_hash": payload_hash,
        "payload_ref": f"payload_evidence:{payload_hash}",
        "window_id": window_id,
        "transformations": transformations,
        "visible_ids": visible_ids,
        "visible_spans": presented,
        "evidence": "present",
        "capture_method": capture_method,
    }


def unknown_exposure(
    reason: str,
    *,
    capture_method: str = _CAPTURE_METHOD,
    temporarily: bool = False,
    pending_ref: str | None = None,
) -> dict:
    """Record unknown exposure honestly, never reconstructed.

    ``temporarily=False`` (default): evidence ``absent`` — always E12.
    ``temporarily=True``: evidence ``temporarily_unavailable`` — warns
    at interim validation (W2), errors at final (E12); requires a
    non-empty ``pending_ref`` (reference to evidence not yet
    retrievable), else ``ValueError``. ``visible_ids`` is None in
    both cases: unknown visibility must not fabricate E3 outcomes in
    either direction.
    """
    if temporarily and (not pending_ref or not pending_ref.strip()):
        raise ValueError(
            "temporarily unavailable exposure requires a pending_ref"
        )
    return {
        "payload_hash": None,
        "payload_ref": pending_ref if temporarily else None,
        "window_id": None,
        "transformations": [],
        "visible_ids": None,
        "visible_spans": [],
        "evidence": "temporarily_unavailable" if temporarily else "absent",
        "capture_method": capture_method,
        "reason": reason,
    }
