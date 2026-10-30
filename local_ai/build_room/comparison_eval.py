"""Blind evaluation machinery for the Moneyball role-only comparison.

Deliberately small: a label-stripping function, a scoring sheet, and
view computation. That is the entire machinery — if it grows beyond
a script plus a sheet, it has violated the adopted constraint and
must be cut back.

HUMAN JUDGES DO THE JUDGING. This module never scores content, never
groups claims on its own, and never sees a model identity except
through the private mapping file, which is written separately from
the scored rows and rejoined only AFTER scoring is complete.

Scoring flow:
  1. ``strip_labels`` turns registry claims into blind rows
     (blind_id, claim text, phase, status, citations) plus a mapping
     file {blind_id: participant}. Judges NEVER see the mapping.
  2. Judges fill the sheet: per-claim scores (useful_unique,
     grounding, actionability, failure_mode_validity, redundant)
     plus ``group_id`` — claims expressing substantially the same
     insight share one group id, however many numbered claims they
     were split into. A group counts ONCE in the distinct view.
  3. After scoring, ``rejoin_mapping`` attaches participants to the
     scored rows (post-scoring only).
  4. ``compute_views`` reports the two views: (a) useful, distinct
     contributions per reservation dollar; (b) highest-impact
     validated contribution. Both views are labeled
     reservation-dollar efficiency, NEVER verified economic
     efficiency (non-GPT costs are estimates).

GPT is an unbriefed PARTICIPANT, not a control: its contributions
are compared across conditions like any other model's, but GPT
differences NEVER invalidate a packet pair (registry-mediated
differences are information, not failure).
"""

from __future__ import annotations

import csv
import io
from typing import Any

# Claim-dict keys that identify a model. Everything else is scored
# material (claim ids are per-meeting sequential, not identifying).
STRIPPED_KEYS: frozenset[str] = frozenset(
    {"participant", "model", "provider", "seat", "author"}
)

SHEET_COLUMNS: tuple[str, ...] = (
    "blind_id",
    "claim_id",
    "phase",
    "claim_text",
    "group_id",
    "useful_unique",
    "grounding",
    "actionability",
    "failure_mode_validity",
    "redundant",
    "highest_impact",
    "judge_disagreement",
    "notes",
)


def strip_labels(claims: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, str]]:
    """Strip model identity from registry claims for blind scoring.

    Returns (blind_rows, mapping). Blind ids are stable in input
    order ("B001", "B002", ...). The mapping {blind_id: participant}
    is PRIVATE custody: it must be stored separately from the scored
    rows and never shared with any judge until scoring is complete.
    A claim without a participant is kept with mapping value None
    (judges still score it; it simply cannot be attributed later).
    """
    rows: list[dict[str, Any]] = []
    mapping: dict[str, str] = {}
    for index, claim in enumerate(claims, start=1):
        blind_id = f"B{index:03d}"
        row = {k: v for k, v in claim.items() if k not in STRIPPED_KEYS}
        row["blind_id"] = blind_id
        rows.append(row)
        mapping[blind_id] = claim.get("participant")
    return rows, mapping


def new_scoring_sheet(blind_rows: list[dict[str, Any]]) -> str:
    """Render an empty scoring sheet (CSV) for blind rows.

    Score columns are left blank for human judges. ``group_id`` is
    the semantic grouping column: judges assign the same group id
    to claims expressing substantially the same insight, even if
    phrased differently or split into multiple numbered claims.
    """
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=SHEET_COLUMNS)
    writer.writeheader()
    for row in blind_rows:
        writer.writerow({
            "blind_id": row.get("blind_id", ""),
            "claim_id": row.get("id", ""),
            "phase": row.get("phase", ""),
            "claim_text": row.get("text", ""),
            "group_id": "",
            "useful_unique": "",
            "grounding": "",
            "actionability": "",
            "failure_mode_validity": "",
            "redundant": "",
            "highest_impact": "",
            "judge_disagreement": "",
            "notes": "",
        })
    return buf.getvalue()


def rejoin_mapping(
    scored_rows: list[dict[str, Any]], mapping: dict[str, str]
) -> list[dict[str, Any]]:
    """Attach participants to scored rows. POST-SCORING ONLY.

    Call this only after all judging (including grouping) is
    complete. The returned rows carry "participant" again, for
    per-model view computation. Never call it before scoring.
    """
    rejoined = []
    for row in scored_rows:
        merged = dict(row)
        merged["participant"] = mapping.get(row.get("blind_id", ""))
        rejoined.append(merged)
    return rejoined


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in ("true", "yes", "y", "1", "useful")
    return bool(value)


def group_scored_rows(
    scored_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Collapse scored claim rows into semantic groups.

    Rows sharing a non-empty ``group_id`` form one group; rows with
    an empty group id each form their own singleton group. A group
    is useful when ANY of its claims is marked useful_unique, is
    redundant when ALL of its claims are marked redundant, is
    grounded when ANY claim is grounded, is actionable when ANY
    claim is actionable, and carries the best failure-mode validity
    among its claims (real > plausible-but-unverified > wrong).
    ``highest_impact`` on a group means a judge flagged at least one
    of its claims as the highest-impact contribution.
    """
    groups: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for row in scored_rows:
        gid = (row.get("group_id") or "").strip()
        if not gid:
            gid = f"__single__:{row.get('blind_id', '')}"
        if gid not in groups:
            groups[gid] = {
                "group_id": gid,
                "model": row.get("participant"),
                "condition": row.get("condition"),
                "claim_ids": [],
                "useful": False,
                "redundant": True,
                "grounded": False,
                "actionable": False,
                "failure_validity": None,
                "highest_impact": False,
                "judge_disagreement": False,
            }
            order.append(gid)
        group = groups[gid]
        group["claim_ids"].append(row.get("claim_id", ""))
        if _truthy(row.get("useful_unique")):
            group["useful"] = True
        if not _truthy(row.get("redundant")):
            group["redundant"] = False
        grounding = (row.get("grounding") or "").strip().lower()
        if grounding in ("grounded", "true", "yes"):
            group["grounded"] = True
        if _truthy(row.get("actionability")):
            group["actionable"] = True
        validity = (row.get("failure_mode_validity") or "").strip().lower()
        rank = {"real": 3, "plausible-but-unverified": 2, "plausible": 2,
                "wrong": 1}
        current = group["failure_validity"]
        current_rank = rank.get((current or "").lower(), 0)
        if rank.get(validity, 0) > current_rank:
            group["failure_validity"] = validity
        if _truthy(row.get("highest_impact")):
            group["highest_impact"] = True
        if _truthy(row.get("judge_disagreement")):
            group["judge_disagreement"] = True
    return [groups[gid] for gid in order]


def _validated(group: dict[str, Any]) -> bool:
    """A group counts as validated: grounded AND (actionable or a
    real failure mode). Validation is a judge verdict, never
    mechanical."""
    return bool(group["grounded"]) and (
        bool(group["actionable"]) or group["failure_validity"] == "real"
    )


def compute_views(
    scored_rows: list[dict[str, Any]],
    costs: dict[tuple[str, str], float],
) -> dict[str, Any]:
    """Compute the two reported views from scored rows.

    ``scored_rows`` are post-rejoin rows (participant + condition
    present) with judge-filled columns, including ``group_id``.
    ``costs`` maps (model, condition) -> admitted reservation cost
    for that meeting. A missing or zero cost yields ratio None —
    never a division by zero, never an invented cost.

    View (a): useful, distinct contributions per reservation
    dollar — distinct useful non-redundant groups ÷ cost, per
    model per condition. View (b): highest-impact validated
    contribution — flagged groups that are validated, per model
    per condition (all flagged groups reported; none flagged
    yields an empty list, never a silent pick). Both views are labeled
    reservation-dollar efficiency in the report, never verified
    economic efficiency.
    """
    groups = group_scored_rows(scored_rows)
    per_model: dict[tuple[str, str], dict[str, Any]] = {}
    for group in groups:
        key = (group["model"], group["condition"])
        entry = per_model.setdefault(key, {
            "distinct_useful_nonredundant": 0,
            "highest_impact_validated": [],
            "groups": 0,
        })
        entry["groups"] += 1
        if group["useful"] and not group["redundant"]:
            entry["distinct_useful_nonredundant"] += 1
        if group["highest_impact"] and _validated(group):
            entry["highest_impact_validated"].append(group)
    views: dict[str, Any] = {}
    for key, entry in per_model.items():
        cost = costs.get(key)
        ratio = None
        if cost:
            ratio = entry["distinct_useful_nonredundant"] / cost
        views[f"{key[0]}|{key[1]}"] = {
            "distinct_useful_nonredundant": entry["distinct_useful_nonredundant"],
            "reservation_cost_usd": cost,
            "distinct_per_reservation_dollar": ratio,
            "highest_impact_validated_claim_ids": [
                g["claim_ids"] for g in entry["highest_impact_validated"]
            ],
            "groups_scored": entry["groups"],
        }
    return views


def assert_phase1_base_prompts_equal(capture_a: dict[str, Any], capture_b: dict[str, Any]) -> None:
    """Assert byte-identical Phase 1 base prompts for a packet pair.

    Compares the "opening" base-prompt hashes from two meetings'
    comparison captures. A mismatch is a BUILD BUG and invalidates
    that packet pair. Later-phase hashes are deliberately NOT
    compared here: see :func:`later_phase_hashes`.
    """
    hash_a = (capture_a.get("base_prompt_hashes") or {}).get("opening")
    hash_b = (capture_b.get("base_prompt_hashes") or {}).get("opening")
    if hash_a is None or hash_b is None:
        raise AssertionError(
            "missing Phase 1 base-prompt hash in a comparison capture; "
            "cannot verify the role-only guarantee"
        )
    if hash_a != hash_b:
        raise AssertionError(
            f"Phase 1 base-prompt mismatch for packet "
            f"{capture_a.get('packet_work_item')!r}: A={hash_a} B={hash_b}. "
            "The ONLY sanctioned difference is the appended brief; "
            "a Phase 1 base difference is a build bug."
        )


def later_phase_hashes(capture: dict[str, Any]) -> dict[str, str]:
    """Later-phase base-prompt hashes, for traceability ONLY.

    These are NEVER required to match across conditions and NEVER
    a failure signal: Phase 2/3 prompts contain the generated
    registry, which SHOULD differ if the briefs work. Record them,
    compare them for the report if useful, but do not assert on
    them.
    """
    hashes = capture.get("base_prompt_hashes") or {}
    return {phase: h for phase, h in hashes.items() if phase != "opening"}
