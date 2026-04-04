"""Unit tests for meeting proposition discipline (no LLM)."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from local_ai.vision_execution.meeting_extract import preclean_transcript  # noqa: E402
from local_ai.vision_execution.meeting_proposition import (  # noqa: E402
    build_anchor_hints_block,
    infer_anchor_role,
    normalize_speaker_timestamp_lines,
    strip_transcript_header,
    title_is_propositional,
)


def test_title_rejects_literals():
    assert not title_is_propositional("Jane")
    assert not title_is_propositional("BEST")
    assert not title_is_propositional("Speaker A")
    assert not title_is_propositional("yeah okay")
    assert title_is_propositional("Rebuild Healing Haven website into a conversion-focused guided flow")
    assert title_is_propositional("Create dual funnels for Medi-Cal and paying clients")


def test_infer_anchor_role_buckets():
    assert infer_anchor_role("Integrate Jane with the clinic dashboard") == "system_tool"
    assert infer_anchor_role("Post Craigslist ads and cold outreach") == "marketing_acquisition"
    assert infer_anchor_role("Living from the heart philosophy on the platform") == "product_philosophy"
    assert infer_anchor_role("Clinic staffing and 50/50 collaboration model") == "operations"


def test_strip_header_and_speaker_lines():
    raw = """Transcript of Foo
Created on March 1 by Summary AI
https://example.com/x
---

Speaker A (00:00)

Hello this is substantive content about the website rebuild.
"""
    h = strip_transcript_header(raw)
    assert "Transcript of" not in h
    assert "https://example.com" not in h
    n = normalize_speaker_timestamp_lines(h)
    assert "Speaker A (00:00)" not in n
    assert "website rebuild" in n.lower()


def test_preclean_combined():
    t = preclean_transcript(
        "Transcript of X\n\n---\n\nSpeaker A (00:01)\n\nWe need to rebuild the landing page.\n"
    )
    assert "Transcript of" not in t
    assert "Speaker A (00:01)" not in t
    assert "rebuild" in t.lower()


def test_anchor_hints_nonempty_for_meeting_style_text():
    blob = """
    Speaker A (00:00)
    The Jane integration and clinic dashboard need work.
    We discussed WordPress and the website conversion flow several times.
    """ * 3
    block = build_anchor_hints_block(blob)
    assert "jane" in block.lower() or "dashboard" in block.lower()
    assert "[" in block and "]" in block
