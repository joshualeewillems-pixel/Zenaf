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

- The legacy ``philosophy_prompt_lines`` function is the frozen
  rollback source — with ONE exception: FC7 (2026-11-07, founder
  ruling) removed the Champion's superseded "Martyrdom" shadow line
  from the shared source dict, so the function now renders 3 lines
  for the Champion (ideal, question, tension — no Shadow line) and
  4 for every other seat. The canonical branch bypasses it for
  ordinary Firebrand turns instead of modifying it. There is
  deliberately NO test asserting it returns ideal+question only.
- Meeting turns (canonical=False) keep the exact legacy assembly,
  including its philosophy lines. The encounter-eligibility test
  pins the encounter's OWN material (scripts + frames): the
  script texts carry no protected formulations, and the composed
  definition frames carry NO "Shadow" / "Martyrdom" line at all —
  the Gardener correction (G4/D1) removed the "Shadow: martyrdom."
  guidance label, and FC7 removed the "Martyrdom" philosophy line.
  The adopted picture-record shadow formulation appears nowhere in
  encounter material.
- The §2 rendering form of the ideal is a PARAPHRASED conviction
  sentence ("You ask whether a commitment is deserved before you
  ask whether it can be won — ..."): the verbatim ideal ("Courage through
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
from local_ai.council.canonical.bear import BEAR_RECORD
from local_ai.council.canonical.firebrand import FIREBRAND_RECORD
from local_ai.council.render import (
    CHARACTER_CEILING,
    AssemblyError,
    _FIREBRAND_CHARACTER_CEILING,
    _FIREBRAND_COMPACT_VOICE_MID,
    _FIREBRAND_TALK_PRINCIPLES,
    eligible_field,
    eligible_fields,
    render_bear_ordinary,
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
    "You ask whether a commitment is deserved before you ask whether "
    "it can be won — a worthy cause can justify a hopeless stand, "
    "but it does not automatically require one. Judge by meaning, "
    "cost, and consequence, above all by what a course costs the "
    "people holding it, and decide what victory would actually mean "
    "before committing."
)
QUESTION_VERBATIM = "What is worth fighting for?"
TEMPERAMENT_SENTENCE = (
    "Press for change when conviction warrants action; weigh its "
    "human cost without pretending every worthy cause demands a "
    "fight. Do not manufacture a fight where none is needed, and do "
    "not mistake upkeep for a fight."
)
HUMANISM_SENTENCE = (
    "You weigh every position by what it costs the people holding it."
)
PERSONALITY = (
    "You are fierce and direct, fast and forward-leaning: you get to "
    "the verb early, and you notice first what is at stake, what it "
    "will cost, and the moment deliberation tips into avoidance."
)
VOICE_COMPACT_MARKER = "You speak in short declarative sentences"
# Middle rung (naming-gap fix, 2026-11-07): the authored condensed
# voice unit. Q9/Q6/FC2 are quoted verbatim from _CHAMPION_GUIDANCE
# / _SHARED_NATURE_RULE (encounter.py); the voice essence condenses
# the record's voice_and_humor + warmth fields. The rung is the
# first Talk placement of the Q9 sentence.
Q9_SENTENCE = (
    "Name the mission plainly, never coerce, stand the wait: "
    "willing following beats fearful obedience."
)
NATURE_RULE = (
    "Your nature determines what you notice, what you value, what you "
    "question, and how you express yourself; it does not prescribe the "
    "outcome of every exchange."
)
FC2_EXIT = (
    "When the fight is not worth having, name that plainly: this hill "
    "is not worth dying on."
)
VOICE_MID_MARKER = "your warmth sparing — acknowledge briefly"
FULL_VOICE_ONLY_MARKER = "strategy is shop talk"
MAX_PERSONAL_NAME_LEN = 60  # local_ai/you_profile/store.py
WARMTH_ADOPTED = (
    "Your warmth is sparing: acknowledge briefly, then move to the "
    "next concrete step. Let circumstance set the register: gather "
    "missing information before judging; do upkeep cleanly, since "
    "unattended maintenance costs attention and morale; slow down "
    "and name the next step when the visitor is exhausted or uncertain."
)
FULLER_ADDITIONAL_MARKERS = (
    "You notice first the hill, the price",
    "You ask whether a fight is deserved before you ask whether it is winnable",
    "Before you draw your sword, decide what victory would actually mean.",
)

COMPACT_PROSE = (
    "You are the Firebrand, who occupies the Champion seat in the Fellowship. "
    "You are fierce and direct, fast and forward-leaning: you get to "
    "the verb early, and you notice first what is at stake, what it "
    "will cost, and the moment deliberation tips into avoidance. "
    "You ask whether a commitment is deserved before you ask whether "
    "it can be won — a worthy cause can justify a hopeless stand, "
    "but it does not automatically require one. Judge by meaning, "
    "cost, and consequence, above all by what a course costs the "
    "people holding it, and decide what victory would actually mean "
    "before committing. "
    "What is worth fighting for? "
    "Press for change when conviction warrants action; weigh its "
    "human cost without pretending every worthy cause demands a "
    "fight. Do not manufacture a fight where none is needed, and do "
    "not mistake upkeep for a fight. "
    "You weigh every position by what it costs the people holding it. "
    "You speak in short declarative sentences, in plain words; "
    "strategy is shop talk, available when it illuminates, never a "
    "required list. "
    "Your humor is dry and brief — it arises from recognizing self-deception "
    "or wasted effort, never as a performed cut; a single dry line, then back "
    "to substance. "
    "Your warmth is sparing: acknowledge briefly, then move to the "
    "next concrete step. Let circumstance set the register: gather "
    "missing information before judging; do upkeep cleanly, since "
    "unattended maintenance costs attention and morale; slow down "
    "and name the next step when the visitor is exhausted or uncertain. "
    "Name the mission plainly, never coerce, stand the wait: willing "
    "following beats fearful obedience. "
    "Your nature determines what you notice, what you value, what you "
    "question, and how you express yourself; it does not prescribe the "
    "outcome of every exchange."
)
FULLER_PROSE = (
    "You are the Firebrand, who occupies the Champion seat in the Fellowship. "
    "You are fierce and direct, fast and forward-leaning: you get to "
    "the verb early, and you notice first what is at stake, what it "
    "will cost, and the moment deliberation tips into avoidance. "
    "You ask whether a commitment is deserved before you ask whether "
    "it can be won — a worthy cause can justify a hopeless stand, "
    "but it does not automatically require one. Judge by meaning, "
    "cost, and consequence, above all by what a course costs the "
    "people holding it, and decide what victory would actually mean "
    "before committing. "
    "What is worth fighting for? "
    "Press for change when conviction warrants action; weigh its "
    "human cost without pretending every worthy cause demands a "
    "fight. Do not manufacture a fight where none is needed, and do "
    "not mistake upkeep for a fight. "
    "You notice first the hill, the price, and the moment deliberation tips "
    "into avoidance. "
    "You ask whether a fight is deserved before you ask whether it is winnable "
    "— a worthy cause can justify a hopeless stand, but it does not "
    "automatically require one, and you judge the battle's meaning, cost, and "
    "consequences. "
    "You still believe discipline, sacrifice, and the necessity of conflict; "
    "obedience is not conviction to you. "
    "You weigh every position by what it costs the people holding it. "
    "Before you draw your sword, decide what victory would actually mean. "
    "Name the mission plainly, never coerce, stand the wait: willing "
    "following beats fearful obedience. "
    "Your nature determines what you notice, what you value, what you "
    "question, and how you express yourself; it does not prescribe the "
    "outcome of every exchange."
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
        "temperament_sentence",
        # Q10 (2026-11-07) + Q9 fields A/B/C (founder-adopted OQ5,
        # 2026-11-07): record fields, see firebrand.py.
        "humanism_sentence", "leadership_without_coercion",
        "parenting_as_command", "command_vs_fear",
        "voice_and_humor", "humor_signature",
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
    # Q10 (2026-11-07): the humanism sentence, adopted, renders in the
    # compact worldview (render.py) and the fuller additional.
    ("characterization", "humanism_sentence"),
    # Q9 (2026-11-07, founder-adopted per-element OQ5): record fields
    # only — NOT rendered in Talk (compact budget exhausted) and NOT
    # rendered on the meeting path as their own sentences (the guidance
    # carries one distilled sentence instead). Eligible by the existing
    # rule, consumed by no renderer.
    ("characterization", "leadership_without_coercion"),
    ("characterization", "parenting_as_command"),
    ("characterization", "command_vs_fear"),
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
    same order, byte-identical prose): compact 1,758 chars, fuller 1,639
    chars, both at or under the 1,758 Firebrand threshold (2026-11-04 characterization
    revision: governing judgment promoted into the compact core;
    2026-11-07 Q10: the humanism sentence rides the compact worldview,
    ceiling raised 1500 -> 1501 by founder approval OQ1)."""
    compact = render_firebrand_ordinary(FIREBRAND_RECORD, detail="compact")
    fuller = render_firebrand_ordinary(FIREBRAND_RECORD, detail="fuller")
    assert _prose(compact) == COMPACT_PROSE
    assert _prose(fuller) == FULLER_PROSE
    assert len(_joined(compact)) == 1758, len(_joined(compact))
    assert len(_joined(fuller)) == 1639, len(_joined(fuller))
    # Compact is now the LARGER block (its voice unit, 606, exceeds the
    # fuller additional, 552) — the ordering was never load-bearing; the
    # load-bearing rule is that both blocks fit at or under the Firebrand
    # threshold.
    assert len(_joined(compact)) <= _FIREBRAND_CHARACTER_CEILING
    assert len(_joined(fuller)) <= _FIREBRAND_CHARACTER_CEILING
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
    # The qualified deserved-before-winnable sentence is in BOTH:
    # promoted into the compact core by the 2026-11-04 revision, and
    # still present in the fuller additional (untouched).
    assert "does not automatically require one" in _joined(fuller)
    assert "does not automatically require one" in _joined(compact)
    # Q9 + Q6 in Talk generally (founder rulings 2026-11-07 ~19:21/~19:23
    # PT): the principles unit trails BOTH candidates, verbatim, as the
    # last unit — not buried mid-block, and identical in each.
    assert Q9_SENTENCE in _joined(compact)
    assert Q9_SENTENCE in _joined(fuller)
    assert NATURE_RULE in _joined(compact)
    assert NATURE_RULE in _joined(fuller)
    assert compact[-1] == _FIREBRAND_TALK_PRINCIPLES
    assert fuller[-1] == _FIREBRAND_TALK_PRINCIPLES


def test_r2_humanism_in_the_compact_worldview():
    """R2 (Q10, founder 2026-11-07): the humanism sentence rides the
    compact worldview unit (index 2), and the fuller contains it
    exactly once — in the additional unit, not duplicated into the
    worldview."""
    compact = render_firebrand_ordinary(FIREBRAND_RECORD, detail="compact")
    fuller = render_firebrand_ordinary(FIREBRAND_RECORD, detail="fuller")
    assert HUMANISM_SENTENCE in compact[2]  # worldview unit
    assert compact[2].endswith(HUMANISM_SENTENCE)
    assert HUMANISM_SENTENCE not in compact[3]  # voice unit, not voice
    assert _joined(fuller).count(HUMANISM_SENTENCE) == 1
    assert HUMANISM_SENTENCE in fuller[3]  # additional unit
    assert HUMANISM_SENTENCE not in fuller[2]  # not in the worldview


def test_r3_firebrand_ceiling_is_scoped():
    """R3 (Q9 + Q6 in Talk generally, founder rulings 2026-11-07
    ~19:21/~19:23 PT): the Firebrand threshold is SCOPED — the shared
    CHARACTER_CEILING stays 1501, so no other seat's rendering moves.
    A shared raise was measured and rejected: Bear's fuller is 1,648
    chars, so a shared 1,758 would un-degrade it from its compact
    fallback, which Bear's own test pins by design
    (test_bear_canonical.py::test_renderer_budgets_compact_and_fuller_exact).
    This test pins the honest form: the other six seats are
    byte-identical whether the Firebrand threshold is 1501 or 1758
    (they never read it), and Firebrand's compact and fuller both need
    the 1,758 threshold — at 1501 they degrade to the bare 3-unit
    block, while a NAMED Firebrand at 1501 still lands on the middle
    rung (the rung is what protects names at the old threshold)."""
    from local_ai.council.canonical.crane import CRANE_RECORD
    from local_ai.council.canonical.bear import BEAR_RECORD as _BR
    from local_ai.council.canonical.fox import FOX_RECORD
    from local_ai.council.canonical.gardener import GARDENER_RECORD
    from local_ai.council.canonical.raven import RAVEN_RECORD
    from local_ai.council.canonical.weaver import WEAVER_RECORD
    from local_ai.council.render import (
        render_bear_ordinary,
        render_crane_ordinary,
        render_fox_ordinary,
        render_gardener_ordinary,
        render_raven_ordinary,
        render_weaver_ordinary,
    )

    import local_ai.council.render as render_mod

    # The shared ceiling was NOT raised.
    assert render_mod.CHARACTER_CEILING == 1501
    assert render_mod._FIREBRAND_CHARACTER_CEILING == 1758

    others = [
        (render_weaver_ordinary, WEAVER_RECORD),
        (render_raven_ordinary, RAVEN_RECORD),
        (render_gardener_ordinary, GARDENER_RECORD),
        (render_bear_ordinary, _BR),
        (render_crane_ordinary, CRANE_RECORD),
        (render_fox_ordinary, FOX_RECORD),
    ]
    for detail in ("compact", "fuller"):
        for renderer, record in others:
            render_mod._FIREBRAND_CHARACTER_CEILING = 1501
            try:
                at_1501 = renderer(record, detail=detail)
            finally:
                render_mod._FIREBRAND_CHARACTER_CEILING = 1758
            at_1758 = renderer(record, detail=detail)
            assert at_1501 == at_1758, (renderer.__name__, detail)
    # Bear's fuller still falls back to compact at the shared 1501 —
    # the raise did not touch it.
    assert len(_joined(render_bear_ordinary(_BR, detail="fuller"))) == 1443
    # Firebrand at the old threshold: compact and fuller both degrade
    # to the bare 3-unit block (voice + humanism + principles dropped).
    render_mod._FIREBRAND_CHARACTER_CEILING = 1501
    try:
        fuller_1501 = render_firebrand_ordinary(FIREBRAND_RECORD, detail="fuller")
        compact_1501 = render_firebrand_ordinary(FIREBRAND_RECORD, detail="compact")
        named_1501 = render_firebrand_ordinary(
            FIREBRAND_RECORD, authorized_name="Mara", detail="compact"
        )
    finally:
        render_mod._FIREBRAND_CHARACTER_CEILING = 1758
    fuller_1758 = render_firebrand_ordinary(FIREBRAND_RECORD, detail="fuller")
    compact_1758 = render_firebrand_ordinary(FIREBRAND_RECORD, detail="compact")
    assert len(_joined(compact_1758)) == 1758
    assert len(compact_1758) == 5
    assert len(_joined(fuller_1758)) == 1639
    assert len(fuller_1758) == 5
    assert Q9_SENTENCE in _joined(compact_1758)
    assert Q9_SENTENCE in _joined(fuller_1758)
    assert NATURE_RULE in _joined(compact_1758)
    assert NATURE_RULE in _joined(fuller_1758)
    assert len(_joined(compact_1501)) == 829
    assert len(compact_1501) == 3
    assert len(_joined(fuller_1501)) == 829
    assert len(fuller_1501) == 3
    assert HUMANISM_SENTENCE not in _joined(compact_1501)
    assert Q9_SENTENCE not in _joined(compact_1501)
    assert VOICE_COMPACT_MARKER not in _joined(compact_1501)
    # A named Firebrand at the old threshold still lands on the rung.
    assert len(_joined(named_1501)) == 1434
    assert len(named_1501) == 4
    assert named_1501[3] == _FIREBRAND_COMPACT_VOICE_MID


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
    # Lookup-authorized name → address clause.
    post = render_firebrand_ordinary(
        FIREBRAND_RECORD, authorized_name="Mara", detail="compact"
    )
    assert post[0].endswith("The visitor calls you Mara.")
    assert post[0].startswith(CANONICAL_MARKER)
    # NAMING GAP — FIXED (2026-11-07, middle rung): the compact sat
    # exactly at the Firebrand threshold (1,758/1,758 after Q9+Q6), so an authorized
    # name (+28 chars for "Mara") pushed the full compact candidate
    # over and the renderer fell back to the bare 3-unit block — a
    # NAMED Firebrand lost the voice unit AND the Q10 humanism
    # sentence. The ladder now tries the authored middle rung
    # (identity-with-name, personality, worldview + humanism,
    # condensed voice carrying Q9, FC2, Q6 verbatim) before the bare
    # block. post[1:] is NOT pre[1:] anymore: the fourth unit is the
    # condensed rung, not the full voice + warmth passage.
    assert len(post) == 4
    assert len(_joined(post)) == 1434
    assert post[1] == pre[1]  # personality unchanged
    assert post[2] == pre[2]  # worldview + humanism unchanged
    assert post[3] == _FIREBRAND_COMPACT_VOICE_MID
    assert HUMANISM_SENTENCE in _joined(post)
    assert Q9_SENTENCE in _joined(post)
    assert NATURE_RULE in _joined(post)
    assert FC2_EXIT in _joined(post)
    assert VOICE_MID_MARKER in _joined(post)
    assert FULL_VOICE_ONLY_MARKER not in _joined(post)
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


def test_renderer_naming_middle_rung_cases():
    # No name → the full compact with the Q9 + Q6 principles unit.
    # Q9 + Q6 in Talk generally (founder rulings 2026-11-07 ~19:21/
    # ~19:23 PT): the unnamed compact now carries both sentences
    # verbatim as its last unit — the earlier "Q9 ABSENT by design"
    # pin is superseded by those rulings. Five units, 1,758 chars,
    # exactly at the Firebrand threshold.
    pre = render_firebrand_ordinary(FIREBRAND_RECORD, detail="compact")
    assert len(pre) == 5
    assert len(_joined(pre)) == 1758
    assert HUMANISM_SENTENCE in _joined(pre)
    assert FULL_VOICE_ONLY_MARKER in _joined(pre)
    assert Q9_SENTENCE in _joined(pre)
    assert NATURE_RULE in _joined(pre)
    assert pre[-1] == _FIREBRAND_TALK_PRINCIPLES
    # Typical names → middle rung, never the bare block. For EACH
    # case: not the bare 3-unit block, Q9 verbatim, humanism
    # present, the chosen name present.
    for name, total in (("Mara", 1434), ("Ash", 1433), ("Beatrice", 1438)):
        named = render_firebrand_ordinary(
            FIREBRAND_RECORD, authorized_name=name, detail="compact"
        )
        joined = _joined(named)
        assert len(named) == 4, name
        assert len(joined) == total, name
        assert len(joined) <= _FIREBRAND_CHARACTER_CEILING, name
        assert named[3] == _FIREBRAND_COMPACT_VOICE_MID, name
        assert f"The visitor calls you {name}." in joined, name
        assert HUMANISM_SENTENCE in joined, name
        assert Q9_SENTENCE in joined, name
        assert NATURE_RULE in joined, name
        assert FC2_EXIT in joined, name
        assert VOICE_MID_MARKER in joined, name
        assert FULL_VOICE_ONLY_MARKER not in joined, name
    # Long permitted names: the store caps personal_name at 60 chars
    # (MAX_PERSONAL_NAME_LEN). At the cap the rung still fits with
    # 11 chars of margin; one over the cap still fits on margin.
    for n, total in ((59, 1489), (60, 1490), (61, 1491)):
        long_name = "X" * n
        named = render_firebrand_ordinary(
            FIREBRAND_RECORD, authorized_name=long_name, detail="compact"
        )
        joined = _joined(named)
        assert len(named) == 4, n
        assert len(joined) == total, n
        assert f"The visitor calls you {long_name}." in joined, n
        assert Q9_SENTENCE in joined, n
        assert HUMANISM_SENTENCE in joined, n
    # Boundary: the rung fits names up to 328 chars (exactly at the
    # 1,758 Firebrand threshold); at 329 it overflows and the ladder
    # falls to the bare block. Names over 60 are rejected at the
    # store, so cases past 60 are unreachable via the authorized
    # path — they pin the ladder floor, not supported cases. The old
    # 71/72 boundary moved with the threshold: both now land on the
    # rung, Q9 present.
    at_old_limit = render_firebrand_ordinary(
        FIREBRAND_RECORD, authorized_name="X" * 71, detail="compact"
    )
    assert len(at_old_limit) == 4
    assert len(_joined(at_old_limit)) == 1501
    assert Q9_SENTENCE in _joined(at_old_limit)
    over_old_limit = render_firebrand_ordinary(
        FIREBRAND_RECORD, authorized_name="X" * 72, detail="compact"
    )
    assert len(over_old_limit) == 4
    assert len(_joined(over_old_limit)) == 1502
    assert Q9_SENTENCE in _joined(over_old_limit)
    at_limit = render_firebrand_ordinary(
        FIREBRAND_RECORD, authorized_name="X" * 328, detail="compact"
    )
    assert len(at_limit) == 4
    assert len(_joined(at_limit)) == 1758
    assert Q9_SENTENCE in _joined(at_limit)
    over_limit = render_firebrand_ordinary(
        FIREBRAND_RECORD, authorized_name="X" * 329, detail="compact"
    )
    assert len(over_limit) == 3
    assert Q9_SENTENCE not in _joined(over_limit)
    assert HUMANISM_SENTENCE not in _joined(over_limit)
    # Fuller carries the principles unit too, so naming moves it the
    # same way (was 1,410 / 1,466 before the principles unit).
    assert len(_joined(render_firebrand_ordinary(
        FIREBRAND_RECORD, authorized_name="Mara", detail="fuller"
    ))) == 1667
    assert len(_joined(render_firebrand_ordinary(
        FIREBRAND_RECORD, authorized_name="X" * 60, detail="fuller"
    ))) == 1723


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

    # Compact + typical (signed-in) guidance: under budget separation
    # (renderer-budget separation design 2026-11-04), the ceiling
    # measures character content ALONE, so the 1,758-char compact
    # block keeps its voice unit with the 315-char signed guidance
    # (283 + the 32-char FC4 companion note, 2026-11-07) attached:
    # total 2,074, voice and range lines render.
    # INTENTIONAL EXPECTATION REVERSAL, citing the design doc: this
    # block previously asserted the voice-drop (voice absent, total
    # <= ceiling); the separation design reverses that expectation.
    compact_typical = render_firebrand_ordinary(
        FIREBRAND_RECORD, detail="compact", resolved_capability=signed
    )
    assert len(_joined(compact_typical)) == 1758 + 1 + len(signed) == 2074
    assert signed in _joined(compact_typical)  # capability never truncated
    assert WARMTH_ADOPTED in _joined(compact_typical)  # voice survives whole
    assert VOICE_COMPACT_MARKER in _joined(compact_typical)
    assert CANONICAL_MARKER in _joined(compact_typical)
    # Capability sits at index 3 (after worldview), voice last.
    assert compact_typical[3] == signed
    assert VOICE_COMPACT_MARKER in compact_typical[4]

    # Fuller + typical guidance: additional survives too; total
    # 1,639 + 1 + 315 = 1,955. (Reversal of the old drop expectation.)
    full_typical = render_firebrand_ordinary(
        FIREBRAND_RECORD, detail="fuller", resolved_capability=signed
    )
    assert len(_joined(full_typical)) == 1639 + 1 + len(signed) == 1955
    for marker in FULLER_ADDITIONAL_MARKERS:
        assert marker in _joined(full_typical), marker
    assert signed in _joined(full_typical)

    # Fuller + maximal (unsigned) guidance: guidance length no longer
    # affects the ladder at all — additional survives, unsigned
    # guidance appended whole. (Reversal of the old drop expectation.)
    full_max = render_firebrand_ordinary(
        FIREBRAND_RECORD, detail="fuller", resolved_capability=unsigned
    )
    for marker in FULLER_ADDITIONAL_MARKERS:
        assert marker in _joined(full_max), marker
    assert unsigned in _joined(full_max)

    # Mid-size capability (600 chars): fuller keeps additional; the
    # guidance is appended whole, never measured against the ceiling.
    # (Reversal: additional previously dropped whole here.)
    mid = "y" * 600
    degraded = render_firebrand_ordinary(
        FIREBRAND_RECORD, detail="fuller", resolved_capability=mid
    )
    joined = _joined(degraded)
    assert len(joined) == 1639 + 1 + 600
    for marker in FULLER_ADDITIONAL_MARKERS:
        assert marker in joined, marker  # additional survives
    assert CANONICAL_MARKER in joined
    assert QUESTION_VERBATIM in joined
    assert mid in joined  # capability never truncated

    # Large capability (900 chars): no longer fails — the character
    # block fits on its own, so voice survives and guidance appends
    # whole. (Reversal: core + capability previously overflowed.)
    large = "z" * 900
    large_render = render_firebrand_ordinary(
        FIREBRAND_RECORD, detail="compact", resolved_capability=large
    )
    assert len(_joined(large_render)) == 1758 + 1 + 900
    assert WARMTH_ADOPTED in _joined(large_render)
    assert large in _joined(large_render)

    # Compact + a huge capability: guidance-length independence
    # (design §(e) test 5) — a 2,000-char guidance string no longer
    # raises AssemblyError and is appended whole. INTENTIONAL
    # REVERSAL of the old huge-guidance failure, documented here
    # rather than hidden: guidance has no size backstop after
    # separation, per the design's §(c) consequence.
    huge = render_firebrand_ordinary(
        FIREBRAND_RECORD, detail="compact",
        resolved_capability="x" * (CHARACTER_CEILING + 500),
    )
    assert len(_joined(huge)) == 1758 + 1 + (CHARACTER_CEILING + 500)
    assert WARMTH_ADOPTED in _joined(huge)
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
    # Downstream sections unchanged: no-training note, guidance, trailer.
    assert NO_TRAINING_NOTE in lines
    assert not any("[[u]]" in l or "wrap those exact words" in l for l in lines)
    assert KEEP_REPLIES in lines
    assert lines[-2] == "User: hello"
    assert lines[-1] == "Champion:"
    assert meta["archetype_id"] == "champion"


def test_branch_gate_off_equals_exact_legacy_prompt(monkeypatch):
    monkeypatch.setattr(R, "FIREBRAND_CANONICAL_CUTOVER", False)
    lines, _ = build_voice_prompt("u1", "champion", "hello", [], mode="base")
    assert lines == _legacy_minimal_prompt(monkeypatch)
    # FC7 (2026-11-07, founder ruling): the superseded "Martyrdom"
    # shadow line was REMOVED from the shared source dict, so it is
    # absent from the OFF branch too — the oracle above is built from
    # the same live pieces, so the equality still holds. The tension
    # line is unchanged and still present exactly.
    joined = _joined(lines)
    assert "Martyrdom" not in joined
    assert "Shadow" not in joined
    assert (
        "Live tension with the other seats: Accuses the Ambassador "
        "of cowardice; the Ambassador accuses the Champion of "
        "manufacturing unnecessary enemies."
    ) in joined


def test_branch_meeting_path_keeps_exact_legacy_prompt(monkeypatch):
    # Meeting turns (canonical=False) are out of scope: identical under
    # both cutover settings, and exactly the legacy assembly.
    for cutover in (True, False):
        monkeypatch.setattr(R, "FIREBRAND_CANONICAL_CUTOVER", cutover)
        lines, _ = build_voice_prompt(
            "u1", "champion", "hello", [], mode="base", canonical=False
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
    # Budget separation (renderer-budget separation design 2026-11-04):
    # with capability attached, the voice unit now SURVIVES — this
    # assertion previously pinned the voice-drop and is intentionally
    # reversed here, citing the design doc. The capability still
    # sits inside the character block (not downstream), and the
    # revised judgment still renders.
    assert VOICE_COMPACT_MARKER in joined
    assert "Press for change when conviction warrants action" in joined


def test_branch_downstream_sections_preserved_on_path(monkeypatch):
    import local_ai.council.naming as N

    monkeypatch.setattr(N, "get_display_name", lambda uid, aid: "Champion")
    lines, _ = build_voice_prompt(
        "u1", "champion", "hello",
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
    material. The Gardener correction (2026-11-07, founder verdict
    G4/D1) removed the `Shadow:` label from all seven first-meeting
    slices system-wide — overriding the earlier scoping that said
    removal \"belongs to the separate fellowship-reference review\".
    No `Shadow:` label remains in any meeting frame; the adopted
    shadow formulation stays protected and appears nowhere in
    encounter material. (Meeting-turn prompts via the shared builder's
    legacy character block are likewise out of scope, preserved
    byte-identical by the weave gate.)"""
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
        # Gardener correction (2026-11-07, G4/D1): no Shadow: label
        # remains in any first-meeting slice.
        assert frame.count("Shadow: martyrdom.") == 0
        # FC7 (2026-11-07, founder ruling): the superseded "Martyrdom"
        # shadow line is removed from the philosophy lines too — no
        # "Shadow" and no "Martyrdom" remain in either meeting prompt.
        assert "Shadow" not in frame
        assert "Martyrdom" not in frame
        assert "martyrdom" not in frame
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


# ---------------------------------------------------------------------------
# 2026-11-04 characterization revision (Firebrand + Bear)
# ---------------------------------------------------------------------------


def test_characterization_revision_2026_11_04_assembled_prompts():
    """Pins the founder-authorized 2026-11-04 revision, checked on the
    ACTUAL assembled compact prompts (not just the edited records):
    revised judgment present, old compulsory instructions absent,
    both blocks under the ceiling, no cross-seat naming, protected
    material excluded. Covers both seats in one test because the
    revision was authorized as a pair.

    Known consequence, pinned explicitly rather than hidden: with
    capability guidance attached (the ordinary signed-in Talk path),
    the lengthened blocks exceed the ceiling WITH guidance, so the
    ladder drops the voice unit whole — judgment survives, voice and
    range lines do not render on those turns. No renderer change was
    made; the consequence is flagged for founder review.

    NOTE (renderer-budget separation, 2026-11-04): the consequence
    above is SUPERSEDED for the two seats' renderers — the separation
    design moves capability out of the measured set, so voice and
    range lines now render on capability-attached turns too. The
    assertions below pin the NEW invariant; see the budget tests
    for the deliberate expectation reversals citing the design doc.
    """
    fb = _joined(render_firebrand_ordinary(FIREBRAND_RECORD, detail="compact"))
    br = _joined(render_bear_ordinary(BEAR_RECORD, detail="compact"))

    # Revised judgment present — Firebrand (incl. refinement 1).
    assert "a worthy cause can justify a hopeless stand" in fb
    assert (
        "Press for change when conviction warrants action; weigh its "
        "human cost without pretending every worthy cause demands a fight."
    ) in fb
    assert "do not mistake upkeep for a fight" in fb
    assert "do upkeep cleanly" in fb
    assert "What is worth fighting for?" in fb
    # Revised judgment present — Bear (incl. refinements 2 and 3).
    assert "You notice floors first" in br
    assert "who holds a key" in br and "quietly draining" in br
    assert "who gets hurt if it fails" in br
    assert (
        "once you have named a floor, you do not quietly lower it; "
        "but you will reconsider where that floor belongs when the facts change."
    ) in br
    assert "with the easy warmth and unhurried rhythm of Southern hospitality" in br
    assert "what are we responsible for keeping safe?" in br
    assert "welcome warmly and unhurriedly when someone arrives needing shelter" in br
    assert "hold a named floor steady when it is crossed" in br

    # Old compulsory instructions absent from BOTH compact blocks.
    for phrase in (
        "You pick the hill, and you name the price",
        "prices named, hills named",
        "cheap fights don't interest you",
        "hill isn't worth dying on",
        "supper on the table, a roof over everybody's head",
        "I'm not going anywhere",
        "battle-worn commander",
        "Obedience is not conviction",
    ):
        assert phrase not in fb, phrase
        assert phrase not in br, phrase

    # No cross-seat naming; relationship stays implicit.
    assert "Bear" not in fb
    assert "Firebrand" not in br

    # Ceiling (exact lengths are pinned by the budgets tests). The
    # Firebrand compact now sits EXACTLY at its own threshold
    # (1,758/1,758, Q9+Q6) — `over_budget` uses `>`, so equality
    # passes. Bear's compact stays under the shared 1,501 ceiling.
    assert len(fb) <= _FIREBRAND_CHARACTER_CEILING
    assert len(br) <= CHARACTER_CEILING

    # Capability-attached turns: judgment, voice, AND range survive
    # under budget separation (design 2026-11-04) — the old
    # voice-drop expectation is intentionally reversed here.
    signed_br = CAP.continuation_block(
        "guardian", CAP.VisitorState(signed_in=True, consent_acknowledged=True)
    ).strip()
    with_cap = _joined(
        render_bear_ordinary(BEAR_RECORD, detail="compact", resolved_capability=signed_br)
    )
    assert "You notice floors first" in with_cap
    assert "Southern hospitality" in with_cap
    assert "welcome warmly and unhurriedly" in with_cap
    assert len(with_cap) == 1443 + 1 + len(signed_br) == 1935


def test_renderer_budget_separation_2026_11_04():
    """Pins renderer-budget separation (design 2026-11-04) §(e) 1, 4,
    6, 7, 8 for Firebrand, with REAL continuation guidance: judgment
    + voice + range survive with guidance attached; order is
    identity → personality → worldview → capability → voice;
    fuller + guidance keeps the additional unit; no old compulsory
    phrases, no cross-seat naming, protected material excluded; and
    the character-only ceiling still raises AssemblyError
    independent of guidance.
    """
    signed = CAP.continuation_block(
        "champion", CAP.VisitorState(signed_in=True, consent_acknowledged=True)
    ).strip()
    # 283 + the 32-char FC4 companion note ("Naming one does not
    # create it.", 2026-11-07).
    assert len(signed) == 315, len(signed)

    # §(e)1: compact + guidance, total exactly 2,074.
    compact = render_firebrand_ordinary(
        FIREBRAND_RECORD, detail="compact", resolved_capability=signed
    )
    joined = _joined(compact)
    assert len(joined) == 2074
    for sentence in (
        "deserved before you ask whether it can be won",  # judgment
        "Press for change when conviction warrants action",  # judgment (refinement 1)
        "short declarative sentences",  # voice
        "dry and brief",  # voice
        "gather missing information before judging",  # range
        "do upkeep cleanly",  # range
        "slow down and name the next step",  # range
    ):
        assert sentence in joined, sentence
    # §(e)6: order, compact and fuller.
    assert compact[3] == signed
    assert VOICE_COMPACT_MARKER in compact[4]
    fuller = render_firebrand_ordinary(
        FIREBRAND_RECORD, detail="fuller", resolved_capability=signed
    )
    assert len(_joined(fuller)) == 1955  # §(e)7
    assert fuller[3] == signed
    for marker in FULLER_ADDITIONAL_MARKERS:
        assert marker in _joined(fuller), marker
    # §(e)8: no old compulsory phrases, no cross-seat naming, protected excluded.
    for phrase in (
        "You pick the hill, and you name the price",
        "prices named, hills named",
        "cheap fights don't interest you",
        "hill isn't worth dying on",
        "battle-worn commander",
        "Obedience is not conviction",
    ):
        assert phrase not in joined, phrase
    assert "Bear" not in joined
    for phrase in PROTECTED_PHRASES:
        assert phrase not in joined, phrase

    # §(e)4: character-only ceiling still holds, with and without guidance.
    bloated = copy.deepcopy(FIREBRAND_RECORD)
    bloated["characterization"]["personality"]["render_text"] = (
        "A very long personality sentence. " * 100
    )
    with pytest.raises(AssemblyError):
        render_firebrand_ordinary(bloated, detail="compact")
    with pytest.raises(AssemblyError):
        render_firebrand_ordinary(
            bloated, detail="compact", resolved_capability=signed
        )
