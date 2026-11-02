"""Step 2 (2026-11-02) regression: the ordinary-chat weave instruction is
gone, the canonical renderers are intact, and the meeting path is
unchanged (legacy assembly, no instruction).

Deterministic: prompt assembly only, no model calls. Covers all seven
seats on both paths, so a future re-coupling of the canonical flag to
any prompt instruction fails here first.
"""

import pytest

from local_ai.conversation.reply import build_voice_prompt

KEEP_REPLIES = "Keep replies conversational (2-5 sentences)."

SEATS = [
    # (archetype_id, stock display name, canonical identity line)
    ("conductor", "Weaver", "You are the Weaver, who occupies the Conductor seat"),
    ("skeptic", "Raven", "You are the Raven, who occupies the Skeptic seat"),
    ("mentor", "Gardener", "You are the Gardener, who occupies the Mentor seat"),
    ("champion", "Firebrand", "You are the Firebrand, who occupies the Champion seat"),
    ("guardian", "Bear", "You are the Bear, who occupies the Guardian seat"),
    ("ambassador", "Crane", "You are the Crane, who occupies the Ambassador seat"),
    ("maverick", "Fox", "You are the Fox, who occupies the Maverick seat"),
]


def _stock_name(monkeypatch, name):
    import local_ai.council.naming as N

    monkeypatch.setattr(N, "get_display_name", lambda uid, aid: name)


def _has_weave_instruction(lines):
    return any("[[u]]" in l or "wrap those exact words" in l for l in lines)


@pytest.mark.parametrize("arch_id,display,canonical_marker", SEATS)
def test_ordinary_prompt_canonical_no_weave_instruction(
    monkeypatch, arch_id, display, canonical_marker
):
    _stock_name(monkeypatch, display)
    lines, _ = build_voice_prompt("u1", arch_id, "hello", [], mode="base")
    joined = "\n".join(lines)
    # (a) no weave instruction text anywhere on the ordinary path.
    assert not _has_weave_instruction(lines)
    # (b) the seat's canonical block is present.
    assert canonical_marker in joined
    # (c) the response-length guidance is unchanged.
    assert KEEP_REPLIES in lines


@pytest.mark.parametrize("arch_id,display,canonical_marker", SEATS)
def test_meeting_prompt_legacy_no_weave_instruction(
    monkeypatch, arch_id, display, canonical_marker
):
    _stock_name(monkeypatch, display)
    lines, _ = build_voice_prompt(
        "u1", arch_id, "hello", [], mode="base", canonical=False
    )
    joined = "\n".join(lines)
    # No weave instruction text on the meeting path either.
    assert not _has_weave_instruction(lines)
    # Legacy assembly: canonical block absent, legacy opener present.
    assert canonical_marker not in joined
    assert lines[0].startswith(
        f"You are {display}, a voice in the user's Zenaf council"
    )
    # Length guidance unchanged on the meeting path too.
    assert KEEP_REPLIES in lines
