"""Reframe-once tests: malformed declaration blocks earn exactly one
re-emit attempt, and a twice-failed piece stands as a failure.

Generation is mocked — no live API calls, no real key values anywhere.
Fakes branch on prompt markers: reframe prompts contain
"could not be parsed"; revision prompts contain "state the
relationship explicitly"; response prompts contain "Claim registry";
everything else is an opening.
"""

from __future__ import annotations

from local_ai.build_room import meeting as meeting_mod
from local_ai.build_room.meeting import (
    Budget,
    EvidencePacket,
    GateDecision,
    _reframe_prompt,
    run_multi_model_meeting,
)
from local_ai.build_room.participants import SEAT_SPECS, Seat

WASTED_EFFORT = (
    "Declarations that do not follow this format will not count: "
    "prose about your targets is wasted effort; only entries in this "
    "block are recorded."
)


class _ReframeFake:
    """Duck-typed seat participant counting every generate() call."""

    def __init__(self, name, *, opening="", response="", revision="",
                 reframe=""):
        self.name = name
        self.provider_id = dict((n, p) for n, p, _ in SEAT_SPECS)[name]
        self.model = "fake-model"
        self.key_source = "settings"
        self._texts = {
            "revision": revision,
            "response": response,
            "opening": opening,
            "reframe": reframe,
        }
        self.prompts: list[str] = []
        self.calls = 0
        self.reframe_calls = 0

    def generate(self, prompt, *, timeout=120):
        self.prompts.append(prompt)
        self.calls += 1
        if "could not be parsed" in prompt:
            self.reframe_calls += 1
            return self._texts["reframe"]
        if "state the relationship explicitly" in prompt:
            return self._texts["revision"]
        if "Claim registry" in prompt:
            return self._texts["response"]
        return self._texts["opening"]


def _packet():
    return EvidencePacket(
        work_item="Test work item",
        question="What would make the Build-Council Room fail?",
        excerpts=("excerpt one",),
        constraints=("room deliberates, never decides",),
        source_refs=("local_ai/build_room/meeting.py",),
    )


def _seats(fakes):
    seats = []
    for name, provider_id, model in SEAT_SPECS:
        fake = fakes.get(name)
        if fake is None:
            seats.append(Seat(name, provider_id, model, None,
                              absence_note=f"absent: no {provider_id} key"))
        else:
            seats.append(Seat(name, provider_id, model, fake))
    return seats


def _others():
    """Non-subject seats: one opening claim each, prose-only follow-ups
    (no blocks, no objection moves, so they never trigger a reframe
    and never invite anyone to revision — baseline calls per seat
    are opening + response = 2)."""
    return {
        "Claude": _ReframeFake(
            "Claude",
            opening="1. Inferred: Parallel monologues are a failure mode.",
            response="1. Inferred: The registry point stands, "
                     "in response to C1.",
            revision="Relationship: defended.\n"
                     "1. Inferred: Parallel monologues remain a risk.",
        ),
        "Gemini": _ReframeFake(
            "Gemini",
            opening="1. Proposed: Add addressable claims.",
            response="1. Inferred: Addressability helps, in response to C1.",
            revision="Relationship: defended.\n"
                     "1. Inferred: Addressability still helps.",
        ),
        "Grok": _ReframeFake(
            "Grok",
            opening="1. Speculative: The room may perform deliberation.",
            response="1. Inferred: Deliberation needs structure, "
                     "in response to C1.",
            revision="Relationship: defended.\n"
                     "1. Inferred: Structure still matters.",
        ),
        "Muse": _ReframeFake(
            "Muse",
            opening="1. Observed: A fourth opening claim.",
            response="1. Inferred: The registry point stands, "
                     "in response to C1.",
            revision="Relationship: defended.\n"
                     "1. Inferred: The point still stands.",
        ),
    }


def _run(tmp_path, fakes, **kwargs):
    kwargs.setdefault("budget", Budget(max_contributions=30))
    return run_multi_model_meeting(_packet(), store_dir=tmp_path,
                                   seats=_seats(fakes), **kwargs)


def _claims(result, participant, phase):
    return [c for c in result.artifact["claim_registry"]
            if c["participant"] == participant and c["phase"] == phase]


def _notes(result, needle):
    return [e.text for e in result.transcript.entries
            if e.kind == "note" and needle in e.text]


def _gpt_response_malformed(reframe_text):
    return _ReframeFake(
        "GPT",
        opening="1. Inferred: Authority confusion is a failure mode.",
        response="1. Inferred: The registry point stands.\n\n"
                 "Declarations (declaration-block-v1):\n"
                 "this is not an entry",
        revision="Relationship: defended.\n"
                 "1. Inferred: Authority confusion remains the top risk.",
        reframe=reframe_text,
    )


def test_first_attempt_success_makes_no_reframe(tmp_path):
    gpt = _ReframeFake(
        "GPT",
        opening="1. Inferred: Authority confusion is a failure mode.",
        response="1. Inferred: The registry point stands.\n\n"
                 "Declarations (declaration-block-v1):\n"
                 "1: extends C2",
        revision="Relationship: defended.\n"
                 "1. Inferred: Authority confusion remains the top risk.",
    )
    fakes = {"GPT": gpt, **_others()}
    result = _run(tmp_path, fakes)
    assert gpt.calls == 2
    assert gpt.reframe_calls == 0
    assert _notes(result, "Declaration reframe") == []
    claim = _claims(result, "GPT", "response")[0]
    assert claim["target_state"] == "populated"
    assert "declaration_reframed" not in claim


def test_failure_then_successful_reframe_uses_reframed(tmp_path):
    reframe_block = ("Declarations (declaration-block-v1):\n"
                     "1: extends C2")
    gpt = _gpt_response_malformed(reframe_block)
    fakes = {"GPT": gpt, **_others()}
    result = _run(tmp_path, fakes)
    assert gpt.calls == 3
    assert gpt.reframe_calls == 1
    claim = _claims(result, "GPT", "response")[0]
    assert claim["target_state"] == "populated"
    assert [(d["kind"], d["target_claim"])
            for d in claim["declarations"]] == [("extends", "C2")]
    assert claim["declaration_raw"] == reframe_block
    assert claim["declaration_reframed"] is True
    notes = _notes(result, "Declaration reframe (response, GPT)")
    assert len(notes) == 1
    assert "parsed" in notes[0]
    assert reframe_block in notes[0]
    # The reframe is a budgeted generation with its own settlement
    # row, distinct from the original generation's row.
    assert any(s["phase"] == "response:reframe"
               and s["participant"] == "GPT"
               for s in result.artifact["cap_budget"]["settlements"])


def test_double_failure_stands_and_reframes_exactly_once(tmp_path):
    original_block = ("Declarations (declaration-block-v1):\n"
                      "this is not an entry")
    gpt = _gpt_response_malformed(
        "Declarations (declaration-block-v1):\nstill garbage")
    fakes = {"GPT": gpt, **_others()}
    result = _run(tmp_path, fakes)
    # Call counts prove exactly one reframe: opening + response +
    # one reframe, no more (no revision invitations in this fixture).
    assert gpt.calls == 3
    assert gpt.reframe_calls == 1
    claim = _claims(result, "GPT", "response")[0]
    assert claim["target_state"] == "unknown"
    assert claim["uncertainty_reason"] == "malformed declaration block"
    assert claim["declaration_parse_failure"] is not None
    assert claim.get("declarations") is None
    assert claim["declaration_raw"] == original_block
    assert "declaration_reframed" not in claim
    notes = _notes(result, "Declaration reframe (response, GPT)")
    assert len(notes) == 1
    assert "also failed to parse" in notes[0]
    # Validator semantics unchanged: the twice-failed claim still
    # earns E6 in the final report — the failure is reported, not
    # repaired.
    section = result.artifact["transjective_record"]
    assert section["conformant"] is False
    assert any(e["code"] == "E6" and e["claim_id"] == claim["id"]
               for e in section["validation"]["errors"])


def test_reframe_with_no_block_is_failure_not_repair(tmp_path):
    gpt = _gpt_response_malformed("I decline to format.")
    fakes = {"GPT": gpt, **_others()}
    result = _run(tmp_path, fakes)
    assert gpt.calls == 3
    assert gpt.reframe_calls == 1
    claim = _claims(result, "GPT", "response")[0]
    assert claim["target_state"] == "unknown"
    assert claim["uncertainty_reason"] == "malformed declaration block"
    assert claim["declaration_parse_failure"] is not None
    assert claim.get("declarations") is None
    notes = _notes(result, "Declaration reframe (response, GPT)")
    assert len(notes) == 1
    assert "returned no declaration block" in notes[0]


def test_budget_exhausted_count_cap_skips_reframe(tmp_path):
    gpt = _gpt_response_malformed(
        "Declarations (declaration-block-v1):\n1: extends C2")
    fakes = {"GPT": gpt, **_others()}
    # 5 openings + 5 responses = 10 attempts: the count cap is hit
    # exactly when the response-phase reframe would be attempted.
    result = run_multi_model_meeting(
        _packet(), store_dir=tmp_path, seats=_seats(fakes),
        budget=Budget(max_contributions=10))
    assert gpt.reframe_calls == 0
    claim = _claims(result, "GPT", "response")[0]
    assert claim["target_state"] == "unknown"
    assert claim["uncertainty_reason"] == "malformed declaration block"
    notes = _notes(result, "Declaration reframe (response, GPT)")
    assert len(notes) == 1
    assert "skipped" in notes[0]


def test_budget_exhausted_admission_refusal_skips_reframe(tmp_path,
                                                          monkeypatch):
    real_eval = meeting_mod.evaluate_admission

    def _refuse_reframes(*, model, prompt, budget, remaining_budget):
        if "could not be parsed" in prompt:
            return GateDecision(
                admitted=False, code="budget",
                reason="test refusal: reframe prompt refused",
                prompt_chars=len(prompt), prompt_tokens=10,
                margin_tokens=0, counted_tokens=10,
                reservation_tokens=10, window=None,
                estimated_cost_usd=None, fleet_ceiling_exceeded=False)
        return real_eval(model=model, prompt=prompt, budget=budget,
                         remaining_budget=remaining_budget)

    monkeypatch.setattr(meeting_mod, "evaluate_admission",
                        _refuse_reframes)
    gpt = _gpt_response_malformed(
        "Declarations (declaration-block-v1):\n1: extends C2")
    fakes = {"GPT": gpt, **_others()}
    result = _run(tmp_path, fakes)
    assert gpt.calls == 2
    assert gpt.reframe_calls == 0
    claim = _claims(result, "GPT", "response")[0]
    assert claim["target_state"] == "unknown"
    assert claim["uncertainty_reason"] == "malformed declaration block"
    notes = _notes(result, "Declaration reframe (response, GPT)")
    assert len(notes) == 1
    assert "skipped" in notes[0]
    assert "gate=budget" in notes[0]


def test_revision_phase_reframe(tmp_path):
    # Claude's response objects to C1, which invites GPT (C1's
    # author) to revision — revision is invitation-only.
    others = _others()
    others["Claude"] = _ReframeFake(
        "Claude",
        opening="1. Inferred: Parallel monologues are a failure mode.",
        response="1. Objection to C1: authorization alone does not "
                 "prevent misrepresentation.\n\n"
                 "Declarations (declaration-block-v1):\n"
                 "1: challenges C1",
        revision="Relationship: defended.\n"
                 "1. Inferred: Parallel monologues remain a risk.",
    )
    gpt = _ReframeFake(
        "GPT",
        opening="1. Inferred: Authority confusion is a failure mode.",
        response="1. Inferred: The registry point stands.\n\n"
                 "Declarations (declaration-block-v1):\n"
                 "1: extends C2",
        revision="Relationship: defended.\n"
                 "In response to C6, I defend my claim:\n"
                 "1. Inferred: Authority confusion remains the top risk.\n\n"
                 "Declarations (declaration-block-v1):\n"
                 "garbage line",
        reframe="Declarations (declaration-block-v1):\n1: defends C1",
    )
    fakes = {"GPT": gpt, **others}
    result = _run(tmp_path, fakes)
    assert gpt.calls == 4
    assert gpt.reframe_calls == 1
    claim = _claims(result, "GPT", "revision")[0]
    assert claim["target_state"] == "populated"
    assert claim["declarations"][0]["kind"] == "defends"
    assert claim["declaration_reframed"] is True
    notes = _notes(result, "Declaration reframe (revision, GPT)")
    assert len(notes) == 1


def test_no_reframe_for_absent_or_invalid_kind_blocks(tmp_path):
    # Muse: prose-only response, no block at all. Claude: block that
    # parses fine but names an out-of-vocabulary kind (E4, authored
    # content — not a structural failure). Neither may trigger.
    fakes = {
        "GPT": _ReframeFake(
            "GPT",
            opening="1. Inferred: Authority confusion is a failure mode.",
            response="1. Inferred: The registry point stands.\n\n"
                     "Declarations (declaration-block-v1):\n"
                     "1: extends C2",
            revision="Relationship: defended.\n"
                     "1. Inferred: Authority confusion remains.",
        ),
        "Claude": _ReframeFake(
            "Claude",
            opening="1. Inferred: Parallel monologues are a failure mode.",
            response="1. Objection to C1: authorization alone does not "
                     "prevent misrepresentation.\n\n"
                     "Declarations (declaration-block-v1):\n"
                     "1: frobs C1",
            revision="Relationship: defended.\n"
                     "1. Inferred: Parallel monologues remain a risk.",
        ),
        "Muse": _ReframeFake(
            "Muse",
            opening="1. Observed: A fourth opening claim.",
            response="1. Inferred: The registry point stands, "
                     "in response to C1.",
            revision="Relationship: defended.\n"
                     "1. Inferred: The point still stands.",
        ),
    }
    # Gemini/Grok absent: their absence notes keep the meeting small.
    result = _run(tmp_path, fakes)
    for fake in fakes.values():
        assert fake.reframe_calls == 0
    assert _notes(result, "Declaration reframe") == []
    claude_response = _claims(result, "Claude", "response")[0]
    assert claude_response["target_state"] == "unknown"
    assert claude_response["declarations"][0]["kind"] == "frobs"
    assert claude_response.get("declaration_parse_failure") is None


def test_wasted_effort_sentence_in_response_and_revision_prompts(tmp_path):
    # Claude's objection invites GPT to revision, so GPT records a
    # revision prompt as well as a response prompt.
    others = _others()
    others["Claude"] = _ReframeFake(
        "Claude",
        opening="1. Inferred: Parallel monologues are a failure mode.",
        response="1. Objection to C1: authorization alone does not "
                 "prevent misrepresentation.\n\n"
                 "Declarations (declaration-block-v1):\n"
                 "1: challenges C1",
        revision="Relationship: defended.\n"
                 "1. Inferred: Parallel monologues remain a risk.",
    )
    gpt = _ReframeFake(
        "GPT",
        opening="1. Inferred: Authority confusion is a failure mode.",
        response="1. Inferred: The registry point stands.\n\n"
                 "Declarations (declaration-block-v1):\n"
                 "1: extends C2",
        revision="Relationship: defended.\n"
                 "1. Inferred: Authority confusion remains.",
    )
    fakes = {"GPT": gpt, **others}
    _run(tmp_path, fakes)
    response_prompts = [p for p in gpt.prompts
                        if "Claim registry" in p
                        and "state the relationship explicitly" not in p]
    revision_prompts = [p for p in gpt.prompts
                        if "state the relationship explicitly" in p]
    assert len(response_prompts) == 1
    assert len(revision_prompts) == 1
    assert WASTED_EFFORT in response_prompts[0]
    assert WASTED_EFFORT in revision_prompts[0]
    opening_prompts = [p for p in gpt.prompts
                       if "Claim registry" not in p
                       and "state the relationship explicitly" not in p]
    assert all(WASTED_EFFORT not in p for p in opening_prompts)


def test_reframe_prompt_is_self_contained():
    failed = ("Declarations (declaration-block-v1):\n"
              "this is not an entry")
    prompt = _reframe_prompt(failed, 2)
    assert "could not be parsed" in prompt
    assert failed in prompt
    assert "Declarations (declaration-block-v1):" in prompt
    for kind in ("extends", "corrects", "challenges", "integrates",
                 "endorses", "repeats", "defends", "requests-evidence"):
        assert kind in prompt
