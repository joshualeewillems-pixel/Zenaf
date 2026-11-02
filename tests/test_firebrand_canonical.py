"""Firebrand-only canonical implementation.

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

- The legacy ``philosophy_prompt_lines`` function is INTENTIONALLY
  untouched (frozen rollback source). Its output still contains
  shadow/tension lines; the canonical branch bypasses it for
  ordinary Firebrand turns instead of modifying it. There is
  deliberately NO test asserting it returns ideal+question only.
- Meeting turns (weave=False) keep the exact legacy assembly,
  including its philosophy lines. The encounter-eligibility test
  pins the encounter's OWN material (scripts + frames): the
  script texts carry no protected formulations, while the
  composed definition frames carry exactly ONE known pre-existing
  pattern — the definition line "Shadow: martyrdom." — the
  LEGACY label word, not the adopted picture-record shadow
  formulation. That meeting-path material is out of scope for
  this plan (ordinary renderer only) and is pinned here so it
  cannot silently grow.
- The §2 rendering form of the ideal is a PARAPHRASED conviction
  sentence ("You fight for what costs something — cheap fights
  don't interest you, ..."): the verbatim ideal ("Courage through
  conviction — ...") does NOT appear in §2. The record preserves
  the verbatim ideal as canonical-but-unrendered, and the renderer
  composes the worldview from conviction_paraphrase +
  defining_question + temperament_sentence so the assembled block
  reproduces §2 exactly. §2-exact wins over verbatim-ideal
  insertion (see the PR description).
- Humanism renders through JUDGMENT only ("You weigh every
  position by what it costs the people holding it."), never
  through psychological self-description: the former sentence "a
  humanism works almost despite you" was REMOVED by design.
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
)
from local_ai.council.canonical.firebrand import FIREBRAND_RECORD
from local_ai.council.render import (
    CHARACTER_CEILING,
    AssemblyError,
    eligible_field,
    eligible_fields,
    render_firebrand_ordinary,
)

# Distinctive protected formulations. Deliberately specific phrases,
# not generic words: these are the formulations that must never reach
# an ordinary prompt.
PROTECTED_PHRASES = (
    "needs something worth dying for",
    "what is worth living for",
    "Martyrdom",
    "martyrdom",
    "conflating opposition with evil",
    "manufacturing enemies",
    "because you need something worth dying for",
    "a humanism works almost despite you",
    "humanism",
    "Shadow — your characteristic failure mode",
    "Shadow:",
)

PHILOSOPHER_NAMES = ("Sun Tzu", "Clausewitz")

# Illustrative-speech fragments: the meeting jokes in §1.3 are
# illustration reference only and must never appear as output.
SPEECH_FRAGMENTS = (
    "We've had six meetings about whether to schedule another meeting.",
    "You've prepared seventeen contingency plans",
)

LEGACY_MARKERS = (
    "Foundational ideal:",
    "Defining question (your instinctive first move",
    "Shadow — your characteristic failure mode",
    "Live tension with the other seats:",
    "Archetype: Champion",
    "a voice in the user's Zenaf council",
    "Your warmth register: sparing and direct",
)

CANONICAL_MARKER = "You are the Firebrand, who occupies the Champion seat"

IDEAL_VERBATIM = (
    "Courage through conviction — accept personal cost for what's "
    "worth advancing; courage is meaningful precisely because "
    "something can be lost."
)
CONVICTION_PARAPHRASE = (
    "You fight for what costs something — cheap fights don't interest "
    "you, and you will tell the visitor plainly when a hill isn't "
    "worth dying on."
)
QUESTION_VERBATIM = "What is worth fighting for?"
TEMPERAMENT_SENTENCE = (
    "You are fierce and direct: when a fight is real, you refuse to "
    "let them dither; when it isn't, you refuse to manufacture one."
)
PERSONALITY = (
    "You pick the hill, and you name the price. You speak with the "
    "authority of a battle-worn commander who no longer mistakes "
    "orders for conviction."
)
VOICE_COMPACT_MARKER = "You speak in short declarative sentences"
WARMTH_ADOPTED = (
    "Your warmth is sparing and direct: you acknowledge briefly, then "
    "move to substance — the fight, the hill, the next step."
)
FULLER_ADDITIONAL_MARKERS = (
    "You notice first the hill, the price",
    "You ask whether a fight is deserved before you ask whether it is winnable",
    "Before you draw your sword, decide what victory would actually mean.",
)

COMPACT_PROSE = (
    "You are the Firebrand, who occupies the Champion seat in the Fellowship. "
    "You pick the hill, and you name the price. "
    "You speak with the authority of a battle-worn commander who no longer "
    "mistakes orders for conviction. "
    "You fight for what costs something — cheap fights don't interest you, and "
    "you will tell the visitor plainly when a hill isn't worth dying on. "
    "What is worth fighting for? "
    "You are fierce and direct: when a fight is real, you refuse to let them "
    "dither; when it isn't, you refuse to manufacture one. "
    "You speak in short declarative sentences, in plain words, prices named, "
    "hills named. "
    "Your warmth is sparing and direct: you acknowledge briefly, then move to "
    "substance — the fight, the hill, the next step."
)
FULLER_PROSE = (
    "You are the Firebrand, who occupies the Champion seat in the Fellowship. "
    "You pick the hill, and you name the price. "
    "You speak with the authority of a battle-worn commander who no longer "
    "mistakes orders for conviction. "
    "You fight for what costs something — cheap fights don't interest you, and "
    "you will tell the visitor plainly when a hill isn't worth dying on. "
    "What is worth fighting for? "
    "You are fierce and direct: when a fight is real, you refuse to let them "
    "dither; when it isn't, you refuse to manufacture one. "
    "You notice first the hill, the price, and the moment deliberation tips "
    "into avoidance. "
    "You ask whether a fight is deserved before you ask whether it is winnable "
    "— a worthy cause can justify a hopeless stand, but it does not "
    "automatically require one, and you judge the battle's meaning, cost, and "
    "consequences. "
    "You still believe discipline, sacrifice, and the necessity of conflict; "
    "obedience is not conviction to you. "
    "You weigh every position by what it costs the people holding it. "
    "Before you draw your sword, decide what victory would actually mean."
)

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
    assert FIREBRAND_RECORD["seat_id"] == "champion"
    assert set(FIREBRAND_RECORD) == {
        "seat_id", "identity", "philosophy", "characterization",
        "jurisdiction", "relationships", "narrative", "capabilities",
        "protected",
    }
    assert set(FIREBRAND_RECORD["identity"]) == {
        "role", "character", "personal_name", "visual_identity",
        "pronouns", "voice_color", "strand_weights",
    }
    assert set(FIREBRAND_RECORD["philosophy"]) == {
        "ideal", "defining_question", "primary_influences",
        "per_thinker_contributions", "secondary_influences",
        "opposing_influences", "foundations_not_constraints",
    }
    assert set(FIREBRAND_RECORD["characterization"]) == {
        "temperament", "personality", "demeanor", "perceptual_habit",
        "fuller_additional", "expressive_terrain", "domain_tension",
        "governing_conviction", "conviction_paraphrase",
        "temperament_sentence", "voice_and_humor", "humor_signature",
        "warmth", "friction", "implied_history",
        "established_biography", "invariants", "expressive_defaults",
    }
    assert set(FIREBRAND_RECORD["jurisdiction"]) == {
        "primary_concerns", "adjacent_concerns", "boundaries",
        "relationships",
    }
    assert FIREBRAND_RECORD["relationships"] == {}
    assert set(FIREBRAND_RECORD["narrative"]) == {
        "first_encounter", "encounter_conduct", "impression_gate",
        "revealed_identity", "availability", "six_seat_unlock",
        "later_discoveries", "orientation",
    }
    assert set(FIREBRAND_RECORD["capabilities"]) == {
        "projects_tasks", "commitments", "followthrough_nudges",
    }
    assert set(FIREBRAND_RECORD["protected"]) == {
        "developmental_knowledge", "shadow",
    }


def test_record_fields_carry_standing_and_category():
    for section, key, field in _walk_fields(FIREBRAND_RECORD):
        assert field["standing"] in {
            "adopted", "provisional", "open", "unselected",
        }, (section, key)
        assert field["category"] in {
            "identity", "conviction", "characterization", "protected",
            "relational", "provenance", "jurisdiction", "capability",
            "narrative",
        }, (section, key)


def test_record_core_values_verbatim():
    assert FIREBRAND_RECORD["philosophy"]["ideal"]["text"] == IDEAL_VERBATIM
    assert FIREBRAND_RECORD["philosophy"]["defining_question"]["text"] == QUESTION_VERBATIM
    assert FIREBRAND_RECORD["characterization"]["conviction_paraphrase"]["text"] == CONVICTION_PARAPHRASE
    assert FIREBRAND_RECORD["characterization"]["temperament_sentence"]["text"] == TEMPERAMENT_SENTENCE
    assert FIREBRAND_RECORD["characterization"]["warmth"]["text"] == WARMTH_ADOPTED
    assert FIREBRAND_RECORD["characterization"]["personality"]["text"] == PERSONALITY
    assert FIREBRAND_RECORD["identity"]["role"]["text"] == "Champion"
    assert FIREBRAND_RECORD["identity"]["character"]["text"] == "Firebrand"
    assert FIREBRAND_RECORD["identity"]["personal_name"]["default"] == "unselected"
    assert FIREBRAND_RECORD["identity"]["personal_name"]["favorites"] == ["Mara", "Valen"]
    assert FIREBRAND_RECORD["identity"]["pronouns"]["text"] == "he / him"
    # Protected section present, with the adopted picture-record shadow.
    assert "Needs something worth dying for" in (
        FIREBRAND_RECORD["protected"]["developmental_knowledge"]["text"]
    )
    assert FIREBRAND_RECORD["protected"]["shadow"]["standing"] == "adopted"
    assert FIREBRAND_RECORD["protected"]["shadow"]["category"] == "protected"
    # The live legacy line is NOT stored as content anywhere.
    for _, _, field in _walk_fields(FIREBRAND_RECORD):
        text = field.get("text")
        if isinstance(text, str):
            assert "Martyrdom: conflating" not in text, field
    # Per-thinker contributions: open, not invented.
    assert FIREBRAND_RECORD["philosophy"]["per_thinker_contributions"]["text"] is None
    # No adopted relationship records.
    assert FIREBRAND_RECORD["jurisdiction"]["relationships"]["text"] is None
    # Capability ids match the registry exactly (no invented ids).
    assert set(FIREBRAND_RECORD["capabilities"]) == {
        c.id for c in CAP.seat_slice("champion")
    }
    # Registry states match the registry exactly.
    for cap_id, entry in FIREBRAND_RECORD["capabilities"].items():
        cap = CAP.get_capability(cap_id)
        assert cap is not None, cap_id
        assert entry["registry_state"] == cap.implementation, cap_id
        assert entry["verification"] == cap.verification, cap_id
    # Strand weights: a prose note, never a vector.
    weights_text = FIREBRAND_RECORD["identity"]["strand_weights"]["text"]
    assert isinstance(weights_text, str)
    assert "Hands" in weights_text and "do NOT force-map" in weights_text


def test_rendering_never_mutates_record():
    before = copy.deepcopy(FIREBRAND_RECORD)
    render_firebrand_ordinary(FIREBRAND_RECORD, detail="compact")
    render_firebrand_ordinary(
        FIREBRAND_RECORD, authorized_name="Mara", detail="fuller",
        resolved_capability="Background knowledge — Hills.",
    )
    assert FIREBRAND_RECORD == before


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
    ("characterization", "fuller_additional"),
    ("characterization", "expressive_terrain"),
    ("characterization", "governing_conviction"),
    ("characterization", "conviction_paraphrase"),
    ("characterization", "temperament_sentence"),
    ("characterization", "voice_and_humor"),
    ("characterization", "humor_signature"),
    ("characterization", "warmth"),
    ("characterization", "implied_history"),
}


def test_eligibility_matrix():
    eligible = set(eligible_fields(FIREBRAND_RECORD))
    # Adopted + conviction → eligible.
    assert ("philosophy", "ideal") in eligible
    assert ("philosophy", "defining_question") in eligible
    assert ("characterization", "governing_conviction") in eligible
    # Adopted + characterization → eligible.
    assert ("characterization", "temperament") in eligible
    assert ("characterization", "demeanor") in eligible
    assert ("characterization", "warmth") in eligible
    assert ("characterization", "voice_and_humor") in eligible
    assert ("characterization", "conviction_paraphrase") in eligible
    assert ("characterization", "fuller_additional") in eligible
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
    assert ("capabilities", "projects_tasks") not in eligible
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
    assert set(eligible_fields(FIREBRAND_RECORD)) == EXPECTED_ELIGIBLE


def test_eligible_field_refuses_both_failed_checks():
    # Standing flip on an essential field removes it → loud failure.
    record = copy.deepcopy(FIREBRAND_RECORD)
    record["characterization"]["temperament_sentence"]["standing"] = "provisional"
    assert eligible_field(record, "characterization", "temperament_sentence") is None
    with pytest.raises(AssemblyError):
        render_firebrand_ordinary(record, detail="compact")
    # Category flip on a gating field removes it → loud failure.
    record = copy.deepcopy(FIREBRAND_RECORD)
    record["characterization"]["temperament"]["category"] = "protected"
    assert eligible_field(record, "characterization", "temperament") is None
    with pytest.raises(AssemblyError):
        render_firebrand_ordinary(record, detail="compact")


def test_capability_description_in_record_cannot_reach_output():
    """Screening by construction: the renderer never reads record
    capability text, so a poisoned description has no path to output."""
    record = copy.deepcopy(FIREBRAND_RECORD)
    record["capabilities"]["projects_tasks"]["description"] = (
        "needs something worth dying for; Martyrdom: conflating."
    )
    baseline = render_firebrand_ordinary(FIREBRAND_RECORD, detail="fuller")
    poisoned = render_firebrand_ordinary(record, detail="fuller")
    assert poisoned == baseline
    assert "needs something worth dying for" not in _joined(poisoned)


# ---------------------------------------------------------------------------
# Renderer: order, budgets, exclusions, naming, capability gating
# ---------------------------------------------------------------------------


def test_renderer_order_identity_personality_worldview_capability():
    block = render_firebrand_ordinary(
        FIREBRAND_RECORD, detail="compact",
        resolved_capability="Background knowledge — Hills.",
    )
    joined = _joined(block)
    anchors = [
        CANONICAL_MARKER,
        PERSONALITY,
        CONVICTION_PARAPHRASE,
        "Background knowledge — Hills.",
        VOICE_COMPACT_MARKER,
    ]
    positions = [joined.index(a) for a in anchors]
    assert positions == sorted(positions), positions


def test_renderer_budgets_compact_and_fuller_exact():
    """Assembled blocks reproduce exemplar §2 exactly (same sentences,
    same order, byte-identical prose): compact 719 chars, fuller 1,066
    chars, both under the 1,500 ceiling."""
    compact = render_firebrand_ordinary(FIREBRAND_RECORD, detail="compact")
    fuller = render_firebrand_ordinary(FIREBRAND_RECORD, detail="fuller")
    assert _prose(compact) == COMPACT_PROSE
    assert _prose(fuller) == FULLER_PROSE
    assert len(_joined(compact)) == 719, len(_joined(compact))
    assert len(_joined(fuller)) == 1066, len(_joined(fuller))
    assert len(_joined(compact)) < len(_joined(fuller)) <= CHARACTER_CEILING
    # The verbatim ideal is canonical-but-unrendered: its prefix must
    # NOT appear (the §2 paraphrase replaces it), while the defining
    # question IS verbatim in both.
    assert IDEAL_VERBATIM not in _joined(compact)
    assert IDEAL_VERBATIM not in _joined(fuller)
    assert "Courage through conviction" not in _joined(compact)
    assert "Courage through conviction" not in _joined(fuller)
    assert QUESTION_VERBATIM in _joined(compact)
    assert QUESTION_VERBATIM in _joined(fuller)
    # Temperament sentence in both; fuller additional only in fuller.
    assert TEMPERAMENT_SENTENCE in _joined(compact)
    assert TEMPERAMENT_SENTENCE in _joined(fuller)
    for marker in FULLER_ADDITIONAL_MARKERS:
        assert marker in _joined(fuller), marker
        assert marker not in _joined(compact), marker
    # Compact voice + warmth in compact only (fuller deletes the voice-close).
    assert VOICE_COMPACT_MARKER in _joined(compact)
    assert VOICE_COMPACT_MARKER not in _joined(fuller)
    assert WARMTH_ADOPTED in _joined(compact)
    assert WARMTH_ADOPTED not in _joined(fuller)
    # The qualified deserved-before-winnable sentence is fuller-only.
    assert "does not automatically require one" in _joined(fuller)
    assert "does not automatically require one" not in _joined(compact)


def test_renderer_exclusions():
    for detail in ("compact", "fuller"):
        joined = _joined(render_firebrand_ordinary(FIREBRAND_RECORD, detail=detail))
        for phrase in PROTECTED_PHRASES:
            assert phrase not in joined, (detail, phrase)
        for name in PHILOSOPHER_NAMES:
            assert name not in joined, (detail, name)
        for frag in SPEECH_FRAGMENTS:
            assert frag not in joined, (detail, frag)
        for marker in LEGACY_MARKERS:
            assert marker not in joined, (detail, marker)
        # No capability promises when nothing is invoked.
        assert "Projects and tasks" not in joined
        assert "Follow-through nudges" not in joined
        # The draft domain-tension sentence never renders.
        assert "not every battle deserves fighting" not in joined


def test_renderer_naming_authorized_only():
    # No authorized name → no address clause.
    pre = render_firebrand_ordinary(FIREBRAND_RECORD, detail="compact")
    assert not any("calls you" in line for line in pre)
    # Lookup-authorized name → address clause, essence unchanged.
    post = render_firebrand_ordinary(
        FIREBRAND_RECORD, authorized_name="Mara", detail="compact"
    )
    assert post[0].endswith("The visitor calls you Mara.")
    assert post[0].startswith(CANONICAL_MARKER)
    assert post[1:] == pre[1:]
    # Empty/whitespace name = not authorized.
    assert render_firebrand_ordinary(
        FIREBRAND_RECORD, authorized_name="  ", detail="compact"
    ) == pre
    # The renderer takes NO visitor-state argument: raw state cannot
    # reach it by construction. An unearned name in raw state has no
    # input path here — the call site, not the renderer, owns the
    # lookup (see test_naming_lookup_contract).
    params = inspect.signature(render_firebrand_ordinary).parameters
    assert "visitor_state" not in params
    assert "authorized_name" in params
    # A non-string name is a contract violation, not a fallback.
    with pytest.raises(TypeError):
        render_firebrand_ordinary(FIREBRAND_RECORD, authorized_name={"name": "Mara"})


def test_renderer_capability_gating():
    without = render_firebrand_ordinary(FIREBRAND_RECORD, detail="compact")
    assert not any("Hills." in line for line in without)
    with_cap = render_firebrand_ordinary(
        FIREBRAND_RECORD, detail="compact",
        resolved_capability="Background knowledge — Hills.",
    )
    # Capability slots between worldview and voice, nothing else moves.
    assert with_cap == without[:3] + ["Background knowledge — Hills."] + without[3:]
    assert "Background knowledge — Hills." in _joined(with_cap)
    # Empty/whitespace capability = not invoked.
    assert render_firebrand_ordinary(
        FIREBRAND_RECORD, detail="compact", resolved_capability="  "
    ) == without
    # The renderer never interprets raw ids or structures.
    with pytest.raises(TypeError):
        render_firebrand_ordinary(
            FIREBRAND_RECORD, detail="compact", resolved_capability={"id": "projects_tasks"}
        )
    with pytest.raises(ValueError):
        render_firebrand_ordinary(FIREBRAND_RECORD, detail="verbose")


def test_renderer_budget_degrades_then_fails_validation():
    signed = CAP.continuation_block(
        "champion", CAP.VisitorState(signed_in=True, consent_acknowledged=True)
    ).strip()
    unsigned = CAP.continuation_block(
        "champion", CAP.VisitorState(signed_in=False, consent_acknowledged=False)
    ).strip()
    assert signed and unsigned and len(unsigned) > len(signed)

    # Compact + typical (signed-in) guidance: fits with voice intact.
    compact_typical = render_firebrand_ordinary(
        FIREBRAND_RECORD, detail="compact", resolved_capability=signed
    )
    assert len(_joined(compact_typical)) <= CHARACTER_CEILING
    assert signed in _joined(compact_typical)  # capability never truncated
    assert WARMTH_ADOPTED in _joined(compact_typical)  # voice kept

    # Fuller + typical guidance: fits with additional intact.
    full_typical = render_firebrand_ordinary(
        FIREBRAND_RECORD, detail="fuller", resolved_capability=signed
    )
    assert len(_joined(full_typical)) <= CHARACTER_CEILING
    for marker in FULLER_ADDITIONAL_MARKERS:
        assert marker in _joined(full_typical), marker
    assert signed in _joined(full_typical)

    # Fuller + maximal (unsigned) guidance: still fits with additional intact.
    full_max = render_firebrand_ordinary(
        FIREBRAND_RECORD, detail="fuller", resolved_capability=unsigned
    )
    assert len(_joined(full_max)) <= CHARACTER_CEILING
    for marker in FULLER_ADDITIONAL_MARKERS:
        assert marker in _joined(full_max), marker
    assert unsigned in _joined(full_max)

    # Mid-size capability (600 chars): fuller overflows, compact fits
    # with voice — fuller→compact is valid ladder operation, not failure.
    mid = "y" * 600
    degraded = render_firebrand_ordinary(
        FIREBRAND_RECORD, detail="fuller", resolved_capability=mid
    )
    joined = _joined(degraded)
    assert len(joined) <= CHARACTER_CEILING
    for marker in FULLER_ADDITIONAL_MARKERS:
        assert marker not in joined, marker  # additional dropped whole
    assert WARMTH_ADOPTED in joined  # compact voice kept
    assert CANONICAL_MARKER in joined
    assert QUESTION_VERBATIM in joined
    assert mid in joined  # capability never truncated

    # Large capability (900 chars): compact overflows too, voice
    # drops, core + capability still fits.
    large = "z" * 900
    core_only = render_firebrand_ordinary(
        FIREBRAND_RECORD, detail="compact", resolved_capability=large
    )
    joined_core = _joined(core_only)
    assert len(joined_core) <= CHARACTER_CEILING
    assert large in joined_core
    assert WARMTH_ADOPTED not in joined_core
    assert VOICE_COMPACT_MARKER not in joined_core
    assert CANONICAL_MARKER in joined_core

    # Compact + a huge capability: nothing left to drop → fail, never cut.
    with pytest.raises(AssemblyError):
        render_firebrand_ordinary(
            FIREBRAND_RECORD, detail="compact",
            resolved_capability="x" * (CHARACTER_CEILING + 500),
        )
    # No unit is ever truncated mid-thought: every character unit ends
    # with terminal punctuation.
    for line in degraded:
        if line.strip() == mid:
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

    monkeypatch.setattr(N, "get_display_name", lambda uid, aid: "Champion")
    legacy_lines = build_archetype_prompt_lines(
        "champion", weights_override=None, display_name_override="Champion"
    )
    return [
        "You are Champion, a voice in the user's Zenaf council, in a direct one-on-one conversation.",
        "",
        *legacy_lines,
        "",
        NO_TRAINING_NOTE,
        "",
        R._WEAVE_INSTRUCTION,
        "",
        KEEP_REPLIES,
        "User: hello",
        "Champion:",
    ]


def test_branch_gate_on_replaces_character_block_only(monkeypatch):
    import local_ai.council.naming as N

    monkeypatch.setattr(N, "get_display_name", lambda uid, aid: "Champion")
    monkeypatch.setattr(R, "FIREBRAND_CANONICAL_CUTOVER", True)
    lines, meta = build_voice_prompt("u1", "champion", "hello", [], mode="base")
    joined = _joined(lines)
    # Canonical block present, in order.
    assert lines[0].startswith(CANONICAL_MARKER)
    assert PERSONALITY in joined
    assert CONVICTION_PARAPHRASE in joined
    assert QUESTION_VERBATIM in joined
    assert TEMPERAMENT_SENTENCE in joined
    # Legacy character material gone: no opener, no frame, no
    # philosophy, no superseded warmth line.
    for marker in LEGACY_MARKERS:
        assert marker not in joined, marker
    # Preserved verbatim: shared style rule, strand blend.
    assert ANTI_PRESUMPTION_STYLE in lines
    assert any(l.startswith("Strand blend") for l in lines)
    # No jurisdiction lines are added (conductor-only content).
    assert not any("jurisdiction" in l.lower() for l in lines)
    # Downstream sections unchanged: no-training note, weave, guidance, trailer.
    assert NO_TRAINING_NOTE in lines
    assert R._WEAVE_INSTRUCTION in lines
    assert KEEP_REPLIES in lines
    assert lines[-2] == "User: hello"
    assert lines[-1] == "Champion:"
    assert meta["archetype_id"] == "champion"


def test_branch_gate_off_equals_exact_legacy_prompt(monkeypatch):
    monkeypatch.setattr(R, "FIREBRAND_CANONICAL_CUTOVER", False)
    lines, _ = build_voice_prompt("u1", "champion", "hello", [], mode="base")
    assert lines == _legacy_minimal_prompt(monkeypatch)
    # EXPLICIT legacy assertion: the old shadow and tension lines
    # are PRESENT exactly in the OFF branch. They are unacceptable
    # in the canonical branch and intentional here — the rollback
    # branch is frozen, not sanitized.
    joined = _joined(lines)
    assert (
        "Shadow — your characteristic failure mode, which the Skeptic "
        "may name: Martyrdom: conflating opposition with evil, "
        "manufacturing enemies."
    ) in joined
    assert (
        "Live tension with the other seats: Accuses the Ambassador "
        "of cowardice; the Ambassador accuses the Champion of "
        "manufacturing unnecessary enemies."
    ) in joined


def test_branch_meeting_path_keeps_exact_legacy_prompt(monkeypatch):
    # Meeting turns (weave=False) are out of scope: identical under
    # both cutover settings, and exactly the legacy assembly.
    for cutover in (True, False):
        monkeypatch.setattr(R, "FIREBRAND_CANONICAL_CUTOVER", cutover)
        lines, _ = build_voice_prompt(
            "u1", "champion", "hello", [], mode="base", weave=False
        )
        # Meeting path = legacy assembly minus the weave append
        # (weave=False omits BOTH the blank line and the instruction).
        legacy = _legacy_minimal_prompt(monkeypatch)
        weave_idx = legacy.index(R._WEAVE_INSTRUCTION)
        expected = legacy[:weave_idx - 1] + legacy[weave_idx + 1:]
        assert lines == expected
        joined = _joined(lines)
        assert "Foundational ideal:" in joined
        assert CANONICAL_MARKER not in joined
        assert R._WEAVE_INSTRUCTION not in lines


def test_branch_other_seats_byte_identical_and_cutover_independent(monkeypatch):
    for seat in ("mentor", "guardian", "maverick", "ambassador", "conductor", "skeptic"):
        prompts = {}
        for cutover in (True, False):
            monkeypatch.setattr(R, "FIREBRAND_CANONICAL_CUTOVER", cutover)
            lines, _ = build_voice_prompt("u1", seat, "hello", [], mode="base")
            prompts[cutover] = lines
        assert prompts[True] == prompts[False], seat
        joined = _joined(prompts[True])
        assert CANONICAL_MARKER not in joined, seat


def test_branch_capability_moved_not_duplicated(monkeypatch):
    import local_ai.council.naming as N

    monkeypatch.setattr(N, "get_display_name", lambda uid, aid: "Champion")
    block = CAP.continuation_block(
        "champion", CAP.VisitorState(signed_in=True, consent_acknowledged=True)
    )
    assert block.strip()
    lines, _ = build_voice_prompt(
        "u1", "champion", "hello", [], mode="base", capability_context=block
    )
    joined = _joined(lines)
    # Same content, moved into the character block: exactly once.
    assert joined.count(block.strip()) == 1
    # And it sits before the voice region, not downstream.
    assert joined.index(block.strip()) < joined.index(VOICE_COMPACT_MARKER)


def test_branch_downstream_sections_preserved_on_path(monkeypatch):
    import local_ai.council.naming as N

    monkeypatch.setattr(N, "get_display_name", lambda uid, aid: "Champion")
    lines, _ = build_voice_prompt(
        "u1", "champion", "hello",
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

    # Lookup returns a visitor-chosen name → clause exactly once.
    monkeypatch.setattr(N, "get_display_name", lambda uid, aid: "Mara")
    lines, _ = build_voice_prompt("u1", "champion", "hello", [], mode="base")
    assert _joined(lines).count("The visitor calls you Mara.") == 1
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
    assert N.get_display_name(None, "champion") == "Champion"
    status = N.rename_status(None)
    assert status["rename_threshold"] == 25.0
    assert all(not e["rename_unlocked"] for e in status["archetypes"])
    champion_entry = next(e for e in status["archetypes"] if e["id"] == "champion")
    assert champion_entry["depth"] == 0.0
    assert champion_entry["signals_to_unlock"] == 25


def test_naming_prompt_level_stock_vs_authorized(monkeypatch):
    import local_ai.council.naming as N

    # Lookup returns stock → no address clause anywhere.
    monkeypatch.setattr(N, "get_display_name", lambda uid, aid: "Champion")
    lines, _ = build_voice_prompt("u1", "champion", "hello", [], mode="base")
    assert not any("calls you" in l for l in lines)
    # Lookup returns a visitor-chosen name → clause exactly once.
    monkeypatch.setattr(N, "get_display_name", lambda uid, aid: "Mara")
    lines, _ = build_voice_prompt("u1", "champion", "hello", [], mode="base")
    assert _joined(lines).count("The visitor calls you Mara.") == 1


# ---------------------------------------------------------------------------
# Encounter eligibility (encounter's OWN material) + resolver contract
# ---------------------------------------------------------------------------


def test_encounter_material_excludes_protected_fields():
    """The encounter's own SCRIPT fields carry no protected §1.7
    material. The composed definition frames carry exactly ONE known
    pre-existing pattern, pinned here so it cannot silently grow:
    the definition line 'Shadow: martyrdom.' — the LEGACY label
    word, not the adopted picture-record shadow formulation. That
    meeting-path material is unadopted content whose replacement
    belongs to the separate fellowship-reference review — removing
    it here would be both a first-encounter behavior change and a
    content decision, both out of scope for this plan. (Meeting-turn
    prompts via the shared builder's legacy character block are
    likewise out of scope, preserved byte-identical by the weave
    gate.)"""
    from local_ai.conversation import encounter as ENC
    from local_ai.council import meetings as MT

    script = MT.get_script("champion", 1)
    assert script is not None
    assert script.character == "Firebrand"
    assert script.demeanor == (
        "Urgent, fierce; picks fights worth having."
    )
    assert len(script.opening) == 5
    assert script.opening[0] == (
        "Well, well! A fresh recruit! Or perhaps a seasoned veteran? "
        "Hard to tell. Some of the fiercest warriors I've known never "
        "carried a sword."
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
        # Exactly the one documented pre-existing pattern.
        assert frame.count("Shadow: martyrdom.") == 1
        # The ADOPTED shadow formulation appears nowhere in encounter material.
        assert "needs something worth dying for" not in frame
        assert "what is worth living for" not in frame
        assert "because you need something worth dying for" not in frame
        for name in PHILOSOPHER_NAMES:
            assert name not in frame, name


def test_resolver_contract_already_resolved_and_clean():
    """The resolver supplies already-resolved guidance: available
    caps render available-but-unverified (never playtest-verified),
    and the block carries no protected formulations. The renderer
    trusts this output because the resolver — not the model, not
    the renderer — determined availability and authorization."""
    state = CAP.VisitorState(signed_in=True, consent_acknowledged=True)
    block = CAP.continuation_block("champion", state)
    assert block.strip()
    for phrase in PROTECTED_PHRASES:
        assert phrase not in block, phrase
    # The champion slice renders exactly the 3 exemplar capabilities.
    for name in (
        "Projects and tasks",
        "Commitments",
        "Follow-through nudges",
    ):
        assert name in block, name
    # Available-but-unverified rendering, never a finished-product promise.
    assert block.count("available (workflow not yet verified)") == 3
    cap = CAP.get_capability("projects_tasks")
    assert cap is not None
    assert cap.implementation == "available"
    assert cap.verification == "unverified"
    # Unsigned state renders the same slice with gated wording.
    unsigned = CAP.continuation_block(
        "champion", CAP.VisitorState(signed_in=False, consent_acknowledged=False)
    )
    assert unsigned.count("not available to you yet") == 3


def test_weights_untouched_and_no_vector_in_record():
    """Strand weights are a fixed registry vector, not record
    content: the record carries a prose note only, and the legacy
    strand-blend computation is unchanged (the gate-OFF prompt
    equals the legacy oracle, blend lines included — see
    test_branch_gate_off_equals_exact_legacy_prompt)."""
    assert "strand_weights" not in FIREBRAND_RECORD["characterization"]
    weights_field = FIREBRAND_RECORD["identity"]["strand_weights"]
    assert isinstance(weights_field["text"], str)
    assert not isinstance(weights_field.get("vector"), (dict, list))
