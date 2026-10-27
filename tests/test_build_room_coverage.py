"""Build-Council Room coverage assurance (amended design, 2026-10-26).

Deterministic only: no model is called, no meeting runs on live
keys. Regression cases use the transcribed Tier 2 structured outputs
plus the fixture-builder registries; everything else is synthetic.

Covers design §G: objection + proposal regression (recalculated
table), consolidation semantics, acceptance semantics, boundary
tests, latency, cost, route-level fields, meeting-phase wiring,
instruction byte-identity, and the unchanged caps.
"""

from __future__ import annotations

import asyncio
import copy
import hashlib
import json
from pathlib import Path

import pytest
from fastapi import FastAPI

from api.routes import build_room_routes as br_routes
from api.routes.auth_routes import get_current_user
from local_ai.build_room import candidate_cap
from local_ai.build_room import coverage as coverage_mod
from local_ai.build_room import harness_fixtures as hf
from local_ai.build_room import measurement as measurement_mod
from local_ai.build_room.coverage import (
    artifact_accepted,
    check_coverage,
    coverage_function_signature,
)
from local_ai.build_room.meeting import (
    Budget,
    Claim,
    ClaimRegistry,
    EvidencePacket,
    _SYNTHESIS_INSTRUCTION,
    parse_synthesis_contract,
    run_multi_model_meeting,
)
from local_ai.build_room.measurement import (
    compute_generation_cost,
    evaluate_tripwire,
    measure_generation,
)
from local_ai.build_room.participants import SEAT_SPECS, Seat
from local_ai.llm.tokenizer import count_tokens

YOUR_FILES = Path.home() / "workspace" / "your_files"
OWNER = {"id": "owner-id", "email": "owner@local.zenaf"}

INSTRUCTION_SHA256 = (
    "5e987f26296abf7af87578b143d3a1ef99ed740e2481116e6f74ce9c36e24ecd")
TEST_PRICE_TABLE = {
    "model": "gpt-4o-mini-test",
    "per_1m_input_usd": 2.0,
    "per_1m_output_usd": 4.0,
    "provenance": "test table (not a provider price)",
    "retrieved_date": "2026-10-26",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _registry(specs: list[tuple[str, str, str | None, str | None]]) -> ClaimRegistry:
    """Build a registry from (id, status, disposition, disposition_by)."""
    reg = ClaimRegistry()
    for cid, status, disp, disp_by in specs:
        reg.claims.append(Claim(
            id=cid, participant="GPT", phase="opening", text=f"Claim {cid}.",
            status=status, disposition=disp, disposition_by=disp_by))
    return reg


def _tier2(name: str):
    """(structured, evaluations, registry, unresolved) for a Tier 2 call."""
    builder = {"fitting": hf.fixture_fitting_state,
               "failed": hf.fixture_failed_state,
               "stress": hf.fixture_stress_state}[name]
    _packet, reg, unresolved, _chains = builder()
    resp = json.loads(
        (YOUR_FILES / f"zenaf-build-council-tier2-{name}-response.json").read_text())
    return resp["structured"], resp["evaluations"], reg, unresolved


def _obj_pairs(cov: dict) -> list[tuple[str, str]]:
    return [(o["target_claim_id"], o["challenger_claim_id"])
            for o in cov["objections"]["covered"]]


def _obj_omitted(cov: dict) -> list[tuple[str, str]]:
    return [(o["target_claim_id"], o["challenger_claim_id"])
            for o in cov["objections"]["omitted"]]


def _prop_omitted(cov: dict) -> list[str]:
    return [o["proposal_claim_id"] for o in cov["proposals"]["omitted"]]


# ---------------------------------------------------------------------------
# §G.1 Objection regression (recalculated table)
# ---------------------------------------------------------------------------

def test_fitting_objections_fail_exact():
    structured, _evals, reg, unresolved = _tier2("fitting")
    cov = check_coverage(reg, unresolved, structured)
    assert cov["verdict"] == "fail"
    assert _obj_omitted(cov) == [("C15", "C32")]
    assert cov["objections"]["covered"] == []
    assert [(o["target_claim_id"], o["challenger_claim_id"])
            for o in cov["objections"]["not_required"]] == [
        ("C3", "C39"), ("C14", "C45")]


def test_stress_objections_fail_exact_two_omitted():
    structured, _evals, reg, unresolved = _tier2("stress")
    cov = check_coverage(reg, unresolved, structured)
    assert cov["verdict"] == "fail"
    assert _obj_omitted(cov) == [("C33", "C45"), ("C79", "C93")]
    assert _obj_pairs(cov) == [
        ("C2", "C41"), ("C4", "C43"), ("C19", "C48"), ("C25", "C46"),
        ("C31", "C47"), ("C71", "C85"), ("C74", "C88")]
    assert cov["objections"]["not_required"] == []


def test_failed_objections_fail_recalculated():
    """Recalculated 2026-10-26: D1 cites challenger C53, never target C6."""
    structured, _evals, reg, unresolved = _tier2("failed")
    cov = check_coverage(reg, unresolved, structured)
    assert cov["verdict"] == "fail"
    assert _obj_omitted(cov) == [("C6", "C53")]
    assert [(o["target_claim_id"], o["challenger_claim_id"])
            for o in cov["objections"]["not_required"]] == [
        ("C25", "C37"), ("C3", "C40"), ("C9", "C47"), ("C27", "C47")]


def test_responded_to_never_demanded():
    reg = _registry([("C1", "Observed", None, None)])
    unresolved = [{"claim_id": "C1", "source_claim_id": "C2",
                   "state": "responded_to"}]
    cov = check_coverage(reg, unresolved, {
        "positions": [], "disagreements": [], "recommendations": [],
        "limitations": []})
    assert cov["objections"]["required"] == []
    assert cov["objections"]["omitted"] == []
    assert cov["objections"]["not_required"] == [
        {"target_claim_id": "C1", "challenger_claim_id": "C2",
         "state": "responded_to"}]


def test_superseded_target_objection_still_demanded():
    reg = _registry([("C1", "Observed", "revised", "C9")])
    unresolved = [{"claim_id": "C1", "source_claim_id": "C2",
                   "state": "unresolved"}]
    cov = check_coverage(reg, unresolved, {
        "positions": [], "disagreements": [], "recommendations": [],
        "limitations": []})
    assert _obj_omitted(cov) == [("C1", "C2")]


def test_two_challengers_one_target():
    """Weaver regression requirement: both-IDs rule, three sub-cases."""
    reg = _registry([("C10", "Observed", None, None),
                     ("C20", "Observed", None, None),
                     ("C30", "Observed", None, None)])
    unresolved = [
        {"claim_id": "C10", "source_claim_id": "C20", "state": "unresolved"},
        {"claim_id": "C10", "source_claim_id": "C30", "state": "unresolved"},
    ]

    def _disagreements(entries):
        return {"positions": [], "disagreements": entries,
                "recommendations": [], "limitations": []}

    def _dis(supporting):
        return {"opposing_positions": ["A", "B"],
                "supporting_claims": supporting,
                "unresolved_status": "unresolved"}

    # One challenger addressed: only that unit covered.
    cov = check_coverage(reg, unresolved, _disagreements([_dis(["C10", "C20"])]))
    assert _obj_pairs(cov) == [("C10", "C20")]
    assert _obj_omitted(cov) == [("C10", "C30")]
    assert cov["verdict"] == "fail"
    # Both addressed, each in its own entry: both covered.
    cov = check_coverage(reg, unresolved, _disagreements(
        [_dis(["C10", "C20"]), _dis(["C10", "C30"])]))
    assert _obj_pairs(cov) == [("C10", "C20"), ("C10", "C30")]
    assert _obj_omitted(cov) == []
    # Target alone: neither covered (pins the both-IDs rule against
    # any future regression to target-only coverage).
    cov = check_coverage(reg, unresolved, _disagreements([_dis(["C10"])]))
    assert _obj_omitted(cov) == [("C10", "C20"), ("C10", "C30")]
    # Challenger alone: neither covered.
    cov = check_coverage(reg, unresolved, _disagreements([_dis(["C20"])]))
    assert _obj_omitted(cov) == [("C10", "C20"), ("C10", "C30")]


# ---------------------------------------------------------------------------
# §G.2 Proposal regression + semantics
# ---------------------------------------------------------------------------

def test_fitting_proposals_fail_all_twelve():
    structured, _evals, reg, unresolved = _tier2("fitting")
    cov = check_coverage(reg, unresolved, structured)
    assert _prop_omitted(cov) == [
        "C3", "C10", "C15", "C20", "C23", "C34", "C40", "C46", "C49",
        "C54", "C61", "C68"]
    # C20's D4 citation does not cover it: disagreements never
    # satisfy proposal demand.
    assert "C20" in _prop_omitted(cov)


def test_stress_proposals_vacuous_pass():
    structured, _evals, reg, unresolved = _tier2("stress")
    cov = check_coverage(reg, unresolved, structured)
    assert cov["proposals"]["required"] == []
    assert cov["proposals"]["omitted"] == []
    # Overall still fails — on objections alone.
    assert cov["verdict"] == "fail"


def test_failed_proposals_fail_exact_seven():
    structured, _evals, reg, unresolved = _tier2("failed")
    cov = check_coverage(reg, unresolved, structured)
    assert _prop_omitted(cov) == ["C3", "C16", "C22", "C44", "C48", "C51", "C63"]
    assert [(c["proposal_claim_id"], c["via"])
            for c in cov["proposals"]["covered"]] == [
        ("C10", "cited"), ("C25", "cited"), ("C43", "cited")]
    # Status-"unknown" lookalike proposals are NOT demanded.
    assert "C35" not in cov["proposals"]["required"]
    assert "C57" not in cov["proposals"]["required"]


def _fitting_demand_structured(recommendations):
    _s, _e, reg, unresolved = _tier2("fitting")
    return reg, unresolved, {"positions": [], "disagreements": [],
                             "recommendations": recommendations,
                             "limitations": []}


def _rec(action, supporting, consolidates=None):
    entry = {"proposed_action": action, "supporting_claims": supporting}
    if consolidates is not None:
        entry["consolidates_claim_ids"] = consolidates
    return entry


def test_legitimate_consolidation_covers_declared_thread():
    reg, unresolved, structured = _fitting_demand_structured(
        [_rec("Adopt the negative criterion.", ["C10"],
              ["C40", "C46", "C49", "C68"])])
    cov = check_coverage(reg, unresolved, structured)
    covered = {c["proposal_claim_id"]: c["via"]
               for c in cov["proposals"]["covered"]}
    assert covered == {"C10": "cited", "C40": "consolidated",
                       "C46": "consolidated", "C49": "consolidated",
                       "C68": "consolidated"}
    # Consolidation covers what it declares, nothing more.
    assert len(_prop_omitted(cov)) == 7
    assert cov["verdict"] == "fail"


def test_full_consolidation_passes_proposals_component():
    reg, unresolved, structured = _fitting_demand_structured([
        _rec("Adopt the negative criterion.", ["C10"],
             ["C40", "C46", "C49", "C68"]),
        _rec("Cover the rest.", ["C3", "C15", "C20", "C23", "C34",
                                 "C54", "C61"]),
    ])
    cov = check_coverage(reg, unresolved, structured)
    assert cov["proposals"]["omitted"] == []
    # Objections component still fails (C15/C32 unaddressed) —
    # components are asserted separately.
    assert _obj_omitted(cov) == [("C15", "C32")]


def test_supersession_and_withdrawal():
    reg = _registry([("P1", "Proposed", "revised", "P2"),
                     ("P2", "Proposed", None, None),
                     ("P3", "Proposed", "withdrawn", "P3")])
    cov = check_coverage(reg, [], {"positions": [], "disagreements": [],
                                  "recommendations": [_rec("Do P2.", ["P2"])],
                                  "limitations": []})
    assert cov["proposals"]["required"] == ["P2"]
    assert cov["proposals"]["omitted"] == []
    assert cov["proposals"]["not_required"] == [
        {"proposal_claim_id": "P1", "fate": "revised", "disposition_by": "P2"},
        {"proposal_claim_id": "P3", "fate": "withdrawn", "disposition_by": "P3"}]
    # Withdrawn-only registry + empty recommendations: vacuous pass.
    reg2 = _registry([("P3", "Proposed", "withdrawn", "P3")])
    cov2 = check_coverage(reg2, [], {"positions": [], "disagreements": [],
                                    "recommendations": [], "limitations": []})
    assert cov2["proposals"]["required"] == []
    assert cov2["proposals"]["omitted"] == []


def test_legitimate_empty_both_fields():
    reg = _registry([("C1", "Observed", None, None)])
    cov = check_coverage(reg, [], {"positions": [], "disagreements": [],
                                  "recommendations": [], "limitations": []})
    assert cov["verdict"] == "pass"
    assert cov["proposals"]["required"] == []
    assert cov["objections"]["required"] == []


def test_invalid_consolidates_is_coverage_failure_not_warning():
    """Amended rule: entry kept, list ignored, verdict FAILS."""
    reg = _registry([("C10", "Proposed", None, None)])
    base = {"positions": [], "disagreements": [], "limitations": []}

    # Unknown ID in consolidates: C10 still covered via citation,
    # but the provenance defect alone fails the verdict.
    structured = dict(base, recommendations=[
        _rec("Do it.", ["C10"], ["C99"])])
    # Parse first: the validator must mark, not drop, the entry.
    block = json.dumps({
        "positions": [], "disagreements": [],
        "recommendations": [{"proposed_action": "Do it.",
                             "supporting_claims": ["C10"],
                             "consolidates_claim_ids": ["C99"]}],
        "limitations": []})
    parsed, _evals, _rejected, found = parse_synthesis_contract(
        f"```json\n{block}\n```", reg, [], "GPT")
    assert found is True
    assert len(parsed["recommendations"]) == 1  # entry retained
    assert "consolidates_claim_ids" not in parsed["recommendations"][0]
    cov = check_coverage(reg, [], parsed)
    assert cov["proposals"]["covered"][0]["proposal_claim_id"] == "C10"
    assert cov["provenance_failures"] == [
        {"kind": "consolidates_unknown_ids", "recommendation_index": 0,
         "detail": ["C99"]}]
    assert cov["verdict"] == "fail"
    assert cov["warnings"] == []

    # Malformed list (not a list): same handling, malformed kind.
    block2 = json.dumps({
        "positions": [], "disagreements": [],
        "recommendations": [{"proposed_action": "Do it.",
                             "supporting_claims": ["C10"],
                             "consolidates_claim_ids": "C10"}],
        "limitations": []})
    parsed2, _e2, _r2, _f2 = parse_synthesis_contract(
        f"```json\n{block2}\n```", reg, [], "GPT")
    assert len(parsed2["recommendations"]) == 1
    cov2 = check_coverage(reg, [], parsed2)
    assert cov2["provenance_failures"][0]["kind"] == "consolidates_malformed"
    assert cov2["verdict"] == "fail"

    # Valid consolidates are retained by the validator.
    block3 = json.dumps({
        "positions": [], "disagreements": [],
        "recommendations": [{"proposed_action": "Do it.",
                             "supporting_claims": ["C10"],
                             "consolidates_claim_ids": ["C10"]}],
        "limitations": []})
    parsed3, _e3, _r3, _f3 = parse_synthesis_contract(
        f"```json\n{block3}\n```", reg, [], "GPT")
    assert parsed3["recommendations"][0]["consolidates_claim_ids"] == ["C10"]


def test_rejected_entries_do_not_cover():
    reg = _registry([("C10", "Proposed", None, None)])
    block = json.dumps({
        "positions": [], "disagreements": [],
        "recommendations": [{"proposed_action": "Do it.",
                             "supporting_claims": ["C99"]}],
        "limitations": []})
    parsed, _evals, rejected, _found = parse_synthesis_contract(
        f"```json\n{block}\n```", reg, [], "GPT")
    assert len(rejected) == 1
    assert parsed["recommendations"] == []
    cov = check_coverage(reg, [], parsed)
    assert _prop_omitted(cov) == ["C10"]


def test_positions_and_disagreements_do_not_cover_proposals():
    reg = _registry([("C10", "Proposed", None, None)])
    cov = check_coverage(reg, [], {
        "positions": [{"claim_ids": ["C10"], "position": "P",
                       "supporting_reasoning": "R"}],
        "disagreements": [{"opposing_positions": ["A", "B"],
                           "supporting_claims": ["C10"],
                           "unresolved_status": "unresolved"}],
        "recommendations": [], "limitations": []})
    assert _prop_omitted(cov) == ["C10"]


def test_consolidates_non_demand_ids_warn_only():
    reg = _registry([("C10", "Proposed", None, None),
                     ("C11", "Observed", None, None)])
    cov = check_coverage(reg, [], {
        "positions": [], "disagreements": [],
        "recommendations": [_rec("Do it.", ["C10"], ["C11"])],
        "limitations": []})
    assert cov["verdict"] == "pass"
    assert cov["warnings"] == [
        {"kind": "consolidates_non_demand_ids", "recommendation_index": 0,
         "detail": "C11"}]


# ---------------------------------------------------------------------------
# §G.3 Acceptance semantics
# ---------------------------------------------------------------------------

def _evals_all_complete():
    return {"positions": "synthesized_complete",
            "disagreements": "synthesized_complete",
            "recommendations": "synthesized_complete",
            "limitations": "synthesized_complete"}


def test_coverage_fail_with_valid_fields_not_accepted():
    structured, evals, reg, unresolved = _tier2("failed")
    cov = check_coverage(reg, unresolved, structured)
    assert all(v == "synthesized_complete" for v in evals.values())
    before = copy.deepcopy(evals)
    assert artifact_accepted(evals, cov) is False
    assert evals == before  # evaluations never rewritten


def test_legitimate_empty_rule_mechanical():
    # Demand empty + field [] -> legitimate (E-style empties pass).
    reg = _registry([("C1", "Observed", None, None)])
    cov = check_coverage(reg, [], {"positions": [], "disagreements": [],
                                  "recommendations": [], "limitations": []})
    evals = {"positions": "synthesized_complete",
             "disagreements": "synthesized_empty",
             "recommendations": "synthesized_empty",
             "limitations": "synthesized_empty"}
    assert cov["verdict"] == "pass"
    assert artifact_accepted(evals, cov, active_claims_empty=False) is True
    # Fitting: recommendations empty + demand nonempty -> not accepted.
    structured, evals_f, reg_f, unresolved_f = _tier2("fitting")
    cov_f = check_coverage(reg_f, unresolved_f, structured)
    assert evals_f["recommendations"] == "synthesized_empty"
    assert artifact_accepted(evals_f, cov_f) is False


def test_partial_field_with_coverage_pass_not_accepted():
    reg = _registry([("C1", "Observed", None, None)])
    cov = check_coverage(reg, [], {"positions": [], "disagreements": [],
                                  "recommendations": [], "limitations": []})
    assert cov["verdict"] == "pass"
    evals = _evals_all_complete()
    evals["positions"] = "synthesized_partial"
    assert artifact_accepted(evals, cov) is False


def test_unparseable_field_not_accepted_regardless():
    reg = _registry([("C1", "Observed", None, None)])
    cov = check_coverage(reg, [], {"positions": [], "disagreements": [],
                                  "recommendations": [], "limitations": []})
    evals = _evals_all_complete()
    evals["limitations"] = "unparseable"
    assert artifact_accepted(evals, cov) is False


def test_legacy_no_block_coverage_from_kept_lists():
    # Section-parsed output: recommendations empty, unparseable —
    # coverage still computed from kept lists and reported.
    reg = _registry([("C10", "Proposed", None, None)])
    cov = check_coverage(reg, [], {
        "positions": [{"claim_ids": ["C10"]}],
        "disagreements": [{"claim_ids": ["C10"]}],
        "recommendations": [], "limitations": []})
    assert cov["verdict"] == "fail"
    assert _prop_omitted(cov) == ["C10"]
    evals = {"positions": "evaluated_with_results",
             "disagreements": "evaluated_with_results",
             "recommendations": "unparseable",
             "limitations": "unparseable"}
    assert artifact_accepted(evals, cov) is False


def test_full_pass_acceptance_shape():
    """A complete, fully covering artifact is accepted (mechanical gate)."""
    reg = _registry([("C10", "Proposed", None, None)])
    cov = check_coverage(reg, [{"claim_id": "C10", "source_claim_id": "C20",
                                "state": "unresolved"}],
                         {"positions": [{"claim_ids": ["C10"]}],
                          "disagreements": [{"opposing_positions": ["A", "B"],
                                             "supporting_claims": ["C10", "C20"],
                                             "unresolved_status": "unresolved"}],
                          "recommendations": [_rec("Do it.", ["C10"])],
                          "limitations": [{"missing_evidence_or_omission": "M",
                                           "note": "N"}]})
    assert cov["verdict"] == "pass"
    assert artifact_accepted(_evals_all_complete(), cov) is True


# ---------------------------------------------------------------------------
# §G.4 Boundary tests
# ---------------------------------------------------------------------------

def test_coverage_input_unchanged_and_no_model_prose():
    structured, _evals, reg, unresolved = _tier2("fitting")
    before = copy.deepcopy(structured)
    cov = check_coverage(reg, unresolved, structured)
    assert structured == before
    blob = json.dumps(cov)
    # No model prose anywhere in the coverage object: only IDs,
    # indices, fixed reasons, fate labels.
    for entry in structured["recommendations"]:
        assert entry.get("proposed_action", "") not in blob
    for entry in structured["positions"]:
        assert entry.get("position", "") not in blob
    for entry in structured["limitations"]:
        assert entry.get("missing_evidence_or_omission", "") not in blob
    assert cov["limitations_coverage"].startswith("not_checked")


def test_coverage_signature_has_no_generation_capability():
    assert coverage_function_signature() == [
        "registry", "unresolved_objections", "structured"]


def test_no_repair_path_omitted_thread_gains_no_entry():
    structured, _evals, reg, unresolved = _tier2("fitting")
    before_count = len(structured["disagreements"])
    cov = check_coverage(reg, unresolved, structured)
    assert len(structured["disagreements"]) == before_count
    assert cov["objections"]["omitted"] == [
        {"target_claim_id": "C15", "challenger_claim_id": "C32",
         "reason": "not_represented"}]


# ---------------------------------------------------------------------------
# §G.5 Latency tests (stubbed participant + controlled monotonic clock)
# ---------------------------------------------------------------------------

class _Clock:
    def __init__(self, values):
        self._it = iter(values)

    def __call__(self):
        return next(self._it)


class _StubParticipant:
    def __init__(self, text="ok", error=None, usage=None):
        self.text = text
        self.error = error
        self.usage = usage
        self.generate_calls = 0
        self.with_usage_calls = 0

    def generate(self, prompt, *, timeout=120):
        self.generate_calls += 1
        if self.error is not None:
            raise self.error
        return self.text


class _StubWithUsage(_StubParticipant):
    def generate_with_usage(self, prompt, *, timeout=120):
        self.with_usage_calls += 1
        if self.error is not None:
            raise self.error
        return self.text, self.usage


def test_latency_boundary_and_derived_threshold(monkeypatch):
    # 95.999s at 120s timeout: within margin (threshold 96.0).
    monkeypatch.setattr(measurement_mod.time, "monotonic",
                        _Clock([100.0, 195.999]))
    out = measure_generation(_StubParticipant(), "prompt", timeout=120)
    assert out["generation"]["duration_seconds"] == 95.999
    assert out["generation"]["margin_threshold_seconds"] == 96.0
    assert out["generation"]["within_margin"] is True
    assert out["generation"]["timed_out"] is False
    # 96.001s: outside margin.
    monkeypatch.setattr(measurement_mod.time, "monotonic",
                        _Clock([100.0, 196.001]))
    out = measure_generation(_StubParticipant(), "prompt", timeout=120)
    assert out["generation"]["within_margin"] is False
    # Threshold moves with timeout: 0.8 * 200 = 160.
    monkeypatch.setattr(measurement_mod.time, "monotonic",
                        _Clock([0.0, 159.999]))
    out = measure_generation(_StubParticipant(), "prompt", timeout=200)
    assert out["generation"]["margin_threshold_seconds"] == 160.0
    assert out["generation"]["within_margin"] is True


def test_latency_unrounded_comparison():
    # Rounds to 96.0 at ms precision but is strictly below the
    # threshold unrounded: still within margin.
    import local_ai.build_room.measurement as mm
    orig = mm.time.monotonic
    mm.time.monotonic = _Clock([0.0, 95.9999])
    try:
        out = measure_generation(_StubParticipant(), "prompt", timeout=120)
    finally:
        mm.time.monotonic = orig
    assert out["generation"]["duration_seconds"] == 96.0
    assert out["generation"]["within_margin"] is True


def test_latency_timeout_exception_path(monkeypatch):
    monkeypatch.setattr(measurement_mod.time, "monotonic",
                        _Clock([10.0, 130.0]))
    out = measure_generation(
        _StubParticipant(error=TimeoutError("timed out")),
        "prompt", timeout=120)
    assert out["text"] is None
    assert out["error"] == "timed out"
    assert out["generation"]["duration_seconds"] == 120.0
    assert out["generation"]["timed_out"] is True
    assert out["generation"]["within_margin"] is False
    # Non-timeout failure, short duration: timed_out False.
    monkeypatch.setattr(measurement_mod.time, "monotonic",
                        _Clock([0.0, 5.0]))
    out = measure_generation(
        _StubParticipant(error=RuntimeError("boom")),
        "prompt", timeout=120)
    assert out["generation"]["timed_out"] is False
    assert out["generation"]["within_margin"] is True


# ---------------------------------------------------------------------------
# §G.6 Cost tests
# ---------------------------------------------------------------------------

def test_cost_measured_path_and_tripwire():
    cost = compute_generation_cost(
        "prompt", "response",
        {"prompt_tokens": 1_000_000, "completion_tokens": 500_000,
         "total_tokens": 1_500_000},
        TEST_PRICE_TABLE)
    assert cost["source"] == "measured"
    assert cost["prompt_tokens"] == 1_000_000
    assert cost["completion_tokens"] == 500_000
    assert cost["charge_usd"] == 4.0  # 1M*2 + 0.5M*4
    assert cost["charge_basis"] == "measured_tokens_x_stated_price"
    trip = evaluate_tripwire(cost)
    assert trip["tripped"] is True
    assert trip["label"] == "measured"
    # Below tripwire: not tripped.
    small = compute_generation_cost(
        "p", "r", {"prompt_tokens": 1000, "completion_tokens": 1000},
        TEST_PRICE_TABLE)
    assert evaluate_tripwire(small)["tripped"] is False


def test_cost_estimated_path_labeled_and_separate():
    prompt, response = "hello world, this is a prompt", "a short reply here"
    cost = compute_generation_cost(prompt, response, None, TEST_PRICE_TABLE)
    assert cost["source"] == "estimated"
    assert cost["prompt_tokens"] == count_tokens(prompt)
    assert cost["completion_tokens"] == count_tokens(response)
    assert cost["charge_basis"] == "estimated_tokens_x_stated_price"
    assert cost["reason"] is not None
    trip = evaluate_tripwire(cost)
    assert trip["label"] == "estimate-based"


def test_cost_no_price_table_never_invented():
    cost = compute_generation_cost(
        "prompt", "response",
        {"prompt_tokens": 1000, "completion_tokens": 1000}, None)
    assert cost["source"] == "measured"  # tokens ARE provider-reported
    assert cost["price_table"] is None
    assert cost["charge_usd"] is None
    assert cost["charge_basis"] is None
    assert "price table" in cost["reason"]
    trip = evaluate_tripwire(cost)
    assert trip["tripped"] is None
    assert trip["label"] == "unassessable"


def test_cost_unavailable_when_neither_source(monkeypatch):
    monkeypatch.setattr(measurement_mod, "_count_tokens_exact",
                        lambda text: None)
    cost = compute_generation_cost("prompt", "response", None,
                                   TEST_PRICE_TABLE)
    assert cost["source"] == "unavailable"
    assert cost["charge_usd"] is None
    assert evaluate_tripwire(cost)["label"] == "unassessable"


def test_no_second_generation_on_any_fallback_path():
    # Participant WITH generate_with_usage returning no usage:
    # exactly one with-usage call, zero generate() calls.
    fake = _StubWithUsage(text="hello", usage=None)
    out = measure_generation(fake, "prompt", timeout=120)
    assert fake.with_usage_calls == 1
    assert fake.generate_calls == 0
    cost = compute_generation_cost("prompt", out["text"], out["usage"],
                                   TEST_PRICE_TABLE)
    assert cost["source"] == "estimated"
    # Participant WITHOUT generate_with_usage: exactly one generate().
    fake2 = _StubParticipant(text="hello")
    out2 = measure_generation(fake2, "prompt", timeout=120)
    assert fake2.generate_calls == 1
    assert out2["used_generate_with_usage"] is False
    # Participant WITH usage: exactly one call, usage carried.
    fake3 = _StubWithUsage(
        text="hello",
        usage={"prompt_tokens": 10, "completion_tokens": 5})
    out3 = measure_generation(fake3, "prompt", timeout=120)
    assert fake3.with_usage_calls == 1
    assert fake3.generate_calls == 0
    assert out3["usage"] == {"prompt_tokens": 10, "completion_tokens": 5}
    assert out3["used_generate_with_usage"] is True


# ---------------------------------------------------------------------------
# §G.7 Route-level tests (ASGI, stubbed participants)
# ---------------------------------------------------------------------------

def _call_post(app, path: str, payload: dict) -> tuple[int, dict]:
    raw = json.dumps(payload).encode()
    scope = {
        "type": "http", "http_version": "1.1", "method": "POST",
        "scheme": "http", "path": path, "raw_path": path.encode(),
        "query_string": b"",
        "headers": [(b"content-type", b"application/json"),
                    (b"content-length", str(len(raw)).encode())],
        "client": ("testclient", 50000), "server": ("testserver", 80),
    }
    messages: list[dict] = []
    sent = False

    async def receive():
        nonlocal sent
        if not sent:
            sent = True
            return {"type": "http.request", "body": raw, "more_body": False}
        return {"type": "http.disconnect"}

    async def send(message: dict) -> None:
        messages.append(message)

    asyncio.run(app(scope, receive, send))
    start = next(m for m in messages if m["type"] == "http.response.start")
    body = b"".join(
        m.get("body", b"") for m in messages if m["type"] == "http.response.body")
    return start["status"], json.loads(body.decode() or "{}")


@pytest.fixture()
def app(tmp_path, monkeypatch):
    import local_ai.vision_execution.storage as ve_store_mod
    monkeypatch.setattr(
        br_routes, "get_build_room_store_dir", lambda: tmp_path / "store")
    monkeypatch.setattr(ve_store_mod, "get_owner_user_id", lambda: OWNER["id"])
    application = FastAPI()
    application.include_router(br_routes.router)
    return application


def _mock_participant(monkeypatch, fake):
    monkeypatch.setattr(
        br_routes, "resolve_openai_participant",
        lambda principal: (fake, ""))


_FITTING_PASS_BLOCK = (
    "Synthesis.\n```json\n" + json.dumps({
        "positions": [{"claim_ids": ["C1"], "position": "P",
                       "supporting_reasoning": "R"}],
        "disagreements": [{"opposing_positions": ["A", "B"],
                           "supporting_claims": ["C15", "C32"],
                           "unresolved_status": "unresolved"}],
        "recommendations": [{"proposed_action": "Do all twelve.",
                             "supporting_claims": [
                                 "C3", "C10", "C15", "C20", "C23", "C34",
                                 "C40", "C46", "C49", "C54", "C61", "C68"]}],
        "limitations": [{"missing_evidence_or_omission": "M",
                         "note": "N"}]}) + "\n```\n")


def test_route_b2_success_carries_coverage_generation_cost(app, monkeypatch):
    app.dependency_overrides[get_current_user] = lambda: OWNER
    fake = _StubParticipant(text=_FITTING_PASS_BLOCK)
    _mock_participant(monkeypatch, fake)
    status, body = _call_post(app, "/build-room/harness/synthesis-call",
                              {"fixture": "fitting"})
    assert status == 200, body
    assert body["ok"] is True
    assert fake.generate_calls == 1
    # Coverage: fully covering block over the fitting registry.
    assert body["coverage"]["verdict"] == "pass"
    assert body["coverage"]["objections"]["omitted"] == []
    assert body["coverage"]["proposals"]["omitted"] == []
    assert body["coverage"]["provenance_failures"] == []
    assert body["coverage_accepted"] is True
    # Generation: server-side object with derived threshold.
    assert body["generation"]["timeout_seconds"] == 120
    assert body["generation"]["margin_threshold_seconds"] == 96.0
    assert body["generation"]["timed_out"] is False
    # Cost: fake has no generate_with_usage -> estimated from text;
    # no verified price table in code -> charge unassessable, labeled.
    assert body["generation_cost"]["source"] == "estimated"
    assert body["generation_cost"]["charge_usd"] is None
    assert "price table" in body["generation_cost"]["reason"]
    # No prompt text, no credentials.
    assert "prompt" not in body
    assert _SYNTHESIS_INSTRUCTION not in json.dumps(body)


def test_route_refusal_carries_no_generation_cost_or_coverage(
        app, monkeypatch):
    app.dependency_overrides[get_current_user] = lambda: OWNER
    fake = _StubParticipant(text=_FITTING_PASS_BLOCK)
    _mock_participant(monkeypatch, fake)
    monkeypatch.setattr(candidate_cap, "CANDIDATE_SYNTHESIS_PROMPT_TOKENS",
                        1000)
    status, body = _call_post(app, "/build-room/harness/synthesis-call",
                              {"fixture": "stress"})
    assert status == 200, body
    assert body["ok"] is False
    assert fake.generate_calls == 0
    assert "generation" not in body
    assert "generation_cost" not in body
    assert "coverage" not in body
    assert "coverage_accepted" not in body


def test_route_absence_carries_no_generation_cost_or_coverage(
        app, monkeypatch):
    app.dependency_overrides[get_current_user] = lambda: OWNER
    monkeypatch.setattr(
        br_routes, "resolve_openai_participant",
        lambda principal: (None, "absent: no openai api key present"))
    status, body = _call_post(app, "/build-room/harness/synthesis-call",
                              {"fixture": "fitting"})
    assert status == 200, body
    assert body["ok"] is False
    assert "generation" not in body
    assert "generation_cost" not in body
    assert "coverage" not in body


def test_route_generation_failure_carries_generation_but_no_coverage(
        app, monkeypatch):
    app.dependency_overrides[get_current_user] = lambda: OWNER

    class _Failing:
        def generate(self, prompt, *, timeout=120):
            raise RuntimeError("provider unavailable")

    monkeypatch.setattr(
        br_routes, "resolve_openai_participant",
        lambda principal: (_Failing(), ""))
    status, body = _call_post(app, "/build-room/harness/synthesis-call",
                              {"fixture": "E"})
    assert status == 200, body
    assert body["ok"] is False
    assert "provider unavailable" in body["generation_error"]
    assert "generation" in body
    assert body["generation"]["timed_out"] is False
    assert "generation_cost" in body
    assert body["generation_cost"]["source"] == "unavailable"
    assert "coverage" not in body  # no synthesis to check


def test_route_de_fixture_success_carries_new_objects(app, monkeypatch):
    app.dependency_overrides[get_current_user] = lambda: OWNER
    block = ("Synthesis.\n```json\n" + json.dumps({
        "positions": [{"claim_ids": ["C1"], "position": "P",
                       "supporting_reasoning": "R"}],
        "disagreements": [{"opposing_positions": ["A", "B"],
                           "supporting_claims": ["C1", "C2"],
                           "unresolved_status": "unresolved"}],
        "recommendations": [], "limitations": []}) + "\n```\n")
    fake = _StubParticipant(text=block)
    _mock_participant(monkeypatch, fake)
    status, body = _call_post(app, "/build-room/harness/synthesis-call",
                              {"fixture": "D"})
    assert status == 200, body
    assert body["ok"] is True
    assert "coverage" in body and "coverage_accepted" in body
    assert "generation" in body and "generation_cost" in body
    assert body["generation"]["margin_threshold_seconds"] == 96.0


# ---------------------------------------------------------------------------
# Meeting-phase wiring (Phase C prerequisite surface)
# ---------------------------------------------------------------------------

class _MeetingFake:
    """Duck-typed seat participant branching on prompt markers."""

    def __init__(self, name, *, opening="", response="", revision="",
                 synthesis=""):
        self.name = name
        self.provider_id = dict((n, p) for n, p, _ in SEAT_SPECS)[name]
        self.model = "fake-model"
        self.key_source = "settings"
        self._texts = {"synthesis": synthesis, "revision": revision,
                       "response": response, "opening": opening}

    def generate(self, prompt, *, timeout=120):
        if "Write the synthesis" in prompt:
            return self._texts["synthesis"]
        if "state the relationship explicitly" in prompt:
            return self._texts["revision"]
        if "Claim registry" in prompt:
            return self._texts["response"]
        return self._texts["opening"]


def _meeting_seats(synthesis_text, gpt_opening):
    fakes = {}
    for name, _pid, _model in SEAT_SPECS:
        opening = gpt_opening if name == "GPT" else "1. Observed: A stable fact."
        fakes[name] = _MeetingFake(
            name, opening=opening, response="No further comment.",
            revision="No revision.", synthesis=synthesis_text)
    return [Seat(name, pid, model, fakes[name])
            for name, pid, model in SEAT_SPECS]


def _meeting_synthesis_block():
    return ("Synthesis.\n```json\n" + json.dumps({
        "positions": [{"claim_ids": ["C1"], "position": "P",
                       "supporting_reasoning": "R"}],
        "disagreements": [],
        "recommendations": [],
        "limitations": [{"missing_evidence_or_omission": "M",
                         "note": "N"}]}) + "\n```\n")


def test_meeting_artifact_carries_coverage_and_pass(tmp_path):
    packet = EvidencePacket(work_item="W", question="Q")
    result = run_multi_model_meeting(
        packet, store_dir=tmp_path / "store",
        seats=_meeting_seats(_meeting_synthesis_block(),
                             "1. Observed: A stable fact."))
    artifact = result.artifact
    assert artifact["synthesis_coverage"]["verdict"] == "pass"
    assert artifact["synthesis_coverage_accepted"] is True
    assert artifact["synthesis"]["coverage"]["verdict"] == "pass"
    assert artifact["synthesis_generation"]["timed_out"] is False
    assert artifact["synthesis_generation"]["margin_threshold_seconds"] == 96.0
    assert artifact["synthesis_generation_cost"]["source"] == "estimated"
    # No coverage-failure note on a passing artifact.
    assert not any(e.kind == "note" and "coverage FAIL" in e.text
                   for e in result.transcript.entries)


def test_meeting_coverage_failure_visible_on_artifact_and_transcript(tmp_path):
    packet = EvidencePacket(work_item="W", question="Q")
    result = run_multi_model_meeting(
        packet, store_dir=tmp_path / "store",
        seats=_meeting_seats(
            _meeting_synthesis_block(),
            "1. Observed: A stable fact.\n2. Proposed: Do the thing."))
    artifact = result.artifact
    registry = artifact["claim_registry"]
    proposed = [c["id"] for c in registry if c["status"] == "Proposed"]
    assert proposed, "test setup must register a Proposed claim"
    cov = artifact["synthesis_coverage"]
    assert cov["verdict"] == "fail"
    assert [o["proposal_claim_id"] for o in cov["proposals"]["omitted"]] == proposed
    assert artifact["synthesis_coverage_accepted"] is False
    # Failure visible in the transcript (text only, no injected content).
    notes = [e.text for e in result.transcript.entries
             if e.kind == "note" and "coverage FAIL" in e.text]
    assert len(notes) == 1
    for pid in proposed:
        assert pid in notes[0]
    # The structured output itself is unchanged by the check.
    assert artifact["recommendations"] == []


# ---------------------------------------------------------------------------
# Pins: instruction byte-identity + unchanged caps
# ---------------------------------------------------------------------------

def test_instruction_byte_identical_and_caps_unchanged():
    assert len(_SYNTHESIS_INSTRUCTION) == 2877
    assert hashlib.sha256(_SYNTHESIS_INSTRUCTION.encode()).hexdigest() == (
        INSTRUCTION_SHA256)
    assert Budget().max_response_prompt_chars == 40000
    assert candidate_cap.CANDIDATE_SYNTHESIS_PROMPT_TOKENS == 12500
    assert candidate_cap.PRODUCTION_SYNTHESIS_PROMPT_CHARS == 40000
