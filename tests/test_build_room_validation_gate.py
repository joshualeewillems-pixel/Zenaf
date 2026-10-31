"""Increment G tests: validation-in-the-loop gate.

No live generations, no provider calls, no real keys anywhere. The
gate REPORTS; it never repairs, never generates declarations, and
never rewrites a capture into conformance (plan Rev 2 correction 4).
Every test below asserts reporting behavior: exact error codes for
fixtures, interim vs final labeling, and byte-identical inputs after
the gate runs.

Coverage maps to the plan's G acceptance: synthetic conformant
fixture -> zero errors; malformed block (E6) and invalid kind (E4);
missing acceptance (proposal, no event, standing open);
dangling targets (E1/E2); absent declaration (unknown + reason +
warnings, not repaired); SPEC adapter output (C89 {E7}, C94
{E7, E13}); interim vs final escalation (W2 -> E12); no-fabrication
negatives; artifact carrying interim + final; runner end-to-end.
"""

from __future__ import annotations

import copy

from local_ai.build_room.artifact import build_draft_artifact_r2
from local_ai.build_room.declarations import (
    REASON_ABSENT,
    REASON_MALFORMED,
    extract_declaration_block,
    parse_declaration_block,
)
from local_ai.build_room.dispositions import convener_close, extract_proposals
from local_ai.build_room.exposure import unknown_exposure
from local_ai.build_room.meeting import (
    Claim,
    ClaimRegistry,
    EvidencePacket,
    run_multi_model_meeting,
)
from local_ai.build_room.participants import SEAT_SPECS, Seat
from local_ai.build_room.transjective_record import (
    adapt_claims_to_contract_inputs,
    build_transjective_record,
)
from local_ai.build_room.validation_gate import interim_validation_report


# ---------------------------------------------------------------- helpers


def _claim(cid, who, phase, text="", **kw):
    d = {"id": cid, "participant": who, "phase": phase, "text": text}
    d.update(kw)
    return d


def _present(*visible):
    """Native exposure_ref shape (Increment B): present + visible ids."""
    return {"payload_ref": "payload_evidence:deadbeef",
            "payload_hash": "deadbeef", "evidence": "present",
            "visible_ids": list(visible)}


def _codes(report_or_section):
    validation = report_or_section.get("validation", report_or_section)
    return {e["code"] for e in validation["errors"]}


def _wcodes(report_or_section):
    validation = report_or_section.get("validation", report_or_section)
    return {w["code"] for w in validation["warnings"]}


def _native_decl(target, kind="extends"):
    return {"target_claim": target, "kind": kind, "layer": "declared",
            "note": "native declaration"}


def _runner_claim_from_outcome(cid, who, phase, outcome, block, **kw):
    """Mirror the runner's declaration-outcome mapping onto a claim dict.

    Mirrors meeting.py: outcome fields ride on the claim, the raw
    block is preserved verbatim, None-valued fields are omitted (as
    Claim.to_dict omits them).
    """
    d = _claim(cid, who, phase, "", **kw)
    d["target_state"] = outcome["target_state"]
    d["target_state_set_by"] = outcome["target_state_set_by"]
    if outcome["uncertainty_reason"] is not None:
        d["uncertainty_reason"] = outcome["uncertainty_reason"]
    if outcome["declarations"] is not None:
        d["declarations"] = outcome["declarations"]
    if outcome["declaration_parse_failure"] is not None:
        d["declaration_parse_failure"] = outcome["declaration_parse_failure"]
    if block is not None:
        d["declaration_raw"] = block
    return d


# ---------------------------------------------------------------- 1. conformant


def test_conformant_fixture_zero_errors_final_and_interim():
    claims = [
        _claim("C1", "GPT", "opening", "Opening claim.",
               exposure_ref=_present()),
        _claim("C2", "Claude", "response", "Response claim.",
               target_state="populated", target_state_set_by="author",
               declarations=[_native_decl("C1")],
               exposure_ref=_present("C1")),
    ]
    section = build_transjective_record(claims)
    assert section["validation_phase"] == "final"
    assert section["conformant"] is True
    assert section["validation"]["errors"] == []
    # Warnings do not break conformance: the opening claim is unknown
    # with reason (no targets declared), which warns W1.
    assert "W1" in _wcodes(section)

    interim = interim_validation_report(claims, meeting_phase="response")
    assert interim["phase"] == "interim"
    assert interim["meeting_phase"] == "response"
    assert interim["conformant"] is True
    assert interim["errors"] == []
    assert interim["claim_count"] == 2


# ---------------------------------------------------------------- 2. malformed / invalid kind


def test_malformed_block_fixture_e6_raw_preserved():
    text = ("1. Inferred: Some claim.\n"
            "Declarations (declaration-block-v1):\n"
            "garbage line here\n")
    _, block = extract_declaration_block(text)
    assert block is not None
    outcome = parse_declaration_block(block, 1)[0]
    assert outcome["target_state"] == "unknown"
    assert outcome["uncertainty_reason"] == REASON_MALFORMED
    assert outcome["declaration_parse_failure"] is not None
    assert outcome["declarations"] is None

    claim = _runner_claim_from_outcome(
        "C2", "Claude", "response", outcome, block,
        exposure_ref=_present())
    section = build_transjective_record([claim])
    assert section["conformant"] is False
    assert _codes(section) == {"E6"}
    # Failure preserved and reported, not repaired: the input claim
    # still carries the raw block and parse-failure record verbatim
    # after the gate ran (the gate never mutates its inputs), and the
    # section records the unknown state with its reason.
    assert claim["declaration_raw"] == block
    assert claim["declaration_parse_failure"] == \
        outcome["declaration_parse_failure"]
    assert section["target_states"]["C2"]["state"] == "unknown"
    assert section["target_states"]["C2"]["uncertainty_reason"] == \
        REASON_MALFORMED


def test_invalid_kind_fixture_e4_not_e6_declarations_kept():
    text = ("1. Inferred: Some claim.\n"
            "Declarations (declaration-block-v1):\n"
            "1: frobs C1\n")
    _, block = extract_declaration_block(text)
    outcome = parse_declaration_block(block, 1)[0]
    assert outcome["target_state"] == "unknown"
    assert outcome["declarations"] is not None
    assert outcome["declarations"][0]["kind"] == "frobs"
    assert outcome["declaration_parse_failure"] is None

    claims = [
        _claim("C1", "GPT", "opening", "Opening claim.",
               exposure_ref=_present()),
        _runner_claim_from_outcome(
            "C2", "Claude", "response", outcome, block,
            exposure_ref=_present("C1")),
    ]
    section = build_transjective_record(claims)
    assert section["conformant"] is False
    assert _codes(section) == {"E4"}
    # Invalid-kind declarations are preserved verbatim (E4 fires on
    # them); the plan's E4-else-E6 mapping means no E6 alongside.
    kept = [d for d in section["declarations"]
            if d["source_claim"] == "C2"]
    assert kept and kept[0]["kind"] == "frobs"


# ---------------------------------------------------------------- 3. missing acceptance


def test_missing_acceptance_fixture_proposal_no_event_standing_open():
    claims = [
        _claim("C1", "GPT", "opening", "Opening claim.",
               exposure_ref=_present()),
        _claim("C2", "Claude", "revision", "Corrects C1.",
               relates_to=["C1"], relationship="corrects",
               exposure_ref=_present("C1")),
    ]
    adapted = adapt_claims_to_contract_inputs(claims)
    props, chals = extract_proposals(claims, adapted["declarations"])
    assert len(props) == 1
    assert props[0]["proposed_standing"] == "revised"
    assert props[0]["target_claim"] == "C1"
    close = convener_close(claims, props, [], chals,
                           meeting_kind="build_council", meeting_rules=[])
    # No acceptance input exists: nothing is issued, nothing is
    # enacted. The proposal stays pending with a refusal reason.
    assert close["events"] == []
    assert close["proposals"][0]["id"] == props[0]["id"]

    section = build_transjective_record(
        claims, proposals=close["proposals"], events=close["events"],
        close_report={
            "issued_event_ids": [],
            "refusals": close["refusals"],
            "unmatched_acceptances": close["unmatched_acceptances"],
        })
    assert section["contract_standing"]["C1"] == "open"
    assert section["validation"]["errors"] == []
    assert section["proposals"][0]["id"] == props[0]["id"]


# ---------------------------------------------------------------- 4. dangling targets


def test_dangling_target_fixture_e1():
    claims = [
        _claim("C1", "GPT", "opening", "Opening claim.",
               exposure_ref=_present()),
        _claim("C2", "Claude", "response", "Response claim.",
               target_state="populated", target_state_set_by="author",
               declarations=[_native_decl("C1"), _native_decl("C99")],
               exposure_ref=_present("C1", "C99")),
    ]
    section = build_transjective_record(claims)
    # The valid declaration to C1 keeps the populated state honest,
    # so the dangling target fires exactly E1 (no companion E6).
    assert _codes(section) == {"E1"}
    assert section["conformant"] is False


def test_forward_reference_fixture_e2():
    claims = [
        _claim("C1", "GPT", "opening", "Opening claim.",
               exposure_ref=_present()),
        _claim("C2", "Claude", "response", "Response claim.",
               target_state="populated", target_state_set_by="author",
               declarations=[_native_decl("C1"), _native_decl("C3")],
               exposure_ref=_present("C1", "C3")),
        _claim("C3", "Muse", "opening", "Later opening.",
               exposure_ref=_present()),
    ]
    section = build_transjective_record(claims)
    # C2's valid declaration to C1 keeps it populated; the forward
    # reference to later claim C3 fires exactly E2.
    assert _codes(section) == {"E2"}
    assert section["conformant"] is False


# ---------------------------------------------------------------- 5. absent declaration


def test_absent_declaration_fixture_unknown_reason_warnings_not_repaired():
    outcome = parse_declaration_block(None, 1)[0]
    assert outcome["target_state"] == "unknown"
    assert outcome["uncertainty_reason"] == REASON_ABSENT
    claims = [
        _claim("C1", "GPT", "opening", "Opening claim.",
               exposure_ref=_present()),
        _runner_claim_from_outcome(
            "C2", "Claude", "response", outcome, None,
            exposure_ref=_present("C1")),
    ]
    section = build_transjective_record(claims)
    assert section["target_states"]["C2"]["state"] == "unknown"
    assert section["target_states"]["C2"]["uncertainty_reason"] == \
        REASON_ABSENT
    assert "W1" in _wcodes(section)
    # No declarations synthesized for the undeclared claim, and the
    # absence is a warning, not a silent repair into conformance
    # failure or success: errors from this claim are none, and the
    # section carries zero declarations sourced at C2.
    assert section["validation"]["errors"] == []
    assert section["conformant"] is True
    assert not [d for d in section["declarations"]
                if d["source_claim"] == "C2"]


# ---------------------------------------------------------------- 6. SPEC adapter output


def _spec_exposure(*cids):
    """Native exposure_refs with visible = earlier claims (real payloads)."""
    out = {}
    for i, cid in enumerate(cids):
        out[cid] = _present(*cids[:i])
    return out


def test_spec_c89_through_adapter_gate_exactly_e7():
    order = ["C35", "C71", "C32", "C76", "C89"]
    refs = _spec_exposure(*order)
    claims = [
        _claim("C35", "Gemini", "opening", "Original framing.",
               disposition="revised", disposition_by="C89",
               exposure_ref=refs["C35"]),
        _claim("C71", "Grok", "response", "Objection to C35.",
               relates_to=["C35"], exposure_ref=refs["C71"]),
        _claim("C32", "Gemini", "opening", "Registry contradiction.",
               exposure_ref=refs["C32"]),
        _claim("C76", "Muse", "response", "Extension of C32.",
               relates_to=["C32"], exposure_ref=refs["C76"]),
        _claim("C89", "Gemini", "revision",
               "Revised C35 in response to objection C71.",
               relates_to=["C35", "C71", "C32", "C76"],
               relationship="revised", exposure_ref=refs["C89"]),
    ]
    section = build_transjective_record(claims)
    assert _codes(section) == {"E7"}
    assert section["contract_standing"]["C35"] == "open"


def test_spec_c94_through_adapter_gate_exactly_e7_e13():
    order = ["C37", "C54", "C94"]
    refs = _spec_exposure(*order)
    claims = [
        _claim("C37", "Muse", "opening", "Both framings carried forward.",
               disposition="maintained", disposition_by="C94",
               exposure_ref=refs["C37"]),
        _claim("C54", "Gemini", "response", "In response to C37: evidence?",
               relates_to=["C37"], exposure_ref=refs["C54"]),
        _claim("C94", "Muse", "revision", "Defended C37 against C54.",
               relates_to=["C37", "C54"], relationship="defended",
               exposure_ref=refs["C94"]),
    ]
    section = build_transjective_record(claims)
    assert _codes(section) == {"E7", "E13"}
    assert section["contract_standing"]["C37"] == "open"


# ---------------------------------------------------------------- 7. interim vs final


def test_interim_vs_final_temp_unavailable_w2_then_e12():
    claim = _claim(
        "C1", "GPT", "opening", "Opening claim.",
        exposure_ref=unknown_exposure(
            "pending retrieval", temporarily=True,
            pending_ref="payload_evidence:pending-1"))
    interim = interim_validation_report([claim], meeting_phase="opening")
    assert interim["phase"] == "interim"
    assert "W2" in {w["code"] for w in interim["warnings"]}
    assert "E12" not in {e["code"] for e in interim["errors"]}

    section = build_transjective_record([claim])
    assert section["validation_phase"] == "final"
    assert "E12" in _codes(section)


# ---------------------------------------------------------------- 8. no fabrication


def test_no_fabrication_gate_preserves_inputs_and_reports_nonconformant():
    text = ("1. Inferred: Some claim.\n"
            "Declarations (declaration-block-v1):\n"
            "garbage line here\n")
    _, block = extract_declaration_block(text)
    outcome = parse_declaration_block(block, 1)[0]
    claims = [
        _claim("C1", "GPT", "opening", "Opening claim.",
               exposure_ref=_present()),
        _runner_claim_from_outcome(
            "C2", "Claude", "response", outcome, block,
            exposure_ref=_present("C1")),
        _claim("C3", "Muse", "response", "Response claim.",
               target_state="populated", target_state_set_by="author",
               declarations=[_native_decl("C99")],
               exposure_ref=_present("C1", "C99")),
    ]
    snapshot = copy.deepcopy(claims)

    interim = interim_validation_report(claims, meeting_phase="response")
    section = build_transjective_record(claims)

    # Inputs byte-identical after both gate legs: nothing repaired,
    # nothing generated, nothing rewritten.
    assert claims == snapshot
    # No declarations synthesized for the malformed claim.
    assert not [d for d in section["declarations"]
                if d["source_claim"] == "C2"]
    # Both legs report nonconformance; neither claims conformance.
    assert interim["conformant"] is False
    assert section["conformant"] is False
    assert interim["errors"] and section["validation"]["errors"]


# ---------------------------------------------------------------- 9. artifact carries interim + final


def test_artifact_carries_interim_and_final_reports():
    from types import SimpleNamespace

    registry = SimpleNamespace(claims=[
        SimpleNamespace(to_dict=lambda: {
            "id": "C1", "participant": "GPT", "phase": "opening",
            "text": "Opening.", "relationship": None, "relates_to": [],
            "supersedes": None, "withdraws": None,
            "relationship_target": None, "relationship_targets": [],
            "disposition": None, "disposition_by": None,
            "status": "unknown", "epistemic_assessment": "unresolved",
            "assessment_sources": []}),
    ])
    packet = SimpleNamespace(work_item="w", question="q")
    transcript = SimpleNamespace(entries=[])
    interim = interim_validation_report(
        [c.to_dict() for c in registry.claims], meeting_phase="opening")
    artifact = build_draft_artifact_r2(
        "m1", packet, transcript, [], registry,
        claim_standing={"version": 1, "entries": []},
        transjective_validation_reports=[interim])
    assert artifact["transjective_validation_reports"] == [interim]
    assert artifact["transjective_record"]["validation_phase"] == "final"
    assert "validation" in artifact["transjective_record"]

    # Without the kwarg, no new key appears (replays, direct callers).
    bare = build_draft_artifact_r2(
        "m1", packet, transcript, [], registry,
        claim_standing={"version": 1, "entries": []})
    assert "transjective_validation_reports" not in bare


# ---------------------------------------------------------------- 10. runner end-to-end


class _FakeParticipant:
    def __init__(self, name, *, opening="", response="", revision=""):
        self.name = name
        self.provider_id = dict((n, p) for n, p, _ in SEAT_SPECS)[name]
        self.model = "fake-model"
        self.key_source = "settings"
        self._texts = {"revision": revision, "response": response,
                       "opening": opening}

    def generate(self, prompt, *, timeout=120):
        if "state the relationship explicitly" in prompt:
            return self._texts["revision"]
        if "Claim registry" in prompt:
            return self._texts["response"]
        return self._texts["opening"]


def _packet():
    return EvidencePacket(
        work_item="Test work item",
        question="What would make the Build-Council Room fail?",
        excerpts=("excerpt one",),
        constraints=("room deliberates, never decides",),
        source_refs=("local_ai/build_room/meeting.py",),
    )


def _seats(fakes):
    seats = []
    for name, provider_id, model in SEAT_SPECS:
        fake = fakes.get(name)
        if fake is None:
            seats.append(Seat(name, provider_id, model, None,
                              absence_note=f"absent: no {provider_id} key"))
        else:
            seats.append(Seat(name, provider_id, model, fake))
    return seats


def test_runner_gate_end_to_end(tmp_path):
    fakes = {
        "GPT": _FakeParticipant(
            "GPT",
            opening="1. Inferred: Authority confusion is a failure mode.\n"
                    "2. Proposed: Keep authorization with Joshua.",
            response="1. Inferred: The registry point stands.",
            revision="Relationship: defended.\nIn response to C1, I defend my claim:\n"
                     "1. Inferred: Authority confusion remains the top risk.",
        ),
        "Claude": _FakeParticipant(
            "Claude",
            opening="1. Inferred: Parallel monologues are a failure mode.",
            response="1. Objection to C1: authorization alone does not "
                     "prevent misrepresentation.",
        ),
    }
    result = run_multi_model_meeting(_packet(), store_dir=tmp_path,
                                     seats=_seats(fakes))
    reports = result.artifact["transjective_validation_reports"]
    assert [r["meeting_phase"] for r in reports] == [
        "opening", "response", "revision"]
    assert all(r["phase"] == "interim" for r in reports)
    registry = result.artifact["claim_registry"]
    by_phase = {}
    for c in registry:
        by_phase.setdefault(c["phase"], []).append(c["id"])
    assert [r["claim_count"] for r in reports] == [
        len(by_phase["opening"]),
        len(by_phase["opening"]) + len(by_phase["response"]),
        len(registry),
    ]
    section = result.artifact["transjective_record"]
    assert section["validation_phase"] == "final"
    assert "validation" in section
    assert "conformant" in section
