"""Mechanical checks: flow-reading hypotheses → developmental packet → enriched council (non-scoped)."""
from __future__ import annotations

import pytest

from local_ai.council_preflight import CouncilPreflight, build_enriched_council_context
from local_ai.developmental_guidance import _PACKET_MAX_CHARS, format_developmental_guidance_packet_block

# Keep aligned with frontend/src/developmentalGuidance/buildDevelopmentalGuidanceContext.ts
_HUMAN_POS_STATEMENT = (
    "One possible read (uncertain): recent acknowledged execution on this focus may be building capacity."
)
_HUMAN_NEG_STATEMENT = (
    "One possible read (uncertain): repeated checkpoint-backed reads suggest strain on clarity, capacity, or "
    "friction — worth a light touch, not a verdict."
)
_COUNCIL_POS_STATEMENT = (
    "One possible read (uncertain): recent execution-flow signals on this focus leaned positive — momentum may "
    "be present (tentative)."
)


def _minimal_flow_guidance_payload(*, hypotheses: list[dict], evidence_excerpt: str = "x") -> dict:
    return {
        "as_of": "2026-04-03T12:00:00Z",
        "evidence_refs": [
            {
                "source_type": "execution_flow_reading",
                "source_id_or_key": "j1",
                "excerpt_or_hash": evidence_excerpt,
            }
        ],
        "signals_summary": {"council_runs_in_window": 0, "execution_flow_readings_supplied": 2},
        "hypotheses": hypotheses,
        "suggested_guidance_style": "neutral",
    }


def test_packet_includes_human_positive_hypothesis_before_evidence_and_within_cap():
    raw = _minimal_flow_guidance_payload(
        hypotheses=[
            {
                "kind": "strength",
                "confidence": "low",
                "basis": ["execution_flow_reading", "positive_cluster", "human_checkpoint"],
                "statement": _HUMAN_POS_STATEMENT,
            }
        ],
    )
    block = format_developmental_guidance_packet_block(raw)
    assert block
    assert len(block) <= _PACKET_MAX_CHARS
    assert "Hypotheses:" in block
    assert "Evidence pointers" in block
    assert block.index("Hypotheses:") < block.index("Evidence pointers")
    assert "recent acknowledged execution on this focus may be building capacity" in block


def test_packet_includes_human_negative_hypothesis_before_truncation():
    raw = _minimal_flow_guidance_payload(
        hypotheses=[
            {
                "kind": "friction",
                "confidence": "low",
                "basis": ["execution_flow_reading", "negative_cluster", "human_checkpoint"],
                "statement": _HUMAN_NEG_STATEMENT,
            }
        ],
    )
    block = format_developmental_guidance_packet_block(raw)
    assert block
    assert len(block) <= _PACKET_MAX_CHARS
    assert "repeated checkpoint-backed reads suggest strain" in block


def test_packet_council_positive_hypothesis_survives():
    raw = _minimal_flow_guidance_payload(
        hypotheses=[
            {
                "kind": "strength",
                "confidence": "low",
                "basis": ["execution_flow_reading", "positive_cluster", "council_or_mixed"],
                "statement": _COUNCIL_POS_STATEMENT,
            }
        ],
    )
    block = format_developmental_guidance_packet_block(raw)
    assert block
    assert "momentum may be present" in block


def test_build_enriched_includes_developmental_when_not_scoped():
    raw = _minimal_flow_guidance_payload(
        hypotheses=[
            {
                "kind": "strength",
                "confidence": "low",
                "basis": ["execution_flow_reading", "positive_cluster", "human_checkpoint"],
                "statement": _HUMAN_POS_STATEMENT,
            }
        ],
    )
    p = CouncilPreflight(
        user_question="What should we consider next?",
        active_surface="vision_map",
        developmental_guidance=raw,
        scoped_digression=False,
    )
    enriched = build_enriched_council_context(
        p, legacy_context_str=None, subject_ref=None, object_snapshot=None
    )
    assert "DEVELOPMENTAL GUIDANCE (hypotheses — uncertain, not diagnostic):" in enriched
    assert "recent acknowledged execution on this focus may be building capacity" in enriched


def test_build_enriched_omits_developmental_when_scoped():
    raw = _minimal_flow_guidance_payload(
        hypotheses=[
            {
                "kind": "strength",
                "confidence": "low",
                "basis": ["execution_flow_reading", "positive_cluster", "human_checkpoint"],
                "statement": _HUMAN_POS_STATEMENT,
            }
        ],
    )
    p = CouncilPreflight(
        user_question="q",
        active_surface="vision_map",
        developmental_guidance=raw,
        scoped_digression=True,
        ve_focus={"entity_type": "project", "entity_id": "p1"},
    )
    enriched = build_enriched_council_context(
        p, legacy_context_str=None, subject_ref=None, object_snapshot=None
    )
    assert "DEVELOPMENTAL GUIDANCE (hypotheses — uncertain, not diagnostic):" not in enriched
