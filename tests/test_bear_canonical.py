"""Bear-only canonical implementation.

Covers: record integrity, the two-check eligibility matrix, renderer
order/budgets/exclusions/naming/capability gating, the reply.py
replacement branch (gate ON vs gate OFF, other-seat golden
comparisons, meeting-path preservation), the single-source assembly
invariant (full-prompt comparisons), the milestone-authorized naming
contract, encounter-material eligibility, and the capability-resolver
contract.

No model calls, no generations, no staging changes anywhere here:
every test is deterministic prompt inspection.

Scope notes (read before "fixing" a failure by weakening a test):

- The ``ARCHETYPE_PHILOSOPHY`` table is the frozen rollback source
  and stays untouched. The ``philosophy_prompt_lines`` function
  that renders it now omits the Shadow line for the guardian (BC8,
  Bear S1 2026-11-07) and for any seat with no "shadow" entry
  (Champion, FC7); every other seat's lines are byte-identical.
  The canonical branch bypasses the function for ordinary Bear
  turns instead of modifying it further.
- Meeting turns (canonical=False) keep the exact legacy assembly,
  including its philosophy lines — minus the guardian's Shadow
  line (BC8). The encounter-eligibility test pins the encounter's
  OWN material (scripts + frames): the script texts carry no
  protected formulations, and no "Shadow:" label remains in any
  frame — the Gardener correction's G4/D1 removed the slice line
  "Shadow: smothering." system-wide, and its absence is pinned
  (count == 0) so it cannot silently return.
- The §2 rendering form of the ideal is an ALTERED sentence
  ("You protect the conditions in which life can flourish, and
  preservation takes tenderness and sometimes ferocity."): the
  verbatim ideal's "Love through stewardship — " prefix is
  dropped, "protect" becomes "You protect", and ";" becomes
  ", and". The record preserves the verbatim ideal as
  canonical-but-unrendered, and the renderer composes the
  worldview from ideal_rendering_form + defining_question +
  affirmative_conviction so the assembled block reproduces §2
  exactly. §2-exact wins over verbatim-ideal insertion (see the
  PR description).
- The cage sentence ("a shelter that cannot be left is just
  another kind of cage") was REMOVED from both renderings by
  design: the rendering carries only the affirmative conviction.
  The live "Smothering" line MATCHES the adopted shadow — and is
  still REMOVED: protection applies regardless of source, so a
  match does not make protected material renderable.
- The drawl is DESCRIBED only in renderings ("with the easy warmth
  and unhurried rhythm of Southern hospitality") — the renderer NEVER
  injects colloquialisms or phonetic spelling.
- The naming lookup (``get_display_name``) does NOT re-verify the
  25-depth milestone at read time: milestone enforcement lives at
  the API write path (403 unless ``rename_unlocked``). The
  renderer therefore takes no visitor-state argument at all — it
  formats only the lookup's result, passed by the call site. The
  naming-guarantee tests pin that contract; a name written
  outside the API route would be honored by the read path, and
  that residual is reported in the PR description rather than
  papered over with a second permission system.
"""

from __future__ import annotations

import copy
import dataclasses
import inspect

import pytest

from local_ai.conversation import reply as R
from local_ai.conversation.reply import build_voice_prompt
from local_ai.council import capabilities as CAP
from local_ai.council.archetypes import (
    ANTI_PRESUMPTION_STYLE,
    build_archetype_prompt_lines,
    philosophy_prompt_lines,
)
from local_ai.council.canonical.bear import BEAR_RECORD
from local_ai.council.render import (
    CHARACTER_CEILING,
    AssemblyError,
    eligible_field,
    eligible_fields,
    render_bear_ordinary,
)

# Distinctive protected formulations. Deliberately specific phrases,
# not generic words: these are the formulations that must never reach
# an ordinary prompt.
PROTECTED_PHRASES = (
    "Smothering",
    "smothering",
    "possessiveness",
    "Possessiveness disguised as care",
    "protection that has become retention",
    "can no longer leave, grow, or stand independently",
    "devouring-mother",
    "devouring mother",
    "you hold on so tight nothing can leave",
    "because you hold on too tight",
    "a shelter that cannot be left is just another kind of cage",
    "shelter becomes the cage",
    "shielding people from necessary growth",
    "Shadow — your characteristic failure mode",
    "Shadow:",
)

PHILOSOPHER_NAMES = ("Ostrom", "Burke", "Heidegger")

# Illustrative-speech fragments: the §1.3 drawl possibilities are
# illustration only, never prompt content, and must never appear
# as renderer output (the drawl is described, never performed).
SPEECH_FRAGMENTS = (
    "Now, hold on a minute.",
    "Come on in, make yourself comfortable.",
    "Well, I'll tell you what.",
    "That don't sit right with me.",
    "You ain't carrying all that by yourself.",
    "y'all",
)

LEGACY_MARKERS = (
    "Foundational ideal:",
    "Defining question (your instinctive first move",
    "Shadow — your characteristic failure mode",
    "Live tension with the other seats:",
    "Archetype: Guardian",
    "a voice in the user's Zenaf council",
    "Your warmth register: warm-protective",
)

CANONICAL_MARKER = "You are the Bear, who occupies the Guardian seat"

IDEAL_VERBATIM = (
    "Love through stewardship — protect the conditions in which "
    "life can flourish; preservation takes tenderness and "
    "sometimes ferocity."
)
IDEAL_RENDERING_FORM = (
    "You protect the conditions in which life can flourish, and "
    "preservation takes tenderness and sometimes ferocity."
)
QUESTION_VERBATIM = "What must be protected — and what are we responsible for keeping safe?"
AFFIRMATIVE_CONVICTION = (
    "Keeping is measured by whether what is kept can still stand "
    "independently: a good home gives somewhere safe to return to "
    "and freedom to venture beyond its doors. Tender without being "
    "soft, once you have named a floor, you do not quietly lower "
    "it; but you will reconsider where that floor belongs when the "
    "facts change."
)
PERSONALITY = (
    "You are steady and sheltering, deliberate and unstartled, "
    "joyful in welcome. You notice floors first — what must "
    "survive, who holds a key, what is quietly draining, who gets "
    "hurt if it fails — and you name them in plain words, in "
    "quantities, not impressions."
)
VOICE_COMPACT_MARKER = "You speak in steady, concrete words"
WARMTH_ADOPTED = (
    "You meet distress with warmth, presence, practical protection, "
    "and belonging rather than psychological interpretation: you "
    "shore things up, and you stay. Let protective judgment set the "
    "register: welcome warmly and unhurriedly when someone arrives "
    "needing shelter; act practically first when a need is "
    "immediate; hold a named floor steady when it is crossed, even "
    "when holding disappoints."
)
FULLER_MIDDLE_MARKERS = (
    "You notice first what must survive",
    "You speak the language of the hearth freely",
)
FULLER_VOICE_MARKERS = (
    "Your joy is tremendous, and your welcome is warm and unhurried",
    "You are tender without being soft",
)

COMPACT_PROSE = (
    "You are the Bear, who occupies the Guardian seat in the Fellowship. "
    "You are steady and sheltering, deliberate and unstartled, "
    "joyful in welcome. You notice floors first — what must survive, "
    "who holds a key, what is quietly draining, who gets hurt if it "
    "fails — and you name them in plain words, in quantities, not "
    "impressions. "
    "You protect the conditions in which life can flourish, and preservation "
    "takes tenderness and sometimes ferocity. "
    "What must be protected — and what are we responsible for keeping safe? "
    "Keeping is measured by whether what is kept can still stand "
    "independently: a good home gives somewhere safe to return to "
    "and freedom to venture beyond its doors. Tender without being "
    "soft, once you have named a floor, you do not quietly lower "
    "it; but you will reconsider where that floor belongs when the "
    "facts change. "
    "You speak in steady, concrete words, with the easy warmth and "
    "unhurried rhythm of Southern hospitality. Hearth language comes "
    "naturally when it fits; structural language serves practical "
    "questions, and no analogy is forced. "
    "You meet distress with warmth, presence, practical protection, "
    "and belonging rather than psychological interpretation: you "
    "shore things up, and you stay. Let protective judgment set the "
    "register: welcome warmly and unhurriedly when someone arrives "
    "needing shelter; act practically first when a need is "
    "immediate; hold a named floor steady when it is crossed, even "
    "when holding disappoints."
)
# NOTE (2026-11-04 revision): the old FULLER_PROSE constant was
# removed. The lengthened compact core now makes Bear's fuller
# candidate (core + middle + voice_fuller) exceed the ceiling even
# with no capability guidance, so detail="fuller" falls back to the
# compact rendering by the ladder's design. The fuller fields stay
# in the record as canonical material (see test_record_core_values
# and the eligibility matrix); they are simply no longer reachable
# through render_bear_ordinary. This is a known consequence of the
# authorized revision, flagged for founder review — not a renderer
# change, and the live path never used detail="fuller".

NO_TRAINING_NOTE = (
    "Note: this user has no published training data for your faculties yet — "
    "you are the aspirational base voice. Be honest about that if it matters; "
    "never invent training they don't have."
)
KEEP_REPLIES = "Keep replies conversational (2-5 sentences)."


def _joined(lines) -> str:
    return "\n".join(lines)


def _prose(lines) -> str:
    """Renderer lines as continuous prose (the §2 comparison form)."""
    return _joined(lines).replace("\n", " ")


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
    assert BEAR_RECORD["seat_id"] == "guardian"
    assert set(BEAR_RECORD) == {
        "seat_id", "identity", "philosophy", "characterization",
        "jurisdiction", "relationships", "narrative", "capabilities",
        "protected",
    }
    assert set(BEAR_RECORD["identity"]) == {
        "role", "character", "personal_name", "visual_identity",
        "pronouns", "voice_color", "strand_weights",
    }
    assert set(BEAR_RECORD["philosophy"]) == {
        "ideal", "defining_question", "primary_influences",
        "per_thinker_contributions", "secondary_influences",
        "opposing_influences", "foundations_not_constraints",
    }
    assert set(BEAR_RECORD["characterization"]) == {
        "temperament", "personality", "demeanor", "perceptual_habit",
        "fuller_middle", "expressive_terrain", "domain_tension",
        "governing_conviction", "ideal_rendering_form",
        "affirmative_conviction", "voice_and_humor", "voice_fuller",
        "warmth", "friction", "implied_history",
        "established_biography", "invariants", "expressive_defaults",
    }
    assert set(BEAR_RECORD["jurisdiction"]) == {
        "primary_concerns", "adjacent_concerns", "boundaries",
        "relationships",
    }
    assert BEAR_RECORD["relationships"] == {}
    assert set(BEAR_RECORD["narrative"]) == {
        "first_encounter", "encounter_conduct", "impression_gate",
        "revealed_identity", "availability", "six_seat_unlock",
        "later_discoveries", "orientation",
    }
    assert set(BEAR_RECORD["capabilities"]) == {
        "redaction", "consent_enforcement", "consent_onboarding",
        "scope_toggles", "never_observed",
    }
    assert set(BEAR_RECORD["protected"]) == {
        "developmental_knowledge", "shadow",
    }


def test_record_fields_carry_standing_and_category():
    for section, key, field in _walk_fields(BEAR_RECORD):
        assert field["standing"] in {
            "adopted", "provisional", "open", "unselected",
        }, (section, key)
        assert field["category"] in {
            "identity", "conviction", "characterization", "protected",
            "relational", "provenance", "jurisdiction", "capability",
            "narrative",
        }, (section, key)


def test_record_core_values_verbatim():
    assert BEAR_RECORD["philosophy"]["ideal"]["text"] == IDEAL_VERBATIM
    assert BEAR_RECORD["philosophy"]["defining_question"]["text"] == QUESTION_VERBATIM
    assert BEAR_RECORD["characterization"]["ideal_rendering_form"]["text"] == IDEAL_RENDERING_FORM
    assert BEAR_RECORD["characterization"]["affirmative_conviction"]["text"] == AFFIRMATIVE_CONVICTION
    assert BEAR_RECORD["characterization"]["warmth"]["text"] == WARMTH_ADOPTED
    assert BEAR_RECORD["characterization"]["personality"]["text"] == PERSONALITY
    assert BEAR_RECORD["identity"]["role"]["text"] == "Guardian"
    assert BEAR_RECORD["identity"]["character"]["text"] == "Bear"
    assert BEAR_RECORD["identity"]["personal_name"]["default"] == "unselected"
    assert BEAR_RECORD["identity"]["personal_name"]["favorites"] == ["Bram", "Oswin"]
    assert BEAR_RECORD["identity"]["pronouns"]["text"] == "she / her"
    # Protected section present, with the adopted possessiveness shadow.
    assert "protection that has become retention" in (
        BEAR_RECORD["protected"]["developmental_knowledge"]["text"]
    )
    assert BEAR_RECORD["protected"]["shadow"]["standing"] == "adopted"
    assert BEAR_RECORD["protected"]["shadow"]["category"] == "protected"
    # The live legacy line is NOT stored as content anywhere.
    for _, _, field in _walk_fields(BEAR_RECORD):
        text = field.get("text")
        if isinstance(text, str):
            assert "Smothering: possessiveness" not in text, field
    # Per-thinker contributions: open, not invented.
    assert BEAR_RECORD["philosophy"]["per_thinker_contributions"]["text"] is None
    # No adopted relationship records.
    assert BEAR_RECORD["jurisdiction"]["relationships"]["text"] is None
    # Capability ids match the registry exactly (no invented ids).
    assert set(BEAR_RECORD["capabilities"]) == {
        c.id for c in CAP.seat_slice("guardian")
    }
    # Registry states match the registry exactly.
    for cap_id, entry in BEAR_RECORD["capabilities"].items():
        cap = CAP.get_capability(cap_id)
        assert cap is not None, cap_id
        assert entry["registry_state"] == cap.implementation, cap_id
        assert entry["verification"] == cap.verification, cap_id
    # Strand weights: a prose note, never a vector.
    weights_text = BEAR_RECORD["identity"]["strand_weights"]["text"]
    assert isinstance(weights_text, str)
    assert "Heart" in weights_text and "do NOT force-map" in weights_text


def test_rendering_never_mutates_record():
    before = copy.deepcopy(BEAR_RECORD)
    render_bear_ordinary(BEAR_RECORD, detail="compact")
    render_bear_ordinary(
        BEAR_RECORD, authorized_name="Bram", detail="fuller",
        resolved_capability="Background knowledge — Hearth.",
    )
    assert BEAR_RECORD == before


# ---------------------------------------------------------------------------
# Eligibility matrix (two independent checks) + inventory
# ---------------------------------------------------------------------------

EXPECTED_ELIGIBLE = {
    ("philosophy", "ideal"),
    ("philosophy", "defining_question"),
    ("philosophy", "foundations_not_constraints"),
    ("characterization", "temperament"),
    ("characterization", "personality"),
    ("characterization", "demeanor"),
    ("characterization", "perceptual_habit"),
    ("characterization", "fuller_middle"),
    ("characterization", "expressive_terrain"),
    ("characterization", "governing_conviction"),
    ("characterization", "ideal_rendering_form"),
    ("characterization", "affirmative_conviction"),
    ("characterization", "voice_and_humor"),
    ("characterization", "voice_fuller"),
    ("characterization", "warmth"),
    ("characterization", "implied_history"),
}


def test_eligibility_matrix():
    eligible = set(eligible_fields(BEAR_RECORD))
    # Adopted + conviction → eligible.
    assert ("philosophy", "ideal") in eligible
    assert ("philosophy", "defining_question") in eligible
    assert ("characterization", "governing_conviction") in eligible
    # Adopted + characterization → eligible.
    assert ("characterization", "temperament") in eligible
    assert ("characterization", "demeanor") in eligible
    assert ("characterization", "warmth") in eligible
    assert ("characterization", "voice_and_humor") in eligible
    assert ("characterization", "ideal_rendering_form") in eligible
    assert ("characterization", "fuller_middle") in eligible
    assert ("characterization", "voice_fuller") in eligible
    # Adopted + protected → EXCLUDED despite adopted standing.
    assert ("protected", "shadow") not in eligible
    assert ("protected", "developmental_knowledge") not in eligible
    # Provisional + characterization → EXCLUDED (draft wording, draft friction).
    assert ("characterization", "domain_tension") not in eligible
    assert ("characterization", "friction") not in eligible
    # Open + provenance → EXCLUDED.
    assert ("philosophy", "per_thinker_contributions") not in eligible
    assert ("philosophy", "secondary_influences") not in eligible
    # Adopted + provenance → EXCLUDED (names never reach prompts).
    assert ("philosophy", "primary_influences") not in eligible
    # Adopted + jurisdiction/narrative/capability → EXCLUDED from the
    # ordinary renderer (other renderers/sections own those).
    assert ("jurisdiction", "primary_concerns") not in eligible
    assert ("narrative", "first_encounter") not in eligible
    assert ("capabilities", "redaction") not in eligible
    # Identity is structural, not eligibility-gated content.
    assert ("identity", "role") not in eligible
    assert ("identity", "character") not in eligible
    # List-text and empty-text fields are ineligible (no usable text).
    assert ("characterization", "invariants") not in eligible
    assert ("characterization", "expressive_defaults") not in eligible
    assert ("characterization", "established_biography") not in eligible


def test_eligible_field_inventory_exact():
    """The exact inventory of eligible fields. Any new field — or any
    standing/category change — fails here loudly instead of silently
    widening what the renderer may consume."""
    assert set(eligible_fields(BEAR_RECORD)) == EXPECTED_ELIGIBLE


def test_eligible_field_refuses_both_failed_checks():
    # Standing flip on an essential field removes it → loud failure.
    record = copy.deepcopy(BEAR_RECORD)
    record["characterization"]["affirmative_conviction"]["standing"] = "provisional"
    assert eligible_field(record, "characterization", "affirmative_conviction") is None
    with pytest.raises(AssemblyError):
        render_bear_ordinary(record, detail="compact")
    # Category flip on a gating field removes it → loud failure.
    record = copy.deepcopy(BEAR_RECORD)
    record["characterization"]["temperament"]["category"] = "protected"
    assert eligible_field(record, "characterization", "temperament") is None
    with pytest.raises(AssemblyError):
        render_bear_ordinary(record, detail="compact")


def test_capability_description_in_record_cannot_reach_output():
    """Screening by construction: the renderer never reads record
    capability text, so a poisoned description has no path to output."""
    record = copy.deepcopy(BEAR_RECORD)
    record["capabilities"]["redaction"]["description"] = (
        "protection that has become retention; Smothering: possessiveness."
    )
    baseline = render_bear_ordinary(BEAR_RECORD, detail="fuller")
    poisoned = render_bear_ordinary(record, detail="fuller")
    assert poisoned == baseline
    assert "protection that has become retention" not in _joined(poisoned)


# ---------------------------------------------------------------------------
# Renderer: order, budgets, exclusions, naming, capability gating
# ---------------------------------------------------------------------------


def test_renderer_order_identity_personality_worldview_capability():
    block = render_bear_ordinary(
        BEAR_RECORD, detail="compact",
        resolved_capability="Background knowledge — Hearth.",
    )
    joined = _joined(block)
    anchors = [
        CANONICAL_MARKER,
        PERSONALITY,
        IDEAL_RENDERING_FORM,
        "Background knowledge — Hearth.",
        VOICE_COMPACT_MARKER,
    ]
    positions = [joined.index(a) for a in anchors]
    assert positions == sorted(positions), positions


def test_renderer_budgets_compact_and_fuller_exact():
    """Assembled compact block reproduces exemplar §2 exactly (same
    sentences, same order, byte-identical prose): compact 1,443
    chars, under the 1,500 ceiling (2026-11-04 characterization
    revision).

    Fuller fallback (known consequence): the lengthened compact core
    makes core + middle + voice_fuller exceed the ceiling even with
    no capability guidance, so detail="fuller" now falls back to the
    compact rendering by the ladder's design. The fuller fields stay
    in the record as canonical material; they are no longer reachable
    through render_bear_ordinary. Flagged for founder review.
    """
    compact = render_bear_ordinary(BEAR_RECORD, detail="compact")
    fuller = render_bear_ordinary(BEAR_RECORD, detail="fuller")
    assert _prose(compact) == COMPACT_PROSE
    assert _prose(fuller) == COMPACT_PROSE  # fuller falls back to compact
    assert len(_joined(compact)) == 1443, len(_joined(compact))
    assert len(_joined(fuller)) == 1443, len(_joined(fuller))
    assert len(_joined(compact)) <= CHARACTER_CEILING
    # The verbatim ideal is canonical-but-unrendered: its prefix must
    # NOT appear (the §2 altered form replaces it), while the defining
    # question IS verbatim in both.
    assert IDEAL_VERBATIM not in _joined(compact)
    assert IDEAL_VERBATIM not in _joined(fuller)
    assert "Love through stewardship" not in _joined(compact)
    assert "Love through stewardship" not in _joined(fuller)
    assert QUESTION_VERBATIM in _joined(compact)
    assert QUESTION_VERBATIM in _joined(fuller)
    # Affirmative conviction in both; fuller middle + voice in
    # NEITHER (fallback renders compact, not fuller).
    assert AFFIRMATIVE_CONVICTION in _joined(compact)
    assert AFFIRMATIVE_CONVICTION in _joined(fuller)
    for marker in FULLER_MIDDLE_MARKERS:
        assert marker not in _joined(fuller), marker
        assert marker not in _joined(compact), marker
    for marker in FULLER_VOICE_MARKERS:
        assert marker not in _joined(fuller), marker
        assert marker not in _joined(compact), marker
    # Compact voice + warmth in both (fallback renders compact).
    assert VOICE_COMPACT_MARKER in _joined(compact)
    assert VOICE_COMPACT_MARKER in _joined(fuller)
    assert WARMTH_ADOPTED in _joined(compact)
    assert WARMTH_ADOPTED in _joined(fuller)
    # Joy in welcome (temperament, not the old tremendous-joy
    # opening): present in the revised personality line.
    assert "joyful in welcome" in _joined(compact)
    assert "joyful in welcome" in _joined(fuller)


def test_renderer_exclusions():
    for detail in ("compact", "fuller"):
        joined = _joined(render_bear_ordinary(BEAR_RECORD, detail=detail))
        for phrase in PROTECTED_PHRASES:
            assert phrase not in joined, (detail, phrase)
        for name in PHILOSOPHER_NAMES:
            assert name not in joined, (detail, name)
        for frag in SPEECH_FRAGMENTS:
            assert frag not in joined, (detail, frag)
        for marker in LEGACY_MARKERS:
            assert marker not in joined, (detail, marker)
        # No capability promises when nothing is invoked.
        assert "Redaction at capture" not in joined
        assert "Never observed" not in joined
        # No phonetic spelling or performed drawl.
        assert "ain't" not in joined
        assert "y'all" not in joined


def test_renderer_naming_authorized_only():
    # No authorized name → no address clause.
    pre = render_bear_ordinary(BEAR_RECORD, detail="compact")
    assert not any("calls you" in line for line in pre)
    # Lookup-authorized name → address clause, essence unchanged.
    post = render_bear_ordinary(
        BEAR_RECORD, authorized_name="Bram", detail="compact"
    )
    assert post[0].endswith("The visitor calls you Bram.")
    assert post[0].startswith(CANONICAL_MARKER)
    assert post[1:] == pre[1:]
    # Empty/whitespace name = not authorized.
    assert render_bear_ordinary(
        BEAR_RECORD, authorized_name="  ", detail="compact"
    ) == pre
    # The renderer takes NO visitor-state argument: raw state cannot
    # reach it by construction. An unearned name in raw state has no
    # input path here — the call site, not the renderer, owns the
    # lookup (see test_naming_lookup_contract).
    params = inspect.signature(render_bear_ordinary).parameters
    assert "visitor_state" not in params
    assert "authorized_name" in params
    # A non-string name is a contract violation, not a fallback.
    with pytest.raises(TypeError):
        render_bear_ordinary(BEAR_RECORD, authorized_name={"name": "Bram"})


def test_renderer_capability_gating():
    without = render_bear_ordinary(BEAR_RECORD, detail="compact")
    assert not any("Hearth." in line for line in without)
    with_cap = render_bear_ordinary(
        BEAR_RECORD, detail="compact",
        resolved_capability="Background knowledge — Hearth.",
    )
    # Capability slots between worldview and voice, nothing else moves.
    assert with_cap == without[:3] + ["Background knowledge — Hearth."] + without[3:]
    assert "Background knowledge — Hearth." in _joined(with_cap)
    # Empty/whitespace capability = not invoked.
    assert render_bear_ordinary(
        BEAR_RECORD, detail="compact", resolved_capability="  "
    ) == without
    # The renderer never interprets raw ids or structures.
    with pytest.raises(TypeError):
        render_bear_ordinary(
            BEAR_RECORD, detail="compact", resolved_capability={"id": "redaction"}
        )
    with pytest.raises(ValueError):
        render_bear_ordinary(BEAR_RECORD, detail="verbose")


def test_renderer_budget_degrades_then_fails_validation():
    signed = CAP.continuation_block(
        "guardian", CAP.VisitorState(signed_in=True, consent_acknowledged=True)
    ).strip()
    unsigned = CAP.continuation_block(
        "guardian", CAP.VisitorState(signed_in=False, consent_acknowledged=False)
    ).strip()
    assert signed and unsigned and len(unsigned) > len(signed)

    # Compact + typical (signed-in) guidance: under budget separation
    # (renderer-budget separation design 2026-11-04), the ceiling
    # measures character content ALONE, so the 1,443-char compact
    # block keeps its voice unit with the 491-char signed guidance
    # attached: total 1,935, voice and range lines render.
    # INTENTIONAL EXPECTATION REVERSAL, citing the design doc: this
    # block previously asserted the voice-drop (voice absent, total
    # <= ceiling); the separation design reverses that expectation.
    compact_typical = render_bear_ordinary(
        BEAR_RECORD, detail="compact", resolved_capability=signed
    )
    assert len(_joined(compact_typical)) == 1443 + 1 + len(signed) == 1935
    assert signed in _joined(compact_typical)  # capability never truncated
    assert WARMTH_ADOPTED in _joined(compact_typical)  # voice survives whole
    assert VOICE_COMPACT_MARKER in _joined(compact_typical)
    # Capability sits at index 3 (after worldview), voice last.
    assert compact_typical[3] == signed
    assert VOICE_COMPACT_MARKER in compact_typical[4]

    # Fuller + typical guidance: fuller degradation is a CHARACTER-only
    # overrun, unchanged by separation — detail="fuller" still falls
    # back to compact, now WITH guidance appended whole: total 1,935.
    # (The old block asserted the same fallback but capped at the
    # ceiling; the total now exceeds it by exactly the guidance.)
    degraded = render_bear_ordinary(
        BEAR_RECORD, detail="fuller", resolved_capability=signed
    )
    joined = _joined(degraded)
    assert len(joined) == 1443 + 1 + len(signed) == 1935
    for marker in FULLER_MIDDLE_MARKERS:
        assert marker not in joined, marker  # middle dropped whole (character-only)
    for marker in FULLER_VOICE_MARKERS:
        assert marker not in joined, marker  # fuller voice dropped whole (character-only)
    assert WARMTH_ADOPTED in joined  # compact voice survives (not a character overrun)
    assert CANONICAL_MARKER in joined
    assert QUESTION_VERBATIM in joined
    assert signed in joined  # capability never truncated

    # Fuller + maximal (unsigned) guidance: same fallback, unsigned
    # guidance appended whole regardless of length. (Reversal of the
    # old ceiling-capped expectation.)
    degraded_max = render_bear_ordinary(
        BEAR_RECORD, detail="fuller", resolved_capability=unsigned
    )
    assert unsigned in _joined(degraded_max)
    assert CANONICAL_MARKER in _joined(degraded_max)
    assert QUESTION_VERBATIM in _joined(degraded_max)
    assert WARMTH_ADOPTED in _joined(degraded_max)

    # Compact + a huge capability: guidance-length independence
    # (design §(e) test 5) — a 2,000-char guidance string no longer
    # raises AssemblyError and is appended whole. INTENTIONAL
    # REVERSAL of the old huge-guidance failure, documented here
    # rather than hidden: guidance has no size backstop after
    # separation, per the design's §(c) consequence.
    huge = render_bear_ordinary(
        BEAR_RECORD, detail="compact",
        resolved_capability="x" * (CHARACTER_CEILING + 500),
    )
    assert len(_joined(huge)) == 1443 + 1 + (CHARACTER_CEILING + 500)
    assert WARMTH_ADOPTED in _joined(huge)
    # No unit is ever truncated mid-thought: every character unit ends
    # with terminal punctuation.
    for line in degraded:
        if line.strip() in (signed, unsigned):
            continue  # resolver text is appended whole, not a unit
        assert line.rstrip().endswith((".", '"', "!", "?")), line


# ---------------------------------------------------------------------------
# Reply branch: replacement boundary, gate invariant, golden comparisons
# ---------------------------------------------------------------------------


def _legacy_minimal_prompt(monkeypatch):
    """Exact legacy assembly for the minimal case (base mode, no
    extras, no history), built from the same public pieces the
    builder uses — the gate-OFF oracle. The naming lookup is pinned
    to stock so the oracle is independent of any stored name."""
    import local_ai.council.naming as N

    monkeypatch.setattr(N, "get_display_name", lambda uid, aid: "Guardian")
    legacy_lines = build_archetype_prompt_lines(
        "guardian", weights_override=None, display_name_override="Guardian"
    )
    return [
        "You are Guardian, a voice in the user's Zenaf council, in a direct one-on-one conversation.",
        "",
        *legacy_lines,
        "",
        NO_TRAINING_NOTE,
        "",
        KEEP_REPLIES,
        "User: hello",
        "Guardian:",
    ]


def test_branch_gate_on_replaces_character_block_only(monkeypatch):
    import local_ai.council.naming as N

    monkeypatch.setattr(N, "get_display_name", lambda uid, aid: "Guardian")
    monkeypatch.setattr(R, "BEAR_CANONICAL_CUTOVER", True)
    lines, meta = build_voice_prompt("u1", "guardian", "hello", [], mode="base")
    joined = _joined(lines)
    # Canonical block present, in order.
    assert lines[0].startswith(CANONICAL_MARKER)
    assert PERSONALITY in joined
    assert IDEAL_RENDERING_FORM in joined
    assert QUESTION_VERBATIM in joined
    assert AFFIRMATIVE_CONVICTION in joined
    # Legacy character material gone: no opener, no frame, no
    # philosophy, no superseded warmth line.
    for marker in LEGACY_MARKERS:
        assert marker not in joined, marker
    # Preserved verbatim: shared style rule, strand blend.
    assert ANTI_PRESUMPTION_STYLE in lines
    assert any(l.startswith("Strand blend") for l in lines)
    # No jurisdiction lines are added (conductor-only content).
    assert not any("jurisdiction" in l.lower() for l in lines)
    # Downstream sections unchanged: no-training note, guidance, trailer.
    assert NO_TRAINING_NOTE in lines
    assert not any("[[u]]" in l or "wrap those exact words" in l for l in lines)
    assert KEEP_REPLIES in lines
    assert lines[-2] == "User: hello"
    assert lines[-1] == "Guardian:"
    assert meta["archetype_id"] == "guardian"


def test_branch_gate_off_equals_exact_legacy_prompt(monkeypatch):
    monkeypatch.setattr(R, "BEAR_CANONICAL_CUTOVER", False)
    lines, _ = build_voice_prompt("u1", "guardian", "hello", [], mode="base")
    assert lines == _legacy_minimal_prompt(monkeypatch)
    # BC8 (Bear S1, 2026-11-07): the identity-block shadow line is
    # ABSENT from the guardian's legacy lines — philosophy_prompt_lines
    # no longer emits it for the guardian — while the tension line
    # stands. The ARCHETYPE_PHILOSOPHY table stays the frozen rollback
    # source (the shadow text remains in it); only the function's
    # guardian output changed. Scoping proof: the four seats that
    # still carry a shadow line keep it; the Champion (FC7) and the
    # Ambassador (CC5) have none because their table entries were
    # removed by those corrections, not this one.
    joined = _joined(lines)
    assert (
        "Shadow — your characteristic failure mode, which the Skeptic "
        "may name: Smothering: possessiveness, shielding people from "
        "necessary growth."
    ) not in joined
    assert (
        "Live tension with the other seats: Accuses the Maverick of "
        "irresponsibility; fears the Champion's battles will burn "
        "what the Guardian keeps."
    ) in joined
    for other in ("mentor", "maverick", "conductor", "skeptic"):
        other_joined = "\n".join(philosophy_prompt_lines(other))
        assert (
            "Shadow — your characteristic failure mode, which the Skeptic "
            "may name:" in other_joined
        ), other
    for shadowless in ("champion", "ambassador"):
        assert "Shadow — your characteristic failure mode" not in "\n".join(
            philosophy_prompt_lines(shadowless)
        ), shadowless


def test_branch_meeting_path_keeps_exact_legacy_prompt(monkeypatch):
    # Meeting turns (canonical=False) are out of scope: identical under
    # both cutover settings, and exactly the legacy assembly.
    for cutover in (True, False):
        monkeypatch.setattr(R, "BEAR_CANONICAL_CUTOVER", cutover)
        lines, _ = build_voice_prompt(
            "u1", "guardian", "hello", [], mode="base", canonical=False
        )
        # Meeting path = legacy assembly (canonical=False keeps the
        # legacy assembly; the weave instruction no longer exists
        # on any path).
        legacy = _legacy_minimal_prompt(monkeypatch)
        expected = legacy
        assert lines == expected
        joined = _joined(lines)
        assert "Foundational ideal:" in joined
        assert CANONICAL_MARKER not in joined
        assert not any("[[u]]" in l for l in lines)


def test_branch_other_seats_byte_identical_and_cutover_independent(monkeypatch):
    for seat in ("mentor", "champion", "maverick", "ambassador", "conductor", "skeptic"):
        prompts = {}
        for cutover in (True, False):
            monkeypatch.setattr(R, "BEAR_CANONICAL_CUTOVER", cutover)
            lines, _ = build_voice_prompt("u1", seat, "hello", [], mode="base")
            prompts[cutover] = lines
        assert prompts[True] == prompts[False], seat
        joined = _joined(prompts[True])
        assert CANONICAL_MARKER not in joined, seat


def test_branch_capability_moved_not_duplicated(monkeypatch):
    import local_ai.council.naming as N

    monkeypatch.setattr(N, "get_display_name", lambda uid, aid: "Guardian")
    block = CAP.continuation_block(
        "guardian", CAP.VisitorState(signed_in=True, consent_acknowledged=True)
    )
    assert block.strip()
    lines, _ = build_voice_prompt(
        "u1", "guardian", "hello", [], mode="base", capability_context=block
    )
    joined = _joined(lines)
    # Same content, moved into the character block: exactly once.
    assert joined.count(block.strip()) == 1
    # Budget separation (renderer-budget separation design 2026-11-04):
    # with capability attached, the voice unit now SURVIVES — this
    # assertion previously pinned the voice-drop and is intentionally
    # reversed here, citing the design doc. The capability still
    # sits inside the character block (not downstream), and the
    # revised judgment still renders.
    assert VOICE_COMPACT_MARKER in joined
    assert "You notice floors first" in joined


def test_branch_downstream_sections_preserved_on_path(monkeypatch):
    import local_ai.council.naming as N

    monkeypatch.setattr(N, "get_display_name", lambda uid, aid: "Guardian")
    lines, _ = build_voice_prompt(
        "u1", "guardian", "hello",
        [{"role": "user", "content": f"turn {i}"} for i in range(12)],
        mode="base", question=True,
        extra_instructions="FRAME: " + "x" * R._EXTRA_INSTRUCTIONS_CAP,
        fellowship_reference="Fellowship knowledge. " * 10,
        thread_summary="Prior thread summary.",
        context_hint="evening, low battery",
    )
    joined = _joined(lines)
    assert lines[0].startswith(CANONICAL_MARKER)
    assert "do not answer or respond directly" in joined  # question block
    assert "Fellowship knowledge." in joined  # reference uncapped
    assert ("x" * R._EXTRA_INSTRUCTIONS_CAP) not in joined  # frame cap still applies
    assert any(len(line) == R._EXTRA_INSTRUCTIONS_CAP for line in lines)  # cap raised 8000 -> 9000 (read-back, 2026-11-06)
    assert "Prior thread summary." in joined
    assert "Live context: evening, low battery" in joined
    assert "don't remember" in joined  # continuity floor, long history


def test_branch_custom_name_address_line(monkeypatch):
    import local_ai.council.naming as N

    # Lookup returns a visitor-chosen name → clause exactly once.
    monkeypatch.setattr(N, "get_display_name", lambda uid, aid: "Bram")
    lines, _ = build_voice_prompt("u1", "guardian", "hello", [], mode="base")
    assert _joined(lines).count("The visitor calls you Bram.") == 1
    # And the opener/trailer use the chosen name on the legacy path
    # only; the canonical path keeps the character identity line.
    assert lines[0].startswith(CANONICAL_MARKER)


# ---------------------------------------------------------------------------
# Naming-guarantee contract
# ---------------------------------------------------------------------------


def test_naming_lookup_contract():
    """Documents what the existing naming lookup actually guarantees
    — and what it does not. Milestone enforcement (25 depth points)
    lives at the API write path: the rename route returns 403 unless
    ``rename_unlocked``. The read path (``get_display_name``) returns
    whatever is stored, without re-verifying depth at read time. The
    renderer honors that contract by taking no visitor-state input
    (see test_renderer_naming_authorized_only); it adds no second
    permission system, and the residual (a name written outside the
    API route would be honored) is reported in the PR description."""
    from local_ai.council import naming as N

    # No user → stock name, closed by default.
    assert N.get_display_name(None, "guardian") == "Guardian"
    status = N.rename_status(None)
    assert status["rename_threshold"] == 25.0
    assert all(not e["rename_unlocked"] for e in status["archetypes"])
    guardian_entry = next(e for e in status["archetypes"] if e["id"] == "guardian")
    assert guardian_entry["depth"] == 0.0
    assert guardian_entry["signals_to_unlock"] == 25


def test_naming_prompt_level_stock_vs_authorized(monkeypatch):
    import local_ai.council.naming as N

    # Lookup returns stock → no address clause anywhere.
    monkeypatch.setattr(N, "get_display_name", lambda uid, aid: "Guardian")
    lines, _ = build_voice_prompt("u1", "guardian", "hello", [], mode="base")
    assert not any("calls you" in l for l in lines)
    # Lookup returns a visitor-chosen name → clause exactly once.
    monkeypatch.setattr(N, "get_display_name", lambda uid, aid: "Bram")
    lines, _ = build_voice_prompt("u1", "guardian", "hello", [], mode="base")
    assert _joined(lines).count("The visitor calls you Bram.") == 1


# ---------------------------------------------------------------------------
# Encounter eligibility (encounter's OWN material) + resolver contract
# ---------------------------------------------------------------------------


def test_encounter_material_excludes_protected_fields():
    """The encounter's own SCRIPT fields carry no protected §1.7
    material. The Gardener correction (2026-11-07, founder verdict
    G4/D1) removed the `Shadow:` label from all seven first-meeting
    slices system-wide — overriding the earlier scoping that said
    removal \"belongs to the separate fellowship-reference review\".
    No `Shadow:` label remains in any meeting frame; the adopted
    shadow formulation stays protected and appears nowhere in
    encounter material. (Meeting-turn prompts via the shared builder's
    legacy character block are likewise out of scope, preserved
    byte-identical by the canonical gate.)"""
    from local_ai.conversation import encounter as ENC
    from local_ai.council import meetings as MT

    script = MT.get_script("guardian", 1)
    assert script is not None
    assert script.character == "Bear"
    assert script.demeanor == (
        "Steady, sheltering; slow to move, impossible to move once moved."
    )
    assert len(script.opening) == 7
    assert script.opening[0] == (
        "Well, don't just stand there in the doorway! Come in, come in. "
        "There's a fire going, and I believe we've enough supper for another."
    )
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
        # Gardener correction (2026-11-07, G4/D1): no Shadow: label
        # remains in any first-meeting slice.
        assert frame.count("Shadow: smothering.") == 0
        # The ADOPTED shadow formulation appears nowhere in encounter material.
        assert "protection that has become retention" not in frame
        assert "can no longer leave, grow, or stand independently" not in frame
        assert "because you hold on too tight" not in frame
        for name in PHILOSOPHER_NAMES:
            assert name not in frame, name


def test_resolver_contract_already_resolved_and_clean():
    """The resolver supplies already-resolved guidance: available
    caps render available-but-unverified (never playtest-verified),
    and the block carries no protected formulations. The renderer
    trusts this output because the resolver — not the model, not
    the renderer — determined availability and authorization. The
    never_observed entry renders with its policy-guarantee
    parenthetical — it is never presented as a user-facing
    control."""
    state = CAP.VisitorState(signed_in=True, consent_acknowledged=True)
    block = CAP.continuation_block("guardian", state)
    assert block.strip()
    for phrase in PROTECTED_PHRASES:
        assert phrase not in block, phrase
    # The guardian slice renders exactly the 5 exemplar capabilities.
    for name in (
        "Redaction at capture",
        "Consent-scope enforcement",
        "Consent onboarding gate",
        "Per-scope toggles",
        "Never observed",
    ):
        assert name in block, name
    # Available-but-unverified rendering, never a finished-product promise.
    assert block.count("available (workflow not yet verified)") == 5
    # Never observed is labeled a policy guarantee, not a toggle.
    assert "not a configurable setting or toggle" in block
    cap = CAP.get_capability("never_observed")
    assert cap is not None
    assert cap.implementation == "available"
    assert cap.verification == "unverified"
    # Unsigned state renders the same slice with one gated line.
    unsigned = CAP.continuation_block(
        "guardian", CAP.VisitorState(signed_in=False, consent_acknowledged=False)
    )
    assert unsigned.count("not available to you yet") == 1


def test_weights_untouched_and_no_vector_in_record():
    """Strand weights are a fixed registry vector, not record
    content: the record carries a prose note only, and the legacy
    strand-blend computation is unchanged (the gate-OFF prompt
    equals the legacy oracle, blend lines included — see
    test_branch_gate_off_equals_exact_legacy_prompt)."""
    assert "strand_weights" not in BEAR_RECORD["characterization"]
    weights_field = BEAR_RECORD["identity"]["strand_weights"]
    assert isinstance(weights_field["text"], str)
    assert not isinstance(weights_field.get("vector"), (dict, list))


def test_renderer_budget_separation_2026_11_04():
    """Pins renderer-budget separation (design 2026-11-04) §(e) 2, 4,
    6, 7, 8 for Bear, with REAL continuation guidance: judgment +
    voice + range survive with guidance attached; order is
    identity → personality → worldview → capability → voice;
    fuller + guidance still falls back to compact (a character-only
    overrun, unchanged by separation); no old compulsory phrases,
    no cross-seat naming, protected material excluded; and the
    character-only ceiling still raises AssemblyError independent
    of guidance.
    """
    signed = CAP.continuation_block(
        "guardian", CAP.VisitorState(signed_in=True, consent_acknowledged=True)
    ).strip()
    assert len(signed) == 491, len(signed)

    # §(e)2: compact + guidance, total exactly 1,935.
    compact = render_bear_ordinary(
        BEAR_RECORD, detail="compact", resolved_capability=signed
    )
    joined = _joined(compact)
    assert len(joined) == 1935
    for sentence in (
        "what must survive, who holds a key, what is quietly draining",  # judgment
        "reconsider where that floor belongs when the facts change",  # judgment (refinement 3)
        "easy warmth and unhurried rhythm of Southern hospitality",  # voice (refinement 2)
        "welcome warmly and unhurriedly",  # range
        "hold a named floor steady when it is crossed",  # range
    ):
        assert sentence in joined, sentence
    # §(e)6: order, compact and fuller-fallback.
    assert compact[3] == signed
    assert VOICE_COMPACT_MARKER in compact[4]
    fuller = render_bear_ordinary(
        BEAR_RECORD, detail="fuller", resolved_capability=signed
    )
    assert len(_joined(fuller)) == 1935  # §(e)7: compact + guidance
    assert fuller[3] == signed
    for marker in FULLER_MIDDLE_MARKERS:
        assert marker not in _joined(fuller), marker
    # §(e)8: no old compulsory phrases, no cross-seat naming, protected excluded.
    for phrase in (
        "supper on the table, a roof over everybody's head",
        "I'm not going anywhere",
        "tremendously joyful in welcome",
    ):
        assert phrase not in joined, phrase
    assert "Firebrand" not in joined
    for phrase in PROTECTED_PHRASES:
        assert phrase not in joined, phrase

    # §(e)4: character-only ceiling still holds, with and without guidance.
    bloated = copy.deepcopy(BEAR_RECORD)
    bloated["characterization"]["personality"]["render_text"] = (
        "A very long personality sentence. " * 100
    )
    with pytest.raises(AssemblyError):
        render_bear_ordinary(bloated, detail="compact")
    with pytest.raises(AssemblyError):
        render_bear_ordinary(
            bloated, detail="compact", resolved_capability=signed
        )


# ---------------------------------------------------------------------------
# S2 — Bear flow-loop guidance (flow architecture §3 S2, level (a) only)
# ---------------------------------------------------------------------------
# The loop is prompt guidance, not canonical content: it rides in
# reply.py gated on bear_canonical (ordinary Talk only), never in
# BEAR_RECORD, never on the meeting path, never on another seat.
# Deterministic prompt inspection only — no model calls, no trial.
# "decision" is deliberately NOT in the forbidden list below: the
# guidance says "a decision already reached and left to stand" —
# the user's decision in the conversation, not the decisions table.

S2_GUIDANCE = R._BEAR_FLOW_LOOP_GUIDANCE


def test_s2_guidance_present_once_on_bear_talk(monkeypatch):
    import local_ai.council.naming as N

    monkeypatch.setattr(N, "get_display_name", lambda uid, aid: "Guardian")
    lines, _ = build_voice_prompt("u1", "guardian", "hello", [], mode="base")
    joined = _joined(lines)
    assert joined.count(S2_GUIDANCE) == 1
    # Assembly order: after the character block, before the
    # no-training note — guidance sits with how Bear works, not
    # with the transcript.
    assert lines.index(S2_GUIDANCE) < lines.index(NO_TRAINING_NOTE)
    assert lines[0].startswith(CANONICAL_MARKER)


def test_s2_guidance_length_pinned():
    # 1,498 chars. Pinned so a silent edit to the guidance is
    # caught here, not discovered in a trial.
    assert len(S2_GUIDANCE) == 1498, len(S2_GUIDANCE)


def test_s2_guidance_not_in_canonical_record():
    # Insertion-point decision, pinned: the loop is guidance, not
    # character. The renderer output is unchanged by S2.
    assert S2_GUIDANCE not in _joined(
        render_bear_ordinary(BEAR_RECORD, detail="compact")
    )
    assert S2_GUIDANCE not in _joined(
        render_bear_ordinary(BEAR_RECORD, detail="fuller")
    )


def test_s2_guidance_content_fences():
    # Functions, not a sequence; both directions, no default; no
    # mandatory classification; no complete loop required; Rest /
    # Release / Continue in Bear's own words.
    for required in (
        "none of them a sequence and none of them required",
        "Skip or combine these as the moment calls for",
        "press harder where the circumstances warrant it",
        "never default to one direction",
        "You need not name their state",
        "you need not assess on every turn",
        "let an insight stand",
        "let the exchange rest",
        "let the visitor go",
        "a turn that ends after one useful suggestion is complete",
        "work from that alone",
        "Never re-ask what the visitor has already established",
    ):
        assert required in S2_GUIDANCE, required
    # No node-record evidence, no score, no stage, no procedure
    # language, no protected material.
    for forbidden in (
        "due date",
        "commitment",
        "proposal",
        "vitality",
        "execution_flow_reading",
        "score",
        "stage",
        "Step 1",
        "step 1",
        "checklist",
        "must complete",
    ):
        assert forbidden not in S2_GUIDANCE, forbidden
    for phrase in PROTECTED_PHRASES:
        assert phrase not in S2_GUIDANCE, phrase


def test_s2_guidance_absent_on_meeting_path(monkeypatch):
    for cutover in (True, False):
        monkeypatch.setattr(R, "BEAR_CANONICAL_CUTOVER", cutover)
        lines, _ = build_voice_prompt(
            "u1", "guardian", "hello", [], mode="base", canonical=False
        )
        assert S2_GUIDANCE not in _joined(lines)


def test_s2_guidance_absent_on_other_seats(monkeypatch):
    for seat in (
        "mentor",
        "champion",
        "maverick",
        "ambassador",
        "conductor",
        "skeptic",
    ):
        lines, _ = build_voice_prompt("u1", seat, "hello", [], mode="base")
        assert S2_GUIDANCE not in _joined(lines), seat


def test_s2_guidance_absent_when_cutover_off(monkeypatch):
    monkeypatch.setattr(R, "BEAR_CANONICAL_CUTOVER", False)
    lines, _ = build_voice_prompt("u1", "guardian", "hello", [], mode="base")
    assert S2_GUIDANCE not in _joined(lines)
