"""Increment D: disagreement records at close time.

Convener-recorded pairs are tested directly on build_disagreement /
validate_disagreement and through the record validator and the
artifact close funnel, with synthetic fixtures (no model calls, no
spend). Fixture claims carry no exposure, so validator reports
contain fixture codes (e.g. E12); tests filter to the codes under
test (E10/E1/W3) instead of asserting full conformance. No
model-emitted incompatibility parser exists in v1 (deliberate);
these tests cover convener-recorded pairs only.
"""

from types import SimpleNamespace

from local_ai.build_room.artifact import build_draft_artifact_r2
from local_ai.build_room.disagreements import (
    STAGES,
    build_disagreement,
    validate_disagreement,
)
from local_ai.build_room.meeting import Claim
from local_ai.build_room.transjective_record import (
    build_transjective_record,
    validate_contract_record,
)


def claims():
    return [
        {"id": "C1", "participant": "GPT", "phase": "opening", "text": "tC1"},
        {"id": "C2", "participant": "Claude", "phase": "response", "text": "tC2"},
        {"id": "C3", "participant": "Gemini", "phase": "response", "text": "tC3"},
    ]


def pair(**over):
    d = build_disagreement(
        id="dis:0",
        claims=["C1", "C2"],
        incompatibility="C1 says X, C2 says not-X.",
        proposer="convener",
        cited_evidence=["C1", "C2"],
        stage="identified",
    )
    d.update(over)
    return d


def errors_of(report, code):
    return [e for e in report["errors"] if e["code"] == code]


def warnings_of(report, code):
    return [e for e in report["warnings"] if e["code"] == code]


def validate_with(disagreements):
    record = {"claims": claims(), "disagreements": disagreements}
    return validate_contract_record(record)


# --- constructor ---


def test_build_disagreement_exact_fields():
    d = pair()
    assert set(d) == {
        "id", "claims", "incompatibility", "proposer",
        "cited_evidence", "stage",
    }
    assert d["id"] == "dis:0"
    assert d["claims"] == ["C1", "C2"]
    assert d["incompatibility"] == "C1 says X, C2 says not-X."
    assert d["proposer"] == "convener"
    assert d["cited_evidence"] == ["C1", "C2"]
    assert d["stage"] == "identified"


def test_stage_articulated_preserved():
    assert pair(stage="articulated")["stage"] == "articulated"
    assert STAGES == ("identified", "articulated")


def test_cited_evidence_string_kept_whole():
    d = pair(cited_evidence="C1 says X in its own words.")
    assert d["cited_evidence"] == "C1 says X in its own words."


def test_cited_evidence_list_copied():
    evidence = ["C1", "C2"]
    d = build_disagreement("dis:0", ["C1", "C2"], "x", "convener",
                           evidence, "identified")
    evidence.append("C3")
    assert d["cited_evidence"] == ["C1", "C2"]


# --- helper validation (E10 conditions only) ---


def test_validate_helper_valid():
    assert validate_disagreement(pair()) == []


def test_validate_helper_fewer_than_two():
    assert validate_disagreement(pair(claims=["C1"])) == ["E10"]
    assert validate_disagreement(pair(claims=[])) == ["E10"]


def test_validate_helper_missing_incompatibility():
    assert validate_disagreement(pair(incompatibility="")) == ["E10"]


def test_validate_helper_missing_proposer():
    assert validate_disagreement(pair(proposer="")) == ["E10"]


def test_validate_helper_stage_clarified():
    assert validate_disagreement(pair(stage="clarified")) == ["E10"]


def test_validate_helper_stage_other_invalid():
    assert validate_disagreement(pair(stage="resolved")) == ["E10"]


def test_validate_helper_multiple_violations():
    d = pair(claims=["C1"], incompatibility="", proposer="")
    assert validate_disagreement(d) == ["E10", "E10", "E10"]


# --- record validator: E10 cases, each failing E10 ---


def test_validator_valid_pair_no_e10():
    report = validate_with([pair(), pair(id="dis:1", stage="articulated",
                                         claims=["C1", "C2", "C3"])])
    assert errors_of(report, "E10") == []


def test_validator_fewer_than_two_e10():
    assert errors_of(validate_with([pair(claims=["C1"])]), "E10")


def test_validator_missing_incompatibility_e10():
    assert errors_of(validate_with([pair(incompatibility="")]), "E10")


def test_validator_missing_proposer_e10():
    assert errors_of(validate_with([pair(proposer="")]), "E10")


def test_validator_stage_clarified_e10():
    report = validate_with([pair(stage="clarified")])
    assert errors_of(report, "E10")
    # Clarified is failed, never silently accepted or rewritten.
    assert report["errors"]


def test_validator_missing_evidence_warns_w3_only():
    report = validate_with([pair(cited_evidence=None)])
    assert errors_of(report, "E10") == []
    assert warnings_of(report, "W3")


def test_validator_unknown_claim_e1():
    report = validate_with([pair(claims=["C1", "C9"])])
    assert errors_of(report, "E1")


def test_validator_duplicate_disagreement_id_e1():
    report = validate_with([pair(), pair()])
    assert errors_of(report, "E1")


# --- section wiring: shape + standing separation ---


def test_section_no_new_key_when_unsupplied():
    section = build_transjective_record(claims())
    assert "disagreements" not in section


def test_section_key_when_supplied():
    section = build_transjective_record(claims(), disagreements=[pair()])
    assert section["disagreements"] == [pair()]
    section_empty = build_transjective_record(claims(), disagreements=[])
    assert section_empty["disagreements"] == []


def test_section_adds_no_events():
    # D's path issues nothing: with disagreements but no close
    # report, the section carries no events key at all.
    section = build_transjective_record(claims(), disagreements=[pair()])
    assert "events" not in section


def test_standing_unchanged_by_disagreements():
    events = [
        {"event_id": "evt:0", "target_claim": "C1",
         "new_standing": "revised", "sequence": 0},
        {"event_id": "evt:1", "target_claim": "C2",
         "new_standing": "maintained", "sequence": 1},
        {"event_id": "evt:2", "target_claim": "C3",
         "new_standing": "contested-standing", "sequence": 2},
    ]
    base = build_transjective_record(claims(), events=events,
                                     close_report={})
    with_dis = build_transjective_record(
        claims(), events=events, close_report={},
        disagreements=[pair(), pair(id="dis:1", claims=["C2", "C3"])])
    assert with_dis["contract_standing"] == base["contract_standing"]
    assert with_dis["contract_standing"] == {
        "C1": "revised", "C2": "maintained",
        "C3": "contested-standing",
    }


# --- artifact close funnel ---


def _artifact(disagreements_marker, *claim_objs, **kw):
    registry = SimpleNamespace(claims=list(claim_objs))
    packet = SimpleNamespace(work_item="w", question="q")
    transcript = SimpleNamespace(entries=[])
    if disagreements_marker is None:
        return build_draft_artifact_r2("m1", packet, transcript, [],
                                       registry, **kw)
    return build_draft_artifact_r2("m1", packet, transcript, [],
                                   registry,
                                   disagreements=disagreements_marker,
                                   **kw)


def test_artifact_funnel_carries_disagreements():
    c1 = Claim(id="C1", participant="GPT", phase="opening", text="one")
    c2 = Claim(id="C2", participant="Claude", phase="response", text="two")
    artifact = _artifact([pair()], c1, c2)
    section = artifact["transjective_record"]
    assert section["disagreements"] == [pair()]
    # No events: no challenges, no acceptances, and D adds none.
    assert section["events"] == []
    assert section["contract_standing"]["C1"] == "open"


def test_artifact_funnel_no_key_when_unsupplied():
    c1 = Claim(id="C1", participant="GPT", phase="opening", text="one")
    c2 = Claim(id="C2", participant="Claude", phase="response", text="two")
    artifact = _artifact(None, c1, c2)
    assert "disagreements" not in artifact["transjective_record"]


def test_disagreement_alone_issues_no_contested_event():
    # The §4.3 bar needs a challenge CLAIM; a disagreement record
    # citing the same claims is not one, so close issues nothing.
    c1 = Claim(id="C1", participant="GPT", phase="opening", text="one")
    c2 = Claim(id="C2", participant="Claude", phase="response", text="two")
    artifact = _artifact([pair()], c1, c2)
    section = artifact["transjective_record"]
    assert section["events"] == []
    assert section["contract_standing"]["C1"] == "open"


def test_disagreement_plus_challenge_contested_via_c():
    # Same disagreement, but now a genuine challenge candidate
    # exists: C's machinery issues contested-standing, unchanged
    # by D's presence. D issued nothing; the one event is C's.
    c1 = Claim(id="C1", participant="GPT", phase="opening", text="one")
    c2 = Claim(id="C2", participant="Claude", phase="response", text="two",
               relationship="challenges", relationship_target="C1")
    artifact = _artifact([pair()], c1, c2)
    section = artifact["transjective_record"]
    assert [e["new_standing"] for e in section["events"]] == \
        ["contested-standing"]
    assert section["contract_standing"]["C1"] == "contested-standing"
    assert section["disagreements"] == [pair()]


def test_presupplied_record_bypasses_close_unchanged():
    c1 = Claim(id="C1", participant="GPT", phase="opening", text="one")
    supplied = {"version": 1, "caller-owned": True}
    registry = SimpleNamespace(claims=[c1])
    packet = SimpleNamespace(work_item="w", question="q")
    transcript = SimpleNamespace(entries=[])
    artifact = build_draft_artifact_r2(
        "m1", packet, transcript, [], registry,
        transjective_record=supplied, disagreements=[pair()])
    assert artifact["transjective_record"] == supplied
