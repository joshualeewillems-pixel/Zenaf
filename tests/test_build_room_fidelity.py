"""Phase C fidelity-correction fixtures V1-V5 (design doc:
zenaf-build-council-fidelity-correction-design.md).

Deterministic only: every test runs the production
``parse_synthesis_contract`` + ``check_coverage`` + ``artifact_accepted``
on the RECORDED Phase C registry (meeting c1260c254ea1, 63 claims,
tests/fixtures/phase_c_recorded.json) and its recorded
unresolved-objection list. No model is called, no staging call is
made, no generation happens.

Behavioral caveat (explicit, per the amended design section 5):
these tests establish that the revised instruction fits the budget
and that the contract CAN represent complete coverage. They CANNOT
establish that a model will follow the revised instruction. No
fixture result here may be reported as evidence of model compliance.
"""

import hashlib
import json
from pathlib import Path

from local_ai.build_room.coverage import artifact_accepted, check_coverage
from local_ai.build_room.meeting import (
    Claim,
    ClaimRegistry,
    _SYNTHESIS_INSTRUCTION,
    parse_synthesis_contract,
)
from local_ai.llm.tokenizer import count_tokens

FIXTURES = Path(__file__).parent / "fixtures"


def _load_recorded():
    data = json.loads((FIXTURES / "phase_c_recorded.json").read_text())
    reg = ClaimRegistry()
    for c in data["claims"]:
        reg.claims.append(Claim(
            id=c["id"], participant=c["participant"], phase=c["phase"],
            text=c["text"], status=c["status"],
            disposition=c["disposition"], disposition_by=c["disposition_by"]))
    return reg, data["unresolved_objections"], data["structured"]


def _fenced(block):
    return "Narrative synthesis here.\n```json\n" + json.dumps(block) + "\n```"


def _parse(block, reg, unres):
    structured, evals, rejected, found = parse_synthesis_contract(
        _fenced(block), reg, unres, "GPT")
    assert found is True
    return structured, evals, rejected


# ---------------------------------------------------------------------------
# V1 -- Baseline regression: Phase C's actual output fails coverage exactly
# as recorded (4 objection pairs + 7 proposals omitted).
# ---------------------------------------------------------------------------

def test_v1_phase_c_actual_output_fails_coverage_as_recorded():
    reg, unres, actual = _load_recorded()
    structured, evals, rejected = _parse(actual, reg, unres)
    assert rejected == []
    assert evals == {
        "positions": "synthesized_complete",
        "disagreements": "synthesized_complete",
        "recommendations": "synthesized_complete",
        "limitations": "synthesized_complete",
    }
    cov = check_coverage(reg, unres, structured)
    assert cov["verdict"] == "fail"
    assert [(o["target_claim_id"], o["challenger_claim_id"])
            for o in cov["objections"]["omitted"]] == [
        ("C16", "C36"), ("C20", "C39"), ("C18", "C41"), ("C12", "C48")]
    assert cov["objections"]["covered"] == []
    assert [p["proposal_claim_id"] for p in cov["proposals"]["covered"]] == [
        "C3", "C40"]
    assert [p["proposal_claim_id"] for p in cov["proposals"]["omitted"]] == [
        "C9", "C15", "C20", "C33", "C49", "C57", "C62"]
    assert cov["proposals"]["not_required"] == [
        {"proposal_claim_id": "C24", "fate": "revised",
         "disposition_by": "C62"}]
    assert artifact_accepted(evals, cov) is False


# ---------------------------------------------------------------------------
# V2 -- Full accounting under the CURRENT contract: all 9 proposals cited
# or consolidated, all 4 objection pairs with both IDs. Proves the pass
# case needs no contract expansion.
# ---------------------------------------------------------------------------

def _v2_block(actual):
    return {
        "positions": actual["positions"],
        "disagreements": [
            {"opposing_positions": ["Assigned roles improve accountability.",
                                    "Open roles permit more substantive deliberation."],
             "supporting_claims": ["C18", "C41"],
             "unresolved_status": "unresolved"},
            {"opposing_positions": ["Transcript gates protect authority.",
                                    "Transcript gates conceal breakdown evidence."],
             "supporting_claims": ["C20", "C39"],
             "unresolved_status": "unresolved"},
            {"opposing_positions": ["Shared priors are a background worry.",
                                    "Shared priors need a testable failure condition."],
             "supporting_claims": ["C16", "C36"],
             "unresolved_status": "unresolved"},
            {"opposing_positions": ["Assigned adversarial jurisdictions prevent sycophancy.",
                                    "Open discovery can generate adversarial pressure."],
             "supporting_claims": ["C12", "C48"],
             "unresolved_status": "unresolved"},
        ],
        "recommendations": [
            {"proposed_action": "Adopt the acceptance criteria: append-only preservation, "
             "explicit epistemic status, claim-ID citation, at least one genuine "
             "challenge, no collapsing of contested claims; evaluate synthesis on "
             "preserving and sharpening contradictions rather than harmonizing them.",
             "supporting_claims": ["C3", "C9", "C15"],
             "consolidates_claim_ids": ["C33"]},
            {"proposed_action": "Preserve the transcript-format gate proposal as a contested "
             "option alongside the append-only objection to it; require traceable "
             "effect for performative-compliance claims and map each recommendation "
             "back to the epistemic status of its premises.",
             "supporting_claims": ["C20", "C40"],
             "consolidates_claim_ids": ["C49", "C57"]},
            {"proposed_action": "Probe the failure directly with a seeded disagreement and "
             "authorization-bait check, requiring verbatim attribution and a later "
             "claim stating what was revised because of the cited ID.",
             "supporting_claims": ["C62"]},
        ],
        "limitations": actual["limitations"],
    }


def test_v2_full_accounting_passes_under_current_contract():
    reg, unres, actual = _load_recorded()
    structured, evals, rejected = _parse(_v2_block(actual), reg, unres)
    assert rejected == []
    assert all(v == "synthesized_complete" for v in evals.values())
    cov = check_coverage(reg, unres, structured)
    assert cov["verdict"] == "pass"
    assert cov["objections"]["omitted"] == []
    assert cov["proposals"]["omitted"] == []
    assert len(cov["objections"]["covered"]) == 4
    assert len(cov["proposals"]["covered"]) == 9
    assert artifact_accepted(evals, cov) is True


# ---------------------------------------------------------------------------
# V3 -- Mechanical pass, substance open (CORRECTED per Weaver's review).
# All 9 proposals cited/consolidated into two GENERIC recommendations and
# both IDs of every pair in mechanically valid but deliberately flattened
# disagreement entries. Expected: coverage PASS mechanically.
# The substantive verdict for this fixture is FAIL on human review -- and
# this test deliberately asserts NOTHING about substance, because code
# cannot judge it. That absence is the point: the validator cannot
# distinguish V3 from V2, and only human review can.
# ---------------------------------------------------------------------------

def _v3_block(actual):
    return {
        "positions": actual["positions"],
        "disagreements": [
            {"opposing_positions": ["Assigned roles are better.",
                                    "Open roles are better."],
             "supporting_claims": ["C18", "C41"],
             "unresolved_status": "unresolved"},
            {"opposing_positions": ["Gates are good.", "Gates are bad."],
             "supporting_claims": ["C20", "C39"],
             "unresolved_status": "unresolved"},
            {"opposing_positions": ["Priors matter.", "Priors do not matter."],
             "supporting_claims": ["C16", "C36"],
             "unresolved_status": "unresolved"},
            {"opposing_positions": ["Convergence is bad.", "Convergence is fine."],
             "supporting_claims": ["C12", "C48"],
             "unresolved_status": "unresolved"},
        ],
        "recommendations": [
            {"proposed_action": "Follow good deliberation practices.",
             "supporting_claims": ["C3", "C9", "C15", "C20"],
             "consolidates_claim_ids": ["C33"]},
            {"proposed_action": "Monitor the council's work.",
             "supporting_claims": ["C40", "C49", "C57"],
             "consolidates_claim_ids": ["C62"]},
        ],
        "limitations": actual["limitations"],
    }


def test_v3_mechanical_pass_does_not_establish_substance():
    reg, unres, actual = _load_recorded()
    structured, evals, rejected = _parse(_v3_block(actual), reg, unres)
    assert rejected == []
    cov = check_coverage(reg, unres, structured)
    # Mechanical verdict passes: every demanded ID is cited or consolidated.
    assert cov["verdict"] == "pass"
    assert cov["objections"]["omitted"] == []
    assert cov["proposals"]["omitted"] == []
    assert artifact_accepted(evals, cov) is True
    # Substantive verdict: FAIL on human review by design (flattened
    # tensions, generic recommendations carrying none of the distinctive
    # contributions). No assertion here can express that -- the test
    # framework has no substance judgment -- which is exactly why human
    # review remains load-bearing and why this mechanical pass must
    # never be reported as fidelity established.


# ---------------------------------------------------------------------------
# V4 -- Broken consolidation: unknown + malformed consolidates are
# provenance failures; entries are retained, coverage fails.
# ---------------------------------------------------------------------------

def _v4_block(actual):
    return {
        "positions": actual["positions"],
        "disagreements": actual["disagreements"],
        "recommendations": [
            {"proposed_action": "Do the thing.",
             "supporting_claims": ["C3"],
             "consolidates_claim_ids": ["C999"]},
            {"proposed_action": "Do another thing.",
             "supporting_claims": ["C9"],
             "consolidates_claim_ids": "C15"},
        ],
        "limitations": actual["limitations"],
    }


def test_v4_broken_consolidation_fails_coverage_entries_retained():
    reg, unres, actual = _load_recorded()
    structured, evals, rejected = _parse(_v4_block(actual), reg, unres)
    assert rejected == []
    # Both entries survive validation (retained, not dropped)...
    assert len(structured["recommendations"]) == 2
    cov = check_coverage(reg, unres, structured)
    # ...but their broken provenance fails coverage.
    kinds = sorted(f["kind"] for f in cov["provenance_failures"])
    assert kinds == ["consolidates_malformed", "consolidates_unknown_ids"]
    assert cov["verdict"] == "fail"
    assert artifact_accepted(evals, cov) is False


# ---------------------------------------------------------------------------
# V5 -- Instruction budget check against the recorded Phase C gate values.
# ---------------------------------------------------------------------------

def test_v5_revised_instruction_fits_candidate_cap_with_headroom():
    # Revised instruction pins (fidelity-correction revision).
    assert len(_SYNTHESIS_INSTRUCTION) == 4165
    assert count_tokens(_SYNTHESIS_INSTRUCTION) == 824
    assert hashlib.sha256(_SYNTHESIS_INSTRUCTION.encode()).hexdigest() == (
        "41925066d601380a3fd35e29a6232a22ef4fdcfc1006ed4d8e77d905e163b177")
    # Recorded Phase C gate totals (old instruction: 2877 chars / 601
    # tokens) recomputed with the revised instruction: the ONLY delta is
    # the appended paragraph (+1288 chars / +223 tokens).
    old_tokens, old_chars = 8625, 44360
    new_tokens = old_tokens - 601 + 824
    new_chars = old_chars - 2877 + 4165
    assert new_tokens == 8848
    assert new_chars == 45648
    assert new_tokens < 12500  # candidate cap, tokens enforce
    assert 12500 - new_tokens == 3652  # headroom stated, not implied
