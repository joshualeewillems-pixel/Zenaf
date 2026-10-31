"""Transjective schema contract tests (accepted contract, 2026-10-30).

No live API calls, no provider keys, no spend. Every test builds plain
dicts in memory; the validation engine is pure and deterministic.
At least one test per error (E1–E14) and warning (W1–W4), plus
target-state consistency, event ordering + derived standing,
correction-chain conflicts + reconciliation, exposure four-way +
permanent-loss escalation, clarified-stage rejection,
maintained/contested-standing semantics, authority sets (including
user product-only vs build-council exclusion), the SPEC C89/C94 cases
(failing exactly E7 and E7+E13), the read-only adapter, and the
artifact + captures-route wiring (additive, computed on read, stored
captures untouched).
"""

from __future__ import annotations

import copy

from local_ai.build_room.transjective_record import (
    adapt_claims_to_contract_inputs,
    build_transjective_record,
    compute_target_states,
    derive_contract_standing,
    derive_revision_links,
    validate_contract_record,
)


# ---------------------------------------------------------------- helpers


def claim(cid, participant, phase, text="", **kw):
    d = {"id": cid, "participant": participant, "phase": phase, "text": text}
    d.update(kw)
    return d


def decl(src, tgt, kind="extends"):
    return {"source_claim": src, "target_claim": tgt, "kind": kind,
            "layer": "declared"}


def exposure_present(*cids, visible=None):
    """All claims present; visible defaults to every earlier claim."""
    out = {}
    ordered = list(cids)
    for i, cid in enumerate(ordered):
        vis = visible[cid] if visible and cid in visible else ordered[:i]
        out[cid] = {"ref": f"ctx-{cid}", "evidence": "present",
                    "visible_ids": vis}
    return out


def valid_record():
    """Conformant record (zero errors; W1 warnings for opening unknowns)."""
    claims = [
        claim("C1", "GPT", "opening", "Opening one."),
        claim("C2", "Claude", "opening", "Opening two."),
        claim("C3", "Gemini", "response", "Extends C1."),
        claim("C4", "Gemini", "revision", "Corrects C1."),
    ]
    return {
        "claims": claims,
        "declarations": [decl("C3", "C1"), decl("C4", "C1", "corrects")],
        "exposure": exposure_present("C1", "C2", "C3", "C4"),
    }


def codes(report):
    return {e["code"] for e in report["errors"]}


def wcodes(report):
    return {w["code"] for w in report["warnings"]}


def accepted_event(eid, target, new, prior, seq, author="GPT", **basis_extra):
    basis = {"proposal_ids": ["P1"],
             "acceptance": {"author": author, "proposal_id": "P1"}}
    basis.update(basis_extra)
    event = {"event_id": eid, "target_claim": target,
             "prior_standing": prior, "new_standing": new,
             "authorizer": "convener-close", "authorizing_basis": basis,
             "sequence": seq}
    return event


def record_with_event(new="revised", **event_kw):
    rec = valid_record()
    rec["proposals"] = [{"id": "P1", "proposer": "Gemini",
                         "target_claim": "C1", "proposed_standing": new,
                         "evidence": ["C4"]}]
    event = accepted_event("EV1", "C1", new, "open", 1, **event_kw)
    if new == "revised":
        event["revision_claim"] = "C4"
    rec["events"] = [event]
    return rec


# ---------------------------------------------------------------- basics


def test_valid_record_conformant_derives_open():
    report = validate_contract_record(valid_record())
    assert report["conformant"] is True
    assert report["errors"] == []
    assert report["derived_contract_standing"] == {
        "C1": "open", "C2": "open", "C3": "open", "C4": "open",
    }
    assert report["revision_links"] == {"revision_of": {}, "revised_by": {},
                                        "conflicts": []}


def test_target_state_computation():
    claims = valid_record()["claims"]
    states = compute_target_states(
        claims, [decl("C3", "C1"), decl("C4", "C1", "corrects")])
    assert states["C1"]["state"] == "unknown"  # opening, no declarations
    assert states["C1"]["uncertainty_reason"]
    assert states["C2"]["state"] == "unknown"
    assert states["C3"]["state"] == "populated"
    assert states["C4"]["state"] == "populated"
    # Response claim with no declarations -> missing.
    states2 = compute_target_states(
        [claim("C1", "GPT", "opening"),
         claim("C2", "Claude", "response")], [])
    assert states2["C2"]["state"] == "missing"
    # Explicit author-set declared-none passes through.
    states3 = compute_target_states(
        [claim("C1", "GPT", "response")], [],
        explicit={"C1": {"state": "declared-none", "set_by": "author"}})
    assert states3["C1"]["state"] == "declared-none"


# ---------------------------------------------------------------- E1–E4


def test_e1_dangling_declaration_target():
    rec = valid_record()
    rec["declarations"].append(decl("C3", "C99"))
    assert "E1" in codes(validate_contract_record(rec))


def test_e1_duplicate_claim_ids():
    rec = valid_record()
    rec["claims"].append(claim("C1", "Grok", "opening"))
    assert "E1" in codes(validate_contract_record(rec))


def test_e1_duplicate_event_ids():
    rec = record_with_event()
    rec["events"].append(accepted_event("EV1", "C2", "maintained", "open", 2))
    assert "E1" in codes(validate_contract_record(rec))


def test_e2_forward_reference():
    rec = valid_record()
    rec["declarations"].append(decl("C1", "C3"))
    assert "E2" in codes(validate_contract_record(rec))


def test_e3_target_outside_visible_set():
    rec = valid_record()
    rec["exposure"]["C3"]["visible_ids"] = ["C2"]  # C1 not visible
    assert "E3" in codes(validate_contract_record(rec))


def test_e4_bad_kind_and_bad_layer():
    rec = valid_record()
    rec["declarations"][0]["kind"] = "demolishes"
    assert "E4" in codes(validate_contract_record(rec))
    rec = valid_record()
    rec["declarations"][0]["layer"] = "verified"
    assert "E4" in codes(validate_contract_record(rec))


# ---------------------------------------------------------------- E5/E6


def test_e5_response_claim_missing_target_state():
    rec = valid_record()
    rec["claims"].append(claim("C5", "Grok", "response", "No targets."))
    rec["exposure"]["C5"] = {"ref": "ctx-C5", "evidence": "present",
                             "visible_ids": ["C1", "C2", "C3", "C4"]}
    assert "E5" in codes(validate_contract_record(rec))


def test_e6_populated_without_declarations():
    rec = valid_record()
    rec["target_states"] = {"C2": {"state": "populated", "set_by": "author"}}
    assert "E6" in codes(validate_contract_record(rec))


def test_e6_declared_none_with_declarations():
    rec = valid_record()
    rec["target_states"] = {"C3": {"state": "declared-none", "set_by": "author"}}
    assert "E6" in codes(validate_contract_record(rec))


def test_e6_declared_none_system_set():
    rec = valid_record()
    rec["target_states"] = {"C3": {"state": "declared-none", "set_by": "system"}}
    assert "E6" in codes(validate_contract_record(rec))


def test_e6_unknown_without_reason():
    rec = valid_record()
    rec["target_states"] = {"C1": {"state": "unknown", "set_by": "system",
                                   "uncertainty_reason": None}}
    assert "E6" in codes(validate_contract_record(rec))


def test_e6_state_outside_vocabulary():
    rec = valid_record()
    rec["target_states"] = {"C1": {"state": "vibing", "set_by": "author"}}
    assert "E6" in codes(validate_contract_record(rec))


# ---------------------------------------------------------------- E7 authority


def test_e7_event_without_authorizer_or_basis():
    rec = record_with_event()
    rec["events"][0]["authorizer"] = ""
    assert "E7" in codes(validate_contract_record(rec))
    rec = record_with_event()
    rec["events"][0]["authorizing_basis"] = {}
    assert "E7" in codes(validate_contract_record(rec))


def test_e7_authorizer_outside_set():
    rec = record_with_event()
    rec["events"][0]["authorizer"] = "GPT"
    assert "E7" in codes(validate_contract_record(rec))


def test_e7_revised_without_target_author_acceptance():
    rec = record_with_event()
    rec["events"][0]["authorizing_basis"]["acceptance"]["author"] = "Claude"
    assert "E7" in codes(validate_contract_record(rec))


def test_e7_superseded_without_rule_or_claim():
    rec = valid_record()
    rec["proposals"] = [{"id": "P1", "proposer": "Gemini",
                         "target_claim": "C1", "proposed_standing": "superseded",
                         "evidence": ["C4"]}]
    rec["events"] = [{"event_id": "EV1", "target_claim": "C1",
                      "prior_standing": "open", "new_standing": "superseded",
                      "authorizer": "convener-close",
                      "authorizing_basis": {"proposal_ids": ["P1"]},
                      "sequence": 1}]
    assert "E7" in codes(validate_contract_record(rec))
    rec["events"][0]["authorizing_basis"] = {
        "proposal_ids": ["P1"], "meeting_rule": "R1",
        "superseding_claim": "C4"}
    report = validate_contract_record(rec, meeting_rules=["R1"])
    assert "E7" not in codes(report)
    assert report["derived_contract_standing"]["C1"] == "superseded"


def test_e7_user_build_council_excluded_product_allowed():
    rec = record_with_event()
    rec["events"][0]["authorizer"] = "user"
    rec["events"][0]["authorizing_basis"] = {"user_decision": "accept C4"}
    assert "E7" in codes(validate_contract_record(rec))  # build-council
    report = validate_contract_record(rec, meeting_kind="product")
    assert "E7" not in codes(report)
    rec["events"][0]["authorizing_basis"] = {}
    report = validate_contract_record(rec, meeting_kind="product")
    assert "E7" in codes(report)  # no cited decision


# ---------------------------------------------------------------- E8/E9


def test_e8_revised_without_revision_claim():
    rec = record_with_event()
    del rec["events"][0]["revision_claim"]
    assert "E8" in codes(validate_contract_record(rec))


def test_e8_explicit_links_disagree_with_derived():
    rec = record_with_event()
    rec["explicit_revision_links"] = {"revision_of": {"C4": "C2"},
                                      "revised_by": {"C2": "C4"}}
    assert "E8" in codes(validate_contract_record(rec))
    rec = record_with_event()
    rec["explicit_revision_links"] = {"revision_of": {"C4": "C1"},
                                      "revised_by": {"C1": "C4"}}
    assert "E8" not in codes(validate_contract_record(rec))


def test_revision_links_derived():
    rec = record_with_event()
    links = derive_revision_links(rec["events"])
    assert links["revision_of"] == {"C4": "C1"}
    assert links["revised_by"] == {"C1": "C4"}


def test_e9_first_event_prior_not_open():
    rec = record_with_event()
    rec["events"][0]["prior_standing"] = "maintained"
    assert "E9" in codes(validate_contract_record(rec))


def test_e9_chain_break_and_duplicate_sequence():
    rec = record_with_event()
    rec["events"].append(accepted_event("EV2", "C1", "maintained", "open", 2))
    assert "E9" in codes(validate_contract_record(rec))  # prior should be revised
    rec = record_with_event()
    rec["events"].append(accepted_event("EV2", "C1", "maintained", "revised", 1))
    assert "E9" in codes(validate_contract_record(rec))  # duplicate sequence


def test_e9_stored_standing_mismatch():
    rec = record_with_event()
    rec["stored_contract_standing"] = {"C1": "maintained"}
    assert "E9" in codes(validate_contract_record(rec))
    rec["stored_contract_standing"] = {"C1": "revised"}
    assert "E9" not in codes(validate_contract_record(rec))


# ---------------------------------------------------------------- E10–E14


def test_e10_disagreement_rules_and_clarified_rejected():
    base = {"id": "D1", "claims": ["C1", "C2"],
            "incompatibility": "They conflict.", "proposer": "Gemini",
            "cited_evidence": ["C1"], "stage": "identified"}
    rec = valid_record()
    rec["disagreements"] = [dict(base, claims=["C1"])]
    assert "E10" in codes(validate_contract_record(rec))
    rec["disagreements"] = [dict(base, incompatibility="")]
    assert "E10" in codes(validate_contract_record(rec))
    rec["disagreements"] = [dict(base, proposer="")]
    assert "E10" in codes(validate_contract_record(rec))
    rec["disagreements"] = [dict(base, stage="clarified")]
    assert "E10" in codes(validate_contract_record(rec))
    rec["disagreements"] = [dict(base, stage="articulated")]
    assert "E10" not in codes(validate_contract_record(rec))


def test_e11_correction_rules():
    def corr(cid, sup, **kw):
        d = {"id": cid, "original_value": "a", "corrected_value": "b",
             "author_or_process": "convener", "reason": "typo",
             "superseded_record": sup}
        d.update(kw)
        return d
    rec = valid_record()
    rec["corrections"] = [dict(corr("K1", "C1"), reason=None)]
    assert "E11" in codes(validate_contract_record(rec))
    rec["corrections"] = [corr("K1", "C99")]
    assert "E11" in codes(validate_contract_record(rec))
    # Competing corrections: second cites the old head -> E11.
    rec["corrections"] = [corr("K1", "C1"), corr("K2", "C1")]
    assert "E11" in codes(validate_contract_record(rec))
    # Second cites the current head -> valid.
    rec["corrections"] = [corr("K1", "C1"), corr("K2", "K1")]
    assert "E11" not in codes(validate_contract_record(rec))
    # Competing correction with explicit reconciliation -> valid.
    rec["corrections"] = [
        corr("K1", "C1"),
        corr("K2", "C1", reconciles={"heads": ["K1"],
                                     "resolver": "convener",
                                     "reason": "merged"})]
    report = validate_contract_record(rec)
    assert "E11" not in codes(report)
    # Reconciliation missing resolver -> E11.
    rec["corrections"] = [
        corr("K1", "C1"),
        corr("K2", "C1", reconciles={"heads": ["K1"],
                                     "reason": "merged"})]
    assert "E11" in codes(validate_contract_record(rec))


def test_e12_exposure_cases():
    rec = valid_record()
    rec["exposure"]["C1"] = {"ref": None, "evidence": "absent",
                             "visible_ids": []}
    assert "E12" in codes(validate_contract_record(rec))
    rec = valid_record()
    rec["exposure"]["C1"] = {"ref": "   ", "evidence": "present",
                             "visible_ids": []}
    assert "E12" in codes(validate_contract_record(rec))
    rec = valid_record()
    rec["exposure"]["C1"] = {"ref": "ctx-C1", "evidence": "absent",
                             "visible_ids": []}
    assert "E12" in codes(validate_contract_record(rec))


def test_e13_and_e7_legacy_dispositions():
    # C94 shape: maintained via defense -> E7 + E13.
    rec = valid_record()
    rec["legacy_dispositions"] = [{"claim_id": "C1",
                                   "disposition": "maintained",
                                   "disposition_by": "C4"}]
    report = validate_contract_record(rec)
    assert "E7" in codes(report) and "E13" in codes(report)
    assert report["derived_contract_standing"]["C1"] == "open"
    # Event-shaped revised legacy disposition -> E7 only.
    rec["legacy_dispositions"] = [{"claim_id": "C1",
                                   "disposition": "revised",
                                   "disposition_by": "C4"}]
    report = validate_contract_record(rec)
    assert "E7" in codes(report) and "E13" not in codes(report)


def test_e14_score_fields():
    rec = valid_record()
    rec["claims"][0]["grounding"] = 2
    assert "E14" in codes(validate_contract_record(rec))
    rec = valid_record()
    rec["score_fields_present"] = True
    assert "E14" in codes(validate_contract_record(rec))


# ---------------------------------------------------------------- warnings


def test_w1_unknown_with_reason_warns():
    report = validate_contract_record(valid_record())
    assert "W1" in wcodes(report)  # openings C1/C2 unknown with reason


def test_w2_interim_temp_unavailable_final_errors():
    rec = valid_record()
    rec["exposure"]["C3"] = {"ref": "ctx-C3",
                             "evidence": "temporarily_unavailable",
                             "visible_ids": ["C1", "C2"]}
    report = validate_contract_record(rec, validation_phase="interim")
    assert "W2" in wcodes(report) and "E12" not in codes(report)
    report = validate_contract_record(rec, validation_phase="final")
    assert "E12" in codes(report)  # permanent-loss escalation


def test_w3_disagreement_thin_evidence():
    rec = valid_record()
    rec["disagreements"] = [{"id": "D1", "claims": ["C1", "C2"],
                             "incompatibility": "Conflict.",
                             "proposer": "Gemini", "cited_evidence": [],
                             "stage": "identified"}]
    assert "W3" in wcodes(validate_contract_record(rec))


def test_w4_proposal_without_evidence():
    rec = valid_record()
    rec["proposals"] = [{"id": "P1", "proposer": "Gemini",
                         "target_claim": "C1", "proposed_standing": "revised",
                         "evidence": []}]
    assert "W4" in wcodes(validate_contract_record(rec))


# ---------------------------------------------------------------- standing semantics


def test_maintained_only_via_event_not_default():
    report = validate_contract_record(valid_record())
    assert report["derived_contract_standing"]["C1"] == "open"  # not maintained
    rec = record_with_event(new="maintained")
    rec["events"][0]["authorizing_basis"]["acceptance"] = {
        "author": "GPT", "proposal_id": "P1"}
    report = validate_contract_record(rec)
    assert report["derived_contract_standing"]["C1"] == "maintained"


def test_event_ordering_derives_last_wins():
    rec = valid_record()
    rec["proposals"] = [{"id": "P1", "proposer": "Gemini",
                         "target_claim": "C1", "proposed_standing": "revised",
                         "evidence": ["C4"]}]
    rec["events"] = [
        accepted_event("EV1", "C1", "revised", "open", 1,
                       revision_claim="C4"),
        accepted_event("EV2", "C1", "maintained", "revised", 2),
    ]
    # Fix: accepted_event builds basis with acceptance author GPT (target
    # author) already; revision_claim passed via basis_extra is dropped
    # by accepted_event, so set it explicitly.
    rec["events"][0]["revision_claim"] = "C4"
    assert derive_contract_standing(rec["events"], ["C1"]) == {"C1": "maintained"}
    assert "E9" not in codes(validate_contract_record(rec))


def test_contested_standing_structural_bar():
    def contested_rec(**challenge_kw):
        rec = valid_record()
        rec["declarations"].append(decl("C3", "C1", "challenges"))
        challenge = {"challenge_claim": "C3", "response_claims": []}
        challenge.update(challenge_kw)
        rec["events"] = [{"event_id": "EV1", "target_claim": "C1",
                          "prior_standing": "open",
                          "new_standing": "contested-standing",
                          "authorizer": "convener-close",
                          "authorizing_basis": {"challenge": challenge},
                          "sequence": 1}]
        return rec
    report = validate_contract_record(contested_rec())
    assert "E7" not in codes(report)
    assert report["derived_contract_standing"]["C1"] == "contested-standing"
    # Challenge withdrawn -> bar fails.
    rec = contested_rec()
    rec["events"].append(accepted_event("EV2", "C3", "withdrawn", "open", 2))
    assert "E7" in codes(validate_contract_record(rec))
    # Challenge not addressing the target -> bar fails.
    rec = contested_rec(challenge_claim="C2")
    assert "E7" in codes(validate_contract_record(rec))
    # Weak content still passes: the bar is structural, not intellectual.
    rec = valid_record()
    rec["claims"][2]["text"] = "Nonsense, but it cites C1."
    rec["declarations"].append(decl("C3", "C1", "challenges"))
    rec["events"] = [{"event_id": "EV1", "target_claim": "C1",
                      "prior_standing": "open",
                      "new_standing": "contested-standing",
                      "authorizer": "convener-close",
                      "authorizing_basis": {
                          "challenge": {"challenge_claim": "C3",
                                        "response_claims": []}},
                      "sequence": 1}]
    assert "E7" not in codes(validate_contract_record(rec))


# ---------------------------------------------------------------- SPEC cases (§8)


def test_spec_c89_fails_exactly_e7():
    claims = [
        claim("C35", "Gemini", "opening", "Original framing."),
        claim("C71", "Grok", "response", "Objection to C35.",
              relates_to=["C35"]),
        claim("C32", "Gemini", "opening", "Registry contradiction."),
        claim("C76", "Muse", "response", "Extension of C32.",
              relates_to=["C32"]),
        claim("C89", "Gemini", "revision",
              "Revised C35 in response to objection C71.",
              relates_to=["C35", "C71", "C32", "C76"],
              relationship="revised",
              disposition=None),
    ]
    claims[0]["disposition"] = "revised"
    claims[0]["disposition_by"] = "C89"
    rec = {
        "claims": claims,
        "declarations": [
            decl("C71", "C35", "challenges"),
            decl("C76", "C32", "extends"),
            decl("C89", "C35", "other"),
            decl("C89", "C71", "other"),
            decl("C89", "C32", "other"),
            decl("C89", "C76", "other"),
        ],
        "exposure": exposure_present("C35", "C71", "C32", "C76", "C89"),
        "legacy_dispositions": [{"claim_id": "C35", "disposition": "revised",
                                 "disposition_by": "C89"}],
    }
    report = validate_contract_record(rec)
    assert codes(report) == {"E7"}
    assert report["derived_contract_standing"]["C35"] == "open"


def test_spec_c94_fails_exactly_e7_e13():
    claims = [
        claim("C37", "Muse", "opening", "Both framings carried forward."),
        claim("C54", "Gemini", "response", "In response to C37: evidence?",
              relates_to=["C37"]),
        claim("C94", "Muse", "revision", "Defended C37 against C54.",
              relates_to=["C37", "C54"], relationship="defended"),
    ]
    claims[0]["disposition"] = "maintained"
    claims[0]["disposition_by"] = "C94"
    rec = {
        "claims": claims,
        "declarations": [
            decl("C54", "C37", "requests-evidence"),
            decl("C94", "C37", "defends"),
            decl("C94", "C54", "challenges"),
        ],
        "exposure": exposure_present("C37", "C54", "C94"),
        "legacy_dispositions": [{"claim_id": "C37",
                                 "disposition": "maintained",
                                 "disposition_by": "C94"}],
    }
    report = validate_contract_record(rec)
    assert codes(report) == {"E7", "E13"}
    assert report["derived_contract_standing"]["C37"] == "open"


# ---------------------------------------------------------------- adapter + wiring


def test_adapter_old_capture_nonconformant_and_readonly():
    claims = [
        claim("C1", "GPT", "opening", "The spec includes defer_to."),
        claim("C2", "Claude", "response",
              "Extension of C1 and C3.", relates_to=["C1"],
              relationship="unstated"),
        claim("C3", "Muse", "revision",
              "Defended C1 against C2.", relates_to=["C1", "C2"],
              relationship="defended",
              disposition=None),
    ]
    claims[0]["disposition"] = "maintained"
    claims[0]["disposition_by"] = "C3"
    before = copy.deepcopy(claims)
    adapted = adapt_claims_to_contract_inputs(claims)
    assert claims == before  # adapter never mutates its input
    assert ("C2", "C1") in {(d["source_claim"], d["target_claim"])
                            for d in adapted["declarations"]}
    assert adapted["target_states"]["C2"]["state"] == "populated"
    # C3 is a revision claim with declarations -> populated; a
    # declaration-less response claim would be missing (E5).
    assert adapted["legacy_dispositions"] == [
        {"claim_id": "C1", "disposition": "maintained",
         "disposition_by": "C3"}]
    section = build_transjective_record(claims)
    assert section["conformant"] is False
    assert "E12" in section["validation"]["error_counts"]  # no exposure_refs
    assert "E7" in section["validation"]["error_counts"]
    assert section["contract_standing"] == {"C1": "open", "C2": "open",
                                            "C3": "open"}
    assert "claim_standing" not in section  # own key, never overwrites
    assert claims == before


def test_adapter_missing_target_state_yields_e5():
    claims = [
        claim("C1", "GPT", "opening", "Opening."),
        claim("C2", "Claude", "response", "No targets at all."),
    ]
    section = build_transjective_record(claims)
    assert "E5" in section["validation"]["error_counts"]


def test_artifact_wiring_additive():
    from types import SimpleNamespace

    from local_ai.build_room.artifact import build_draft_artifact_r2

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
    artifact = build_draft_artifact_r2(
        "m1", packet, transcript, [], registry,
        claim_standing={"version": 1, "entries": []},
    )
    assert "transjective_record" in artifact
    assert "claim_standing" in artifact  # untouched, separate key
    assert artifact["transjective_record"]["contract_standing"] == {"C1": "open"}
    assert artifact["claim_standing"] == {"version": 1, "entries": []}
