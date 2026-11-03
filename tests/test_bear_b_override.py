"""Bear-B experimental variant override — trial-only, env-gated.

Covers: dormant (env unset or any other value) renders the exact
Bear-A canonical assembly; active (ZENAF_BEAR_VARIANT=bear-b)
substitutes ONLY the Bear character block with the authored rev2
Bear-B core, leaving preserved lines, downstream sections, meeting
turns, and every other seat untouched. No model calls, no
generations, no staging changes: deterministic prompt inspection.

This override exists solely for the separately authorized Bear-B
A/B run (tandem batch, 2026-11-02). Restoration is a revert of the
override commit: after revert, the dormant behavior is the whole
rollback because no canonical function or record is modified.
"""

from __future__ import annotations

import local_ai.council.naming as N
from local_ai.conversation import reply as R
from local_ai.conversation.reply import BEAR_B_CORE, build_voice_prompt


def _bear_lines(monkeypatch):
    monkeypatch.setattr(N, "get_display_name", lambda uid, aid: "Guardian")
    lines, _ = build_voice_prompt("u1", "guardian", "hello", [], mode="base")
    return lines


def test_bear_b_core_is_rev2_text_under_ceiling():
    assert len(BEAR_B_CORE) == 1078
    assert len(BEAR_B_CORE) < 1500
    assert "safety without making departure a betrayal" in BEAR_B_CORE
    assert "welcome is not agreement" in BEAR_B_CORE
    assert "your warmth never makes staying the price of safety" in BEAR_B_CORE


def test_dormant_unset_equals_bear_a(monkeypatch):
    monkeypatch.delenv("ZENAF_BEAR_VARIANT", raising=False)
    dormant = _bear_lines(monkeypatch)
    monkeypatch.setenv("ZENAF_BEAR_VARIANT", "bear-b")
    active = _bear_lines(monkeypatch)
    assert dormant != active
    assert BEAR_B_CORE not in dormant
    assert dormant[0] != BEAR_B_CORE


def test_dormant_other_value_equals_bear_a(monkeypatch):
    monkeypatch.setenv("ZENAF_BEAR_VARIANT", "legacy")
    lines = _bear_lines(monkeypatch)
    assert BEAR_B_CORE not in lines


def test_active_substitutes_character_block_only(monkeypatch):
    monkeypatch.setenv("ZENAF_BEAR_VARIANT", "bear-b")
    lines = _bear_lines(monkeypatch)
    joined = "\n".join(lines)
    # The variant core is the first unit of the prompt.
    assert lines[0] == BEAR_B_CORE
    # Preserved verbatim: shared style rule, strand blend.
    assert R.ANTI_PRESUMPTION_STYLE in lines
    assert any(line.startswith("Strand blend") for line in lines)
    # Downstream sections unchanged.
    assert "Keep replies conversational (2-5 sentences)." in lines
    assert lines[-2] == "User: hello"
    assert lines[-1] == "Guardian:"
    # No jurisdiction lines added.
    assert not any("jurisdiction" in line.lower() for line in lines)
    # The variant core appears exactly once.
    assert joined.count(BEAR_B_CORE) == 1


def test_active_does_not_touch_other_seats_or_meetings(monkeypatch):
    monkeypatch.setattr(N, "get_display_name", lambda uid, aid: "Fox")
    monkeypatch.setenv("ZENAF_BEAR_VARIANT", "bear-b")
    fox_active, _ = build_voice_prompt("u1", "maverick", "hello", [], mode="base")
    monkeypatch.delenv("ZENAF_BEAR_VARIANT", raising=False)
    fox_dormant, _ = build_voice_prompt("u1", "maverick", "hello", [], mode="base")
    assert fox_active == fox_dormant
    assert BEAR_B_CORE not in fox_active
    # Meeting turns keep the exact legacy assembly even when active.
    monkeypatch.setenv("ZENAF_BEAR_VARIANT", "bear-b")
    meeting_active, _ = build_voice_prompt(
        "u1", "guardian", "hello", [], mode="base", canonical=False
    )
    monkeypatch.delenv("ZENAF_BEAR_VARIANT", raising=False)
    meeting_dormant, _ = build_voice_prompt(
        "u1", "guardian", "hello", [], mode="base", canonical=False
    )
    assert meeting_active == meeting_dormant
    assert BEAR_B_CORE not in meeting_active
