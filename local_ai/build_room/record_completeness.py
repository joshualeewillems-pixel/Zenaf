"""Mechanical record-completeness checks for synthesis-less meetings.

Synthesis-removal stage 2 (design 2026-10-27, Joshua: drop synthesis
entirely; design §4). Synthesis-coverage is retired: with no synthesis
output there is nothing to compress and no compression verdict to
compute. Its replacement is a check that the RECORD is whole — the
registry + transcript + generation records the runner wrote.

Five checks, all mechanical, all over plain data (no model call, no
judgment of quality). The fifth (standing invariants, registry
standing stage 2) runs only when the caller supplies a standing
table; callers without one get the original four checks:

(a) invited_generations_accounted — every invited generation has
    exactly one outcome (completed, or failed with a reason), and no
    outcome exists without an invitation.
(b) claim_ids_sequential — registry IDs are C1..Cn in order with no
    gaps or duplicates, and each (participant, phase) group's IDs are
    a contiguous run (the runner registers one contribution at a
    time, so a group's IDs are contiguous by construction).
(c) transcript_generation_parity — per invited participant, the
    number of transcript "contribution" entries equals completed
    generations and the number of "failure" entries equals failed
    generations; no contribution entry exists for a participant who
    was never invited. (Transcript "failure" entries from the
    convener, e.g. the no-openings note, are meeting-level notes,
    not generation records, and are ignored here.)
(d) unresolved_objection_derivation — the stored
    unresolved-objection list equals an independent re-derivation
    from the verified challenges, the registry, and the revision
    claims. The re-derivation mirrors
    :func:`local_ai.build_room.meeting.compute_unresolved_objections`
    deliberately: an independent derivation that disagrees with the
    stored list is exactly the failure this check exists to catch.
    If that function changes, this check must change with it.
(e) standing_invariants — the supplied standing table is
    structurally sound against the registry it was derived from:
    every entry references an existing claim; every claim has
    exactly one entry; every chain move references an earlier claim
    by the same author and has a corresponding source claim whose
    link names the target; every chain is deterministically ordered;
    and recomputing the table from the immutable record produces
    identical results. A complete standing table does not imply the
    claims themselves are correct — this check is about the
    accounting, never about truth.

The "omitted proposals/objections" concept does not exist here: for
a synthesis-less meeting nothing is selected down, so there is no
omitted set — only the full record, checked whole.

The checker is pure (plain dicts in, verdict dict out) and imports
nothing from meeting.py, so it stays usable from tests and from any
future artifact reader without pulling in the runner. It may import
the equally pure claim_standing module for the recomputation check.
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Any

from local_ai.build_room.claim_standing import compute_claim_standing

_CLAIM_ID_RE = re.compile(r"^C(\d+)$")


def _check_invited_accounted(
    invited: list[dict[str, str]],
    outcomes: list[dict[str, Any]],
) -> tuple[bool, list[str]]:
    """Check (a): every invited generation accounted for, exactly once."""
    failures: list[str] = []
    inv_keys = [(i["phase"], i["participant"]) for i in invited]
    out_keys = [(o["phase"], o["participant"]) for o in outcomes]
    inv_counts = Counter(inv_keys)
    out_counts = Counter(out_keys)
    for phase, participant in sorted(set(inv_keys) | set(out_keys)):
        label = f"{phase}/{participant}"
        if inv_counts[(phase, participant)] == 0:
            failures.append(f"outcome without invitation: {label}")
        elif out_counts[(phase, participant)] == 0:
            failures.append(f"invited generation unaccounted for: {label}")
        elif out_counts[(phase, participant)] > 1:
            failures.append(
                f"duplicate outcomes for invited generation: {label} "
                f"({out_counts[(phase, participant)]} outcomes)")
        elif inv_counts[(phase, participant)] > 1:
            failures.append(
                f"duplicate invitations for generation: {label} "
                f"({inv_counts[(phase, participant)]} invitations)")
    for o in outcomes:
        label = f"{o['phase']}/{o['participant']}"
        status = o.get("status")
        reason = (o.get("reason") or "").strip() if isinstance(o.get("reason"), str) else ""
        if status == "failed" and not reason:
            failures.append(f"failure without reason: {label}")
        elif status == "completed" and reason:
            failures.append(f"completed generation carries a reason: {label}")
        elif status not in ("completed", "failed"):
            failures.append(f"unknown generation status {status!r}: {label}")
    return (not failures, failures)


def _check_claim_ids(
    claims: list[dict[str, str]],
) -> tuple[bool, list[str]]:
    """Check (b): IDs globally sequential, per-group contiguous."""
    failures: list[str] = []
    ids = [c["id"] for c in claims]
    expected = [f"C{i + 1}" for i in range(len(ids))]
    if ids != expected:
        shown = 0
        for i, (got, want) in enumerate(zip(ids, expected)):
            if got != want and shown < 3:
                failures.append(
                    f"claim ID out of sequence at position {i}: got {got}, want {want}")
                shown += 1
        if len(ids) != len(expected):
            failures.append(
                f"claim count mismatch in sequence check: {len(ids)} claims")
        if not failures:
            failures.append("claim IDs not globally sequential")
    groups: dict[tuple[str, str], list[int]] = {}
    for c in claims:
        match = _CLAIM_ID_RE.match(c["id"])
        if match is None:
            failures.append(f"malformed claim ID: {c['id']!r}")
            continue
        groups.setdefault((c["participant"], c["phase"]), []).append(int(match.group(1)))
    for (participant, phase), nums in sorted(groups.items()):
        for prev, cur in zip(nums, nums[1:]):
            if cur != prev + 1:
                failures.append(
                    f"non-contiguous claim IDs for {participant}/{phase}: "
                    f"C{prev} followed by C{cur}")
                break
    return (not failures, failures)


def _check_transcript_parity(
    transcript_entries: list[dict[str, str]],
    invited: list[dict[str, str]],
    outcomes: list[dict[str, Any]],
) -> tuple[bool, list[str]]:
    """Check (c): transcript entries match generation records."""
    failures: list[str] = []
    seat_names = {i["participant"] for i in invited}
    contributions = Counter(
        e["participant"] for e in transcript_entries if e["kind"] == "contribution")
    transcript_failures = Counter(
        e["participant"] for e in transcript_entries if e["kind"] == "failure")
    completed = Counter(
        o["participant"] for o in outcomes if o.get("status") == "completed")
    failed = Counter(
        o["participant"] for o in outcomes if o.get("status") == "failed")
    for name in sorted(seat_names):
        if contributions[name] != completed[name]:
            failures.append(
                f"transcript contribution count mismatch for {name}: "
                f"{contributions[name]} contribution entries vs "
                f"{completed[name]} completed generations")
        if transcript_failures[name] != failed[name]:
            failures.append(
                f"transcript failure count mismatch for {name}: "
                f"{transcript_failures[name]} failure entries vs "
                f"{failed[name]} failed generations")
    for name in sorted(set(contributions) - seat_names):
        failures.append(
            f"orphan contribution entries for non-invited participant: {name} "
            f"({contributions[name]} entries)")
    return (not failures, failures)


def _derive_unresolved_objections(
    verified_challenges: list[dict[str, Any]],
    claims: list[dict[str, str]],
    revision_claims: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Independent re-derivation of the unresolved-objection list.

    Mirrors compute_unresolved_objections: dedupe by
    (target, source), skip challenges whose target is not in the
    registry, and mark responded_to when the target's author later
    revised that claim (first matching revision claim wins).
    """
    by_id = {c["id"]: c for c in claims}
    seen: set[tuple[str, str]] = set()
    expected: list[dict[str, Any]] = []
    for ch in verified_challenges:
        key = (ch["target_claim_id"], ch["source_claim_id"])
        if key in seen:
            continue
        seen.add(key)
        target = by_id.get(ch["target_claim_id"])
        if target is None:
            continue
        responded_by: str | None = None
        for rev in revision_claims:
            if rev["participant"] != target["participant"]:
                continue
            if (rev.get("relationship_target") == target["id"]
                    or ch["source_claim_id"] in (rev.get("relates_to") or [])):
                responded_by = rev["id"]
                break
        expected.append({
            "claim_id": ch["target_claim_id"],
            "originator": target["participant"],
            "cited_by": ch["challenger"],
            "moves": [ch["move"]],
            "source_claim_id": ch["source_claim_id"],
            "state": "responded_to" if responded_by else "unresolved",
            "responded_by": responded_by,
        })
    return expected


def _check_objection_derivation(
    verified_challenges: list[dict[str, Any]],
    claims: list[dict[str, str]],
    revision_claims: list[dict[str, Any]],
    unresolved_objections: list[dict[str, Any]],
) -> tuple[bool, list[str]]:
    """Check (d): stored derivation equals the re-derivation."""
    failures: list[str] = []
    expected = _derive_unresolved_objections(
        verified_challenges, claims, revision_claims)
    if expected == unresolved_objections:
        return (True, [])
    exp_by_key = {(e["claim_id"], e["source_claim_id"]): e for e in expected}
    act_by_key = {(e["claim_id"], e["source_claim_id"]): e
                  for e in unresolved_objections}
    for key in sorted(set(exp_by_key) - set(act_by_key)):
        failures.append(f"missing unresolved-objection entry: {key[0]} <- {key[1]}")
    for key in sorted(set(act_by_key) - set(exp_by_key)):
        failures.append(f"extra unresolved-objection entry: {key[0]} <- {key[1]}")
    for key in sorted(set(exp_by_key) & set(act_by_key)):
        if exp_by_key[key] != act_by_key[key]:
            failures.append(
                f"mismatched unresolved-objection entry {key[0]} <- {key[1]}: "
                f"stored {act_by_key[key]!r}, derived {exp_by_key[key]!r}")
    if len(expected) != len(unresolved_objections) and not failures:
        failures.append(
            f"unresolved-objection count mismatch: stored "
            f"{len(unresolved_objections)}, derived {len(expected)}")
    return (not failures, failures)


def _check_standing_invariants(
    claims_full: list[dict[str, Any]],
    interactions: list[dict[str, Any]],
    standing_table: dict[str, Any],
) -> tuple[bool, list[str]]:
    """Check (e): the standing table is sound against its record.

    Structural invariants (1)–(5) are checked on the supplied table;
    invariant (6) recomputes the table from the immutable record and
    requires identical results. Any failure here means the standing
    accounting cannot be trusted — it never means the underlying
    claims are true or false.
    """
    failures: list[str] = []
    by_id = {c["id"]: c for c in claims_full}
    position = {c["id"]: i for i, c in enumerate(claims_full)}
    entries = standing_table.get("entries", []) if isinstance(standing_table, dict) else []
    entry_ids = [e.get("claim_id", "") for e in entries if isinstance(e, dict)]

    # (1) every entry references an existing claim.
    for cid in entry_ids:
        if cid not in by_id:
            failures.append(f"standing entry references unknown claim: {cid}")
    # (4) exactly one entry per claim.
    counts = Counter(entry_ids)
    for cid in sorted(set(entry_ids) | set(by_id)):
        if counts[cid] == 0:
            failures.append(f"claim without standing entry: {cid}")
        elif counts[cid] > 1:
            failures.append(
                f"duplicate standing entries for claim: {cid} ({counts[cid]} entries)")

    # (2)/(3)/(5) over every chain move.
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        target_id = entry.get("claim_id", "")
        target = by_id.get(target_id)
        chain = entry.get("standing_chain", []) or []
        prev_pos: int | None = None
        for move in chain:
            mover_id = move.get("by", "")
            mover = by_id.get(mover_id)
            if mover is None:
                failures.append(
                    f"standing move without source claim: {move.get('move', '?')} "
                    f"by {mover_id} on {target_id}")
                continue
            if target is None:
                continue  # already reported under (1)
            if position[target_id] >= position[mover_id]:
                failures.append(
                    f"standing move not to an earlier claim: {move.get('move', '?')} "
                    f"by {mover_id} on {target_id}")
            if mover.get("participant") != target.get("participant"):
                failures.append(
                    f"standing move cross-author: {move.get('move', '?')} "
                    f"by {mover_id} on {target_id}")
            field = "withdraws" if move.get("move") == "withdrawal" else "supersedes"
            if mover.get(field) != target_id:
                failures.append(
                    f"standing move without matching source link: {move.get('move', '?')} "
                    f"by {mover_id} on {target_id}")
            mover_pos = position[mover_id]
            if prev_pos is not None and mover_pos <= prev_pos:
                failures.append(
                    f"standing chain not deterministically ordered for {target_id}")
            prev_pos = mover_pos

    # (6) recomputation from the immutable record must be identical.
    try:
        expected = compute_claim_standing(claims_full, interactions)
    except Exception as exc:  # recomputation bug, not a pass
        failures.append(f"standing recomputation raised {type(exc).__name__}: {exc}")
        return (False, failures)
    if expected != standing_table:
        exp_by_id = {e.get("claim_id", ""): e for e in expected.get("entries", [])}
        act_by_id = {e.get("claim_id", ""): e for e in entries}
        differing = sorted(
            cid for cid in set(exp_by_id) | set(act_by_id)
            if exp_by_id.get(cid) != act_by_id.get(cid))
        shown = ", ".join(differing[:3])
        failures.append(
            "standing table differs from recomputation"
            + (f" (first differing: {shown})" if shown else ""))
    return (not failures, failures)


def check_standing_invariants(
    claims_full: list[dict[str, Any]],
    interactions: list[dict[str, Any]],
    standing_table: dict[str, Any],
) -> tuple[bool, list[str]]:
    """Public entry point for the standing-invariants check alone.

    Added for the migration execution route (design v2), which must
    verify each would-be and persisted table without running the
    other four record checks (stored artifacts carry no live
    generation records to check). Delegates to
    :func:`_check_standing_invariants` without new logic.
    """
    return _check_standing_invariants(claims_full, interactions, standing_table)


def check_record_completeness(
    *,
    invited_generations: list[dict[str, str]],
    generation_outcomes: list[dict[str, Any]],
    transcript_entries: list[dict[str, str]],
    claims: list[dict[str, str]],
    verified_challenges: list[dict[str, Any]],
    revision_claims: list[dict[str, Any]],
    unresolved_objections: list[dict[str, Any]],
    claims_full: list[dict[str, Any]] | None = None,
    interactions: list[dict[str, Any]] | None = None,
    standing_table: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run the record-completeness checks over a meeting record.

    Inputs are plain data (see module docstring for shapes). Returns
    ``{"passed": bool, "checks": {name: {"passed": bool,
    "failures": [str, ...]}}}``. ``passed`` is True only when all
    included checks pass. The standing-invariants check runs only
    when ``claims_full``, ``interactions``, and ``standing_table``
    are all supplied; callers without a standing table (older tests,
    replay paths) get the original four checks. This reports
    wholeness; it never judges the quality of anything in the record.
    """
    checks = {
        "invited_generations_accounted": _check_invited_accounted(
            invited_generations, generation_outcomes),
        "claim_ids_sequential": _check_claim_ids(claims),
        "transcript_generation_parity": _check_transcript_parity(
            transcript_entries, invited_generations, generation_outcomes),
        "unresolved_objection_derivation": _check_objection_derivation(
            verified_challenges, claims, revision_claims, unresolved_objections),
    }
    if claims_full is not None and interactions is not None and standing_table is not None:
        checks["standing_invariants"] = _check_standing_invariants(
            claims_full, interactions, standing_table)
    return {
        "passed": all(passed for passed, _ in checks.values()),
        "checks": {
            name: {"passed": passed, "failures": failures}
            for name, (passed, failures) in checks.items()
        },
    }
