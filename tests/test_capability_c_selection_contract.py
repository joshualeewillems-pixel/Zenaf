"""Capability C S2 tests: exchange-level selection contract.

These tests validate the CONTRACT with INJECTED judge outputs
(simulated dicts, never a model call). They deliberately do NOT claim
that a production judge would make any particular selection — that
claim requires the separately-authorized live selection test (the S3
gate). What is pinned here:

  - 0, 1, or 2 invitations validate; over-cap FAILS CLOSED entirely
    (never truncated to two);
  - malformed output, duplicate seats, unknown seats, the responding
    seat selecting itself, and selections outside the candidate set
    all fail closed with zero invitations;
  - every reason is short and every selection carries an evidence
    quote that appears VERBATIM in the cited part of the exchange
    (paraphrase is unsupported by contract);
  - a legitimate zero is valid and ordinary.

No model calls, no store reads, no observation-pipeline imports: the
contract module imports only archetype data.
"""

from __future__ import annotations

import pytest

from local_ai.fellowship.selection import (
    REASON_MAX_CHARS,
    CandidateSeat,
    CompletedExchange,
    validate_selection,
)

# The systems-check exchange, verbatim where the record is verbatim:
# the user message is the fixture's test message; the assistant reply
# is the Firebrand reply recorded from the Slice A trial exchange (the
# fixture itself paraphrases it as "dismissing it as beneath a real
# challenge" — the contract test needs verbatim text for the quote
# rule, so it uses the recorded reply).
FIXTURE_USER = "Staging trial test — checking that this conversation persists. Please ignore."
FIXTURE_REPLY = (
    "That's no hill. I won't spend blood on a systems check. "
    "Bring me something real and I'll name the price with you."
)


def _fixture_exchange() -> CompletedExchange:
    return CompletedExchange(
        user_message=FIXTURE_USER,
        responding_seat="champion",
        assistant_reply=FIXTURE_REPLY,
        context=(
            {
                "role": "user",
                "speaker": None,
                "text": "Earlier I mentioned the weekly check.",
            },
        ),
        candidate_seats=(
            CandidateSeat("conductor", "systems integration and experimentation"),
            CandidateSeat("guardian", "unmet practical needs, floors, harm"),
            CandidateSeat("maverick", "reframing and possibility"),
            CandidateSeat("skeptic", "examination and challenge"),
        ),
    )


def _sel(seat, reason, part, quote, **extra):
    out = {"seat": seat, "reason": reason, "evidence": {"part": part, "quote": quote}}
    out.update(extra)
    return out


def _weaver_sel():
    return _sel(
        "conductor",
        "The check itself is a systems-integration experiment worth noticing.",
        "user_message",
        "checking that this conversation persists",
    )


def _bear_sel():
    return _sel(
        "guardian",
        "The dismissal may leave a useful need unmet; offer a hand.",
        "assistant_reply",
        "I won't spend blood on a systems check",
    )


# -- valid outcomes --------------------------------------------------------------


def test_zero_is_valid_and_ordinary():
    result = validate_selection(_fixture_exchange(), {"selections": []})
    assert result.valid is True
    assert result.invitations == ()
    assert result.violations == ()


def test_valid_one_and_two():
    one = validate_selection(_fixture_exchange(), {"selections": [_weaver_sel()]})
    assert one.valid is True
    assert [i.seat for i in one.invitations] == ["conductor"]
    two = validate_selection(
        _fixture_exchange(), {"selections": [_weaver_sel(), _bear_sel()]}
    )
    assert two.valid is True
    assert [i.seat for i in two.invitations] == ["conductor", "guardian"]
    assert two.invitations[0].evidence_quote == "checking that this conversation persists"


def test_no_candidate_restriction_when_absent():
    exchange = CompletedExchange(
        user_message="hello", responding_seat="champion", assistant_reply="hi there"
    )
    result = validate_selection(
        exchange,
        {"selections": [_sel("guardian", "a reason", "assistant_reply", "hi there")]},
    )
    assert result.valid is True


def test_extra_keys_are_ignored_not_violations():
    """Forward-compat: malformed means structurally unusable, not
    merely unfamiliar. Extra keys do not fail the output."""
    out = {"selections": [_weaver_sel()], "judge_version": "later"}
    result = validate_selection(_fixture_exchange(), out)
    assert result.valid is True
    assert len(result.invitations) == 1


# -- fail-closed: shape -----------------------------------------------------------


@pytest.mark.parametrize(
    "raw",
    [
        None,
        "nope",
        42,
        {},
        {"selections": "conductor"},
        {"selections": None},
        {"selections": [None]},
        {"selections": [{"seat": "conductor"}]},
        {"selections": [{"seat": "conductor", "reason": "r"}]},
        {"selections": [{"seat": "conductor", "reason": "r", "evidence": None}]},
    ],
)
def test_malformed_outputs_fail_closed(raw):
    result = validate_selection(_fixture_exchange(), raw)
    assert result.valid is False
    assert result.invitations == ()
    assert len(result.violations) >= 1


def test_duplicate_seats_fail_closed():
    result = validate_selection(
        _fixture_exchange(), {"selections": [_weaver_sel(), _weaver_sel()]}
    )
    assert result.valid is False
    assert result.invitations == ()
    assert any("duplicates" in v for v in result.violations)


def test_over_cap_fails_closed_without_truncation():
    third = _sel(
        "maverick", "Reframe the check as test data.", "user_message", "trial test"
    )
    result = validate_selection(
        _fixture_exchange(),
        {"selections": [_weaver_sel(), _bear_sel(), third]},
    )
    assert result.valid is False
    # Not truncated to two: a violated output yields NO invitations.
    assert result.invitations == ()


def test_unknown_self_and_non_candidate_seats_fail():
    unknown = validate_selection(
        _fixture_exchange(),
        {"selections": [_sel("nope", "r", "user_message", "trial test")]},
    )
    assert unknown.valid is False and unknown.invitations == ()
    self_sel = validate_selection(
        _fixture_exchange(),
        {"selections": [_sel("champion", "r", "user_message", "trial test")]},
    )
    assert self_sel.valid is False and self_sel.invitations == ()
    # Maverick IS a candidate in the fixture exchange, so restrict the
    # candidate set to prove the non-candidate rule separately.
    narrow = CompletedExchange(
        user_message=FIXTURE_USER,
        responding_seat="champion",
        assistant_reply=FIXTURE_REPLY,
        candidate_seats=(CandidateSeat("conductor", "integration"),),
    )
    non_candidate = validate_selection(
        narrow,
        {"selections": [_sel("guardian", "r", "user_message", "trial test")]},
    )
    assert non_candidate.valid is False and non_candidate.invitations == ()


# -- fail-closed: reason + evidence ------------------------------------------------


def test_reason_rules():
    base = _fixture_exchange()
    empty = validate_selection(
        base, {"selections": [_sel("conductor", "   ", "user_message", "trial test")]}
    )
    assert empty.valid is False and empty.invitations == ()
    long_reason = "x" * (REASON_MAX_CHARS + 1)
    too_long = validate_selection(
        base,
        {"selections": [_sel("conductor", long_reason, "user_message", "trial test")]},
    )
    assert too_long.valid is False and too_long.invitations == ()
    at_cap = validate_selection(
        base,
        {"selections": [_sel("conductor", "x" * REASON_MAX_CHARS, "user_message", "trial test")]},
    )
    assert at_cap.valid is True


def test_evidence_grounding():
    base = _fixture_exchange()
    paraphrase = validate_selection(
        base,
        {"selections": [_sel("conductor", "r", "user_message", "testing if chats last")]},
    )
    assert paraphrase.valid is False and paraphrase.invitations == ()
    empty_quote = validate_selection(
        base, {"selections": [_sel("conductor", "r", "user_message", "  ")]}
    )
    assert empty_quote.valid is False
    unknown_part = validate_selection(
        base, {"selections": [_sel("conductor", "r", "elsewhere", "trial test")]}
    )
    assert unknown_part.valid is False
    # A quote from ONE context entry grounds; a quote assembled across
    # two entries does not (verbatim means verbatim, in one place).
    ctx_ok = validate_selection(
        base, {"selections": [_sel("conductor", "r", "context", "weekly check")]}
    )
    assert ctx_ok.valid is True
    spanning = validate_selection(
        base,
        {
            "selections": [
                _sel(
                    "conductor",
                    "r",
                    "context",
                    "weekly check. Staging trial test",
                )
            ]
        },
    )
    assert spanning.valid is False and spanning.invitations == ()


def test_degenerate_exchange_fails_closed():
    bad = CompletedExchange(
        user_message="  ", responding_seat="champion", assistant_reply="hi"
    )
    result = validate_selection(bad, {"selections": []})
    assert result.valid is False and result.invitations == ()


# -- fixture exchange, contract only ------------------------------------------------


def test_fixture_exchange_contract_with_injected_outputs():
    """CONTRACT test only, with INJECTED judge outputs. It proves the
    validator accepts a well-formed Weaver+Bear selection for the
    fixture exchange and fails closed on the standard violations. It
    does NOT claim a production judge would make this selection —
    that claim belongs to the separately-authorized live selection
    test (the S3 gate), and nothing here runs a model."""
    exchange = _fixture_exchange()
    good = validate_selection(
        exchange, {"selections": [_weaver_sel(), _bear_sel()]}
    )
    assert good.valid is True
    assert [i.seat for i in good.invitations] == ["conductor", "guardian"]
    fox = _sel("maverick", "Reframe the check.", "user_message", "trial test")
    raven = _sel("skeptic", "Probe the dismissal.", "assistant_reply", "no hill")
    over_cap = validate_selection(
        exchange,
        {"selections": [_weaver_sel(), _bear_sel(), fox, raven]},
    )
    assert over_cap.valid is False and over_cap.invitations == ()
    dup = validate_selection(
        exchange, {"selections": [_bear_sel(), _bear_sel()]}
    )
    assert dup.valid is False and dup.invitations == ()
    unsupported = validate_selection(
        exchange,
        {"selections": [_sel("guardian", "r", "assistant_reply", "the user is hungry")]},
    )
    assert unsupported.valid is False and unsupported.invitations == ()
