"""FC4 action-honesty mechanism tests (Firebrand, 2026-11-07).

The full form (founder tap "Full — confirm first", 2026-11-07 ~16:35 PT):
"Done" / "locked" / "scheduled" only after a persistence
confirmation. The confirmation is a fact about the meeting (kind /
id / label / status / turn) carried in ``EncounterState.confirmed_writes``
and rendered into the generation prompt as system fact by
``_confirmation_suffix`` — appended LAST at the four conversational
generation sites by ``_with_confirmations``.

Until FC5/FC6 land, no confirmation is ever produced: the filing
hook ``_file_accepted_offer`` is a no-op (its contract — returns
``None``, touches no state — is pinned here, design §7.7), the suffix
never renders, and the guidance prohibition governs every turn.

No model calls, no generations, no staging changes anywhere here:
every test is deterministic prompt inspection.
"""

from __future__ import annotations

import json

from local_ai.conversation.encounter import (
    EncounterRuntime,
    EncounterState,
    build_champion_k1_definition,
)
from local_ai.council import meetings as MT


class _StubHost:
    """Minimal host: the hook under test never calls it."""

    def generate(self, frame: str) -> str:  # pragma: no cover - unused
        raise AssertionError("no generation in these tests")

    def say(self, text: str) -> None:  # pragma: no cover - unused
        raise AssertionError("no speech in these tests")

    def store_impression(self, claim: str, strands) -> None:  # pragma: no cover
        raise AssertionError("no filing in these tests")


def _runtime() -> EncounterRuntime:
    return EncounterRuntime(
        build_champion_k1_definition(MT.CHAMPION_FIRST_MEETING)
    )


def test_p1_empty_state_empty_suffix():
    """Empty state renders no suffix — the common case, including
    every turn before FC5/FC6 land."""
    assert EncounterRuntime._confirmation_suffix(EncounterState()) == ""


def test_p2_commitment_confirmation_renders():
    """A recorded commitment licenses 'done', by id and label."""
    state = EncounterState(
        confirmed_writes=[
            {
                "kind": "commitment",
                "id": "c-1",
                "label": "non-complicity at home",
                "status": "recorded",
                "turn": 9,
            }
        ]
    )
    suffix = EncounterRuntime._confirmation_suffix(state)
    assert "c-1" in suffix
    assert "non-complicity at home" in suffix
    assert "You may say it is done" in suffix


def test_p3_proposal_confirmation_never_licenses_done():
    """A filed-awaiting-approval proposal licenses 'filed' only —
    never 'done'."""
    state = EncounterState(
        confirmed_writes=[
            {
                "kind": "proposal",
                "id": "p-1",
                "label": "Confirm dentist slot",
                "status": "filed-awaiting-approval",
                "turn": 12,
            }
        ]
    )
    suffix = EncounterRuntime._confirmation_suffix(state)
    assert "filed and waiting for the visitor's approval" in suffix
    assert "never that it is done" in suffix
    assert "You may say it is done" not in suffix


def test_p4_reminder_confirmation_renders_cadence():
    """A recorded reminder carries its cadence and licenses
    'scheduled'."""
    state = EncounterState(
        confirmed_writes=[
            {
                "kind": "reminder",
                "id": "r-1",
                "label": "non-complicity check-in",
                "status": "recorded",
                "turn": 11,
                "cadence": "daily at 4pm",
            }
        ]
    )
    suffix = EncounterRuntime._confirmation_suffix(state)
    assert "daily at 4pm" in suffix
    assert "You may say it is scheduled" in suffix


def test_p5_state_round_trip():
    """confirmed_writes survives to_json() -> from_json()
    byte-identically (field + both methods)."""
    writes = [
        {
            "kind": "commitment",
            "id": "c-1",
            "label": "non-complicity at home",
            "status": "recorded",
            "turn": 9,
        },
        {
            "kind": "reminder",
            "id": "r-1",
            "label": "non-complicity check-in",
            "status": "recorded",
            "turn": 11,
            "cadence": "daily at 4pm",
        },
    ]
    state = EncounterState(confirmed_writes=list(writes))
    restored = EncounterState.from_json(state.to_json())
    assert restored.confirmed_writes == writes
    # And a state predating the field hydrates to the empty default.
    assert EncounterState.from_json({}).confirmed_writes == []


def test_p6_frames_carry_the_suffix_only_when_confirmations_exist():
    """The suffix is appended at the generation sites by
    _with_confirmations — the frame builders themselves never bake
    it in. With confirmations, the composed frames carry it; with
    an empty state, _with_confirmations returns the frame unchanged
    and neither frame licenses 'done'."""
    runtime = _runtime()
    confirmed = EncounterState(
        confirmed_writes=[
            {
                "kind": "commitment",
                "id": "c-1",
                "label": "non-complicity at home",
                "status": "recorded",
                "turn": 9,
            }
        ]
    )
    turn_frame, _cue = runtime._turn_frame(
        confirmed, "What is worth fighting for?"
    )
    engage_frame = runtime._engage_frame()
    # The raw frames never carry the suffix (not baked in).
    assert "You may say it is done" not in turn_frame
    assert "You may say it is done" not in engage_frame
    # The frames as they reach generation do.
    assert (
        "You may say it is done"
        in runtime._with_confirmations(confirmed, turn_frame)
    )
    assert (
        "You may say it is done"
        in runtime._with_confirmations(confirmed, engage_frame)
    )
    empty = EncounterState()
    assert runtime._with_confirmations(empty, turn_frame) == turn_frame
    assert runtime._with_confirmations(empty, engage_frame) == engage_frame
    assert "You may say it is done" not in turn_frame
    assert "You may say it is done" not in engage_frame


def test_p7_filing_hook_is_a_noop_until_fc5():
    """Design §7.7: the hook returns None and touches no state.
    FC5 replaces this body with acceptance detection, store choice,
    and approval semantics; until then the hook must not invent a
    confirmation."""
    runtime = _runtime()
    state = EncounterState()
    assert runtime._file_accepted_offer(_StubHost(), state, "Yes, lock it in") is None
    assert state.confirmed_writes == []
    assert json.loads(state.to_json())["confirmed_writes"] == []
