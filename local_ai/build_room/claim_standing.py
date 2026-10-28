"""Registry standing (stage 1, design v2 2026-10-27, Joshua).

Pure, deterministic derivation of EFFECTIVE CLAIM STANDING from an
append-only claim record. Stdlib only; no imports from meeting.py, so
this module cannot accidentally mutate the record it reads.

Inputs are plain dicts (claims as produced by ``Claim.to_dict()``,
interactions as stored in the artifact). Outputs are plain dicts for
the artifact's additive ``claim_standing`` section.

Rules (design v2):

- Standing is ``active`` | ``superseded`` | ``withdrawn``. Absence of
  a standing move means ``active``. There is no ``maintained`` in
  the standing vocabulary; a ``defended`` link is not a move.
- A standing move exists ONLY as a structured link on a revision
  claim: ``supersedes = X`` (supersession) or ``withdraws = X``
  (withdrawal). The mover must be X's own author; cross-author
  links never move standing (they remain proposals and are ignored
  here — the link itself is preserved in the claim record).
- The target must be one existing earlier claim. Position in the
  registry list is transcript order (ids are assigned sequentially).
  A range is not a move. A bare stance word with no resolvable
  target is not a move.
- Prohibited moves are never applied but are recorded, on the
  mover's entry, as ``rejected_moves``: ``self_target`` (target is
  the mover itself), ``forward_reference`` (target is not strictly
  earlier than the mover), ``unknown_target`` (target id absent).
- Precedence: the LAST valid standing move wins. The full chain of
  valid moves is preserved in order, so last-wins cannot silently
  rewrite history. There is no move back to ``active``: a withdrawn
  or superseded claim stays so, and re-assertion requires a new
  claim. Standing is therefore not claimed to be monotonic: a
  withdrawn claim that later receives a valid supersession move
  becomes ``superseded``.
- Retraction-language detection signals (NOT standing changes):
  same-author revision spans only, matching retract/withdraw
  language and referencing an identifiable earlier single claim
  (ranges expand to their endpoints' inclusive span, capped — see
  ``_expand_reference``). A match inside a negation scope is an
  ``ambiguous`` signal, never a positive one. A signal records the
  exact triggering line and matched pattern, attaches to the
  TARGET's entry, and never changes standing. Signal absence never
  means "no retraction" (false negatives exist by design).
- Provenance per claim comes from its contribution's interaction:
  ``grounded`` (at least one grounded tool citation),
  ``unverified`` (citations present, none grounded), ``none`` (no
  tool citations). This says what evidence was available in that
  contribution, not that a specific citation supports a specific
  claim.
- Assessment is passed through from the claim record
  (``epistemic_assessment`` + ``assessment_sources``), never
  recomputed here.

Headline rule (reporting contract): a claim is never rendered by
standing alone. Standing, assessment, and provenance travel together.
"""

from __future__ import annotations

import re

__all__ = [
    "compute_claim_standing",
    "format_standing_headline",
    "render_standing_table",
]

# Retraction-language patterns (conservative by design: retract /
# withdraw verb forms only; supersession is a move, not a signal).
_RETRACT_RE = re.compile(r"\b(retract\w*|withdraw\w*)\b", re.IGNORECASE)
# Negation scope: bounded window before the match. Bare "no" is
# deliberately excluded — too broad ("no evidence" is not a negation
# of a withdrawal).
_NEGATION_RE = re.compile(
    r"\b(not|never|don't|doesn't|didn't|do not|does not|did not|cannot)\b",
    re.IGNORECASE,
)
_NEGATION_WINDOW = 40
# Explicit claim references: C6, C12. Ranges (C6-C9, C6–C9, C6—C9)
# expand only for signals, never for moves.
_CLAIM_REF_RE = re.compile(r"C(\d+)")
_RANGE_RE = re.compile(r"C(\d+)\s*[-\u2013\u2014]\s*C(\d+)")
_RANGE_EXPAND_CAP = 50
_SIGNAL_LINE_CAP = 300


def _claim_number(claim_id: str) -> int | None:
    m = re.fullmatch(r"C(\d+)", (claim_id or "").strip())
    return int(m.group(1)) if m else None


def _line_containing(text: str, pos: int) -> str:
    start = text.rfind("\n", 0, pos) + 1
    end = text.find("\n", pos)
    if end == -1:
        end = len(text)
    return text[start:end].strip()[:_SIGNAL_LINE_CAP]


def _expand_reference(text: str) -> list[int]:
    """Claim numbers referenced in text: explicit ids plus range
    expansion (signals only). Duplicates removed, order preserved."""
    seen: list[int] = []

    def add(n: int) -> None:
        if n not in seen:
            seen.append(n)

    for m in _RANGE_RE.finditer(text):
        a, b = int(m.group(1)), int(m.group(2))
        if a <= b and (b - a) <= _RANGE_EXPAND_CAP:
            for n in range(a, b + 1):
                add(n)
        else:
            add(a)
            add(b)
    for m in _CLAIM_REF_RE.finditer(text):
        add(int(m.group(1)))
    return seen


def compute_claim_standing(
    claims: list[dict],
    interactions: list[dict] | None = None,
) -> dict:
    """Derive the standing table from a claim record.

    ``claims`` are claim dicts in registry order (transcript order).
    ``interactions`` are interaction dicts carrying
    ``grounded_tool_citations`` / ``unverified_tool_citations`` counts
    per (participant, phase); when absent, provenance is ``none``.
    Returns ``{"version": 1, "entries": [...]}`` with exactly one
    entry per claim, in claim order.
    """
    interactions = interactions or []
    by_id: dict[str, dict] = {}
    position: dict[str, int] = {}
    for i, claim in enumerate(claims):
        cid = claim.get("id", "")
        by_id[cid] = claim
        position[cid] = i

    # Provenance per (participant, phase) from interaction totals.
    prov_map: dict[tuple[str, str], str] = {}
    for it in interactions:
        key = (it.get("participant", ""), it.get("phase", ""))
        grounded = it.get("grounded_tool_citations")
        unverified = it.get("unverified_tool_citations")
        if grounded is None or unverified is None:
            cits = it.get("tool_citations") or []
            grounded = sum(1 for c in cits if c.get("status") == "grounded")
            unverified = sum(1 for c in cits if c.get("status") == "unverified")
        if grounded > 0:
            prov_map[key] = "grounded"
        elif unverified > 0:
            prov_map[key] = "unverified"
        else:
            prov_map[key] = "none"

    # Collect valid moves and rejected attempts.
    moves_by_target: dict[str, list[dict]] = {c.get("id", ""): [] for c in claims}
    rejected_by_mover: dict[str, list[dict]] = {c.get("id", ""): [] for c in claims}
    for mover in claims:
        mover_id = mover.get("id", "")
        mover_pos = position[mover_id]
        for field, move in (("supersedes", "supersession"), ("withdraws", "withdrawal")):
            target = mover.get(field)
            if not target:
                continue
            if target == mover_id:
                rejected_by_mover[mover_id].append(
                    {"target": target, "move": move, "reason": "self_target"}
                )
                continue
            original = by_id.get(target)
            if original is None:
                rejected_by_mover[mover_id].append(
                    {"target": target, "move": move, "reason": "unknown_target"}
                )
                continue
            if position[target] >= mover_pos:
                rejected_by_mover[mover_id].append(
                    {"target": target, "move": move, "reason": "forward_reference"}
                )
                continue
            if original.get("participant") != mover.get("participant"):
                # Cross-author links are proposals, not moves and not
                # rejections; the link itself stays in the record.
                continue
            moves_by_target[target].append(
                {"move": move, "by": mover_id, "target": target}
            )

    # Retraction-language signals (target entries only, never moves).
    signals_by_target: dict[str, list[dict]] = {c.get("id", ""): [] for c in claims}
    for mover in claims:
        if mover.get("phase") != "revision":
            continue
        text = mover.get("text", "") or ""
        mover_id = mover.get("id", "")
        mover_pos = position[mover_id]
        for m in _RETRACT_RE.finditer(text):
            window = text[max(0, m.start() - _NEGATION_WINDOW) : m.start()]
            kind = "ambiguous" if _NEGATION_RE.search(window) else "signal"
            for num in _expand_reference(text):
                target = f"C{num}"
                original = by_id.get(target)
                if original is None:
                    continue
                if position[target] >= mover_pos:
                    continue
                if original.get("participant") != mover.get("participant"):
                    continue
                signals_by_target[target].append(
                    {
                        "by": mover_id,
                        "pattern": m.group(0),
                        "kind": kind,
                        "text": _line_containing(text, m.start()),
                    }
                )

    entries = []
    for claim in claims:
        cid = claim.get("id", "")
        chain = moves_by_target[cid]
        if chain:
            last = chain[-1]
            standing = "withdrawn" if last["move"] == "withdrawal" else "superseded"
        else:
            standing = "active"
        key = (claim.get("participant", ""), claim.get("phase", ""))
        entries.append(
            {
                "claim_id": cid,
                "participant": claim.get("participant", ""),
                "phase": claim.get("phase", ""),
                "authored_status": claim.get("status", "unknown"),
                "standing": standing,
                "standing_chain": chain,
                "rejected_moves": rejected_by_mover[cid],
                "assessment": claim.get("epistemic_assessment", "unresolved"),
                "assessment_sources": list(claim.get("assessment_sources") or []),
                "provenance": prov_map.get(key, "none"),
                "retraction_signals": signals_by_target[cid],
            }
        )
    return {"version": 1, "entries": entries}


def format_standing_headline(entry: dict) -> str:
    """One claim's three-dimension headline (reporting contract).

    Standing, assessment, and provenance travel together; standing is
    never rendered alone. ``active`` here does NOT mean established,
    verified, or credible — it means only that the claim is still
    being asserted by its author. Retraction signals render as
    ``none``, ``present``, or ``present (ambiguous)`` (ambiguous only
    when every signal is negation-scoped).
    """
    signals = entry.get("retraction_signals") or []
    if not signals:
        signal_text = "none"
    elif any(s.get("kind") == "signal" for s in signals):
        signal_text = "present"
    else:
        signal_text = "present (ambiguous)"
    return (
        f"{entry.get('claim_id', '?')} [authored: "
        f"{entry.get('authored_status', 'unknown')} | standing: "
        f"{entry.get('standing', 'active')} | assessment: "
        f"{entry.get('assessment', 'unresolved')} | retraction signal: "
        f"{signal_text} | provenance: {entry.get('provenance', 'none')}]"
    )


def render_standing_table(table: dict) -> str:
    """Deterministic text rendering of a standing table, in order.

    One headline per entry, in claim order. This is the reporting
    contract's standing table: a deterministic extraction, not a
    model-generated summary.
    """
    lines = [
        "Claim standing (derived from the append-only registry; "
        "the registry itself is untouched):"
    ]
    for entry in table.get("entries", []):
        lines.append(format_standing_headline(entry))
    return "\n".join(lines)
