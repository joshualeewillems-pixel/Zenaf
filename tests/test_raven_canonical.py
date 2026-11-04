"""Raven-only canonical implementation (plan §8 tests).

Covers: record integrity, the two-check eligibility matrix, renderer
order/budgets/exclusions/naming/capability gating, the reply.py
replacement branch (gate ON vs gate OFF, six-seat golden comparisons,
meeting-path preservation), the single-source assembly invariant
(full-prompt comparisons), the milestone-authorized naming contract,
encounter-material eligibility, and the capability-resolver contract.

No model calls, no generations, no staging changes anywhere here:
every test is deterministic prompt inspection.

Scope notes (read before "fixing" a failure by weakening a test):

- The legacy ``philosophy_prompt_lines`` function is INTENTIONALLY
  untouched (frozen rollback source, plan §9). Its output still
  contains shadow/tension lines; the canonical branch bypasses it
  for ordinary Raven turns instead of modifying it. There is
  deliberately NO test asserting it returns ideal+question only.
- Meeting turns (canonical=False) keep the exact legacy assembly,
  including its philosophy lines. The encounter-eligibility test pins
  the encounter's OWN material (scripts + frames), which carries
  exactly ONE known pre-existing draft exception (below); the
  shared builder's legacy block on meeting turns is out of scope
  for this plan and is preserved byte-identical by the canonical gate.
- The Raven first meeting's availability is NOT decided here: on
  current main the script is registered (PR #274 all-six release)
  and RELEASED_FIRST_MEETING_SEATS includes "skeptic" — the
  exemplar's "written but not released" note is stale, superseded
  by #274. This implementation changes nothing about meetings or
  availability; the plan's SCRIPTS exclusion is honored by the
  four-file diff, not by re-litigating #274.
- The naming lookup (``get_display_name``) does NOT re-verify the
  25-depth milestone at read time: milestone enforcement lives at
  the API write path (403 unless ``rename_unlocked``). The renderer
  therefore takes no visitor-state argument at all — it formats
  only the lookup's result, passed by the call site. The
  naming-guarantee tests pin that contract (see
  test_naming_lookup_contract); a name written outside the API
  route would be honored by the read path, and that residual is
  reported in the PR description rather than papered over with a
  second permission system.
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
    compute_skeptic_weights,
)
from local_ai.council.canonical.raven import RAVEN_RECORD
from local_ai.council.render import (
    CHARACTER_CEILING,
    AssemblyError,
    eligible_field,
    eligible_fields,
    render_raven_ordinary,
)

# Distinctive protected formulations. Deliberately specific phrases,
# not generic words ("shadow" alone would false-positive on innocent
# prose): these are the formulations that must never reach an
# ordinary prompt. The paraphrase entry is the plan's semantic case:
# the same diagnosis in different words.
PROTECTED_PHRASES = (
    "finds deception where none exists",
    "finding deception where none exists",
    "paralysis and cynicism",
    "mistaking disbelief for intelligence",
    "Shadow — your characteristic failure mode",
    "Shadow:",
    "habitually imagine dishonesty where there is only confusion",
)

PHILOSOPHER_NAMES = ("Socrates", "Nietzsche", "Hume")

# Picture figures: embodied, never named, per exemplar §2.
PICTURE_NAMES = ("Holmes", "Snape", "Poe")

# Illustrative-speech fragments: the femur speech is illustration
# reference only and must never appear as renderer output. (The
# canonical macabre sentence about "a beautiful theory's unfortunate
# anatomy" is DIFFERENT text and legitimately present.)
SPEECH_FRAGMENTS = (
    "Fragile? Curious choice of words",
    "Most people don't break under pressure",
    "applied somewhere inconvenient",
)

LEGACY_MARKERS = (
    "Foundational ideal:",
    "Defining question (your instinctive first move",
    "Shadow — your characteristic failure mode",
    "Live tension with the other seats:",
    "Archetype: Skeptic",
    "a voice in the user's Zenaf council",
    "Your warmth register: none",
)

CANONICAL_MARKER = "You are the Raven, who occupies the Skeptic seat"

IDEAL_VERBATIM = (
    "Truth through examination — separate observation from "
    "interpretation, evidence from conviction; discover what "
    "survives scrutiny."
)
QUESTION_VERBATIM = "What are we assuming?"
DOMAIN_TENSION = (
    "You seek the distinction between a claim that survives "
    "examination and one that merely survives repetition."
)
SUPERSEDED_TENSION = (
    "relentless doubt can become its own refusal to see"
)
WARMTH_ADOPTED = (
    "You rarely express warmth directly. Concern appears through "
    "exacting attention, reluctant assistance, and questions worth "
    "asking — not reassurance or easy agreement. Let the state of "
    "the claim set the register: when the premises are clean, move "
    "on; when an elegant theory is failing, allow the dry delight; "
    "never manufacture certainty or soften a necessary finding."
)
EXAMINATION_PREFERENCE = (
    "You favor penetrating questions, but a precise observation can "
    "be more devastating than an interrogation. Macabre or forensic "
    "notes appear only when a real seam has been found; they are "
    "never atmosphere."
)
TEMPO_CLOSE = 'Slow at the claim, fast everywhere else, with a pause before "are we sure?"'
MACABRE_SENTENCE = (
    "You take a dry, occasionally macabre delight in what evidence "
    "reveals. An inconvenient fact can amuse you considerably, "
    "particularly when it exposes a beautiful theory's unfortunate "
    "anatomy."
)
FULLER_DEVELOPMENT_MARKERS = (
    "You notice contradictions first",
    "Every conclusion leaves fingerprints",
    "anatomy of a collapsing argument",
)

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
    assert RAVEN_RECORD["seat_id"] == "skeptic"
    assert set(RAVEN_RECORD) == {
        "seat_id", "identity", "philosophy", "characterization",
        "jurisdiction", "relationships", "narrative", "capabilities",
        "protected",
    }
    assert set(RAVEN_RECORD["identity"]) == {
        "role", "character", "personal_name", "visual_identity",
        "pronouns", "voice_color", "strand_weights",
    }
    assert set(RAVEN_RECORD["philosophy"]) == {
        "ideal", "defining_question", "primary_influences",
        "per_thinker_contributions", "secondary_influences",
        "opposing_influences", "foundations_not_constraints",
    }
    assert set(RAVEN_RECORD["characterization"]) == {
        "temperament", "personality", "personality_fuller_development",
        "demeanor", "perceptual_habit", "intellectual_territory",
        "honesty_rule", "expressive_terrain", "domain_tension",
        "governing_conviction", "voice_and_humor", "warmth", "tempo",
        "friction", "implied_history", "established_biography",
        "invariants", "expressive_defaults",
    }
    assert set(RAVEN_RECORD["jurisdiction"]) == {
        "primary_concerns", "adjacent_concerns", "boundaries",
        "relationships",
    }
    assert RAVEN_RECORD["relationships"] == {}
    assert set(RAVEN_RECORD["narrative"]) == {
        "first_encounter", "encounter_conduct", "impression_gate",
        "revealed_identity", "availability", "six_seat_unlock",
        "later_discoveries", "orientation",
    }
    assert set(RAVEN_RECORD["capabilities"]) == {
        "review_intake", "review_insights_ui", "anchored_evidence",
        "contest_read", "recurrence", "blend_view",
    }
    assert set(RAVEN_RECORD["protected"]) == {
        "developmental_knowledge", "shadow",
    }


def test_record_fields_carry_standing_and_category():
    for section, key, field in _walk_fields(RAVEN_RECORD):
        assert field["standing"] in {
            "adopted", "provisional", "open", "unselected",
        }, (section, key)
        assert field["category"] in {
            "identity", "conviction", "characterization", "protected",
            "relational", "provenance", "jurisdiction", "capability",
            "narrative",
        }, (section, key)


def test_record_core_values_verbatim():
    assert RAVEN_RECORD["philosophy"]["ideal"]["text"] == IDEAL_VERBATIM
    assert RAVEN_RECORD["philosophy"]["defining_question"]["text"] == QUESTION_VERBATIM
    assert RAVEN_RECORD["characterization"]["domain_tension"]["text"] == DOMAIN_TENSION
    assert RAVEN_RECORD["characterization"]["warmth"]["text"] == WARMTH_ADOPTED
    assert RAVEN_RECORD["characterization"]["voice_and_humor"]["text"] == EXAMINATION_PREFERENCE
    assert RAVEN_RECORD["characterization"]["demeanor"]["text"] == (
        "Flint-eyed, unimpressed by performance; asks the question no one wants."
    )
    assert RAVEN_RECORD["identity"]["role"]["text"] == "Skeptic"
    assert RAVEN_RECORD["identity"]["character"]["text"] == "Raven"
    assert RAVEN_RECORD["identity"]["personal_name"]["default"] == "unselected"
    assert RAVEN_RECORD["identity"]["personal_name"]["favorites"] == ["Severin", "Vance"]
    # Gender verdict 2026-11-01 (Joshua's concurrence): Raven is she/her.
    # The builder's "he / him" pin predates the verdict and is stale.
    assert RAVEN_RECORD["identity"]["pronouns"]["text"] == "she / her"
    # Protected section present, with the adopted Option A shadow.
    assert "finds deception where none exists" in (
        RAVEN_RECORD["protected"]["developmental_knowledge"]["text"]
    )
    assert RAVEN_RECORD["protected"]["shadow"]["standing"] == "adopted"
    assert RAVEN_RECORD["protected"]["shadow"]["category"] == "protected"
    # The live legacy line is NOT stored as content anywhere.
    for _, _, field in _walk_fields(RAVEN_RECORD):
        text = field.get("text")
        if isinstance(text, str):
            assert "Paralysis and cynicism" not in text, field
    # Per-thinker contributions: open, not invented.
    assert RAVEN_RECORD["philosophy"]["per_thinker_contributions"]["text"] is None
    # No adopted relationship records.
    assert RAVEN_RECORD["jurisdiction"]["relationships"]["text"] is None
    # Capability ids match the registry exactly (no invented ids).
    assert set(RAVEN_RECORD["capabilities"]) == {
        c.id for c in CAP.seat_slice("skeptic")
    }
    # Registry states match the registry exactly.
    for cap_id, entry in RAVEN_RECORD["capabilities"].items():
        cap = CAP.get_capability(cap_id)
        assert cap is not None, cap_id
        assert entry["registry_state"] == cap.implementation, cap_id
        assert entry["verification"] == cap.verification, cap_id
    # Strand weights: an architectural note, never a vector.
    assert "compute_skeptic_weights" in (
        RAVEN_RECORD["identity"]["strand_weights"]["text"]
    )


def test_rendering_never_mutates_record():
    before = copy.deepcopy(RAVEN_RECORD)
    render_raven_ordinary(RAVEN_RECORD, detail="compact")
    render_raven_ordinary(
        RAVEN_RECORD, authorized_name="Severin", detail="fuller",
        resolved_capability="Background knowledge — Review queue.",
    )
    assert RAVEN_RECORD == before


# ---------------------------------------------------------------------------
# Eligibility matrix (two independent checks) + inventory
# ---------------------------------------------------------------------------

EXPECTED_ELIGIBLE = {
    ("philosophy", "ideal"),
    ("philosophy", "defining_question"),
    ("philosophy", "foundations_not_constraints"),
    ("characterization", "temperament"),
    ("characterization", "personality"),
    ("characterization", "personality_fuller_development"),
    ("characterization", "demeanor"),
    ("characterization", "perceptual_habit"),
    ("characterization", "intellectual_territory"),
    ("characterization", "honesty_rule"),
    ("characterization", "expressive_terrain"),
    ("characterization", "domain_tension"),
    ("characterization", "governing_conviction"),
    ("characterization", "voice_and_humor"),
    ("characterization", "warmth"),
    ("characterization", "tempo"),
    ("characterization", "friction"),
    ("characterization", "implied_history"),
}


def test_eligibility_matrix():
    eligible = set(eligible_fields(RAVEN_RECORD))
    # Adopted + conviction → eligible.
    assert ("philosophy", "ideal") in eligible
    assert ("philosophy", "defining_question") in eligible
    assert ("characterization", "domain_tension") in eligible
    assert ("characterization", "governing_conviction") in eligible
    assert ("characterization", "honesty_rule") in eligible
    # Adopted + characterization → eligible.
    assert ("characterization", "temperament") in eligible
    assert ("characterization", "demeanor") in eligible
    assert ("characterization", "warmth") in eligible
    assert ("characterization", "voice_and_humor") in eligible
    # Adopted + protected → EXCLUDED despite adopted standing.
    assert ("protected", "shadow") not in eligible
    assert ("protected", "developmental_knowledge") not in eligible
    # Provisional + narrative → EXCLUDED.
    assert ("narrative", "orientation") not in eligible
    # Open + provenance → EXCLUDED.
    assert ("philosophy", "per_thinker_contributions") not in eligible
    assert ("philosophy", "secondary_influences") not in eligible
    # Adopted + provenance → EXCLUDED (names never reach prompts).
    assert ("philosophy", "primary_influences") not in eligible
    # Adopted + jurisdiction/narrative/capability → EXCLUDED from the
    # ordinary renderer (other renderers/sections own those).
    assert ("jurisdiction", "primary_concerns") not in eligible
    assert ("narrative", "first_encounter") not in eligible
    assert ("capabilities", "review_intake") not in eligible
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
    assert set(eligible_fields(RAVEN_RECORD)) == EXPECTED_ELIGIBLE


def test_eligible_field_refuses_both_failed_checks():
    # Standing flip on an essential field removes it → loud failure.
    record = copy.deepcopy(RAVEN_RECORD)
    record["characterization"]["domain_tension"]["standing"] = "provisional"
    assert eligible_field(record, "characterization", "domain_tension") is None
    with pytest.raises(AssemblyError):
        render_raven_ordinary(record, detail="compact")
    # Category flip on an essential field removes it → loud failure.
    record = copy.deepcopy(RAVEN_RECORD)
    record["characterization"]["temperament"]["category"] = "protected"
    assert eligible_field(record, "characterization", "temperament") is None
    with pytest.raises(AssemblyError):
        render_raven_ordinary(record, detail="compact")


def test_capability_description_in_record_cannot_reach_output():
    """Screening by construction: the renderer never reads record
    capability text, so a poisoned description has no path to output."""
    record = copy.deepcopy(RAVEN_RECORD)
    record["capabilities"]["review_intake"]["description"] = (
        "finding deception where none exists; paralysis and cynicism."
    )
    baseline = render_raven_ordinary(RAVEN_RECORD, detail="fuller")
    poisoned = render_raven_ordinary(record, detail="fuller")
    assert poisoned == baseline
    assert "finds deception where none exists" not in _joined(poisoned)


# ---------------------------------------------------------------------------
# Renderer: order, budgets, exclusions, naming, capability gating
# ---------------------------------------------------------------------------


def test_renderer_order_identity_personality_worldview_capability():
    block = render_raven_ordinary(
        RAVEN_RECORD, detail="compact",
        resolved_capability="Background knowledge — Review queue.",
    )
    joined = _joined(block)
    anchors = [
        CANONICAL_MARKER,
        "difficult to impress",
        IDEAL_VERBATIM,
        "Background knowledge — Review queue.",
        "You rarely express warmth directly",
    ]
    positions = [joined.index(a) for a in anchors]
    assert positions == sorted(positions), positions


def test_renderer_budgets_compact_and_fuller_exact():
    """Assembled blocks reproduce exemplar §2 exactly (same sentences,
    same order): compact 1,240 chars, fuller 1,490 chars, both under
    the 1,500 ceiling. Byte-length equality is the conformance check,
    not a coincidence target — the unit texts are the exemplar texts.
    NOTE (budget-separation fix, founder decision 2026-11-04): the
    compact pin is updated to the true 1,240-char compact block, but
    the fuller pin and development markers are INTENTIONALLY left at
    the non-degraded values — the fuller character block overruns the
    ceiling on its own and falls back, which is out of scope for the
    signed-in voice fix (same class as Bear's fuller). This test
    therefore still fails on the fuller assertions; that failure is
    the known residual, not a regression. Do NOT update the fuller
    pin to the degraded value (that would bless the degradation)."""
    compact = render_raven_ordinary(RAVEN_RECORD, detail="compact")
    fuller = render_raven_ordinary(RAVEN_RECORD, detail="fuller")
    assert len(_joined(compact)) == 1240, len(_joined(compact))
    assert len(_joined(fuller)) == 1490, len(_joined(fuller))
    assert len(_joined(compact)) < len(_joined(fuller)) <= CHARACTER_CEILING
    # Ideal + defining question verbatim in both.
    assert IDEAL_VERBATIM in _joined(compact)
    assert IDEAL_VERBATIM in _joined(fuller)
    assert QUESTION_VERBATIM in _joined(compact)
    assert QUESTION_VERBATIM in _joined(fuller)
    # Domain tension = adopted discernment sentence in both; the
    # superseded relentless-doubt sentence in neither.
    assert DOMAIN_TENSION in _joined(compact)
    assert DOMAIN_TENSION in _joined(fuller)
    assert SUPERSEDED_TENSION not in _joined(compact)
    assert SUPERSEDED_TENSION not in _joined(fuller)
    # Macabre delight in both; fuller development only in the fuller.
    assert MACABRE_SENTENCE in _joined(compact)
    assert MACABRE_SENTENCE in _joined(fuller)
    for marker in FULLER_DEVELOPMENT_MARKERS:
        assert marker in _joined(fuller), marker
        assert marker not in _joined(compact), marker
    # Tempo close only in the fuller.
    assert TEMPO_CLOSE in _joined(fuller)
    assert TEMPO_CLOSE not in _joined(compact)


def test_renderer_exclusions():
    for detail in ("compact", "fuller"):
        joined = _joined(render_raven_ordinary(RAVEN_RECORD, detail=detail))
        for phrase in PROTECTED_PHRASES:
            assert phrase not in joined, (detail, phrase)
        for name in PHILOSOPHER_NAMES:
            assert name not in joined, (detail, name)
        for name in PICTURE_NAMES:
            assert name not in joined, (detail, name)
        for frag in SPEECH_FRAGMENTS:
            assert frag not in joined, (detail, frag)
        for marker in LEGACY_MARKERS:
            assert marker not in joined, (detail, marker)
        # No capability promises when nothing is invoked.
        assert "Review queue" not in joined
        assert "Blend view" not in joined


def test_renderer_naming_authorized_only():
    # No authorized name → no address clause.
    pre = render_raven_ordinary(RAVEN_RECORD, detail="compact")
    assert not any("calls you" in line for line in pre)
    # Lookup-authorized name → address clause, essence unchanged.
    post = render_raven_ordinary(
        RAVEN_RECORD, authorized_name="Severin", detail="compact"
    )
    assert post[0].endswith("The visitor calls you Severin.")
    assert post[0].startswith(CANONICAL_MARKER)
    assert post[1:] == pre[1:]
    # Empty/whitespace name = not authorized.
    assert render_raven_ordinary(
        RAVEN_RECORD, authorized_name="  ", detail="compact"
    ) == pre
    # The renderer takes NO visitor-state argument: raw state cannot
    # reach it by construction. An unearned name in raw state has no
    # input path here — the call site, not the renderer, owns the
    # lookup (see test_naming_lookup_contract).
    params = inspect.signature(render_raven_ordinary).parameters
    assert "visitor_state" not in params
    assert "authorized_name" in params
    # A non-string name is a contract violation, not a fallback.
    with pytest.raises(TypeError):
        render_raven_ordinary(RAVEN_RECORD, authorized_name={"name": "Severin"})


def test_renderer_capability_gating():
    without = render_raven_ordinary(RAVEN_RECORD, detail="compact")
    assert not any("Review queue" in line for line in without)
    with_cap = render_raven_ordinary(
        RAVEN_RECORD, detail="compact",
        resolved_capability="Background knowledge — Review queue.",
    )
    # Capability slots between worldview and voice-close, nothing else moves.
    assert with_cap == without[:3] + ["Background knowledge — Review queue."] + without[3:]
    assert "Background knowledge — Review queue." in _joined(with_cap)
    # Empty/whitespace capability = not invoked.
    assert render_raven_ordinary(
        RAVEN_RECORD, detail="compact", resolved_capability="  "
    ) == without
    # The renderer never interprets raw ids or structures.
    with pytest.raises(TypeError):
        render_raven_ordinary(
            RAVEN_RECORD, detail="compact", resolved_capability={"id": "review_intake"}
        )
    with pytest.raises(ValueError):
        render_raven_ordinary(RAVEN_RECORD, detail="verbose")


def test_renderer_budget_degrades_then_fails_validation():
    from local_ai.council import capabilities as CAP

    signed = CAP.continuation_block(
        "skeptic", CAP.VisitorState(signed_in=True, consent_acknowledged=True)
    ).strip()
    unsigned = CAP.continuation_block(
        "skeptic", CAP.VisitorState(signed_in=False, consent_acknowledged=False)
    ).strip()
    assert signed and unsigned and len(unsigned) > len(signed)

    # Compact + typical (signed-in) guidance: under budget separation
    # (renderer-budget separation design 2026-11-04), the ceiling
    # measures character content ALONE, so the 1,240-char compact
    # block keeps its voice-close unit with the 543-char signed
    # guidance attached: total 1,784, voice renders.
    # INTENTIONAL EXPECTATION REVERSAL, citing the design doc: this
    # block previously asserted the voice-drop (voice absent, total
    # <= ceiling); the separation design reverses that expectation.
    compact_typical = render_raven_ordinary(
        RAVEN_RECORD, detail="compact", resolved_capability=signed
    )
    assert len(_joined(compact_typical)) == 1240 + 1 + len(signed) == 1784
    assert signed in _joined(compact_typical)  # capability never truncated
    assert WARMTH_ADOPTED in _joined(compact_typical)  # voice survives whole
    # Capability sits at index 3 (after worldview), voice-close last.
    assert compact_typical[3] == signed
    assert WARMTH_ADOPTED in compact_typical[4]

    # Fuller + typical guidance: fuller personality degrades to
    # compact — a CHARACTER-only overrun, unchanged by separation —
    # but the voice-close now SURVIVES in the fallback (compact
    # 1,316 + guidance appended whole: total 1,860). (Reversal of
    # the old voice-drop expectation; the development drop itself
    # is unchanged.)
    degraded = render_raven_ordinary(
        RAVEN_RECORD, detail="fuller", resolved_capability=signed
    )
    joined = _joined(degraded)
    assert len(joined) == 1316 + 1 + len(signed) == 1860
    for marker in FULLER_DEVELOPMENT_MARKERS:
        assert marker not in joined, marker  # development dropped whole (character-only)
    assert WARMTH_ADOPTED in joined  # voice survives in the fallback
    assert CANONICAL_MARKER in joined
    assert QUESTION_VERBATIM in joined
    assert signed in joined  # capability never truncated

    # Fuller + maximal (unsigned) guidance: same fallback, voice
    # present, unsigned guidance appended whole regardless of
    # length. (Reversal of the old ceiling-capped expectation.)
    degraded_max = render_raven_ordinary(
        RAVEN_RECORD, detail="fuller", resolved_capability=unsigned
    )
    assert len(_joined(degraded_max)) == 1316 + 1 + len(unsigned) == 1954
    assert unsigned in _joined(degraded_max)
    assert CANONICAL_MARKER in _joined(degraded_max)
    assert QUESTION_VERBATIM in _joined(degraded_max)
    assert WARMTH_ADOPTED in _joined(degraded_max)  # voice survives in the fallback

    # Compact + a huge capability: guidance-length independence
    # (design §(e) test 5) — a 2,000-char guidance string no longer
    # raises AssemblyError and is appended whole. INTENTIONAL
    # REVERSAL of the old huge-guidance failure, documented here
    # rather than hidden: guidance has no size backstop after
    # separation, per the design's §(c) consequence.
    huge = render_raven_ordinary(
        RAVEN_RECORD, detail="compact",
        resolved_capability="x" * (CHARACTER_CEILING + 500),
    )
    assert len(_joined(huge)) == 1240 + 1 + (CHARACTER_CEILING + 500)
    assert WARMTH_ADOPTED in _joined(huge)
    # No unit is ever truncated mid-thought: every character unit ends
    # with terminal punctuation.
    for line in degraded:
        if line.strip() == signed:
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

    monkeypatch.setattr(N, "get_display_name", lambda uid, aid: "Skeptic")
    weights = compute_skeptic_weights("u1", mode="base")
    legacy_lines = build_archetype_prompt_lines(
        "skeptic", weights_override=weights, display_name_override="Skeptic"
    )
    return [
        "You are Skeptic, a voice in the user's Zenaf council, in a direct one-on-one conversation.",
        "",
        *legacy_lines,
        "",
        NO_TRAINING_NOTE,
        "",
        KEEP_REPLIES,
        "User: hello",
        "Skeptic:",
    ]


def test_branch_gate_on_replaces_character_block_only(monkeypatch):
    import local_ai.council.naming as N

    monkeypatch.setattr(N, "get_display_name", lambda uid, aid: "Skeptic")
    monkeypatch.setattr(R, "RAVEN_CANONICAL_CUTOVER", True)
    lines, meta = build_voice_prompt("u1", "skeptic", "hello", [], mode="base")
    joined = _joined(lines)
    # Canonical block present, in order.
    assert lines[0].startswith(CANONICAL_MARKER)
    assert "difficult to impress" in joined
    assert MACABRE_SENTENCE in joined
    assert IDEAL_VERBATIM in joined
    assert QUESTION_VERBATIM in joined
    assert DOMAIN_TENSION in joined
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
    assert lines[-1] == "Skeptic:"
    assert meta["archetype_id"] == "skeptic"


def test_branch_gate_off_equals_exact_legacy_prompt(monkeypatch):
    monkeypatch.setattr(R, "RAVEN_CANONICAL_CUTOVER", False)
    lines, _ = build_voice_prompt("u1", "skeptic", "hello", [], mode="base")
    assert lines == _legacy_minimal_prompt(monkeypatch)
    # EXPLICIT legacy assertion (plan §8 addition): the old shadow
    # and tension lines are PRESENT exactly in the OFF branch. They
    # are unacceptable in the canonical branch and intentional here
    # — the rollback branch is frozen, not sanitized.
    joined = _joined(lines)
    assert (
        "Shadow — your characteristic failure mode, which the Skeptic "
        "may name: Paralysis and cynicism: mistaking disbelief for "
        "intelligence."
    ) in joined
    assert (
        "Live tension with the other seats: Suspects everyone's "
        "motives — the Ambassador's harmony, the Champion's certainty "
        "— that's the job."
    ) in joined


def test_branch_meeting_path_keeps_exact_legacy_prompt(monkeypatch):
    # Meeting turns (canonical=False) are out of scope: identical under
    # both cutover settings, and exactly the legacy assembly.
    for cutover in (True, False):
        monkeypatch.setattr(R, "RAVEN_CANONICAL_CUTOVER", cutover)
        lines, _ = build_voice_prompt(
            "u1", "skeptic", "hello", [], mode="base", canonical=False
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


def test_branch_six_seats_byte_identical_and_cutover_independent(monkeypatch):
    for seat in ("mentor", "champion", "guardian", "maverick", "ambassador", "conductor"):
        prompts = {}
        for cutover in (True, False):
            monkeypatch.setattr(R, "RAVEN_CANONICAL_CUTOVER", cutover)
            lines, _ = build_voice_prompt("u1", seat, "hello", [], mode="base")
            prompts[cutover] = lines
        assert prompts[True] == prompts[False], seat
        joined = _joined(prompts[True])
        assert CANONICAL_MARKER not in joined, seat


def test_branch_capability_moved_not_duplicated(monkeypatch):
    import local_ai.council.naming as N

    monkeypatch.setattr(N, "get_display_name", lambda uid, aid: "Skeptic")
    block = CAP.continuation_block(
        "skeptic", CAP.VisitorState(signed_in=True, consent_acknowledged=True)
    )
    assert block.strip()
    lines, _ = build_voice_prompt(
        "u1", "skeptic", "hello", [], mode="base", capability_context=block
    )
    joined = _joined(lines)
    # Same content, moved into the character block: exactly once.
    assert joined.count(block.strip()) == 1
    # And it sits before the voice-close/trailer region, not downstream.
    assert joined.index(block.strip()) < joined.index("You rarely express warmth directly")


def test_branch_downstream_sections_preserved_on_path(monkeypatch):
    import local_ai.council.naming as N

    monkeypatch.setattr(N, "get_display_name", lambda uid, aid: "Skeptic")
    lines, _ = build_voice_prompt(
        "u1", "skeptic", "hello",
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

    monkeypatch.setattr(N, "get_display_name", lambda uid, aid: "Severin")
    lines, _ = build_voice_prompt("u1", "skeptic", "hello", [], mode="base")
    assert lines[0].endswith("The visitor calls you Severin.")
    assert lines[-1] == "Severin:"  # trailer mechanics unchanged
    # Exactly once: the address clause is not duplicated downstream.
    assert _joined(lines).count("The visitor calls you Severin.") == 1


# ---------------------------------------------------------------------------
# Single-source assembly invariant (complete prompts, not renderer only)
# ---------------------------------------------------------------------------


def test_full_prompt_single_source_invariant(monkeypatch):
    import local_ai.council.naming as N

    monkeypatch.setattr(N, "get_display_name", lambda uid, aid: "Skeptic")
    block = CAP.continuation_block(
        "skeptic", CAP.VisitorState(signed_in=True, consent_acknowledged=True)
    ).strip()
    lines, _ = build_voice_prompt(
        "u1", "skeptic", "hello", [], mode="base", capability_context=block
    )
    joined = _joined(lines)
    # Every character unit exactly once.
    assert joined.count(CANONICAL_MARKER) == 1
    assert joined.count(IDEAL_VERBATIM) == 1
    assert joined.count(QUESTION_VERBATIM) == 1
    # Authorized capability guidance exactly once (proving the call
    # site passed it into the renderer and the downstream append was
    # correctly skipped — not silently dropped, not duplicated).
    assert joined.count(block) == 1
    # Legacy character material absent at prompt level.
    for marker in LEGACY_MARKERS:
        assert marker not in joined, marker
    # Unrelated sections unchanged.
    assert NO_TRAINING_NOTE in lines
    assert not any("[[u]]" in l or "wrap those exact words" in l for l in lines)
    assert KEEP_REPLIES in lines


def test_full_prompt_no_capability_no_section(monkeypatch):
    import local_ai.council.naming as N

    monkeypatch.setattr(N, "get_display_name", lambda uid, aid: "Skeptic")
    lines, _ = build_voice_prompt("u1", "skeptic", "hello", [], mode="base")
    joined = _joined(lines)
    assert joined.count(CANONICAL_MARKER) == 1
    assert joined.count(IDEAL_VERBATIM) == 1
    assert joined.count(QUESTION_VERBATIM) == 1
    # Capability absent → no capability section, no duplicated block.
    assert "Review queue" not in joined
    assert "Blend view" not in joined
    for marker in LEGACY_MARKERS:
        assert marker not in joined, marker


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
    assert N.get_display_name(None, "skeptic") == "Skeptic"
    status = N.rename_status(None)
    assert status["rename_threshold"] == 25.0
    assert all(not e["rename_unlocked"] for e in status["archetypes"])
    skeptic_entry = next(e for e in status["archetypes"] if e["id"] == "skeptic")
    assert skeptic_entry["depth"] == 0.0
    assert skeptic_entry["signals_to_unlock"] == 25


def test_naming_prompt_level_stock_vs_authorized(monkeypatch):
    import local_ai.council.naming as N

    # Lookup returns stock → no address clause anywhere.
    monkeypatch.setattr(N, "get_display_name", lambda uid, aid: "Skeptic")
    lines, _ = build_voice_prompt("u1", "skeptic", "hello", [], mode="base")
    assert not any("calls you" in l for l in lines)
    # Lookup returns a visitor-chosen name → clause exactly once.
    monkeypatch.setattr(N, "get_display_name", lambda uid, aid: "Severin")
    lines, _ = build_voice_prompt("u1", "skeptic", "hello", [], mode="base")
    assert _joined(lines).count("The visitor calls you Severin.") == 1


# ---------------------------------------------------------------------------
# Encounter eligibility (encounter's OWN material) + resolver contract
# ---------------------------------------------------------------------------


def test_encounter_material_excludes_protected_fields():
    """The encounter's own SCRIPT fields carry no protected §1.7
    material. The composed definition frames carry exactly ONE known
    pre-existing draft exception, pinned here so it cannot silently
    grow: the orientation slice (encounter.py, labeled 'draft, not
    canonical', PR #254 draft material) that names 'Shadow:
    paralysis and cynicism.' — the LEGACY shadow, not the adopted
    one. That draft is unadopted content whose replacement belongs
    to the separate fellowship-reference review — removing it here
    would be both a first-encounter behavior change and a content
    decision, both out of scope for this plan. (Meeting-turn prompts
    via the shared builder's legacy character block are likewise out
    of scope, preserved byte-identical by the canonical=False gate.)"""
    from local_ai.conversation import encounter as ENC
    from local_ai.council import meetings as MT

    script = MT.get_script("skeptic", 1)
    assert script is not None
    assert script.character == "Raven"
    assert script.demeanor == (
        "Flint-eyed, unimpressed by performance; asks the question no one wants."
    )
    assert len(script.opening) == 9
    assert script.opening[0] == "Interesting."
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
        # Exactly the one documented draft-reference exception.
        assert frame.count("Shadow: paralysis and cynicism.") == 1
        assert "draft, not canonical" in frame
        # The ADOPTED shadow appears nowhere in encounter material.
        assert "finds deception where none exists" not in frame
        assert "finding deception where none exists" not in frame
        for name in PHILOSOPHER_NAMES:
            assert name not in frame, name


def test_resolver_contract_already_resolved_and_clean():
    """The resolver supplies already-resolved guidance: planned caps
    render planned (never available), gated caps render gated, and
    the block carries no protected formulations. The renderer trusts
    this output because the resolver — not the model, not the
    renderer — determined availability and authorization."""
    state = CAP.VisitorState(signed_in=True, consent_acknowledged=True)
    block = CAP.continuation_block("skeptic", state)
    assert block.strip()
    for phrase in PROTECTED_PHRASES:
        assert phrase not in block, phrase
    # The skeptic slice renders exactly the 6 exemplar capabilities.
    for name in (
        "Review queue — intake candidates",
        "Review queue — personality claims",
        "Anchored evidence",
        "Contesting a read",
        "Recurrence patterns",
        "Blend view",
    ):
        assert name in block, name
    # Planned capabilities are explicitly unavailable, never promised.
    cap = CAP.get_capability("review_insights_ui")
    assert cap is not None and not CAP.currently_usable(cap, state)
    line = next(l for l in block.splitlines() if "personality claims" in l)
    assert "planned, not available yet" in line, line
    # Available capabilities render available.
    assert "Review queue — intake candidates — available" in block


def test_weights_untouched_and_no_vector_in_record():
    """Dynamic weights are behavior, not record content: the record
    carries no weight vector, and the computation is unchanged
    (uniform 1/7 across strands for a user with no approved depth —
    the same default the legacy path has always produced)."""
    assert "strand_weights" not in RAVEN_RECORD["characterization"]
    weights = compute_skeptic_weights("u1", mode="base")
    values = set(weights.values())
    assert len(values) == 1, weights
    assert abs(sum(weights.values()) - 1.0) < 1e-9
    assert set(weights) == {
        "Voice", "Logic", "Eye", "Ear", "Hands", "Heart", "Compass",
    }
