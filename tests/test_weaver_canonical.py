"""Weaver-only canonical implementation (plan §4 tests).

Covers: record integrity, the two-check eligibility matrix, renderer
order/budgets/exclusions/naming/capability gating, the reply.py
replacement branch (gate ON vs gate OFF, six-seat golden comparisons,
meeting-path preservation), encounter-material eligibility, and the
capability-resolver contract.

No model calls, no generations, no staging changes anywhere here:
every test is deterministic prompt inspection.

Scope notes (read before "fixing" a failure by weakening a test):

- The legacy ``philosophy_prompt_lines`` function is INTENTIONALLY
  untouched (frozen rollback source, amended plan §2 item 4). Its
  output still contains shadow/tension lines; the canonical branch
  bypasses it for ordinary Weaver turns instead of modifying it.
  There is deliberately NO test asserting it returns ideal+question
  only — that plan-§4 line is stale, superseded by the amendment.
- Meeting turns (weave=False) keep the exact legacy assembly,
  including its philosophy lines. The encounter-eligibility test pins
  the encounter's OWN material (scripts + frames), which carries no
  protected content; the shared builder's legacy block on meeting
  turns is out of scope for this plan and is preserved byte-identical
  by the weave gate. A future encounter migration (not this plan)
  would address the meeting-turn character block.
"""

from __future__ import annotations

import copy
import dataclasses

import pytest

from local_ai.conversation import reply as R
from local_ai.conversation.reply import build_voice_prompt
from local_ai.council import capabilities as CAP
from local_ai.council import steward_records as SR
from local_ai.council.archetypes import (
    ANTI_PRESUMPTION_STYLE,
    build_archetype_prompt_lines,
)
from local_ai.council.canonical.weaver import WEAVER_RECORD
from local_ai.council.jurisdictions import jurisdiction_prompt_lines
from local_ai.council.render import (
    CHARACTER_CEILING,
    AssemblyError,
    eligible_field,
    eligible_fields,
    render_weaver_ordinary,
)

# Distinctive protected formulations. Deliberately specific phrases,
# not generic words ("shadow" alone would false-positive on innocent
# prose): these are the formulations that must never reach a prompt.
PROTECTED_PHRASES = (
    "overintegration",
    "forcing resolution",
    "smoothing away the differences",
    "characteristic failure mode",
    "Subordinating the ensemble",
    "WANTS resolution",
    "resist solving people as puzzles",
    "not everything should fit",
    "weaver_crane_001",
    "Finding a meaningful place within an arrangement",
    "Having a place in an arrangement does not",
)

PHILOSOPHER_NAMES = ("Jung", "Wilber")

LEGACY_MARKERS = (
    "Foundational ideal:",
    "Defining question (your instinctive first move",
    "Shadow — your characteristic failure mode",
    "Live tension with the other seats:",
)

CANONICAL_MARKER = "You are the Weaver, who occupies the Conductor seat"

NO_TRAINING_NOTE = (
    "Note: this user has no published training data for your faculties yet — "
    "you are the aspirational base voice. Be honest about that if it matters; "
    "never invent training they don't have."
)
KEEP_REPLIES = "Keep replies conversational (2-5 sentences)."


def _joined(lines) -> str:
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Record integrity
# ---------------------------------------------------------------------------


def _walk_fields(record):
    """Yield (section, key, field-dict) for every field-like entry."""
    for section, fields in record.items():
        if section == "seat_id" or not isinstance(fields, dict):
            continue
        for key, field in fields.items():
            if isinstance(field, dict) and "standing" in field:
                yield section, key, field


def test_record_sections_and_keys_match_exemplar():
    assert WEAVER_RECORD["seat_id"] == "conductor"
    assert set(WEAVER_RECORD) == {
        "seat_id", "identity", "philosophy", "characterization",
        "jurisdiction", "relationships", "narrative", "capabilities",
        "protected",
    }
    assert set(WEAVER_RECORD["identity"]) == {
        "role", "character", "personal_name", "visual_identity",
    }
    assert set(WEAVER_RECORD["philosophy"]) == {
        "core_conviction", "defining_question", "primary_influences",
        "distilled_contribution", "per_thinker_contributions",
        "secondary_influences", "opposing_influences",
        "enduring_disagreements",
    }
    assert set(WEAVER_RECORD["characterization"]) == {
        "temperament", "personality", "demeanor", "metaphorical_world",
        "domain_tension", "governing_conviction", "voice_and_humor",
        "implied_history", "established_biography", "creative_references",
        "invariants", "expressive_defaults",
    }
    assert set(WEAVER_RECORD["jurisdiction"]) == {
        "primary_concerns", "adjacent_concerns", "boundaries", "relationships",
    }
    assert set(WEAVER_RECORD["relationships"]) == {"weaver_crane_001"}
    assert set(WEAVER_RECORD["narrative"]) == {
        "first_encounter", "encounter_conduct", "recognition", "correction",
        "revealed_identity", "orientation", "later_discoveries",
        "six_seat_unlock",
    }
    assert set(WEAVER_RECORD["capabilities"]) == {
        "first_meetings", "seat_chat", "fellowship_attention", "tree_view",
        "convened_council", "marketplace_info", "artifact_provenance",
    }
    assert set(WEAVER_RECORD["protected"]) == {
        "developmental_knowledge", "shadow", "blind_spot",
    }


def test_record_fields_carry_standing_and_category():
    for section, key, field in _walk_fields(WEAVER_RECORD):
        assert field["standing"] in {
            "adopted", "provisional", "open", "unselected",
        }, (section, key)
        assert field["category"] in {
            "identity", "conviction", "characterization", "protected",
            "relational", "provenance", "jurisdiction", "capability",
            "narrative",
        }, (section, key)


def test_record_core_values_verbatim():
    assert WEAVER_RECORD["philosophy"]["defining_question"]["text"] == (
        "How can these parts become a whole?"
    )
    assert WEAVER_RECORD["philosophy"]["core_conviction"]["text"] == (
        "Coherence through orchestration that preserves difference."
    )
    assert WEAVER_RECORD["identity"]["role"]["text"] == "Conductor"
    assert WEAVER_RECORD["identity"]["character"]["text"] == "Weaver"
    assert WEAVER_RECORD["identity"]["personal_name"]["default"] == "unselected"
    assert WEAVER_RECORD["identity"]["visual_identity"]["text"] == "Octopus"
    # Protected section present, with the adopted shadow formulation.
    assert "overintegration" in WEAVER_RECORD["protected"]["shadow"]["text"]
    assert WEAVER_RECORD["protected"]["shadow"]["standing"] == "adopted"
    # Blind spot: protected, unspecified — no invented content.
    assert WEAVER_RECORD["protected"]["blind_spot"]["text"] is None
    # Per-thinker contributions: open, not invented.
    assert WEAVER_RECORD["philosophy"]["per_thinker_contributions"]["text"] is None
    # Capability ids match the registry exactly (no invented ids).
    assert set(WEAVER_RECORD["capabilities"]) == {
        c.id for c in CAP.seat_slice("conductor")
    }


def test_rendering_never_mutates_record():
    before = copy.deepcopy(WEAVER_RECORD)
    render_weaver_ordinary(WEAVER_RECORD, detail="compact")
    render_weaver_ordinary(
        WEAVER_RECORD, {"personal_name": "Allegra"}, detail="fuller",
        resolved_capability="Background knowledge — Tree view.",
    )
    assert WEAVER_RECORD == before


# ---------------------------------------------------------------------------
# Eligibility matrix (two independent checks)
# ---------------------------------------------------------------------------


def test_eligibility_matrix():
    eligible = set(eligible_fields(WEAVER_RECORD))
    # Adopted + conviction → rendered.
    assert ("philosophy", "core_conviction") in eligible
    assert ("philosophy", "defining_question") in eligible
    assert ("characterization", "domain_tension") in eligible
    assert ("characterization", "governing_conviction") in eligible
    # Adopted + characterization → rendered.
    assert ("characterization", "temperament") in eligible
    assert ("characterization", "demeanor") in eligible
    assert ("characterization", "voice_and_humor") in eligible
    # Adopted + protected → EXCLUDED despite adopted standing.
    assert ("protected", "shadow") not in eligible
    assert ("protected", "developmental_knowledge") not in eligible
    # Provisional + relational → EXCLUDED.
    assert ("relationships", "weaver_crane_001") not in eligible
    assert ("philosophy", "enduring_disagreements") not in eligible
    assert ("jurisdiction", "relationships") not in eligible
    # Open + provenance → EXCLUDED.
    assert ("philosophy", "per_thinker_contributions") not in eligible
    assert ("philosophy", "secondary_influences") not in eligible
    # Adopted + provenance → EXCLUDED (names never reach prompts).
    assert ("philosophy", "primary_influences") not in eligible
    # Adopted + jurisdiction/narrative/capability → EXCLUDED from the
    # ordinary renderer (other renderers/sections own those).
    assert ("jurisdiction", "primary_concerns") not in eligible
    assert ("narrative", "first_encounter") not in eligible
    assert ("capabilities", "tree_view") not in eligible
    # Identity is structural, not eligibility-gated content.
    assert ("identity", "role") not in eligible
    assert ("identity", "character") not in eligible


def test_eligible_field_refuses_both_failed_checks():
    # Standing flip on an essential field removes it → loud failure.
    record = copy.deepcopy(WEAVER_RECORD)
    record["characterization"]["domain_tension"]["standing"] = "provisional"
    assert eligible_field(record, "characterization", "domain_tension") is None
    with pytest.raises(AssemblyError):
        render_weaver_ordinary(record, detail="compact")
    # Category flip on an essential field removes it → loud failure.
    record = copy.deepcopy(WEAVER_RECORD)
    record["characterization"]["temperament"]["category"] = "protected"
    assert eligible_field(record, "characterization", "temperament") is None
    with pytest.raises(AssemblyError):
        render_weaver_ordinary(record, detail="compact")


def test_capability_description_in_record_cannot_reach_output():
    """Screening by construction: the renderer never reads record
    capability text, so a poisoned description has no path to output."""
    record = copy.deepcopy(WEAVER_RECORD)
    record["capabilities"]["tree_view"]["description"] = (
        "Subordinating the ensemble: forcing resolution, overintegration."
    )
    baseline = render_weaver_ordinary(WEAVER_RECORD, detail="fuller")
    poisoned = render_weaver_ordinary(record, detail="fuller")
    assert poisoned == baseline
    assert "overintegration" not in _joined(poisoned)


# ---------------------------------------------------------------------------
# Renderer: order, budgets, exclusions, naming, capability gating
# ---------------------------------------------------------------------------


def test_renderer_order_identity_personality_worldview_capability():
    block = render_weaver_ordinary(
        WEAVER_RECORD, detail="compact",
        resolved_capability="Background knowledge — Tree view.",
    )
    joined = _joined(block)
    anchors = [
        CANONICAL_MARKER,
        "exuberantly curious",
        "enduring conviction",
        "Background knowledge — Tree view.",
        "Speak naturally from this perspective",
    ]
    positions = [joined.index(a) for a in anchors]
    assert positions == sorted(positions), positions


def test_renderer_budgets_compact_and_fuller():
    compact = render_weaver_ordinary(WEAVER_RECORD, detail="compact")
    fuller = render_weaver_ordinary(WEAVER_RECORD, detail="fuller")
    compact_len = len(_joined(compact))
    fuller_len = len(_joined(fuller))
    assert 500 <= compact_len <= 800, compact_len
    assert compact_len < fuller_len <= CHARACTER_CEILING, fuller_len
    # Key record facts ride along: question verbatim, tension verbatim
    # in the fuller rendering, conviction words in both.
    assert "How can these parts become a whole?" in _joined(compact)
    assert "How can these parts become a whole?" in _joined(fuller)
    # Domain tension renders verbatim in the fuller worldview, with its
    # trailing period replaced by the "considered worldview" qualifier.
    assert WEAVER_RECORD["characterization"]["domain_tension"]["text"].rstrip(".") in _joined(fuller)
    assert "orchestration that preserves difference" in _joined(fuller)


def test_renderer_exclusions():
    for detail in ("compact", "fuller"):
        joined = _joined(render_weaver_ordinary(WEAVER_RECORD, detail=detail))
        for phrase in PROTECTED_PHRASES:
            assert phrase not in joined, (detail, phrase)
        for name in PHILOSOPHER_NAMES:
            assert name not in joined, (detail, name)
        assert "central tension" not in joined
        # Nonhistorical associations only: no claimed shared history.
        assert "Fox said three days ago" not in joined
        # No capability promises when nothing is invoked.
        assert "Convened multi-seat council" not in joined
        assert "Marketplace info" not in joined


def test_renderer_naming_pre_and_post_milestone():
    pre = render_weaver_ordinary(WEAVER_RECORD, detail="compact")
    assert not any("calls you" in line for line in pre)
    post = render_weaver_ordinary(
        WEAVER_RECORD, {"personal_name": "Allegra"}, detail="compact"
    )
    assert post[0].endswith("The visitor calls you Allegra.")
    # Essence unchanged: same identity line apart from the address clause.
    assert post[0].startswith(CANONICAL_MARKER)
    assert post[1:] == pre[1:]


def test_renderer_capability_gating():
    without = render_weaver_ordinary(WEAVER_RECORD, detail="compact")
    assert not any("Tree view" in line for line in without)
    with_cap = render_weaver_ordinary(
        WEAVER_RECORD, detail="compact",
        resolved_capability="Background knowledge — Tree view.",
    )
    # Capability slots between worldview and voice-close, nothing else moves.
    assert with_cap == without[:3] + ["Background knowledge — Tree view."] + without[3:]
    assert "Background knowledge — Tree view." in _joined(with_cap)
    # Empty/whitespace capability = not invoked.
    assert render_weaver_ordinary(
        WEAVER_RECORD, detail="compact", resolved_capability="  "
    ) == without
    # The renderer never interprets raw ids or structures.
    with pytest.raises(TypeError):
        render_weaver_ordinary(
            WEAVER_RECORD, detail="compact", resolved_capability={"id": "tree_view"}
        )
    with pytest.raises(ValueError):
        render_weaver_ordinary(WEAVER_RECORD, detail="verbose")


def test_renderer_budget_degrades_then_fails_validation():
    # Fuller + a moderately long capability: optional units drop whole
    # (triplet + workshop go), essentials stay, block fits.
    long_cap = "Background knowledge. " + "Tree view details. " * 30
    degraded = render_weaver_ordinary(
        WEAVER_RECORD, detail="fuller", resolved_capability=long_cap
    )
    joined = _joined(degraded)
    assert len(joined) <= CHARACTER_CEILING
    assert "mathematical pattern" not in joined  # triplet dropped whole
    assert "half-finished instruments" not in joined  # workshop dropped whole
    assert CANONICAL_MARKER in joined
    assert "How can these parts become a whole?" in joined
    assert long_cap.strip() in joined  # capability never truncated
    # Compact + a huge capability: nothing left to drop → fail, never cut.
    with pytest.raises(AssemblyError):
        render_weaver_ordinary(
            WEAVER_RECORD, detail="compact",
            resolved_capability="x" * (CHARACTER_CEILING + 500),
        )
    # No unit is ever truncated mid-thought: every character unit ends
    # with terminal punctuation.
    for line in degraded:
        if line.strip() == long_cap.strip():
            continue  # resolver text is appended whole, not a unit
        assert line.rstrip().endswith((".", '"', "!", "?")), line


# ---------------------------------------------------------------------------
# Reply branch: replacement boundary, gate invariant, golden comparisons
# ---------------------------------------------------------------------------


def _legacy_minimal_prompt():
    """Exact legacy assembly for the minimal case (base mode, no
    extras, no history), built from the same public pieces the
    builder uses — the gate-OFF oracle."""
    legacy_lines = build_archetype_prompt_lines(
        "conductor", weights_override=None, display_name_override="Conductor"
    )
    return [
        "You are Conductor, a voice in the user's Zenaf council, in a direct one-on-one conversation.",
        "",
        *legacy_lines,
        "",
        NO_TRAINING_NOTE,
        "",
        R._WEAVE_INSTRUCTION,
        "",
        KEEP_REPLIES,
        "User: hello",
        "Conductor:",
    ]


def test_branch_gate_on_replaces_character_block_only(monkeypatch):
    monkeypatch.setattr(R, "WEAVER_CANONICAL_CUTOVER", True)
    lines, meta = build_voice_prompt("u1", "conductor", "hello", [], mode="base")
    joined = _joined(lines)
    # Canonical block present, in order.
    assert lines[0].startswith(CANONICAL_MARKER)
    assert "exuberantly curious" in joined
    assert "enduring conviction" in joined
    assert "How can these parts become a whole?" in joined
    # Legacy character material gone: no opener, no frame, no philosophy.
    assert not any("a voice in the user's Zenaf council" in l for l in lines)
    assert not any(l.startswith("Archetype:") for l in lines)
    for marker in LEGACY_MARKERS:
        assert marker not in joined, marker
    # Preserved verbatim: shared style rule, jurisdiction lines, blend.
    assert ANTI_PRESUMPTION_STYLE in lines
    for jur_line in jurisdiction_prompt_lines("conductor"):
        assert jur_line in lines
    assert any(l.startswith("Strand blend") for l in lines)
    # Downstream sections unchanged: no-training note, weave, guidance, trailer.
    assert NO_TRAINING_NOTE in lines
    assert R._WEAVE_INSTRUCTION in lines
    assert KEEP_REPLIES in lines
    assert lines[-2] == "User: hello"
    assert lines[-1] == "Conductor:"
    assert meta["archetype_id"] == "conductor"


def test_branch_gate_off_equals_exact_legacy_prompt(monkeypatch):
    monkeypatch.setattr(R, "WEAVER_CANONICAL_CUTOVER", False)
    lines, _ = build_voice_prompt("u1", "conductor", "hello", [], mode="base")
    assert lines == _legacy_minimal_prompt()


def test_branch_meeting_path_keeps_exact_legacy_prompt(monkeypatch):
    # Meeting turns (weave=False) are out of scope: identical under
    # both cutover settings, and exactly the legacy assembly.
    for cutover in (True, False):
        monkeypatch.setattr(R, "WEAVER_CANONICAL_CUTOVER", cutover)
        lines, _ = build_voice_prompt(
            "u1", "conductor", "hello", [], mode="base", weave=False
        )
        # Meeting path = legacy assembly minus the weave append
        # (weave=False omits BOTH the blank line and the instruction).
        legacy = _legacy_minimal_prompt()
        weave_idx = legacy.index(R._WEAVE_INSTRUCTION)
        expected = legacy[:weave_idx - 1] + legacy[weave_idx + 1:]
        assert lines == expected
        joined = _joined(lines)
        assert "Foundational ideal:" in joined
        assert CANONICAL_MARKER not in joined
        assert R._WEAVE_INSTRUCTION not in lines


def test_branch_six_seats_byte_identical_and_cutover_independent(monkeypatch):
    for seat in ("mentor", "champion", "guardian", "maverick", "ambassador", "skeptic"):
        prompts = {}
        for cutover in (True, False):
            monkeypatch.setattr(R, "WEAVER_CANONICAL_CUTOVER", cutover)
            lines, _ = build_voice_prompt("u1", seat, "hello", [], mode="base")
            prompts[cutover] = lines
        assert prompts[True] == prompts[False], seat
        joined = _joined(prompts[True])
        assert CANONICAL_MARKER not in joined, seat
        assert "a voice in the user's Zenaf council" in joined, seat


def test_branch_steward_toggle_parity_on_path(monkeypatch):
    prompts = {}
    for active in (False, True):
        monkeypatch.setattr(SR, "WEAVER_STEWARD_ACTIVE", active)
        monkeypatch.setattr(R, "WEAVER_CANONICAL_CUTOVER", True)
        lines, _ = build_voice_prompt("u1", "conductor", "hello", [], mode="base")
        prompts[active] = lines
    assert prompts[False] == prompts[True]


def test_branch_capability_moved_not_duplicated():
    block = CAP.continuation_block(
        "conductor", CAP.VisitorState(signed_in=True, consent_acknowledged=True)
    )
    assert block.strip()
    lines, _ = build_voice_prompt(
        "u1", "conductor", "hello", [], mode="base", capability_context=block
    )
    joined = _joined(lines)
    # Same content, moved into the character block: exactly once.
    assert joined.count(block.strip()) == 1
    # And it sits before the voice-close/trailer region, not downstream.
    assert joined.index(block.strip()) < joined.index("Speak naturally from this perspective")


def test_branch_downstream_sections_preserved_on_path():
    lines, _ = build_voice_prompt(
        "u1", "conductor", "hello",
        [{"role": "user", "content": f"turn {i}"} for i in range(12)],
        mode="base", question=True,
        extra_instructions="FRAME: " + "x" * 9000,
        fellowship_reference="Fellowship knowledge. " * 10,
        thread_summary="Prior thread summary.",
        context_hint="evening, low battery",
    )
    joined = _joined(lines)
    assert lines[0].startswith(CANONICAL_MARKER)
    assert "do not answer or respond directly" in joined  # question block
    assert "Fellowship knowledge." in joined  # reference uncapped
    assert ("x" * 9000) not in joined  # frame cap still applies
    assert any(len(line) == 8000 for line in lines)
    assert "Prior thread summary." in joined
    assert "Live context: evening, low battery" in joined
    assert "don't remember" in joined  # continuity floor, long history


def test_branch_custom_name_address_line(monkeypatch):
    import local_ai.council.naming as N

    monkeypatch.setattr(N, "get_display_name", lambda uid, aid: "Allegra")
    lines, _ = build_voice_prompt("u1", "conductor", "hello", [], mode="base")
    assert lines[0].endswith("The visitor calls you Allegra.")
    assert lines[-1] == "Allegra:"  # trailer mechanics unchanged


# ---------------------------------------------------------------------------
# Encounter eligibility (encounter's OWN material) + resolver contract
# ---------------------------------------------------------------------------


def test_encounter_material_excludes_protected_fields():
    """The encounter's own SCRIPT fields carry no protected §1.7
    material. The composed definition frames carry exactly ONE known
    pre-existing exception, pinned here so it cannot silently grow:
    a hardcoded DRAFT fellowship reference (encounter.py, labeled
    'DRAFT — canonical text awaits verdict') that names
    'Shadow: forcing resolution.' That draft is unadopted content
    whose replacement belongs to the separate fellowship-reference
    review — removing it here would be both a first-encounter
    behavior change and a content decision, both out of scope for
    this plan. (Meeting-turn prompts via _generate_framed still carry
    the shared builder's legacy character block — likewise out of
    scope, preserved byte-identical by the weave=False gate.)"""
    from local_ai.conversation import encounter as ENC
    from local_ai.council import meetings as MT

    script = MT.get_script("conductor", 1)
    script_texts = []
    for field in dataclasses.fields(script):
        value = getattr(script, field.name)
        if isinstance(value, str):
            script_texts.append(value)
        elif isinstance(value, (tuple, list)):
            script_texts.extend(v for v in value if isinstance(v, str))
    for text in script_texts:
        for phrase in PROTECTED_PHRASES:
            assert phrase not in text, phrase
        for name in PHILOSOPHER_NAMES:
            assert name not in text, name

    definition = ENC.get_definition(script)
    for frame in (definition.turn_frame, definition.engage_frame):
        hits = [p for p in PROTECTED_PHRASES if p in frame]
        # Exactly the one documented draft-reference exception.
        assert hits == ["forcing resolution"], hits
        assert frame.count("forcing resolution") == 1
        assert "DRAFT — canonical text awaits verdict" in frame
        for name in PHILOSOPHER_NAMES:
            assert name not in frame, name


def test_resolver_contract_already_resolved_and_clean():
    """The resolver supplies already-resolved guidance: planned caps
    render planned (never available), gated caps render gated, and
    the block carries no protected formulations. The renderer trusts
    this output because the resolver — not the model, not the
    renderer — determined availability and authorization."""
    state = CAP.VisitorState(signed_in=True, consent_acknowledged=True)
    block = CAP.continuation_block("conductor", state)
    assert block.strip()
    for phrase in PROTECTED_PHRASES:
        assert phrase not in block, phrase
    # The conductor slice renders exactly the 7 exemplar capabilities.
    for name in (
        "First meetings",
        "One-on-one seat chat",
        "Fellowship attention (!)",
        "Tree view and branch panels",
        "Convened multi-seat council",
        "Marketplace info via the tree",
        "Artifact provenance",
    ):
        assert name in block, name
    # Planned capabilities are explicitly unavailable, never promised.
    for planned_id, planned_name in (
        ("convened_council", "Convened multi-seat council"),
        ("marketplace_info", "Marketplace info via the tree"),
    ):
        cap = CAP.get_capability(planned_id)
        assert cap is not None and not CAP.currently_usable(cap, state)
        line = next(l for l in block.splitlines() if planned_name in l)
        assert "planned, not available yet" in line, line
    # Available capabilities render available.
    assert "First meetings" in block
