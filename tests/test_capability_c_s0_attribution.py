"""Capability C S0 tests: speaker attribution in model-facing history.

The verdict's prerequisite gap: the store records archetype_id per
message, but the turn path stripped it before the model ever saw it,
and the reply builder labeled every voice turn with the CURRENT
seat's display name — so Bear joining a Firebrand conversation would
see Firebrand's turns labeled as Bear's. These tests pin the fix:

  - history_turns carry archetype_id through the service,
  - voice turns are labeled by their ACTUAL speaker's display name
    (the builder's display-name authority: stock role name, e.g.
    "Champion", or the visitor's chosen name — matching the reply
    trailer convention, not the canonical character name),
  - user turns stay "User" (their archetype_id is the addressee seat,
    not the speaker),
  - unattributed / unknown-speaker voice turns get the neutral
    "Voice" label, never the current seat's name,
  - the history window is UNCHANGED (last 10 turns).

No model calls: the reply builder is called directly, and the service
tests use a fake generate_fn. No training data is written (prompt
tests use mode="base").
"""

from __future__ import annotations

import pytest

import local_ai.conversation.reply as reply_mod
from local_ai.conversation.service import ConversationService
from local_ai.conversation.store import ConversationStore


def _fake_generate(prompt: str, **kwargs) -> str:
    return "Fake reply."


def _svc(tmp_path):
    store = ConversationStore(db_path=tmp_path / "conv.db")
    return ConversationService(store, generate_fn=_fake_generate), store


def _history_section(prompt_lines: list[str], final_user_line: str) -> list[str]:
    """Lines between 'Conversation so far:' and the final user message."""
    start = prompt_lines.index("Conversation so far:")
    end = prompt_lines.index(final_user_line)
    return prompt_lines[start + 1 : end]


# -- reply-builder labeling ---------------------------------------------------


def test_bear_turn_sees_firebrand_label_not_bear():
    """The S0 fixture: Firebrand + user turns, Bear turn sees Champion labels."""
    history = [
        {"role": "user", "content": "Staging trial test.", "archetype_id": "champion"},
        {"role": "voice", "content": "That's no hill.", "archetype_id": "champion"},
        {"role": "user", "content": "And one more thing.", "archetype_id": "champion"},
    ]
    prompt, _meta = reply_mod.build_voice_prompt(
        "u1", "guardian", "Hello.", history, mode="base", canonical=True
    )
    section = _history_section(prompt, "User: Hello.")
    assert "User: Staging trial test." in section
    assert "Champion: That's no hill." in section
    assert "User: And one more thing." in section
    # No history line is mislabeled with the current seat's name.
    assert not any(line.startswith("Guardian:") for line in section)


def test_unattributed_voice_turn_gets_neutral_label():
    """Histories built without archetype_id (e.g. the voice route's
    VoiceChatTurn) must not borrow the current seat's name."""
    history = [{"role": "voice", "content": "Mystery words."}]
    prompt, _meta = reply_mod.build_voice_prompt(
        "u1", "guardian", "Hello.", history, mode="base", canonical=True
    )
    section = _history_section(prompt, "User: Hello.")
    assert "Voice: Mystery words." in section
    assert not any(line.startswith("Guardian:") for line in section)


def test_unknown_archetype_voice_turn_gets_neutral_label():
    history = [{"role": "voice", "content": "Mystery words.", "archetype_id": "nope"}]
    prompt, _meta = reply_mod.build_voice_prompt(
        "u1", "guardian", "Hello.", history, mode="base", canonical=True
    )
    section = _history_section(prompt, "User: Hello.")
    assert "Voice: Mystery words." in section


def test_user_turn_archetype_is_addressee_not_speaker():
    """A user turn's archetype_id names the sheet it was said in, not
    its speaker — so it stays 'User' even with a seat id attached."""
    history = [
        {"role": "user", "content": "Said in the champion sheet.", "archetype_id": "champion"},
    ]
    prompt, _meta = reply_mod.build_voice_prompt(
        "u1", "guardian", "Hello.", history, mode="base", canonical=True
    )
    section = _history_section(prompt, "User: Hello.")
    assert "User: Said in the champion sheet." in section
    assert not any(line.startswith("Champion:") for line in section)


# -- service path: attribution survives the turn loop, window unchanged -------


def test_service_labels_prior_seat_by_actual_speaker(tmp_path):
    """End to end through the service: a mentor turn's prompt labels a
    prior maverick voice turn 'Maverick:', not 'Mentor:'."""
    prompts: list[str] = []

    def _capture(prompt: str, **kwargs) -> str:
        prompts.append(prompt)
        return "Fake reply."

    store = ConversationStore(db_path=tmp_path / "conv.db")
    svc = ConversationService(store, generate_fn=_capture)
    svc.turn("u1", "mentor", "m1")
    svc.turn("u1", "maverick", "v1")
    svc.turn("u1", "mentor", "m2")
    last = prompts[-1].split("\n")
    section = _history_section(last, "User: m2")
    assert "User: m1" in section
    assert "Mentor: Fake reply." in section
    assert "User: v1" in section
    # The decisive line: maverick's prior turn, labeled by its speaker.
    assert "Maverick: Fake reply." in section
    store.close()


def test_service_history_window_still_ten(tmp_path):
    """S0 changes attribution, not volume: the 7th turn's prompt still
    carries exactly the last 10 prior turns."""
    prompts: list[str] = []

    def _capture(prompt: str, **kwargs) -> str:
        prompts.append(prompt)
        return "Fake reply."

    store = ConversationStore(db_path=tmp_path / "conv.db")
    svc = ConversationService(store, generate_fn=_capture)
    for i in range(7):
        svc.turn("u1", "mentor", f"turn {i}")
    last = prompts[-1].split("\n")
    section = _history_section(last, "User: turn 6")
    assert len(section) == 10
    store.close()
