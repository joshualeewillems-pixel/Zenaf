"""Increment C: disposition proposals + deterministic convener-close.

Pure close behavior is tested directly on convener_close /
extract_proposals with synthetic fixtures (no model calls, no spend).
Validator interaction is tested by running validate_contract_record
over close outputs and asserting no E7/E8/E9 codes are attributable
to close events (other codes, e.g. E12 for fixture claims without
exposure, are filtered: they describe the fixtures, not the close).
"""

from types import SimpleNamespace

from local_ai.build_room.artifact import build_draft_artifact_r2
from local_ai.build_room.dispositions import convener_close, extract_proposals
from local_ai.build_room.meeting import Claim
from local_ai.build_room.transjective_record import (
    adapt_claims_to_contract_inputs,
    build_transjective_record,
    derive_revision_links,
    validate_contract_record,
)


def claim(cid, participant, phase="opening", **extra):
    d = {"id": cid, "participant": participant, "phase": phase, "text": f"t{cid}"}
    d.update(extra)
    return d


def prop(pid, target, standing, proposer="GPT", **extra):
    d = {"id": pid, "proposer": proposer, "target_claim": target,
         "proposed_standing": standing, "evidence": ["C9"]}
    d.update(extra)
    return d


def acc(target, pid, author, **extra):
    d = {"target_claim": target, "proposal_id": pid, "accepting_author": author}
    d.update(extra)
    return d


def decl(src, tgt, kind):
    return {"source_claim": src, "target_claim": tgt, "kind": kind,
            "layer": "declared"}


def event_codes(claims, declarations, proposals, events, **kwargs):
    record = {"claims": claims, "declarations": declarations,
              "proposals": proposals, "events": events}
    report = validate_contract_record(record, **kwargs)
    return {e["code"] for e in report["errors"]}


def base_claims():
    return [
        claim("C1", "GPT", "opening"),
        claim("C2", "Claude", "response"),
        claim("C3", "Gemini", "revision"),
    ]


# ---------------------------------------------------------------------------
# Extraction
# ---------------------------------------------------------------------------


def test_extract_defends_maintained_and_revision_proposals():
    claims = base_claims() + [claim("C4", "Grok", "revision"),
                              claim("C5", "Muse", "response")]
    decls = [
        decl("C2", "C1", "defends"),
        decl("C3", "C1", "corrects"),
        decl("C4", "C1", "challenges"),
        decl("C5", "C1", "corrects"),  # response phase: engagement, not revision
    ]
    props, chals = extract_proposals(claims, decls)
    by_id = {p["id"]: p for p in props}
    assert by_id["prop:C2:C1:maintained"]["proposed_standing"] == "maintained"
    assert by_id["prop:C3:C1:revised"]["revision_claim"] == "C3"
    assert "prop:C5:C1:revised" not in by_id
    assert chals == [{"challenge_claim": "C4", "target": "C1",
                      "response_claims": []}]


def test_extract_supersedes_withdraws_fields():
    claims = base_claims()
    claims[2].update({"supersedes": "C1", "withdraws": None})
    claims[1].update({"withdraws": "C1"})
    props, _ = extract_proposals(claims, [])
    by_id = {p["id"]: p for p in props}
    sup = by_id["prop:C3:C1:superseded"]
    assert sup["superseding_claim"] == "C3"
    assert "meeting_rule" not in sup  # no rule cited: stays pending
    assert by_id["prop:C2:C1:withdrawn"]["proposed_standing"] == "withdrawn"


def test_extract_legacy_labels_via_adapter():
    claims = [
        claim("C1", "GPT", "opening"),
        claim("C2", "Claude", "revision", relationship="defended",
              relationship_target="C1"),
        claim("C3", "Gemini", "revision",
              relationship="proposes_revision_of",
              relationship_targets=["C1"]),
        claim("C4", "Grok", "revision",
              relationship="supports_withdrawal_of",
              relationship_targets=["C1"]),
    ]
    adapted = adapt_claims_to_contract_inputs(claims)
    props, _ = extract_proposals(claims, adapted["declarations"])
    by_id = {p["id"]: p for p in props}
    assert by_id["prop:C2:C1:maintained"]["proposed_standing"] == "maintained"
    assert by_id["prop:C3:C1:revised"]["revision_claim"] == "C3"
    assert by_id["prop:C4:C1:withdrawn"]["proposed_standing"] == "withdrawn"


def test_extract_endorses_creates_nothing_and_skips_bad_pairs():
    claims = base_claims()
    decls = [
        decl("C2", "C1", "endorses"),
        decl("C2", "C2", "defends"),  # self-target: skipped
        decl("C2", "C99", "defends"),  # unknown target: skipped
        decl("C2", "C1", "defends"),
        decl("C2", "C1", "defends"),  # duplicate pair: first wins
    ]
    props, chals = extract_proposals(claims, decls)
    assert [p["id"] for p in props] == ["prop:C2:C1:maintained"]
    assert chals == []


# ---------------------------------------------------------------------------
# Close: every §4.2 path (acceptance 1)
# ---------------------------------------------------------------------------


def test_close_revised_on_target_author_acceptance():
    claims = base_claims()
    props = [prop("p1", "C1", "revised", revision_claim="C3")]
    res = convener_close(claims, props,
                         [acc("C1", "p1", "GPT")], [])
    assert len(res["events"]) == 1
    evt = res["events"][0]
    assert evt["target_claim"] == "C1"
    assert evt["new_standing"] == "revised"
    assert evt["prior_standing"] == "open"
    assert evt["sequence"] == 0
    assert evt["revision_claim"] == "C3"
    assert evt["authorizer"] == "convener-close"
    assert evt["authorizing_basis"]["proposal_ids"] == ["p1"]
    assert evt["authorizing_basis"]["acceptance"]["author"] == "GPT"
    assert res["derived_standing"]["C1"] == "revised"
    assert res["refusals"] == []
    links = derive_revision_links(res["events"])
    assert links["revision_of"] == {"C3": "C1"}
    assert links["revised_by"] == {"C1": "C3"}
    assert event_codes(claims, [], props, res["events"]) & {"E7", "E8", "E9"} == set()


def test_close_withdrawn_on_acceptance():
    claims = base_claims()
    props = [prop("p1", "C1", "withdrawn")]
    res = convener_close(claims, props, [acc("C1", "p1", "GPT")], [])
    assert res["events"][0]["new_standing"] == "withdrawn"
    assert res["derived_standing"]["C1"] == "withdrawn"


def test_close_maintained_c94_shape_with_acceptance():
    # C94 defends C37; with C37-author acceptance the maintained event
    # issues. (Without acceptance it must not — see the refusal test.)
    claims = [claim("C37", "GPT", "opening"), claim("C94", "Claude", "revision")]
    props = [prop("p1", "C37", "maintained", proposer="Claude")]
    res = convener_close(claims, props, [acc("C37", "p1", "GPT")], [])
    assert res["events"][0]["new_standing"] == "maintained"
    assert res["derived_standing"]["C37"] == "maintained"


def test_close_superseded_on_rule_and_claim():
    claims = base_claims()
    props = [prop("p1", "C1", "superseded", superseding_claim="C3",
                  meeting_rule="r1")]
    res = convener_close(claims, props, [], [],
                         meeting_rules=["r1"])
    assert res["events"][0]["new_standing"] == "superseded"
    assert res["events"][0]["authorizing_basis"]["meeting_rule"] == "r1"
    assert res["events"][0]["authorizing_basis"]["superseding_claim"] == "C3"
    assert event_codes(claims, [], props, res["events"],
                       meeting_rules=["r1"]) & {"E7", "E8", "E9"} == set()


def test_close_contested_on_structural_bar():
    claims = base_claims()
    chals = [{"challenge_claim": "C2", "target": "C1",
              "response_claims": ["C3"]}]
    res = convener_close(claims, [], [], chals)
    assert len(res["events"]) == 1
    evt = res["events"][0]
    assert evt["new_standing"] == "contested-standing"
    assert evt["authorizing_basis"]["challenge"]["challenge_claim"] == "C2"
    assert evt["authorizing_basis"]["challenge"]["response_claims"] == ["C3"]
    assert res["derived_standing"]["C1"] == "contested-standing"
    assert event_codes(claims, [decl("C2", "C1", "challenges")], [],
                       res["events"]) & {"E7", "E8", "E9"} == set()


def test_close_contested_proposal_rides_bar():
    claims = base_claims()
    props = [prop("p1", "C1", "contested-standing")]
    chals = [{"challenge_claim": "C2", "target": "C1"}]
    res = convener_close(claims, props, [], chals)
    assert res["events"][0]["new_standing"] == "contested-standing"
    assert res["events"][0]["authorizing_basis"]["proposal_ids"] == ["p1"]
    # Same proposal, no qualifying challenge: refused, not issued.
    res2 = convener_close(claims, props, [], [])
    assert res2["events"] == []
    assert res2["refusals"][0]["proposal_id"] == "p1"
    # Dangling response ids are filtered from the basis, never cited
    # (a basis citing an unknown id would be an E1).
    chals = [{"challenge_claim": "C2", "target": "C1",
              "response_claims": ["C3", "C99"]}]
    res3 = convener_close(claims, props, [], chals)
    assert res3["events"][0]["authorizing_basis"]["challenge"][
        "response_claims"] == ["C3"]


def test_close_chain_continues_and_sequences_continue():
    claims = base_claims()
    existing = [{"event_id": "evt:5", "target_claim": "C1",
                 "prior_standing": "open", "new_standing": "revised",
                 "authorizer": "convener-close",
                 "authorizing_basis": {"proposal_ids": ["p0"]},
                 "revision_claim": "C3", "sequence": 5}]
    props = [prop("p1", "C1", "withdrawn")]
    res = convener_close(claims, props, [acc("C1", "p1", "GPT")], [],
                         existing_events=existing)
    assert len(res["events"]) == 1
    assert res["events"][0]["sequence"] == 6
    assert res["events"][0]["prior_standing"] == "revised"
    assert res["derived_standing"]["C1"] == "withdrawn"


# ---------------------------------------------------------------------------
# Close: every refusal (acceptance 2)
# ---------------------------------------------------------------------------


def test_close_proposal_without_acceptance_stays_open():
    claims = base_claims()
    for standing in ("revised", "withdrawn", "maintained"):
        props = [prop("p1", "C1", standing,
                      revision_claim="C3" if standing == "revised" else None)]
        res = convener_close(claims, props, [], [])
        assert res["events"] == []
        assert res["derived_standing"]["C1"] == "open"
        assert res["refusals"][0]["reason"].startswith("no linked acceptance")


def test_close_acceptance_by_non_author_refused():
    claims = base_claims()
    props = [prop("p1", "C1", "revised", revision_claim="C3")]
    res = convener_close(claims, props, [acc("C1", "p1", "Claude")], [])
    assert res["events"] == []
    assert "non-author" in res["refusals"][0]["reason"]


def test_close_acceptance_mismatches_refused():
    claims = base_claims()
    props = [prop("p1", "C1", "revised", revision_claim="C3")]
    # Wrong target on the acceptance.
    res = convener_close(claims, props, [acc("C2", "p1", "GPT")], [])
    assert res["events"] == []
    assert "mismatch" in res["refusals"][0]["reason"]
    # Unknown proposal on the acceptance: unmatched, proposal pending.
    res = convener_close(claims, props, [acc("C1", "pX", "GPT")], [])
    assert res["events"] == []
    assert res["unmatched_acceptances"][0]["reason"] == \
        "acceptance cites unknown proposal"
    assert res["refusals"][0]["reason"].startswith("no linked acceptance")


def test_close_generic_endorsement_not_acceptance():
    claims = base_claims()
    props = [prop("p1", "C1", "revised", revision_claim="C3")]
    # Acceptance-shaped record without a proposal id is not acceptance.
    res = convener_close(claims, props,
                         [{"target_claim": "C1", "accepting_author": "GPT"}],
                         [])
    assert res["events"] == []
    assert "generic endorsement" in \
        res["unmatched_acceptances"][0]["reason"]
    # An endorses declaration likewise creates no acceptance.
    props2, _ = extract_proposals(claims, [decl("C2", "C1", "endorses")])
    assert props2 == []


def test_close_c94_defense_without_authorizer_no_maintained():
    # REGRESSION PROOF (contract §8): C94 defends C37, no acceptance
    # from C37's author -> the maintain proposal is preserved, the
    # enactment is not assumed, standing stays open.
    claims = [claim("C37", "GPT", "opening"), claim("C94", "Claude", "revision")]
    props, _ = extract_proposals(
        claims, [decl("C94", "C37", "defends")])
    assert [p["proposed_standing"] for p in props] == ["maintained"]
    res = convener_close(claims, props, [], [])
    assert res["events"] == []
    assert res["derived_standing"]["C37"] == "open"
    assert res["proposals"] == props  # proposal preserved, not dropped
    assert res["refusals"][0]["proposal_id"] == props[0]["id"]


def test_close_user_authorizer_build_council_refused_product_allowed():
    claims = base_claims()
    props = [prop("p1", "C1", "revised", revision_claim="C3")]
    res = convener_close(claims, props,
                         [acc("C1", "p1", "user")], [])
    assert res["events"] == []
    assert "user authorizer invalid in build-council" in \
        res["refusals"][0]["reason"]
    # Product meetings: user acceptance with a cited decision issues
    # under authorizer "user" (validator-consistent).
    res = convener_close(claims, props,
                         [acc("C1", "p1", "user",
                              user_decision="user:yes")], [],
                         meeting_kind="product")
    assert res["events"][0]["authorizer"] == "user"
    # Product without a cited decision: refused.
    res = convener_close(claims, props,
                         [acc("C1", "p1", "user")], [],
                         meeting_kind="product")
    assert res["events"] == []
    assert "without cited decision" in res["refusals"][0]["reason"]


def test_close_supersession_without_rule_or_claim_refused():
    claims = base_claims()
    # No rule cited at all.
    props = [prop("p1", "C1", "superseded", superseding_claim="C3")]
    res = convener_close(claims, props, [], [], meeting_rules=["r1"])
    assert res["events"] == []
    assert "meeting rule" in res["refusals"][0]["reason"]
    # Rule cited but not in force.
    props = [prop("p1", "C1", "superseded", superseding_claim="C3",
                  meeting_rule="rX")]
    res = convener_close(claims, props, [], [], meeting_rules=["r1"])
    assert res["events"] == []
    # Rule in force but superseding claim unknown.
    props = [prop("p1", "C1", "superseded", superseding_claim="C99",
                  meeting_rule="r1")]
    res = convener_close(claims, props, [], [], meeting_rules=["r1"])
    assert res["events"] == []
    assert "superseding claim" in res["refusals"][0]["reason"]


def test_close_absent_from_final_actives_changes_nothing():
    # Close takes NO active-set input by design: the final active set
    # is a report, not a trigger. A proposal excluded from every
    # active list still changes standing only via an event — and
    # here there is none, so standing stays open.
    claims = base_claims()
    props = [prop("p1", "C1", "withdrawn")]
    final_actives = []  # proposal absent from the final active set
    assert props[0]["id"] not in final_actives
    res = convener_close(claims, props, [], [])
    assert res["events"] == []
    assert res["derived_standing"]["C1"] == "open"
    assert res["refusals"][0]["proposal_id"] == "p1"


def test_close_broken_existing_chain_issues_nothing_and_flags_e9():
    claims = base_claims()
    broken = [
        {"event_id": "evt:0", "target_claim": "C1", "prior_standing": "open",
         "new_standing": "revised", "authorizer": "convener-close",
         "authorizing_basis": {"proposal_ids": ["p0"]},
         "revision_claim": "C3", "sequence": 0},
        {"event_id": "evt:1", "target_claim": "C1", "prior_standing": "open",
         "new_standing": "withdrawn", "authorizer": "convener-close",
         "authorizing_basis": {"proposal_ids": ["p1"]}, "sequence": 1},
    ]
    props = [prop("p1", "C1", "maintained")]
    res = convener_close(claims, props, [acc("C1", "p1", "GPT")], [],
                         existing_events=broken)
    assert res["events"] == []
    assert res["existing_chain_broken"] is not None
    assert "chain break" in res["refusals"][0]["reason"]
    codes = event_codes(claims, [], props, broken)
    assert "E9" in codes  # validator independently flags the break


def test_close_issuer_gate_and_legacy_disposition_not_authorization():
    claims = base_claims()
    props = [prop("p1", "C1", "revised", revision_claim="C3")]
    res = convener_close(claims, props, [acc("C1", "p1", "GPT")], [],
                         issuer="GPT")
    assert res["events"] == []
    assert "issuer is not convener-close" in res["refusals"][0]["reason"]
    # C4 authorial disposition (legacy observation) is not acceptance:
    # an original carrying disposition=revised, by its own revision,
    # with no acceptance record, issues nothing.
    legacy = [dict(claims[0], disposition="revised", disposition_by="C3"),
              claims[1], claims[2]]
    res = convener_close(legacy, props, [], [])
    assert res["events"] == []
    assert res["derived_standing"]["C1"] == "open"


def test_close_revised_without_revision_claim_and_bad_proposals():
    claims = base_claims()
    # Revised proposal without revision_claim: E8 prevention.
    props = [prop("p1", "C1", "revised")]
    res = convener_close(claims, props, [acc("C1", "p1", "GPT")], [])
    assert res["events"] == []
    assert "revision claim" in res["refusals"][0]["reason"]
    # Dangling target, missing proposer, open standing, duplicates.
    props = [
        prop("p1", "C99", "revised", revision_claim="C3"),
        prop("p2", "C1", "withdrawn", proposer=""),
        prop("p3", "C1", "open"),
        prop("p1", "C1", "withdrawn"),
    ]
    res = convener_close(claims, props, [], [])
    assert res["events"] == []
    reasons = [r["reason"] for r in res["refusals"]]
    assert any("unknown claim" in r for r in reasons)
    assert any("without proposer" in r for r in reasons)
    assert any("not issuable" in r for r in reasons)
    assert any("duplicate proposal id" in r for r in reasons)


def test_close_challenge_withdrawn_no_contested():
    claims = base_claims()
    existing = [{"event_id": "evt:0", "target_claim": "C2",
                 "prior_standing": "open", "new_standing": "withdrawn",
                 "authorizer": "convener-close",
                 "authorizing_basis": {"proposal_ids": ["p0"]},
                 "sequence": 0}]
    chals = [{"challenge_claim": "C2", "target": "C1"}]
    res = convener_close(claims, [], [], chals, existing_events=existing)
    assert res["events"] == []
    assert res["derived_standing"]["C1"] == "open"


def test_close_validator_clean_for_mixed_issued_events():
    claims = base_claims()
    decls = [decl("C2", "C1", "challenges")]
    props = [
        prop("p1", "C1", "revised", revision_claim="C3"),
        prop("p2", "C1", "superseded", superseding_claim="C3",
             meeting_rule="r1"),
    ]
    res = convener_close(claims, props, [acc("C1", "p1", "GPT")],
                         [{"challenge_claim": "C2", "target": "C1"}],
                         meeting_rules=["r1"])
    assert [e["new_standing"] for e in res["events"]] == [
        "revised", "superseded", "contested-standing"]
    assert event_codes(claims, decls, props, res["events"],
                       meeting_rules=["r1"]) & {"E7", "E8", "E9"} == set()
    # Revision does not resolve a challenge: last-wins derivation
    # leaves the target contested-standing (documented v1 ordering).
    assert res["derived_standing"]["C1"] == "contested-standing"


# ---------------------------------------------------------------------------
# Wiring + regression safety (acceptance 3)
# ---------------------------------------------------------------------------


def test_section_unchanged_without_close():
    section = build_transjective_record(base_claims())
    assert "proposals" not in section
    assert "events" not in section
    assert "close_report" not in section


def test_section_carries_close_results():
    claims = base_claims()
    props = [prop("p1", "C1", "revised", revision_claim="C3")]
    res = convener_close(claims, props, [acc("C1", "p1", "GPT")], [])
    section = build_transjective_record(
        claims, proposals=res["proposals"], events=res["events"],
        close_report={"issued_event_ids": [e["event_id"]
                                           for e in res["events"]],
                      "refusals": res["refusals"],
                      "unmatched_acceptances": res["unmatched_acceptances"]})
    assert section["proposals"] == res["proposals"]
    assert section["events"] == res["events"]
    assert section["close_report"]["issued_event_ids"] == ["evt:0"]
    assert section["contract_standing"]["C1"] == "revised"


def test_artifact_build_runs_close():
    c1 = Claim(id="C1", participant="GPT", phase="opening", text="one")
    c2 = Claim(id="C2", participant="Claude", phase="response", text="two",
               relationship="challenges", relationship_target="C1")
    registry = SimpleNamespace(claims=[c1, c2])
    packet = SimpleNamespace(work_item="w", question="q")
    transcript = SimpleNamespace(entries=[])
    artifact = build_draft_artifact_r2("m1", packet, transcript, [], registry)
    section = artifact["transjective_record"]
    assert "close_report" in section
    assert [e["new_standing"] for e in section["events"]] == \
        ["contested-standing"]
    assert section["contract_standing"]["C1"] == "contested-standing"
    # Registry standing is untouched by close: it lives under its own
    # key and is computed independently of contract standing.
    assert "claim_standing" in artifact
