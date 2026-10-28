"""Registry standing stage-1 tests: pure derivation, no live calls.

Covers design v2: last-valid-move-wins standing, same-author rule,
prohibited moves recorded (never applied), defense as a non-move,
conservative retraction-language signals, provenance from
interactions, and input immutability. No meeting runs, no staging.
"""

from __future__ import annotations

import copy

from local_ai.build_room.claim_standing import compute_claim_standing


def C(cid, participant, phase, status="unknown", **kw):
    d = {
        "id": cid,
        "participant": participant,
        "phase": phase,
        "text": "",
        "status": status,
        "relationship": None,
        "relationship_target": None,
        "supersedes": None,
        "withdraws": None,
        "epistemic_assessment": "unresolved",
        "assessment_sources": [],
    }
    d.update(kw)
    return d


def entry(table, cid):
    return next(e for e in table["entries"] if e["claim_id"] == cid)


def test_empty_record():
    table = compute_claim_standing([], [])
    assert table == {"version": 1, "entries": []}


def test_no_moves_all_active_provenance_and_assessment():
    claims = [
        C("C1", "GPT", "opening", "Observed"),
        C("C2", "Claude", "opening", "Inferred",
          epistemic_assessment="challenged", assessment_sources=["C9"]),
    ]
    interactions = [
        {"participant": "GPT", "phase": "opening",
         "grounded_tool_citations": 2, "unverified_tool_citations": 0},
        {"participant": "Claude", "phase": "opening",
         "grounded_tool_citations": 0, "unverified_tool_citations": 3},
    ]
    table = compute_claim_standing(claims, interactions)
    assert [e["claim_id"] for e in table["entries"]] == ["C1", "C2"]
    assert entry(table, "C1")["standing"] == "active"
    assert entry(table, "C1")["provenance"] == "grounded"
    assert entry(table, "C1")["standing_chain"] == []
    assert entry(table, "C2")["standing"] == "active"
    assert entry(table, "C2")["provenance"] == "unverified"
    assert entry(table, "C2")["assessment"] == "challenged"
    assert entry(table, "C2")["assessment_sources"] == ["C9"]
    # No interaction for a contribution means provenance "none".
    assert compute_claim_standing(
        [C("C1", "Muse", "opening")], [])["entries"][0]["provenance"] == "none"


def test_same_author_withdrawal_and_supersession():
    claims = [
        C("C1", "GPT", "opening", "Observed"),
        C("C2", "GPT", "opening", "Observed"),
        C("C3", "GPT", "revision", text="Revised.", supersedes="C1"),
        C("C4", "GPT", "revision", text="Withdrawn.", withdraws="C2"),
    ]
    table = compute_claim_standing(claims, [])
    assert entry(table, "C1")["standing"] == "superseded"
    assert entry(table, "C1")["standing_chain"] == [
        {"move": "supersession", "by": "C3", "target": "C1"}
    ]
    assert entry(table, "C2")["standing"] == "withdrawn"
    assert entry(table, "C2")["standing_chain"] == [
        {"move": "withdrawal", "by": "C4", "target": "C2"}
    ]


def test_last_valid_move_wins_with_full_chain():
    # Withdrawn then superseded: non-monotonic, defined, visible.
    claims = [
        C("C1", "Claude", "opening", "Observed"),
        C("C2", "Claude", "revision", text="Withdrawn.", withdraws="C1"),
        C("C3", "Claude", "revision", text="Revised.", supersedes="C1"),
    ]
    table = compute_claim_standing(claims, [])
    e = entry(table, "C1")
    assert e["standing"] == "superseded"
    assert e["standing_chain"] == [
        {"move": "withdrawal", "by": "C2", "target": "C1"},
        {"move": "supersession", "by": "C3", "target": "C1"},
    ]


def test_defense_is_not_a_move_and_cross_author_ignored():
    claims = [
        C("C1", "GPT", "opening", "Observed"),
        C("C2", "GPT", "revision", relationship="defended",
          relationship_target="C1", text="Defended."),
        # Cross-author links never move standing (proposals only).
        C("C3", "Claude", "revision", text="Revised.", supersedes="C1"),
        C("C4", "Claude", "revision", text="Withdrawn.", withdraws="C1"),
    ]
    table = compute_claim_standing(claims, [])
    e = entry(table, "C1")
    assert e["standing"] == "active"
    assert e["standing_chain"] == []
    assert e["rejected_moves"] == []


def test_prohibited_moves_recorded_never_applied():
    claims = [
        C("C1", "GPT", "opening", "Observed"),
        C("C2", "GPT", "revision", text="Self.", supersedes="C2"),
        C("C3", "GPT", "revision", text="Forward.", withdraws="C4"),
        C("C4", "GPT", "revision", text="Later."),
        C("C5", "GPT", "revision", text="Ghost.", withdraws="C99"),
    ]
    table = compute_claim_standing(claims, [])
    assert entry(table, "C1")["standing"] == "active"
    assert entry(table, "C2")["rejected_moves"] == [
        {"target": "C2", "move": "supersession", "reason": "self_target"}
    ]
    assert entry(table, "C3")["rejected_moves"] == [
        {"target": "C4", "move": "withdrawal", "reason": "forward_reference"}
    ]
    assert entry(table, "C5")["rejected_moves"] == [
        {"target": "C99", "move": "withdrawal", "reason": "unknown_target"}
    ]
    assert entry(table, "C4")["standing"] == "active"


def test_retraction_signals_positive_ambiguous_and_scoped():
    claims = [
        C("C1", "Claude", "opening", "Observed"),
        C("C2", "Claude", "opening", "Observed"),
        C("C3", "Claude", "revision",
          text="I retract the read statements in C1."),
        C("C4", "Claude", "revision",
          text="I do not withdraw C2."),
        # Response-phase retraction language: not a signal (revisions only).
        C("C5", "Claude", "response",
          text="I retract C1."),
        # Cross-author revision retraction language: not a signal.
        C("C6", "GPT", "revision",
          text="I retract C1."),
    ]
    table = compute_claim_standing(claims, [])
    sigs = entry(table, "C1")["retraction_signals"]
    assert len(sigs) == 1
    assert sigs[0]["by"] == "C3"
    assert sigs[0]["kind"] == "signal"
    assert sigs[0]["pattern"].lower().startswith("retract")
    assert "retract" in sigs[0]["text"].lower()
    assert entry(table, "C1")["standing"] == "active"  # signal never moves
    amb = entry(table, "C2")["retraction_signals"]
    assert len(amb) == 1 and amb[0]["kind"] == "ambiguous"
    assert amb[0]["by"] == "C4"


def test_retraction_signal_range_expands_for_signals_only():
    claims = [
        C("C1", "Claude", "opening", "Observed"),
        C("C2", "Claude", "opening", "Observed"),
        C("C3", "Claude", "opening", "Observed"),
        C("C4", "Claude", "revision",
          text="The citations in C1–C3 are fabricated. I withdraw them."),
    ]
    table = compute_claim_standing(claims, [])
    for cid in ("C1", "C2", "C3"):
        assert len(entry(table, cid)["retraction_signals"]) == 1
        # A range is a signal, never a move.
        assert entry(table, cid)["standing"] == "active"


def test_probe_shaped_c6_case():
    # Mirrors the corrective probe: C6 Observed + challenged, C54
    # defended, C56 prose retraction over a range. Standing stays
    # active, the retraction is visible, provenance unverified.
    claims = [
        C("C6", "Claude", "opening", "Observed",
          epistemic_assessment="challenged", assessment_sources=["C33"]),
        C("C54", "Claude", "revision", relationship="defended",
          relationship_target="C6",
          text="Defended. The values remain internally consistent."),
        C("C56", "Claude", "revision",
          text="(Withdrawn) The line-number citations in C6–C9 are "
               "fabricated. I cannot cite ranges to a file I did not read."),
    ]
    interactions = [
        {"participant": "Claude", "phase": "opening",
         "grounded_tool_citations": 0, "unverified_tool_citations": 8},
    ]
    before = copy.deepcopy(claims)
    table = compute_claim_standing(claims, interactions)
    e = entry(table, "C6")
    assert e["standing"] == "active"
    assert e["assessment"] == "challenged"
    assert e["provenance"] == "unverified"
    assert len(e["retraction_signals"]) == 1
    assert e["retraction_signals"][0]["by"] == "C56"
    assert e["retraction_signals"][0]["kind"] == "signal"
    # The derivation never mutates its input record.
    assert claims == before


def test_provenance_falls_back_to_citation_list():
    claims = [C("C1", "GPT", "opening")]
    interactions = [
        {"participant": "GPT", "phase": "opening",
         "tool_citations": [{"status": "grounded"}, {"status": "unverified"}]},
    ]
    table = compute_claim_standing(claims, interactions)
    assert table["entries"][0]["provenance"] == "grounded"
