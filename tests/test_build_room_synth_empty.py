"""Bounded synthesis-contract correction tests, part 2: empty-field semantics.

Verification run 4ed23fcbe583 showed two distinct failures after PR #225
fixed quoted IDs: disagreements rejected because unresolved_status was
written as sentences instead of the enum, and recommendations/limitations
returned as valid empty arrays but marked unparseable. The correction is:

A. Prompt: a populated disagreement example showing the enum value.
B. Validator: a valid empty list is synthesized_empty, independently per
   field — never conflated with a parse failure.
C. Disclosure: an empty field with corresponding state material gets a
   transcript note (text only, no status change, no reclassification).

No schema change, no repair layer: sentence-valued statuses are still
rejected, never rewritten into enum values. No live API calls, no real
key values anywhere.
"""

from __future__ import annotations

import copy
import json

from local_ai.build_room.meeting import (
    ClaimRegistry,
    EvidencePacket,
    _SYNTHESIS_INSTRUCTION,
    parse_synthesis_contract,
)


def _registry(n: int) -> ClaimRegistry:
    """Registry with C1..Cn, rotating across the five seats."""
    reg = ClaimRegistry()
    participants = ["GPT", "Claude", "Gemini", "Grok", "Muse"]
    for i in range(n):
        reg.register(participants[i % len(participants)], "opening",
                     f"{i + 1}. Observed: Claim {i + 1}.")
    return reg


def _block(**fields: object) -> str:
    return "Narrative synthesis here.\n```json\n" + json.dumps(fields) + "\n```\n"


def _good_position(cid: str = "C1") -> dict:
    return {"claim_ids": [cid], "position": "Kept.",
            "supporting_reasoning": "Grounded."}


def _good_disagreement() -> dict:
    return {"opposing_positions": ["Merge roles", "Keep roles open"],
            "supporting_claims": ["C3"],
            "unresolved_status": "unresolved"}


def _good_recommendation() -> dict:
    return {"proposed_action": "Ask Joshua.",
            "supporting_claims": ["C5"]}


def _good_limitation() -> dict:
    return {"missing_evidence_or_omission": "No cost data.",
            "note": "Costs were never discussed."}


# --- A. Instruction carries the populated disagreement example -----------

def test_instruction_shows_disagreement_example_and_enum_rule():
    assert "Assigned roles improve accountability." in _SYNTHESIS_INSTRUCTION
    assert "Open roles permit more substantive deliberation." in _SYNTHESIS_INSTRUCTION
    assert '"C6", "C21"' in _SYNTHESIS_INSTRUCTION
    assert '"unresolved_status": "unresolved"' in _SYNTHESIS_INSTRUCTION
    assert "exactly one of the three permitted strings" in _SYNTHESIS_INSTRUCTION
    assert "never an explanation" in _SYNTHESIS_INSTRUCTION
    # An explanation belongs elsewhere, not in the enum field.
    assert "narrative synthesis or another already-permitted descriptive field" \
        in _SYNTHESIS_INSTRUCTION


def test_assembled_prompt_includes_disagreement_example():
    from local_ai.build_room.meeting import build_synthesis_state
    packet = EvidencePacket(work_item="Test work item",
                            question="What would make the Build-Council Room fail?")
    state = build_synthesis_state(packet, _registry(21), [], [],
                                  cap_chars=100000)
    assert state["prompt"] is not None
    assert '"unresolved_status": "unresolved"' in state["prompt"]
    assert "exactly one of the three permitted strings" in state["prompt"]


# --- B. Valid empty is synthesized_empty, independently per field --------

def test_all_empty_block_is_synthesized_empty_not_unparseable():
    structured, evals, rejected, found = parse_synthesis_contract(
        _block(positions=[], disagreements=[], recommendations=[],
               limitations=[]),
        _registry(5), [], "GPT")
    assert found is True
    assert rejected == []
    assert evals == {"positions": "synthesized_empty",
                     "disagreements": "synthesized_empty",
                     "recommendations": "synthesized_empty",
                     "limitations": "synthesized_empty"}
    assert all(v == [] for v in structured.values())


def test_fields_evaluate_independently():
    structured, evals, rejected, found = parse_synthesis_contract(
        _block(
            positions=[_good_position()],
            disagreements=[],
            recommendations=[_good_recommendation(),
                             {"proposed_action": "",
                              "supporting_claims": ["C5"]}],
            limitations=[{"missing_evidence_or_omission": "",
                          "note": "Empty omission."}],
        ),
        _registry(5), [], "GPT")
    assert found is True
    assert evals["positions"] == "synthesized_complete"
    assert evals["disagreements"] == "synthesized_empty"
    assert evals["recommendations"] == "synthesized_partial"
    assert evals["limitations"] == "unparseable"
    assert [(r["field"], r["index"]) for r in rejected] == [
        ("recommendations", 1), ("limitations", 0)]


def test_missing_key_still_unparseable():
    structured, evals, rejected, found = parse_synthesis_contract(
        _block(positions=[_good_position()], disagreements=[],
               recommendations=[]),
        _registry(5), [], "GPT")
    assert found is True
    assert evals["limitations"] == "unparseable"
    assert structured["limitations"] == []
    assert evals["disagreements"] == "synthesized_empty"


def test_nonempty_all_rejected_still_unparseable():
    structured, evals, rejected, found = parse_synthesis_contract(
        _block(
            positions=[{"claim_ids": ["C99"], "position": "Unknown.",
                        "supporting_reasoning": "No such claim."},
                       {"claim_ids": ["C1"]}],
            disagreements=[], recommendations=[], limitations=[]),
        _registry(5), [], "GPT")
    assert found is True
    assert evals["positions"] == "unparseable"
    assert structured["positions"] == []
    assert len(rejected) == 2
    # Empty fields alongside it keep their own evaluation.
    assert evals["disagreements"] == "synthesized_empty"


# --- Sentence-valued unresolved_status is rejected, never repaired -------

def test_sentence_valued_status_rejected_and_disclosed():
    # The 4ed23fcbe583 failure shape: sentences where the enum belongs.
    sentences = [
        "It remains unclear whether the absence of assigned roles leads "
        "to confusion or supports emergent deliberation.",
        "The effectiveness of unguided role discovery under budget "
        "constraints remains a point of contention.",
        "Ambiguities around transliterable shorthand and its impact on "
        "decision-making transparency persist.",
    ]
    block = _block(
        positions=[_good_position()],
        disagreements=[{"opposing_positions": ["A", "B"],
                        "supporting_claims": ["C3"],
                        "unresolved_status": s} for s in sentences],
        recommendations=[], limitations=[])
    structured, evals, rejected, found = parse_synthesis_contract(
        block, _registry(5), [], "GPT")
    assert found is True
    assert evals["disagreements"] == "unparseable"
    assert structured["disagreements"] == []
    assert [(r["field"], r["index"]) for r in rejected] == [
        ("disagreements", 0), ("disagreements", 1), ("disagreements", 2)]
    assert all("unresolved_status must be unresolved, responded_to, or resolved"
               in r["reason"] for r in rejected)
    # No repair: no sentence ever lands in structured output as a status.
    assert not any(isinstance(d.get("unresolved_status"), str)
                   and len(d["unresolved_status"]) > 20
                   for d in structured["disagreements"])


# --- C. Synthesis never erases or reclassifies registry objections -------

def test_synthesis_never_reclassifies_registry_objections():
    objections = [{"claim_id": "C3", "originator": "Gemini",
                   "cited_by": "Claude", "moves": ["objection"],
                   "source_claim_id": "C7", "state": "unresolved",
                   "responded_by": None}]
    before = copy.deepcopy(objections)
    block = _block(
        positions=[_good_position()],
        disagreements=[{"opposing_positions": ["A", "B"],
                        "supporting_claims": ["C3"],
                        "unresolved_status": "resolved"}],
        recommendations=[], limitations=[])
    structured, evals, rejected, found = parse_synthesis_contract(
        block, _registry(7), objections, "GPT")
    assert found is True
    assert evals["disagreements"] == "synthesized_complete"
    entry = structured["disagreements"][0]
    # The synthesis label and the registry state sit side by side,
    # labeled by source; neither overwrites the other.
    assert entry["unresolved_status"] == "resolved"
    assert entry["registry_unresolved_status"] == "unresolved"
    assert entry["resolution_divergence"] is True
    assert objections == before


# --- C. Live path: empty-field disclosure notes ---------------------------

class _FakeSeat:
    """Minimal duck-typed seat participant for live-path tests."""

    def __init__(self, name, *, opening="", response="", revision="",
                 synthesis=""):
        self.name = name
        self.provider_id = "fake"
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


class _RaisingSeat(_FakeSeat):
    """A seat whose generation fails, to exercise failure handling."""

    def generate(self, prompt, *, timeout=120):
        raise RuntimeError("simulated generation failure")


def _live_seats(fakes):
    from local_ai.build_room.participants import SEAT_SPECS, Seat
    seats = []
    for name, provider_id, model in SEAT_SPECS:
        fake = fakes.get(name)
        if fake is None:
            seats.append(Seat(name, provider_id, model, None,
                              absence_note="absent"))
        else:
            seats.append(Seat(name, provider_id, model, fake))
    return seats


def _packet() -> EvidencePacket:
    return EvidencePacket(
        work_item="Test work item",
        question="What would make the Build-Council Room fail?")


def _empty_block() -> str:
    return _block(positions=[], disagreements=[], recommendations=[],
                  limitations=[])


def _note_texts(result) -> list[str]:
    return [e.text for e in result.transcript.entries if e.kind == "note"]


def test_live_empty_disagreements_note_fires_with_unresolved_objections(tmp_path):
    from local_ai.build_room.meeting import run_multi_model_meeting
    fakes = {
        "GPT": _FakeSeat("GPT", opening="1. Observed: Alpha."),
        "Claude": _FakeSeat(
            "Claude", opening="1. Inferred: Beta.",
            synthesis=_empty_block(),
            response="1. Inferred: In response to C1: Objection to C1: "
                     "the recommendation-only framing is insufficient."),
        "Gemini": _FakeSeat("Gemini", opening="1. Proposed: Gamma."),
        "Grok": _FakeSeat("Grok", opening="1. Speculative: Delta."),
        "Muse": _FakeSeat("Muse", opening="1. Observed: Epsilon."),
    }
    result = run_multi_model_meeting(
        _packet(), store_dir=tmp_path, seats=_live_seats(fakes))
    art = result.artifact
    assert art["disagreements"] == []
    assert art["disagreements_evaluation"] == "synthesized_empty"
    # The registry holds an unresolved objection the empty field does
    # not account for — disclosed, not erased or reclassified.
    assert art["unresolved_objections"] != []
    assert art["unresolved_objections"][0]["state"] == "unresolved"
    notes = _note_texts(result)
    assert any("disagreements field is empty" in n
               and "unresolved objections exist in the registry" in n
               and "not that no disagreements exist" in n for n in notes)
    # No omitted context and no failures here, so no limitations note.
    assert not any("limitations field is empty" in n for n in notes)


def test_live_empty_limitations_note_fires_on_failed_contribution(tmp_path):
    from local_ai.build_room.meeting import run_multi_model_meeting
    fakes = {
        "GPT": _FakeSeat("GPT", opening="1. Observed: Alpha."),
        "Claude": _FakeSeat("Claude", opening="1. Inferred: Beta.",
                            synthesis=_empty_block()),
        "Gemini": _FakeSeat("Gemini", opening="1. Proposed: Gamma."),
        "Grok": _RaisingSeat("Grok"),
        "Muse": _FakeSeat("Muse", opening="1. Observed: Epsilon."),
    }
    result = run_multi_model_meeting(
        _packet(), store_dir=tmp_path, seats=_live_seats(fakes))
    art = result.artifact
    assert art["limitations"] == []
    assert art["limitations_evaluation"] == "synthesized_empty"
    notes = _note_texts(result)
    assert any("limitations field is empty" in n
               and "omitted context or failed contributions" in n
               and "not that no limitations exist" in n for n in notes)
