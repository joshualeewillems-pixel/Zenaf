"""Canonical 7-strand taxonomy and the council persona migration to the 7 agents."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from local_ai import strands
from local_ai.strands import STRANDS, BRAID_ORDER


def test_seven_strands_exactly() -> None:
    assert len(STRANDS) == 7


def test_strand_keys_unique_and_canonical() -> None:
    keys = [s.key for s in STRANDS]
    assert keys == ["word", "number", "image", "sound", "body", "people", "self"]
    assert len(set(keys)) == 7


def test_agent_names_warm_and_unique() -> None:
    names = [s.agent_name for s in STRANDS]
    assert names == ["Storyteller", "Patternist", "Seer", "Songwriter", "Maker", "Mediator", "Guide"]
    assert len(set(names)) == 7


def test_strand_colors_unique_hex() -> None:
    colors = [s.color for s in STRANDS]
    assert len(set(colors)) == 7
    for c in colors:
        assert c.startswith("#") and len(c) == 7


def test_canonical_colors() -> None:
    expected = {
        "word": "#c98f6a",
        "number": "#7aa3b8",
        "image": "#c9a86a",
        "sound": "#b983a8",
        "body": "#9db87a",
        "people": "#a88fc9",
        "self": "#7ba889",
    }
    for key, color in expected.items():
        assert strands.strand_color(key) == color


def test_gardner_labels_present() -> None:
    for s in STRANDS:
        assert s.gardner and s.tagline and s.faculty


def test_braid_order_covers_all_keys() -> None:
    assert sorted(BRAID_ORDER) == sorted(s.key for s in STRANDS)


def test_helpers_round_trip() -> None:
    s = strands.strand("word")
    assert s.agent_name == "Storyteller"
    assert strands.strand_for_agent("Storyteller") is s
    assert strands.strand_for_agent("mediator").key == "people"
    assert strands.agent_names()[0] == "Storyteller"
    assert strands.strand_keys()[3] == "sound"


def test_world_is_not_a_strand() -> None:
    keys = {s.key for s in STRANDS}
    assert "world" not in keys
    assert "environment" not in keys


# --- Council persona migration ---

REQUIRED_PERSONA_FIELDS = {
    "id", "name", "strand", "role", "purpose", "values", "aversions",
    "reasoningStyle", "tone", "domain", "decisionRule", "worldview",
    "constraints", "examplePhrases",
}


def test_council_built_ins_are_the_seven_agents() -> None:
    from local_ai import zenaf_tools as T

    assert T.COUNCIL_ROLE_KEYS == ("seer", "guide", "songwriter", "storyteller", "patternist", "maker", "mediator")
    assert T.COUNCIL_SEAT_DISPLAY_NAMES == (
        "Seer", "Guide", "Songwriter", "Storyteller", "Patternist", "Maker", "Mediator",
    )
    assert len(T.COUNCIL_ROLE_KEYS) == len(T.COUNCIL_SEAT_DISPLAY_NAMES) == 7


def test_each_agent_persona_has_required_fields_and_valid_strand() -> None:
    from local_ai import zenaf_tools as T

    valid_strands = set(strands.strand_keys())
    for key in T.COUNCIL_ROLE_KEYS:
        defn = T._built_in_persona_dict(key)  # noqa: SLF001 - intentional
        missing = REQUIRED_PERSONA_FIELDS - set(defn.keys())
        assert not missing, f"{key} missing fields: {missing}"
        assert defn["strand"] in valid_strands, f"{key} has invalid strand"
        assert defn["name"] == strands.strand(defn["strand"]).agent_name
        assert defn["values"] and defn["aversions"] and defn["constraints"]
        assert defn["decisionRule"]


def test_old_persona_keys_are_gone() -> None:
    from local_ai import zenaf_tools as T

    for old in ("strategist", "operator", "analyst", "governance", "brand"):
        assert old not in T.COUNCIL_ROLE_KEYS
        try:
            T._built_in_persona_dict(old)  # noqa: SLF001 - intentional
        except KeyError:
            pass
        else:
            raise AssertionError(f"old persona key {old!r} still resolvable")


def test_special_actors_untouched() -> None:
    from local_ai import zenaf_tools as T

    assert T._built_in_persona_dict("zenaf")["name"] == "Zenaf"  # noqa: SLF001 - intentional
    assert "thinking_partner" in T.BUILT_IN_PERSONA_DEFINITIONS
