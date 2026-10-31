"""Build-room draft artifact, R1.

Clearly marked EXPERIMENTAL. This is NOT a first-class review item
(R3 wires that): it carries no verdict affordance and no execution
affordance. Its authorization text is load-bearing — the artifact
RECOMMENDS and never authorizes (spec §4 authorization boundary).
"""

from __future__ import annotations

from typing import Any

from local_ai.build_room.claim_standing import (
    compute_claim_standing,
    render_standing_table,
)
from local_ai.build_room.participants import OpenAIParticipant, Seat
from local_ai.build_room.dispositions import (
    convener_close,
    extract_proposals,
)
from local_ai.build_room.transjective_record import (
    adapt_claims_to_contract_inputs,
    build_transjective_record,
)

AUTHORIZATION_TEXT = (
    "DRAFT EXPERIMENTAL ARTIFACT — RECOMMENDS ONLY. "
    "This artifact does not authorize execution: no file modification, "
    "no PR creation, no consequential action follows from it. "
    "Execution requires Joshua's explicit authorization, separate from "
    "any approval of the design elements discussed here."
)

CLAIMS_NOTE = (
    "Substantive claims in this artifact are model-authored and "
    "experimental, not verified metadata."
)


def build_draft_artifact(
    meeting_id: str,
    packet: Any,
    transcript: Any,
    participant: OpenAIParticipant | None,
    *,
    contribution: str | None = None,
    failure: str | None = None,
) -> dict[str, Any]:
    """Build the draft artifact dict from a finished (or failed) meeting."""
    if participant is None:
        provenance = {"participant": "GPT", "provider": "openai", "model": None,
                      "status": "absent"}
    else:
        provenance = {"participant": "GPT", "provider": "openai",
                      "model": participant.model,
                      "key_source": participant.key_source,
                      "status": "present"}
    return {
        "status": "DRAFT_EXPERIMENTAL",
        "is_review_item": False,
        "experimental_area": True,
        "authorization": AUTHORIZATION_TEXT,
        "claims_note": CLAIMS_NOTE,
        "meeting_id": meeting_id,
        "work_item": packet.work_item,
        "question": packet.question,
        "recommendation": contribution,
        "failure": failure,
        "provenance": provenance,
        "transcript_entries": len(transcript.entries),
    }


LANGUAGE_NOTE = (
    "Review surface language: this artifact is in English. "
    "Transcript contributions are verbatim and may "
    "include transliterable seat-to-seat shorthand."
)


def build_draft_artifact_r2(
    meeting_id: str,
    packet: Any,
    transcript: Any,
    seats: list[Seat],
    registry: Any,
    *,
    interactions: list[dict[str, Any]] | None = None,
    unresolved_objections: list[dict] | None = None,
    delta_report: dict[str, Any] | None = None,
    generation_timestamps: dict[str, dict[str, float]] | None = None,
    record_complete: bool = False,
    deliberation_complete: bool = False,
    ok: bool = False,
    record_completeness: dict[str, Any] | None = None,
    tool_access: dict[str, Any] | None = None,
    claim_standing: dict[str, Any] | None = None,
    transjective_record: dict[str, Any] | None = None,
    payload_evidence: dict[str, str] | None = None,
    disagreements: list[dict] | None = None,
) -> dict[str, Any]:
    """Build the R2 draft artifact dict (synthesis-less).

    Same boundaries as R1 (DRAFT_EXPERIMENTAL, recommends-only, not a
    review item, claims note) plus the R2 structures: the mechanical
    claim registry, per-response interactions (citations + stated
    moves + mechanical addressability — NOT a genuineness score),
    and the mechanical unresolved-objection derivation. Nothing here
    is marked resolved by the room; resolution is Joshua's verdict.
    There is NO synthesis in this artifact, by design (2026-10-27,
    Joshua: drop synthesis entirely): synthesis fields are absent,
    not failed, and ``synthesis_removed`` marks that explicitly.
    Status fields (design §3B): ``record_complete`` (every expected
    generation accounted for), ``deliberation_complete`` (required
    phases actually completed), ``ok`` (both). Unresolved
    objections are mechanical derivations, labeled as such.
    ``record_completeness`` (stage 2, design §4) is the runner's
    four mechanical checks over the record itself — invited
    generations accounted for, claim IDs sequential, transcript /
    generation parity, unresolved-objection derivation — reported
    as ``{"passed": bool, "checks": {...}}``. Replay paths pass
    nothing (no live generation records exist to check) and get
    the ``not_checked`` placeholder below instead of a fake pass.
    """
    provenance = []
    for seat in seats:
        if seat.participant is None:
            provenance.append({
                "participant": seat.name, "provider": seat.provider_id,
                "model": seat.model, "status": "absent",
            })
        else:
            provenance.append({
                "participant": seat.name, "provider": seat.provider_id,
                "model": seat.participant.model,
                "key_source": seat.participant.key_source,
                "status": "present",
            })
    # Registry standing section: the runner's checked table when
    # supplied, else a fresh computation (replay paths). Computed
    # once so the section and its rendering cannot disagree.
    standing_section = (
        claim_standing
        if claim_standing is not None
        else compute_claim_standing(
            [c.to_dict() for c in registry.claims], interactions or []
        )
    )
    # Transjective record (accepted schema contract, 2026-10-30):
    # adapter-derived contract validation + derived contract standing
    # over the same registry. Computed at build time like
    # claim_standing, under its OWN key — it never overwrites
    # claim_standing, and the registry itself is untouched.
    # Increment C: deterministic convener-close runs here, at artifact
    # build — the single funnel for live meetings and replays. It
    # extracts proposals + challenge candidates from the registry,
    # with NO structured acceptance input (none exists in live runs
    # yet; prose is never parsed into acceptance) and NO meeting-rule
    # registry (none exists yet). Consequence, by design: close from
    # the runner issues contested-standing events where the §4.3 bar
    # holds, and leaves every other proposal pending with a refusal
    # reason. Proposal-driven events await an acceptance input path
    # (convener tooling or a future increment), which C does not
    # invent. Close results ride into the section under their own
    # keys; a pre-supplied transjective_record bypasses close (the
    # caller owns it then).
    # Increment D: the same close funnel accepts convener-recorded
    # disagreement pairs (explicit input only — no producer exists
    # in live runs yet, and no model-emitted incompatibility parser
    # is built in v1, deliberately). Pairs ride into the section
    # under their own key when supplied; when None, no new key
    # appears. Disagreements never move standing and add no events:
    # any §4.3 contested-standing event comes from C's challenge
    # machinery above, never from a disagreement record itself.
    if transjective_record is not None:
        transjective_section = transjective_record
    else:
        _close_claims = [c.to_dict() for c in registry.claims]
        _adapted = adapt_claims_to_contract_inputs(_close_claims)
        _props, _chals = extract_proposals(
            _close_claims, _adapted["declarations"])
        _close = convener_close(
            _close_claims, _props, [], _chals,
            meeting_kind="build_council", meeting_rules=[])
        transjective_section = build_transjective_record(
            _close_claims,
            payload_evidence=payload_evidence,
            proposals=_close["proposals"],
            events=_close["events"],
            close_report={
                "issued_event_ids": [e["event_id"]
                                     for e in _close["events"]],
                "refusals": _close["refusals"],
                "unmatched_acceptances": _close["unmatched_acceptances"],
            },
            disagreements=disagreements)
    return {
        "status": "DRAFT_EXPERIMENTAL",
        "is_review_item": False,
        "experimental_area": True,
        "authorization": AUTHORIZATION_TEXT,
        "claims_note": CLAIMS_NOTE,
        "language_note": LANGUAGE_NOTE,
        "meeting_id": meeting_id,
        "work_item": packet.work_item,
        "question": packet.question,
        "claim_registry": [c.to_dict() for c in registry.claims],
        # Registry standing (stage 1, design v2): a derived view over
        # the append-only registry — effective standing, chain,
        # assessment, provenance, and retraction signals per claim.
        # The registry itself is untouched; this section is computed
        # at build time and recomputable from the stored record.
        # The runner passes the table it already had checked (stage
        # 2), so the artifact's section and the checked table are
        # identical; direct callers (replays) get a fresh computation.
        # R1 artifacts (no registry) do not carry it.
        "claim_standing": standing_section,
        # Transjective record (accepted schema contract, 2026-10-30):
        # adapter-derived validation + derived contract standing, under
        # its own key, computed at build time. Old captures are
        # expected to be non-conformant; that is correct behavior.
        "transjective_record": transjective_section,
        # Registry standing stage 2: the reporting contract's
        # standing table — deterministic rendering of the same
        # section, one three-dimension headline per claim. Standing
        # is never rendered without assessment and provenance.
        "standing_report": render_standing_table(standing_section),
        "interactions": interactions or [],
        "unresolved_objections": unresolved_objections or [],
        "unresolved_objections_evaluation": "mechanical",
        "delta_report": delta_report or {
            "revision_chains": [],
            "synthesis_elements_from_later_phases": [],
            "unclassified_candidates": [],
        },
        # Synthesis removal (2026-10-27, Joshua): synthesis fields
        # are ABSENT by design, not failed. This marker is what
        # distinguishes a synthesis-less artifact from a failed
        # synthesis in a historical artifact (design §3C).
        "synthesis_removed": True,
        "synthesis_removal_decision": "2026-10-27, Joshua: drop synthesis entirely",
        "record_complete": record_complete,
        "deliberation_complete": deliberation_complete,
        "ok": ok,
        # Stage 2: always present. Live meetings carry the computed
        # checks; replays (no generation records) carry an honest
        # not_checked marker, never a fabricated pass.
        "record_completeness": record_completeness if record_completeness is not None else {
            "status": "not_checked",
            "reason": "replay reconstruction: no live generation records to check",
        },
        # Tool access (stage-1 increments B + C): always present.
        # Live meetings carry the flag state, the capable/packet-only
        # split, the nominated set, the snapshot revision, and the
        # full runner-kept tool-call log, plus (increment C) the
        # tool usage summary (generations and tool-round calls
        # stated separately) and citation-validation totals
        # (grounded vs unverified; no grounding score exists).
        # Replays (no live generations) carry an honest note, never
        # a fabricated log.
        "tool_access": tool_access if tool_access is not None else {
            "enabled": False,
            "note": "no tool-enabled generations in this record",
        },
        "provenance": provenance,
        "generation_timestamps": generation_timestamps or {},
        "transcript_entries": len(transcript.entries),
    }
