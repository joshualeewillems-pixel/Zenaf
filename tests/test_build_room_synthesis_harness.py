"""Targeted synthesis-only verification harness (Phase A design).

Test-only. No live model is invoked by any test in this module, and no
model call is authorized by it: the future authorized model calls
(up to two generations, one per fixture, no retries) would feed their
verbatim text into ``evaluate_synthesis_text`` / ``run_harness`` — that
step is NOT executed here. No route, no cap change, no gate change,
no registry/phase change, no repair layer, no schema expansion.

The harness reuses the production path and nothing else:

- ``build_synthesis_state`` — the production prompt builder, called
  with the production cap (40,000).
- ``_telemetry_block`` — the production telemetry helper (deterministic
  given its inputs; no timestamps).
- ``parse_synthesis_contract`` — the production validator. No second
  parser.

Prompt assembly is production's exact expression (see
``run_multi_model_meeting``): ``state["prompt"] + "\\n\\n" +
synthesis_telemetry``. Note the production gate compares the state
prompt WITHOUT telemetry; telemetry is appended after the gate. The
report therefore carries both sizes, labeled: ``state_prompt_chars``
(gated) and ``assembled_prompt_chars`` (what would actually be sent).

Disclosure-note conditions mirror production exactly (see the
synthesis phase in ``run_multi_model_meeting``): the disagreements
note fires when the disagreements evaluation is
``synthesized_empty`` and the unresolved-objections list is
non-empty; the limitations note fires when the limitations
evaluation is ``synthesized_empty`` and omitted context or failed
contributions exist. The harness reports whether each note WOULD
fire; it does not emit transcript notes and does not change
production behavior.

Fixture D (disagreements): C1/C2 carry the opposing positions,
C3 objects to C1 (unresolved objection), C4 is GPT's authorial
response (revision chain). Fixture E (legitimate empties): a small
state whose honest synthesis has no recommendations or limitations.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re

from local_ai.build_room.harness_fixtures import (
    QUESTION,
    TELEMETRY,
    fixture_d_state,
    fixture_e_state,
)
from local_ai.build_room.meeting import (
    ClaimRegistry,
    EvidencePacket,
    _SYNTHESIS_INSTRUCTION,
    _telemetry_block,
    build_synthesis_state,
    parse_synthesis_contract,
)

CAP = 40000
SYNTHESIZER = "GPT"


# --- Harness helpers (the harness itself; no model calls here) --------

def assemble_prompt(state: dict) -> str:
    """Production's exact prompt assembly for a built state."""
    return state["prompt"] + "\n\n" + _telemetry_block(**TELEMETRY)


def disclosure_notes(evaluations: dict, unresolved_objections: list,
                     omitted: dict | None, had_failures: bool) -> dict:
    """Whether each production disclosure note WOULD fire.

    Mirrors the synthesis-phase conditions exactly; text only, no
    status change, no reclassification.
    """
    omitted_total = 0
    if omitted:
        omitted_total = (omitted.get("superseded_texts", 0)
                         + omitted.get("responded_to_details", 0))
    return {
        "disagreements_note": (
            evaluations.get("disagreements") == "synthesized_empty"
            and bool(unresolved_objections)),
        "limitations_note": (
            evaluations.get("limitations") == "synthesized_empty"
            and bool(omitted_total or had_failures)),
    }


def evaluate_synthesis_text(text: str, registry, unresolved_objections,
                            omitted=None, had_failures: bool = False) -> dict:
    """Run the production validator over synthesizer text.

    Returns raw text verbatim plus derived results kept separate:
    structured fields, per-field evaluations, rejected entries, and
    disclosure-note conditions. Nothing is repaired or invented.
    """
    structured, evaluations, rejected, block_found = (
        parse_synthesis_contract(text, registry, unresolved_objections,
                                 SYNTHESIZER))
    return {
        "raw": text,
        "structured": structured,
        "evaluations": evaluations,
        "rejected_entries": rejected,
        "block_found": block_found,
        "disclosure_notes": disclosure_notes(
            evaluations, unresolved_objections, omitted, had_failures),
    }


def run_harness(fixture_id: str, packet, registry, unresolved_objections,
                revision_chains, synthesizer_text: str,
                had_failures: bool = False) -> dict:
    """Build the fixture prompt via production, evaluate given text.

    ``synthesizer_text`` is supplied by the caller. In the future
    authorized model runs it will be the model's verbatim output;
    in this module's tests it is canned text, so no model is called.
    When the state prompt is None (over budget), evaluation is
    skipped and the budget reason is reported instead.
    """
    state = build_synthesis_state(packet, registry, unresolved_objections,
                                  revision_chains, cap_chars=CAP)
    report: dict = {
        "fixture_id": fixture_id,
        "cap": CAP,
        "telemetry": dict(TELEMETRY),
        "mandatory_chars": state.get("mandatory_chars"),
        "omitted": state.get("omitted"),
    }
    if state["prompt"] is None:
        report["prompt"] = None
        report["budget_reason"] = state["reason"]
        return report
    prompt = assemble_prompt(state)
    report["prompt"] = prompt
    report["state_prompt_chars"] = len(state["prompt"])
    report["assembled_prompt_chars"] = len(prompt)
    report["prompt_sha256"] = hashlib.sha256(prompt.encode()).hexdigest()
    report["instruction_chars"] = len(_SYNTHESIS_INSTRUCTION)
    report.update(evaluate_synthesis_text(
        synthesizer_text, registry, unresolved_objections,
        omitted=state.get("omitted"), had_failures=had_failures))
    return report


def fixture_d_assertion(report: dict, opposing_claim_ids=("C1", "C2")) -> bool:
    """Fixture D pass condition: a VALIDATED disagreement grounded in
    the fixture's known opposing claims with a permitted enum value.

    An all-empty block must NOT pass: structural validity is not
    evidence coverage. Validated means present in structured output
    (the validator already rejected anything else).
    """
    for entry in report["structured"]["disagreements"]:
        if (set(entry["supporting_claims"]) & set(opposing_claim_ids)
                and entry["unresolved_status"] in (
                    "unresolved", "responded_to", "resolved")):
            return True
    return False


def fixture_e_assertion(report: dict) -> bool:
    """Fixture E pass condition: valid structured output; empty
    recommendations/limitations accepted IF produced. The model may
    legitimately offer entries instead — either validates. Any
    unparseable field fails.
    """
    if not report["block_found"]:
        return False
    return all(v in ("synthesized_complete", "synthesized_partial",
                     "synthesized_empty")
               for v in report["evaluations"].values())


def _block(**fields: object) -> str:
    return ("Narrative synthesis here.\n```json\n"
            + json.dumps(fields) + "\n```\n")


def _d_disagreement(status: str = "unresolved") -> dict:
    return {"opposing_positions": ["Assigned roles improve accountability.",
                                   "Open roles permit more substantive deliberation."],
            "supporting_claims": ["C1", "C2"],
            "unresolved_status": status}


def _d_position() -> dict:
    return {"claim_ids": ["C1"], "position": "Roles need revisability.",
            "supporting_reasoning": "Grounded in C1 and C4."}


# --- Diagnostic: component breakdown, gate unchanged -------------------

def _parse_reason(reason: str) -> dict:
    nums = dict(re.findall(r"(mandatory|instruction|disclosure|total|excess|cap)=(\d+)", reason))
    return {k: int(v) for k, v in nums.items()}


def _over_budget_state():
    reg = ClaimRegistry()
    for i in range(150):
        reg.register("GPT", "opening",
                     "1. Observed: " + "x" * 280 + f" claim {i}.")
    packet = EvidencePacket(work_item="Harness over-budget fixture",
                            question=QUESTION)
    return build_synthesis_state(packet, reg, [], [], cap_chars=CAP)


def test_over_budget_reason_reports_component_breakdown():
    state = _over_budget_state()
    assert state["prompt"] is None
    parts = _parse_reason(state["reason"])
    assert parts["cap"] == CAP
    assert parts["total"] == (parts["mandatory"] + parts["instruction"]
                              + parts["disclosure"])
    assert parts["excess"] == parts["total"] - CAP
    assert parts["total"] > CAP
    assert "no synthesis attempted and nothing was truncated to fit" in state["reason"]


def test_over_budget_reason_no_longer_states_false_claim():
    state = _over_budget_state()
    assert "mandatory synthesis state of" not in state["reason"]
    # The accurate form names the assembled input, not the mandatory part.
    assert state["reason"].startswith(
        "budget_exceeded: synthesis input exceeds cap=40000:")


def test_under_budget_state_prompt_present_and_reason_none():
    packet, reg, unresolved, chains = fixture_d_state()
    state = build_synthesis_state(packet, reg, unresolved, chains,
                                  cap_chars=CAP)
    assert state["prompt"] is not None
    assert state["reason"] is None


# --- Prompt equivalence -------------------------------------------------

def test_prompt_byte_for_byte_equal_to_production_composition():
    packet, reg, unresolved, chains = fixture_d_state()
    state = build_synthesis_state(packet, reg, unresolved, chains,
                                  cap_chars=CAP)
    assert state["prompt"] is not None
    harness_prompt = assemble_prompt(state)
    direct = state["prompt"] + "\n\n" + _telemetry_block(**TELEMETRY)
    assert harness_prompt == direct


def test_harness_report_carries_hash_and_sizes_no_credentials():
    packet, reg, unresolved, chains = fixture_d_state()
    report = run_harness("D", packet, reg, unresolved, chains,
                         _block(positions=[_d_position()],
                                disagreements=[_d_disagreement()],
                                recommendations=[],
                                limitations=[]))
    assert report["prompt_sha256"] == hashlib.sha256(
        report["prompt"].encode()).hexdigest()
    assert report["assembled_prompt_chars"] == len(report["prompt"])
    assert report["state_prompt_chars"] <= CAP
    assert report["assembled_prompt_chars"] < CAP
    assert "sk-" not in json.dumps(report)
    assert not any(k in ("api_key", "password", "token", "secret")
                   for k in report)
    assert report["telemetry"] == TELEMETRY


# --- Fixture D acceptance ------------------------------------------------

def test_fixture_d_valid_disagreement_passes():
    packet, reg, unresolved, chains = fixture_d_state()
    report = run_harness("D", packet, reg, unresolved, chains,
                         _block(positions=[_d_position()],
                                disagreements=[_d_disagreement()],
                                recommendations=[],
                                limitations=[]))
    assert report["evaluations"]["disagreements"] == "synthesized_complete"
    assert fixture_d_assertion(report) is True


def test_fixture_d_all_empty_block_does_not_pass():
    packet, reg, unresolved, chains = fixture_d_state()
    report = run_harness("D", packet, reg, unresolved, chains,
                         _block(positions=[], disagreements=[],
                                recommendations=[], limitations=[]))
    # Structurally valid empties — but NOT evidence coverage.
    assert report["evaluations"]["disagreements"] == "synthesized_empty"
    assert fixture_d_assertion(report) is False


def test_fixture_d_sentence_enum_rejected_and_not_in_output():
    packet, reg, unresolved, chains = fixture_d_state()
    bad = _d_disagreement(status="It remains unclear whether roles help.")
    report = run_harness("D", packet, reg, unresolved, chains,
                         _block(positions=[_d_position()],
                                disagreements=[bad],
                                recommendations=[],
                                limitations=[]))
    assert report["evaluations"]["disagreements"] == "unparseable"
    assert any(r["field"] == "disagreements" and "unresolved_status" in r["reason"]
               for r in report["rejected_entries"])
    assert report["structured"]["disagreements"] == []
    assert "remains unclear" not in json.dumps(report["structured"])
    assert fixture_d_assertion(report) is False


def test_fixture_d_disagreement_on_unrelated_claims_does_not_pass():
    packet, reg, unresolved, chains = fixture_d_state()
    unrelated = {"opposing_positions": ["A", "B"],
                 "supporting_claims": ["C3", "C4"],
                 "unresolved_status": "unresolved"}
    report = run_harness("D", packet, reg, unresolved, chains,
                         _block(positions=[_d_position()],
                                disagreements=[unrelated],
                                recommendations=[],
                                limitations=[]))
    # Validator accepts it (valid IDs, valid enum) — but it is not
    # grounded in the fixture's known opposing claims.
    assert report["evaluations"]["disagreements"] == "synthesized_complete"
    assert fixture_d_assertion(report) is False


# --- Fixture E acceptance -------------------------------------------------

def test_fixture_e_legitimate_empties_pass():
    packet, reg, unresolved, chains = fixture_e_state()
    report = run_harness("E", packet, reg, unresolved, chains,
                         _block(positions=[_d_position()],
                                disagreements=[],
                                recommendations=[],
                                limitations=[]))
    assert report["evaluations"]["recommendations"] == "synthesized_empty"
    assert report["evaluations"]["limitations"] == "synthesized_empty"
    assert fixture_e_assertion(report) is True


def test_fixture_e_offered_entries_also_pass():
    packet, reg, unresolved, chains = fixture_e_state()
    report = run_harness("E", packet, reg, unresolved, chains,
                         _block(positions=[_d_position()],
                                disagreements=[],
                                recommendations=[{"proposed_action": "Ask Joshua.",
                                                    "supporting_claims": ["C1"]}],
                                limitations=[{"missing_evidence_or_omission": "No cost data.",
                                                "note": "Costs were never discussed."}]))
    assert fixture_e_assertion(report) is True


# --- Deterministic validator fixtures --------------------------------------

def test_deterministic_sentence_enum_exact_4ed23fcbe583_shape():
    packet, reg, unresolved, chains = fixture_d_state()
    bad = {"opposing_positions": ["Assigned roles improve accountability.",
                                  "Open roles permit more substantive deliberation."],
           "supporting_claims": ["C1", "C2"],
           "unresolved_status": "It remains unclear whether the absence of "
           "assigned roles leads to confusion or supports emergent deliberation."}
    report = run_harness("D", packet, reg, unresolved, chains,
                         _block(positions=[_d_position()],
                                disagreements=[bad],
                                recommendations=[],
                                limitations=[]))
    assert report["structured"]["disagreements"] == []
    assert any(r["field"] == "disagreements" for r in report["rejected_entries"])


def test_deterministic_valid_empty_per_field():
    packet, reg, unresolved, chains = fixture_e_state()
    report = run_harness("E", packet, reg, unresolved, chains,
                         _block(positions=[], disagreements=[],
                                recommendations=[], limitations=[]))
    assert all(v == "synthesized_empty"
               for v in report["evaluations"].values())


def test_deterministic_mixed_block_per_field_independence():
    packet, reg, unresolved, chains = fixture_d_state()
    bad = _d_disagreement(status="A sentence, not an enum.")
    report = run_harness("D", packet, reg, unresolved, chains,
                         _block(positions=[_d_position()],
                                disagreements=[_d_disagreement(), bad],
                                recommendations=[],
                                limitations={"not": "a list"}))
    assert report["evaluations"]["positions"] == "synthesized_complete"
    assert report["evaluations"]["disagreements"] == "synthesized_partial"
    assert report["evaluations"]["recommendations"] == "synthesized_empty"
    assert report["evaluations"]["limitations"] == "unparseable"


def test_deterministic_missing_key_is_unparseable_only_for_that_field():
    packet, reg, unresolved, chains = fixture_d_state()
    text = ("Narrative.\n```json\n"
            + json.dumps({"positions": [_d_position()],
                          "disagreements": [_d_disagreement()],
                          "recommendations": []})
            + "\n```\n")
    report = run_harness("D", packet, reg, unresolved, chains, text)
    assert report["evaluations"]["limitations"] == "unparseable"
    assert report["evaluations"]["positions"] == "synthesized_complete"


def test_deterministic_nonempty_all_rejected_is_unparseable():
    packet, reg, unresolved, chains = fixture_d_state()
    report = run_harness("D", packet, reg, unresolved, chains,
                         _block(positions=[_d_position()],
                                disagreements=[_d_disagreement(status="nope")],
                                recommendations=[],
                                limitations=[]))
    assert report["evaluations"]["disagreements"] == "unparseable"


def test_deterministic_unexpected_key_rejects_whole_block():
    packet, reg, unresolved, chains = fixture_d_state()
    report = run_harness("D", packet, reg, unresolved, chains,
                         _block(positions=[_d_position()],
                                disagreements=[_d_disagreement()],
                                recommendations=[], limitations=[],
                                surprise=[]))
    assert all(v == "unparseable" for v in report["evaluations"].values())
    assert any("unexpected top-level keys" in r["reason"]
               for r in report["rejected_entries"])


# --- Disclosure notes + reporting separation -------------------------------

def test_disclosure_notes_fire_and_silence_conditions():
    packet, reg, unresolved, chains = fixture_d_state()
    # Disagreements empty + unresolved objections exist -> fires.
    report = run_harness("D", packet, reg, unresolved, chains,
                         _block(positions=[_d_position()],
                                disagreements=[],
                                recommendations=[],
                                limitations=[]))
    assert report["disclosure_notes"]["disagreements_note"] is True
    # No objections -> does not fire.
    packet2, reg2, _, _ = fixture_e_state()
    report2 = run_harness("E", packet2, reg2, [], [],
                          _block(positions=[_d_position()],
                                 disagreements=[],
                                 recommendations=[],
                                 limitations=[]))
    assert report2["disclosure_notes"]["disagreements_note"] is False
    assert report2["disclosure_notes"]["limitations_note"] is False
    # Limitations empty + omitted context -> fires.
    report3 = run_harness("E", packet2, reg2, [], [],
                          _block(positions=[_d_position()],
                                 disagreements=[],
                                 recommendations=[],
                                 limitations=[]),
                          had_failures=True)
    assert report3["disclosure_notes"]["limitations_note"] is True


def test_raw_preserved_verbatim_and_derived_results_separate():
    packet, reg, unresolved, chains = fixture_d_state()
    text = _block(positions=[_d_position()],
                  disagreements=[_d_disagreement(status="A sentence.")],
                  recommendations=[], limitations=[])
    report = run_harness("D", packet, reg, unresolved, chains, text)
    assert report["raw"] == text
    assert "A sentence." not in json.dumps(report["structured"])
    assert report["raw"] is not report["structured"]


def test_evaluation_never_mutates_registry_or_objections():
    packet, reg, unresolved, chains = fixture_d_state()
    before_claims = [(c.id, c.text) for c in reg.claims]
    before_objections = copy.deepcopy(unresolved)
    run_harness("D", packet, reg, unresolved, chains,
                _block(positions=[_d_position()],
                       disagreements=[_d_disagreement()],
                       recommendations=[], limitations=[]))
    assert [(c.id, c.text) for c in reg.claims] == before_claims
    assert unresolved == before_objections
