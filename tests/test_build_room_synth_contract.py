"""Bounded synthesis-contract correction tests (final R2 rerun follow-up).

Live meeting 7eac64190430 failed structured synthesis because GPT wrote
claim IDs unquoted (``[C2, C6, C12]``) — valid-looking JSON-shaped text,
invalid JSON. The correction is prompt-only: _SYNTHESIS_INSTRUCTION now
states the string requirement explicitly and shows a concrete quoted-ID
format example. The parser, contract keys, validator, and no-repair
behavior are unchanged. No live API calls, no real key values anywhere.
"""

from __future__ import annotations

import json

from local_ai.build_room.meeting import (
    ClaimRegistry,
    EvidencePacket,
    _SYNTHESIS_INSTRUCTION,
    build_synthesis_state,
    parse_synthesis_contract,
)


def _registry_12() -> ClaimRegistry:
    """Registry with C1–C12, so the example IDs C2, C6, C12 exist."""
    reg = ClaimRegistry()
    participants = ["GPT", "Claude", "Gemini", "Grok", "Muse"]
    for i in range(12):
        reg.register(participants[i % len(participants)], "opening",
                     f"{i + 1}. Observed: Claim {i + 1}.")
    assert reg.ids() == {f"C{i}" for i in range(1, 13)}
    return reg


# --- 1. Instruction text carries the requirement + example ----------------

def test_instruction_requires_quoted_ids_and_shows_example():
    assert "double quotation marks" in _SYNTHESIS_INSTRUCTION
    assert "valid JSON" in _SYNTHESIS_INSTRUCTION
    assert "not merely JSON-shaped text" in _SYNTHESIS_INSTRUCTION
    assert "unquoted IDs are invalid" in _SYNTHESIS_INSTRUCTION
    # The concrete format example, with IDs quoted as JSON strings.
    assert '"C2", "C6", "C12"' in _SYNTHESIS_INSTRUCTION
    assert '"positions"' in _SYNTHESIS_INSTRUCTION
    # Disclaimer: format only, never the claims to use.
    assert "shows format only" in _SYNTHESIS_INSTRUCTION
    assert "not the example IDs" in _SYNTHESIS_INSTRUCTION


# --- 2. Assembled synthesis prompt includes them ---------------------------

def test_assembled_synthesis_prompt_includes_example_and_requirement():
    packet = EvidencePacket(
        work_item="Test work item",
        question="What would make the Build-Council Room fail?",
    )
    state = build_synthesis_state(packet, _registry_12(), [], [],
                                  cap_chars=100000)
    prompt = state["prompt"]
    assert prompt is not None
    assert "double quotation marks" in prompt
    assert '"C2", "C6", "C12"' in prompt
    assert "shows format only" in prompt


# --- 3. Regression: the 7eac64190430 failure shape is still rejected --------

def test_unquoted_ids_block_rejected_as_unparseable():
    # Same shape as the failed live block: claim IDs written bare, not
    # as JSON strings. The whole block is invalid JSON, so every field
    # is unparseable and the rejection names JSONDecodeError.
    failed_block = (
        "Narrative synthesis here.\n"
        "```json\n"
        "{\n"
        '  "positions": [\n'
        "    {\n"
        "      \"claim_ids\": [C2, C6, C12],\n"
        '      "position": "The absence of assigned roles may lead to ambiguity.",\n'
        '      "supporting_reasoning": "Grounded in the cited claims."\n'
        "    }\n"
        "  ],\n"
        '  "disagreements": [],\n'
        '  "recommendations": [],\n'
        '  "limitations": []\n'
        "}\n"
        "```\n"
    )
    structured, evals, rejected, found = parse_synthesis_contract(
        failed_block, _registry_12(), [], "GPT")
    assert found is True
    assert structured == {"positions": [], "disagreements": [],
                          "recommendations": [], "limitations": []}
    assert evals == {"positions": "unparseable",
                     "disagreements": "unparseable",
                     "recommendations": "unparseable",
                     "limitations": "unparseable"}
    assert rejected == [{"field": "contract", "index": None,
                         "reason": "invalid JSON: JSONDecodeError"}]


# --- 4. The new example shape parses ---------------------------------------

def test_example_shape_block_parses_positions_complete():
    # The instruction's example block verbatim in shape: one position
    # with quoted IDs, three empty fields (empty fields stay unparseable
    # by design — no entries, nothing rejected, nothing invented).
    example_block = (
        "Narrative synthesis here.\n"
        "```json\n"
        + json.dumps({
            "positions": [
                {"claim_ids": ["C2", "C6", "C12"],
                 "position": "A concise statement of the position.",
                 "supporting_reasoning":
                     "Reasoning grounded in the cited claims."},
            ],
            "disagreements": [],
            "recommendations": [],
            "limitations": [],
        })
        + "\n```\n"
    )
    structured, evals, rejected, found = parse_synthesis_contract(
        example_block, _registry_12(), [], "GPT")
    assert found is True
    assert rejected == []
    assert evals["positions"] == "synthesized_complete"
    assert structured["positions"][0]["claim_ids"] == ["C2", "C6", "C12"]
    assert evals["disagreements"] == "unparseable"
    assert evals["recommendations"] == "unparseable"
    assert evals["limitations"] == "unparseable"


def test_full_block_with_one_entry_per_field_all_complete():
    full_block = (
        "Narrative synthesis here.\n"
        "```json\n"
        + json.dumps({
            "positions": [
                {"claim_ids": ["C2", "C6", "C12"],
                 "position": "A concise statement of the position.",
                 "supporting_reasoning":
                     "Reasoning grounded in the cited claims."},
            ],
            "disagreements": [
                {"opposing_positions": ["Merge roles", "Keep roles open"],
                 "supporting_claims": ["C1", "C3"],
                 "unresolved_status": "unresolved"},
            ],
            "recommendations": [
                {"proposed_action": "Ask Joshua.",
                 "supporting_claims": ["C5"]},
            ],
            "limitations": [
                {"missing_evidence_or_omission": "No cost data.",
                 "note": "Costs were never discussed."},
            ],
        })
        + "\n```\n"
    )
    _structured, evals, rejected, found = parse_synthesis_contract(
        full_block, _registry_12(), [], "GPT")
    assert found is True
    assert rejected == []
    assert evals == {"positions": "synthesized_complete",
                     "disagreements": "synthesized_complete",
                     "recommendations": "synthesized_complete",
                     "limitations": "synthesized_complete"}
