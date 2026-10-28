"""Registry standing stage-3 tests: the revision input contract.

Stage 3 is prompt wording only: the revision prompt gains the
standing-move input contract, and nothing else changes — no budget,
tool, or validation change, no new generation shape, no change to
what the runner accepts. These tests pin the wording, prove the
addition is additive (the original follow-up sentences survive),
prove the prompt assembly still carries every other section
verbatim, and run a live-shape meeting proving the harness still
passes. Generation is mocked — no live API calls.
"""

from __future__ import annotations

from local_ai.build_room.meeting import (
    EvidencePacket,
    _CLAIM_NUMBERING_INSTRUCTION,
    _CONTRIBUTION_DISCIPLINE,
    _FOLLOWUP_INSTRUCTION,
    _LANGUAGE_LINE,
    _RESPONSE_INSTRUCTION,
    run_multi_model_meeting,
)
from local_ai.build_room.participants import SEAT_SPECS, Seat

CONTRACT_PHRASES = (
    "one numbered span per move",
    "exactly one earlier claim ID",
    "C6–C9 is not a move",
    "a stance word with no claim ID is not a move",
    "only move your own claims",
    "stays a proposal and never changes that claim's standing",
    "A defense is not a move",
    "never reactivates it",
    "To move four claims, write four spans",
)


def test_contract_wording_present():
    for phrase in CONTRACT_PHRASES:
        assert phrase in _FOLLOWUP_INSTRUCTION, phrase


def test_original_followup_sentences_preserved():
    # The contract is an addition, not a replacement: the sentences
    # models already followed must still be there verbatim.
    for sentence in (
        "Make ONE follow-up",
        "state the relationship explicitly",
        "A defense links to the original claim without replacing it",
        "a revision may supersede it",
    ):
        assert sentence in _FOLLOWUP_INSTRUCTION, sentence


def test_other_prompt_sections_untouched():
    # No other prompt section was altered: their distinctive lines
    # are exactly as before this stage.
    assert "Do not collapse disagreements into consensus." in _RESPONSE_INSTRUCTION
    assert "do not invent, renumber, or reuse C-numbers" in _CLAIM_NUMBERING_INSTRUCTION
    assert "target 3–6 substantive claims per contribution" in _CONTRIBUTION_DISCIPLINE
    assert "must be understandable in English" in _LANGUAGE_LINE


class FakeParticipant:
    """Duck-typed seat participant that records the prompts it saw."""

    def __init__(self, name, *, opening="", response="", revision=""):
        self.name = name
        self.provider_id = dict((n, p) for n, p, _ in SEAT_SPECS)[name]
        self.model = "fake-model"
        self.key_source = "settings"
        self.prompts: dict[str, str] = {}
        self._texts = {
            "revision": revision,
            "response": response,
            "opening": opening,
        }

    def generate(self, prompt, *, timeout=120):
        if "state the relationship explicitly" in prompt:
            self.prompts["revision"] = prompt
            return self._texts["revision"]
        if "Claim registry" in prompt:
            self.prompts["response"] = prompt
            return self._texts["response"]
        self.prompts["opening"] = prompt
        return self._texts["opening"]


def _packet() -> EvidencePacket:
    return EvidencePacket(
        work_item="Test work item",
        question="What would make the Build-Council Room fail to function as a genuine deliberative council?",
        excerpts=("excerpt one",),
        constraints=("room deliberates, never decides",),
        source_refs=("local_ai/build_room/meeting.py",),
    )


def _seats(fakes) -> list[Seat]:
    seats = []
    for name, provider_id, model in SEAT_SPECS:
        fake = fakes.get(name, FakeParticipant(name, opening="1. Inferred: nothing yet."))
        if fake is None:
            seats.append(Seat(name, provider_id, model, None,
                              absence_note=f"absent: no {provider_id} api key present"))
        else:
            seats.append(Seat(name, provider_id, model, fake))
    return seats


def test_live_shape_meeting_still_passes_with_contract_prompt(tmp_path):
    gpt = FakeParticipant(
        "GPT",
        opening="1. Observed: Authority confusion is a failure mode.\n2. Proposed: Keep authorization with Joshua.",
        response="In response to C3, I agree: the registry point stands.",
        revision="Relationship: withdrawn.\nIn response to C1, I withdraw that claim:\n"
                 "1. Inferred: Authority confusion is not the top risk after all.",
    )
    fakes = {
        "GPT": gpt,
        "Claude": FakeParticipant(
            "Claude",
            opening="1. Inferred: Parallel monologues are a failure mode.",
            response="1. Objection to C1: authorization alone does not "
                     "prevent misrepresentation.",
        ),
        "Gemini": FakeParticipant("Gemini", opening="1. Proposed: Add addressable claims."),
        "Grok": FakeParticipant("Grok", opening="1. Speculative: The room may perform deliberation."),
        "Muse": FakeParticipant("Muse", opening="1. Inferred: Cost grows with participants."),
    }
    result = run_multi_model_meeting(_packet(), store_dir=tmp_path,
                                     seats=_seats(fakes))
    assert result.ok is True
    assert result.artifact["record_complete"] is True
    assert result.artifact["record_completeness"]["checks"]["standing_invariants"]["passed"] is True
    # The revision prompt the model actually saw carries the whole
    # contract and every other prompt section verbatim.
    revision_prompt = gpt.prompts["revision"]
    assert _FOLLOWUP_INSTRUCTION in revision_prompt
    assert _CLAIM_NUMBERING_INSTRUCTION in revision_prompt
    assert _CONTRIBUTION_DISCIPLINE in revision_prompt
    assert _LANGUAGE_LINE in revision_prompt
    # And the contract's phrasing still parses: the withdrawal move
    # landed on C1 through the unchanged stage-1 acceptance rules.
    table = result.artifact["claim_standing"]
    c1 = next(e for e in table["entries"] if e["claim_id"] == "C1")
    assert c1["standing"] == "withdrawn"
    assert c1["standing_chain"][0]["move"] == "withdrawal"
