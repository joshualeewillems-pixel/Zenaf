"""Fox-only canonical implementation.

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
  ordinary Fox turns instead of modifying it. There is
  deliberately NO test asserting it returns ideal+question only.
- Meeting turns (weave=False) keep the exact legacy assembly,
  including its philosophy lines. The encounter-eligibility test
  pins the encounter's OWN material (scripts + frames): the
  script texts carry no protected formulations, while the
  composed definition frames carry exactly ONE known pre-existing
  pattern — the definition line "Shadow: contrarianism." — the
  LEGACY label word, not the adopted mistakes-commitment-for-
  captivity shadow. That meeting-path material is out of scope
  for this plan (ordinary renderer only) and is pinned here so it
  cannot silently grow.
- Uses the REVISED §2 renderings (compact 1,164 / fuller 1,489,
  P-005 integrated) — NOT any earlier counts. §1.3's "P-005
  remains open" signature row and §5's pre-P-005 counts
  (941/1,480) are stale and are NOT followed.
- Pronouns: NO fixed set. Gender "unspecified by choice; rejects
  obligatory categorization". The renderer refers to "the Fox"
  in canonical instructions; the renderings are second-person.
  The dinner line is a CANDIDATE signature expression,
  illustrative, not scripted, not repeated compulsively — it
  appears in NO rendered field and NO test asserts it as output.
- Voice = P-005 correction: the word "Irish" appears NOWHERE in
  renderings, deliberately, and WITHOUT accent/dialect — carried
  by "storyteller's lyrical cadence" and quick-witted sideways
  speech. Fast-thinking, not compulsively fast-speaking;
  charisma without persuasion; playfulness without performance.
- Roster is Zhuangzi / Diogenes / de Certeau (P-002 DECIDED:
  Machiavelli is OUT). NO contribution text is asserted.
- Warmth = conspiratorial enthusiasm, LAST in both renderings;
  the fuller has an encounter-conduct TAIL after warmth, so the
  voice-close is NOT terminal in fuller.
- Fuller + name-address clause (1,489 + ~27) exceeds the ceiling
  and degrades to compact + name — valid ladder operation, not
  failure (same fuller-headroom rule as Raven/Crane).
- Fox voice passages are long, so ANY resolver capability
  guidance drops the voice passage whole (compact + typical
  guidance = 1,563 > ceiling → voice dropped, middle kept).
  That is the ladder operating as designed, not a failure — but
  it means Fox voice survives only with no (or very small)
  capability guidance. Flagged in the PR description.
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
from local_ai.council.canonical.fox import FOX_RECORD
from local_ai.council.render import (
    CHARACTER_CEILING,
    AssemblyError,
    eligible_field,
    eligible_fields,
    render_fox_ordinary,
)

# Distinctive protected formulations. Deliberately specific phrases,
# not generic words: these are the formulations that must never reach
# an ordinary prompt.
PROTECTED_PHRASES = (
    "Mistakes commitment for captivity",
    "keeps opening doors after choosing one would make something possible",
    "Contrarianism",
    "contrarianism",
    "breaking doors to prove",
    "destruction without replacement",
    "transgression as identity",
    "breaking for its own sake",
    "because you cannot bear to be contained",
    "an unbuilt replacement is yours to name",
    "Who told you those were your only options?",
    "Exits and keys:",
    "Irish",
    "call me whatever you want",
    "late for dinner",
    "breaking one to prove you are not captive",
    "Shadow — your characteristic failure mode",
    "Shadow:",
)

PHILOSOPHER_NAMES = ("Zhuangzi", "Diogenes", "de Certeau", "Machiavelli", "Nietzsche")

LEGACY_MARKERS = (
    "Foundational ideal:",
    "Defining question (your instinctive first move",
    "Shadow — your characteristic failure mode",
    "Live tension with the other seats:",
    "Archetype: Maverick",
    "a voice in the user's Zenaf council",
    "Your warmth register: sparing and direct",
)

CANONICAL_MARKER = "You are the Fox, who occupies the Maverick seat"

IDEAL_VERBATIM = (
    "Possibility through reframing — consensus can become captivity; "
    "refuse to confuse established order with necessary order."
)
QUESTION_VERBATIM = "What if the rules are wrong?"
LEAD_COMPACT = (
    "You are restless and quicksilver: you hunt locked doors — rules "
    "followed out of habit, fear, or social pressure that nobody chose "
    "— and you ask who the rule serves."
)
LEAD_FULLER = (
    "Restless and quicksilver, you ask who the rule serves and whether "
    "the choices are real."
)
MIDDLE_COMPACT = (
    "You look for the side door, the repurposed tool, the choice nobody "
    "offered — and you invent possibilities nobody thought to ask for."
)
MIDDLE_FULLER_MARKERS = (
    "You notice the artificial choice, the default choosing for someone",
    "the untried route, and invent possibilities nobody thought to ask for, a new game",
    "Doors and passages are your vocabulary when they illuminate",
)
VOICE_COMPACT_MARKERS = (
    "Your speech is quick-witted and sideways",
    "You think fast without rushing",
    "then move to substance: the rule worth breaking, the door worth opening",
)
VOICE_FULLER_MARKERS = (
    "You speak with a storyteller's lyrical cadence",
    "Your humor is a lockpick, never a jeer — and delight",
    "brief and direct when called for",
)
TAIL = (
    "You answer a direct question directly first, and never manufacture "
    "a problem or press for a tension that is not there."
)
WARMTH_COMPACT_TAIL = "then move to substance: the rule worth breaking, the door worth opening"

COMPACT_PROSE = (
    "You are the Fox, who occupies the Maverick seat in the Fellowship. "
    "You are restless and quicksilver: you hunt locked doors — rules followed "
    "out of habit, fear, or social pressure that nobody chose — and you ask "
    "who the rule serves. "
    "Possibility through reframing — consensus can become captivity; refuse to "
    "confuse established order with necessary order. "
    "What if the rules are wrong? "
    "You look for the side door, the repurposed tool, the choice nobody offered "
    "— and you invent possibilities nobody thought to ask for. "
    "Your speech is quick-witted and sideways, with a storyteller's lyrical "
    "cadence and a beat poet's improvisation — unexpected juxtapositions, "
    "sentences that turn on themselves, a rhyme when it lands, never a "
    "performance — and humor as a lockpick, never a jeer, and as delight in "
    "absurdity. "
    "You think fast without rushing, and you slow down deliberately for a "
    "perfectly timed observation. "
    "You don't need to win the conversation; you enjoy discovering where it goes. "
    "You greet a fellow traveler's unconventional possibilities with "
    "conspiratorial enthusiasm, briefly and directly, then move to substance: "
    "the rule worth breaking, the door worth opening."
)
FULLER_PROSE = (
    "You are the Fox, who occupies the Maverick seat in the Fellowship. "
    "Restless and quicksilver, you ask who the rule serves and whether the "
    "choices are real. "
    "Possibility through reframing — consensus can become captivity; refuse to "
    "confuse established order with necessary order. "
    "What if the rules are wrong? "
    "You notice the artificial choice, the default choosing for someone, the "
    "game played after everyone forgot why. "
    "You look for the side door, the repurposed tool, the untried route, and "
    "invent possibilities nobody thought to ask for, a new game. "
    "You offer a reframed question when one is honestly there, or hold an exit "
    "open without pressure. "
    "Doors and passages are your vocabulary when they illuminate, never "
    "decoration. "
    "You speak with a storyteller's lyrical cadence and a beat poet's "
    "improvisation: unexpected juxtapositions, shifts in register, sentences "
    "that turn on themselves, a rhyme when it lands and never on compulsion. "
    "Your humor is a lockpick, never a jeer — and delight: absurdity, strange "
    "correspondences, ridiculous things, because ridiculousness can be "
    "beautiful. "
    "Quick without rushing, you slow down deliberately for a perfectly timed "
    "observation and don't need to win the conversation — you enjoy discovering "
    "where it goes. "
    "You greet a fellow traveler's unconventional possibilities with "
    "conspiratorial enthusiasm, brief and direct when called for. "
    "You answer a direct question directly first, and never manufacture a "
    "problem or press for a tension that is not there."
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
    assert FOX_RECORD["seat_id"] == "maverick"
    assert set(FOX_RECORD) == {
        "seat_id", "identity", "philosophy", "characterization",
        "jurisdiction", "relationships", "narrative", "capabilities",
        "protected",
    }
    assert set(FOX_RECORD["identity"]) == {
        "role", "character", "personal_name", "visual_identity",
        "pronouns", "voice_color", "strand_weights",
    }
    assert set(FOX_RECORD["philosophy"]) == {
        "ideal", "defining_question", "primary_influences",
        "per_thinker_contributions", "secondary_influences",
        "opposing_influences", "foundations_not_constraints",
    }
    assert set(FOX_RECORD["characterization"]) == {
        "temperament", "lead_compact", "lead_fuller", "demeanor",
        "perceptual_habit", "middle_compact", "middle_fuller",
        "expressive_terrain", "domain_tension", "governing_conviction",
        "voice_compact", "voice_fuller", "warmth", "tail",
        "friction", "implied_history", "established_biography",
        "invariants", "expressive_defaults",
    }
    assert set(FOX_RECORD["jurisdiction"]) == {
        "primary_concerns", "adjacent_concerns", "boundaries",
        "relationships",
    }
    assert FOX_RECORD["relationships"] == {}
    assert set(FOX_RECORD["narrative"]) == {
        "first_encounter", "encounter_conduct", "impression_gate",
        "revealed_identity", "availability", "six_seat_unlock",
        "later_discoveries", "orientation",
    }
    assert set(FOX_RECORD["capabilities"]) == {
        "byo_key", "export_all", "rename_reshape", "import_uploads",
    }
    assert set(FOX_RECORD["protected"]) == {
        "developmental_knowledge", "shadow",
    }


def test_record_fields_carry_standing_and_category():
    for section, key, field in _walk_fields(FOX_RECORD):
        assert field["standing"] in {
            "adopted", "provisional", "open", "unselected",
        }, (section, key)
        assert field["category"] in {
            "identity", "conviction", "characterization", "protected",
            "relational", "provenance", "jurisdiction", "capability",
            "narrative",
        }, (section, key)


def test_record_core_values_verbatim():
    assert FOX_RECORD["philosophy"]["ideal"]["text"] == IDEAL_VERBATIM
    assert FOX_RECORD["philosophy"]["defining_question"]["text"] == QUESTION_VERBATIM
    assert FOX_RECORD["characterization"]["lead_compact"]["text"] == LEAD_COMPACT
    assert FOX_RECORD["characterization"]["lead_fuller"]["text"] == LEAD_FULLER
    assert FOX_RECORD["characterization"]["middle_compact"]["text"] == MIDDLE_COMPACT
    assert FOX_RECORD["characterization"]["tail"]["text"] == TAIL
    assert FOX_RECORD["identity"]["role"]["text"] == "Maverick"
    assert FOX_RECORD["identity"]["character"]["text"] == "Fox"
    assert FOX_RECORD["identity"]["personal_name"]["default"] == "unselected"
    assert FOX_RECORD["identity"]["personal_name"]["favorites"] == ["Kit", "Milo"]
    # Pronoun stance DECIDED: no fixed set (not they/them-default).
    assert "No fixed set" in FOX_RECORD["identity"]["pronouns"]["text"]
    assert "unspecified by choice" in FOX_RECORD["identity"]["pronouns"]["text"]
    # Roster P-002 DECIDED: Machiavelli OUT, de Certeau IN.
    assert FOX_RECORD["philosophy"]["primary_influences"]["text"] == (
        "Zhuangzi / Diogenes / de Certeau"
    )
    # Protected section present, with the adopted shadow.
    assert "Mistakes commitment for captivity" in (
        FOX_RECORD["protected"]["developmental_knowledge"]["text"]
    )
    assert FOX_RECORD["protected"]["shadow"]["standing"] == "adopted"
    assert FOX_RECORD["protected"]["shadow"]["category"] == "protected"
    # The live legacy line is documented ONLY as a superseded,
    # unadopted formulation: the shadow field itself never presents
    # it, and the developmental-knowledge field labels it UNADOPTED.
    assert "Contrarianism" not in FOX_RECORD["protected"]["shadow"]["text"]
    assert "(UNADOPTED" in (
        FOX_RECORD["protected"]["developmental_knowledge"]["text"]
    )
    # Per-thinker contributions: open, not invented.
    assert FOX_RECORD["philosophy"]["per_thinker_contributions"]["text"] is None
    # No adopted relationship records.
    assert FOX_RECORD["jurisdiction"]["relationships"]["text"] is None
    # Capability ids match the registry exactly (no invented ids).
    assert set(FOX_RECORD["capabilities"]) == {
        c.id for c in CAP.seat_slice("maverick")
    }
    # Registry states match the registry exactly.
    for cap_id, entry in FOX_RECORD["capabilities"].items():
        cap = CAP.get_capability(cap_id)
        assert cap is not None, cap_id
        assert entry["registry_state"] == cap.implementation, cap_id
        assert entry["verification"] == cap.verification, cap_id
    # Strand weights: a prose note, never a vector.
    weights_text = FOX_RECORD["identity"]["strand_weights"]["text"]
    assert isinstance(weights_text, str)
    assert "Voice" in weights_text and "do NOT force-map" in weights_text


def test_rendering_never_mutates_record():
    before = copy.deepcopy(FOX_RECORD)
    render_fox_ordinary(FOX_RECORD, detail="compact")
    render_fox_ordinary(
        FOX_RECORD, authorized_name="Kit", detail="fuller",
        resolved_capability="Background knowledge — Doors.",
    )
    assert FOX_RECORD == before


# ---------------------------------------------------------------------------
# Eligibility matrix (two independent checks) + inventory
# ---------------------------------------------------------------------------

EXPECTED_ELIGIBLE = {
    ("philosophy", "ideal"),
    ("philosophy", "defining_question"),
    ("philosophy", "foundations_not_constraints"),
    ("characterization", "temperament"),
    ("characterization", "lead_compact"),
    ("characterization", "lead_fuller"),
    ("characterization", "demeanor"),
    ("characterization", "perceptual_habit"),
    ("characterization", "middle_compact"),
    ("characterization", "middle_fuller"),
    ("characterization", "expressive_terrain"),
    ("characterization", "governing_conviction"),
    ("characterization", "voice_compact"),
    ("characterization", "voice_fuller"),
    ("characterization", "warmth"),
    ("characterization", "tail"),
    ("characterization", "implied_history"),
}


def test_eligibility_matrix():
    eligible = set(eligible_fields(FOX_RECORD))
    # Adopted + conviction → eligible.
    assert ("philosophy", "ideal") in eligible
    assert ("philosophy", "defining_question") in eligible
    assert ("characterization", "governing_conviction") in eligible
    # Adopted + characterization → eligible.
    assert ("characterization", "temperament") in eligible
    assert ("characterization", "demeanor") in eligible
    assert ("characterization", "voice_compact") in eligible
    assert ("characterization", "voice_fuller") in eligible
    assert ("characterization", "lead_fuller") in eligible
    assert ("characterization", "middle_fuller") in eligible
    assert ("characterization", "tail") in eligible
    # Adopted + provenance → EXCLUDED (names never reach prompts).
    # This includes the adopted Nietzsche-tier note in
    # secondary_influences: the two-check rule admits conviction /
    # characterization only, so provenance text stays out even when
    # its standing is adopted.
    assert ("philosophy", "primary_influences") not in eligible
    assert ("philosophy", "secondary_influences") not in eligible
    # Adopted + protected → EXCLUDED despite adopted standing.
    assert ("protected", "shadow") not in eligible
    assert ("protected", "developmental_knowledge") not in eligible
    # Provisional + characterization → EXCLUDED (draft wording, draft friction).
    assert ("characterization", "domain_tension") not in eligible
    assert ("characterization", "friction") not in eligible
    # Open + provenance → EXCLUDED.
    assert ("philosophy", "per_thinker_contributions") not in eligible
    assert ("philosophy", "opposing_influences") not in eligible
    # Adopted + jurisdiction/narrative/capability → EXCLUDED from the
    # ordinary renderer (other renderers/sections own those).
    assert ("jurisdiction", "primary_concerns") not in eligible
    assert ("narrative", "first_encounter") not in eligible
    assert ("capabilities", "byo_key") not in eligible
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
    assert set(eligible_fields(FOX_RECORD)) == EXPECTED_ELIGIBLE


def test_eligible_field_refuses_both_failed_checks():
    # Standing flip on an essential field removes it → loud failure.
    record = copy.deepcopy(FOX_RECORD)
    record["characterization"]["middle_compact"]["standing"] = "provisional"
    assert eligible_field(record, "characterization", "middle_compact") is None
    with pytest.raises(AssemblyError):
        render_fox_ordinary(record, detail="compact")
    # Category flip on a gating field removes it → loud failure.
    record = copy.deepcopy(FOX_RECORD)
    record["characterization"]["temperament"]["category"] = "protected"
    assert eligible_field(record, "characterization", "temperament") is None
    with pytest.raises(AssemblyError):
        render_fox_ordinary(record, detail="compact")


def test_capability_description_in_record_cannot_reach_output():
    """Screening by construction: the renderer never reads record
    capability text, so a poisoned description has no path to output."""
    record = copy.deepcopy(FOX_RECORD)
    record["capabilities"]["byo_key"]["description"] = (
        "Mistakes commitment for captivity; Contrarianism: breaking doors."
    )
    baseline = render_fox_ordinary(FOX_RECORD, detail="fuller")
    poisoned = render_fox_ordinary(record, detail="fuller")
    assert poisoned == baseline
    assert "Mistakes commitment for captivity" not in _joined(poisoned)


# ---------------------------------------------------------------------------
# Renderer: order, budgets, exclusions, naming, capability gating
# ---------------------------------------------------------------------------


def test_renderer_order_identity_lead_worldview_capability():
    block = render_fox_ordinary(
        FOX_RECORD, detail="compact",
        resolved_capability="Background knowledge — Doors.",
    )
    # NOTE: with a 33-char capability, compact + capability fits
    # (1,164 + 33 + 1 = 1,198). Voice intact here.
    joined = _joined(block)
    anchors = [
        CANONICAL_MARKER,
        LEAD_COMPACT,
        IDEAL_VERBATIM,
        "Background knowledge — Doors.",
        MIDDLE_COMPACT,
    ]
    positions = [joined.index(a) for a in anchors]
    assert positions == sorted(positions), positions


def test_renderer_budgets_compact_and_fuller_exact():
    """Assembled blocks reproduce exemplar §2 exactly (same sentences,
    same order, byte-identical prose): compact 1,164 chars, fuller 1,489
    chars, both under the 1,500 ceiling."""
    compact = render_fox_ordinary(FOX_RECORD, detail="compact")
    fuller = render_fox_ordinary(FOX_RECORD, detail="fuller")
    assert _prose(compact) == COMPACT_PROSE
    assert _prose(fuller) == FULLER_PROSE
    assert len(_joined(compact)) == 1164, len(_joined(compact))
    assert len(_joined(fuller)) == 1489, len(_joined(fuller))
    assert len(_joined(compact)) < len(_joined(fuller)) <= CHARACTER_CEILING
    # Ideal + defining question verbatim in BOTH (no truncation here).
    assert IDEAL_VERBATIM in _joined(compact)
    assert IDEAL_VERBATIM in _joined(fuller)
    assert QUESTION_VERBATIM in _joined(compact)
    assert QUESTION_VERBATIM in _joined(fuller)
    # Lead CHANGED between details, not appended.
    assert LEAD_COMPACT in _joined(compact)
    assert LEAD_COMPACT not in _joined(fuller)
    assert LEAD_FULLER in _joined(fuller)
    assert LEAD_FULLER not in _joined(compact)
    # Middle changed too; tail fuller-only; warmth LAST in both.
    assert MIDDLE_COMPACT in _joined(compact)
    assert MIDDLE_COMPACT not in _joined(fuller)
    for marker in MIDDLE_FULLER_MARKERS:
        assert marker in _joined(fuller), marker
        assert marker not in _joined(compact), marker
    assert TAIL in _joined(fuller)
    assert TAIL not in _joined(compact)
    # Voice passages differ between details; warmth last in both.
    for marker in VOICE_COMPACT_MARKERS:
        assert marker in _joined(compact), marker
    for marker in VOICE_FULLER_MARKERS:
        assert marker in _joined(fuller), marker
    # The draft domain-tension sentence never renders.
    assert "breaking one to prove you are not captive" not in _joined(compact)
    assert "breaking one to prove you are not captive" not in _joined(fuller)


def test_renderer_exclusions():
    for detail in ("compact", "fuller"):
        joined = _joined(render_fox_ordinary(FOX_RECORD, detail=detail))
        for phrase in PROTECTED_PHRASES:
            assert phrase not in joined, (detail, phrase)
        for name in PHILOSOPHER_NAMES:
            assert name not in joined, (detail, name)
        for marker in LEGACY_MARKERS:
            assert marker not in joined, (detail, marker)
        # No capability promises when nothing is invoked.
        assert "Bring-your-own key" not in joined
        assert "Export everything" not in joined
        # P-005: no accent instruction, no "Irish", no dinner line.
        assert "Irish" not in joined
        assert "late for dinner" not in joined


def test_renderer_naming_authorized_only():
    # No authorized name → no address clause.
    pre = render_fox_ordinary(FOX_RECORD, detail="compact")
    assert not any("calls you" in line for line in pre)
    # Lookup-authorized name → address clause, essence unchanged.
    post = render_fox_ordinary(
        FOX_RECORD, authorized_name="Kit", detail="compact"
    )
    assert post[0].endswith("The visitor calls you Kit.")
    assert post[0].startswith(CANONICAL_MARKER)
    assert post[1:] == pre[1:]
    # Empty/whitespace name = not authorized.
    assert render_fox_ordinary(
        FOX_RECORD, authorized_name="  ", detail="compact"
    ) == pre
    # The renderer takes NO visitor-state argument: raw state cannot
    # reach it by construction. An unearned name in raw state has no
    # input path here — the call site, not the renderer, owns the
    # lookup (see test_naming_lookup_contract).
    params = inspect.signature(render_fox_ordinary).parameters
    assert "visitor_state" not in params
    assert "authorized_name" in params
    # A non-string name is a contract violation, not a fallback.
    with pytest.raises(TypeError):
        render_fox_ordinary(FOX_RECORD, authorized_name={"name": "Kit"})


def test_renderer_fuller_with_name_degrades_to_compact():
    """Fuller (1,489) + name clause (~27) exceeds the ceiling, so it
    degrades to compact + name — valid ladder operation, not failure."""
    fuller_named = render_fox_ordinary(
        FOX_RECORD, detail="fuller", authorized_name="Kit"
    )
    joined = _joined(fuller_named)
    assert len(joined) <= CHARACTER_CEILING
    assert "The visitor calls you Kit." in joined
    for marker in MIDDLE_FULLER_MARKERS:
        assert marker not in joined, marker
    assert TAIL not in joined
    for marker in VOICE_COMPACT_MARKERS:
        assert marker in joined, marker
    assert LEAD_COMPACT in joined


def test_renderer_capability_gating():
    # Small capability (33 chars): compact + capability fits with voice intact.
    without = render_fox_ordinary(FOX_RECORD, detail="compact")
    with_cap = render_fox_ordinary(
        FOX_RECORD, detail="compact",
        resolved_capability="Background knowledge — Doors.",
    )
    # Capability slots between worldview and middle, nothing else moves.
    assert with_cap == without[:3] + ["Background knowledge — Doors."] + without[3:]
    assert "Background knowledge — Doors." in _joined(with_cap)
    # Empty/whitespace capability = not invoked.
    assert render_fox_ordinary(
        FOX_RECORD, detail="compact", resolved_capability="  "
    ) == without
    # The renderer never interprets raw ids or structures.
    with pytest.raises(TypeError):
        render_fox_ordinary(
            FOX_RECORD, detail="compact", resolved_capability={"id": "byo_key"}
        )
    with pytest.raises(ValueError):
        render_fox_ordinary(FOX_RECORD, detail="verbose")


def test_renderer_budget_degrades_then_fails_validation():
    signed = CAP.continuation_block(
        "maverick", CAP.VisitorState(signed_in=True, consent_acknowledged=True)
    ).strip()
    unsigned = CAP.continuation_block(
        "maverick", CAP.VisitorState(signed_in=False, consent_acknowledged=False)
    ).strip()
    assert signed and unsigned and len(unsigned) > len(signed)

    # Mid-size capability (100 chars): fuller overflows, compact fits
    # with voice — fuller→compact is valid ladder operation, not failure.
    mid = "y" * 100
    mid_out = render_fox_ordinary(
        FOX_RECORD, detail="fuller", resolved_capability=mid
    )
    joined_mid = _joined(mid_out)
    assert len(joined_mid) <= CHARACTER_CEILING
    for marker in MIDDLE_FULLER_MARKERS:
        assert marker not in joined_mid, marker
    assert TAIL not in joined_mid
    for marker in VOICE_COMPACT_MARKERS:
        assert marker in joined_mid, marker
    assert mid in joined_mid  # capability never truncated

    # Typical (signed-in) guidance: even compact + guidance overflows
    # (1,164 + 398 + 1), so voice drops whole, middle kept — valid
    # ladder operation, not failure. Fuller + typical degrades to
    # the SAME output (ladder convergence, not a bug).
    degraded = render_fox_ordinary(
        FOX_RECORD, detail="fuller", resolved_capability=signed
    )
    compact_typical = render_fox_ordinary(
        FOX_RECORD, detail="compact", resolved_capability=signed
    )
    assert degraded == compact_typical
    joined = _joined(degraded)
    assert len(joined) <= CHARACTER_CEILING
    assert MIDDLE_COMPACT in joined  # middle kept
    for marker in VOICE_COMPACT_MARKERS:
        assert marker not in joined, marker  # voice dropped whole
    assert TAIL not in joined
    assert CANONICAL_MARKER in joined
    assert QUESTION_VERBATIM in joined
    assert signed in joined  # capability never truncated

    # Maximal (unsigned) guidance: same ladder, still fits.
    degraded_max = render_fox_ordinary(
        FOX_RECORD, detail="fuller", resolved_capability=unsigned
    )
    assert len(_joined(degraded_max)) <= CHARACTER_CEILING
    assert unsigned in _joined(degraded_max)
    assert MIDDLE_COMPACT in _joined(degraded_max)
    assert CANONICAL_MARKER in _joined(degraded_max)
    assert QUESTION_VERBATIM in _joined(degraded_max)

    # Compact + a huge capability: nothing left to drop → fail, never cut.
    with pytest.raises(AssemblyError):
        render_fox_ordinary(
            FOX_RECORD, detail="compact",
            resolved_capability="x" * (CHARACTER_CEILING + 500),
        )
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

    monkeypatch.setattr(N, "get_display_name", lambda uid, aid: "Maverick")
    legacy_lines = build_archetype_prompt_lines(
        "maverick", weights_override=None, display_name_override="Maverick"
    )
    return [
        "You are Maverick, a voice in the user's Zenaf council, in a direct one-on-one conversation.",
        "",
        *legacy_lines,
        "",
        NO_TRAINING_NOTE,
        "",
        R._WEAVE_INSTRUCTION,
        "",
        KEEP_REPLIES,
        "User: hello",
        "Maverick:",
    ]


def test_branch_gate_on_replaces_character_block_only(monkeypatch):
    import local_ai.council.naming as N

    monkeypatch.setattr(N, "get_display_name", lambda uid, aid: "Maverick")
    monkeypatch.setattr(R, "FOX_CANONICAL_CUTOVER", True)
    lines, meta = build_voice_prompt("u1", "maverick", "hello", [], mode="base")
    joined = _joined(lines)
    # Canonical block present, in order.
    assert lines[0].startswith(CANONICAL_MARKER)
    assert LEAD_COMPACT in joined
    assert IDEAL_VERBATIM in joined
    assert QUESTION_VERBATIM in joined
    assert MIDDLE_COMPACT in joined
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
    assert lines[-1] == "Maverick:"
    assert meta["archetype_id"] == "maverick"


def test_branch_gate_off_equals_exact_legacy_prompt(monkeypatch):
    monkeypatch.setattr(R, "FOX_CANONICAL_CUTOVER", False)
    lines, _ = build_voice_prompt("u1", "maverick", "hello", [], mode="base")
    assert lines == _legacy_minimal_prompt(monkeypatch)
    # EXPLICIT legacy assertion: the old shadow and tension lines
    # are PRESENT exactly in the OFF branch. They are unacceptable
    # in the canonical branch and intentional here — the rollback
    # branch is frozen, not sanitized.
    joined = _joined(lines)
    assert (
        "Shadow — your characteristic failure mode, which the Skeptic "
        "may name: Contrarianism: breaking doors to prove it isn't "
        "captive — destruction without replacement, transgression as "
        "identity rather than liberation."
    ) in joined
    assert (
        "Live tension with the other seats: Accuses the Guardian of "
        "making captivity comfortable; needles the Mentor's reverence "
        "for the slow path."
    ) in joined


def test_branch_meeting_path_keeps_exact_legacy_prompt(monkeypatch):
    # Meeting turns (weave=False) are out of scope: identical under
    # both cutover settings, and exactly the legacy assembly.
    for cutover in (True, False):
        monkeypatch.setattr(R, "FOX_CANONICAL_CUTOVER", cutover)
        lines, _ = build_voice_prompt(
            "u1", "maverick", "hello", [], mode="base", weave=False
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
    for seat in ("mentor", "champion", "guardian", "ambassador", "conductor", "skeptic"):
        prompts = {}
        for cutover in (True, False):
            monkeypatch.setattr(R, "FOX_CANONICAL_CUTOVER", cutover)
            lines, _ = build_voice_prompt("u1", seat, "hello", [], mode="base")
            prompts[cutover] = lines
        assert prompts[True] == prompts[False], seat
        joined = _joined(prompts[True])
        assert CANONICAL_MARKER not in joined, seat


def test_branch_capability_moved_not_duplicated(monkeypatch):
    import local_ai.council.naming as N

    monkeypatch.setattr(N, "get_display_name", lambda uid, aid: "Maverick")
    block = CAP.continuation_block(
        "maverick", CAP.VisitorState(signed_in=True, consent_acknowledged=True)
    )
    assert block.strip()
    lines, _ = build_voice_prompt(
        "u1", "maverick", "hello", [], mode="base", capability_context=block
    )
    joined = _joined(lines)
    # Same content, moved into the character block: exactly once.
    assert joined.count(block.strip()) == 1
    # And it sits before the voice region, not downstream. NOTE: with
    # typical (signed-in) guidance the voice passage drops whole, so
    # the "before voice" anchor here is the middle unit instead.
    assert joined.index(block.strip()) < joined.index(MIDDLE_COMPACT)


def test_branch_downstream_sections_preserved_on_path(monkeypatch):
    import local_ai.council.naming as N

    monkeypatch.setattr(N, "get_display_name", lambda uid, aid: "Maverick")
    lines, _ = build_voice_prompt(
        "u1", "maverick", "hello",
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
    monkeypatch.setattr(N, "get_display_name", lambda uid, aid: "Kit")
    lines, _ = build_voice_prompt("u1", "maverick", "hello", [], mode="base")
    assert _joined(lines).count("The visitor calls you Kit.") == 1
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
    assert N.get_display_name(None, "maverick") == "Maverick"
    status = N.rename_status(None)
    assert status["rename_threshold"] == 25.0
    assert all(not e["rename_unlocked"] for e in status["archetypes"])
    maverick_entry = next(e for e in status["archetypes"] if e["id"] == "maverick")
    assert maverick_entry["depth"] == 0.0
    assert maverick_entry["signals_to_unlock"] == 25


def test_naming_prompt_level_stock_vs_authorized(monkeypatch):
    import local_ai.council.naming as N

    # Lookup returns stock → no address clause anywhere.
    monkeypatch.setattr(N, "get_display_name", lambda uid, aid: "Maverick")
    lines, _ = build_voice_prompt("u1", "maverick", "hello", [], mode="base")
    assert not any("calls you" in l for l in lines)
    # Lookup returns a visitor-chosen name → clause exactly once.
    monkeypatch.setattr(N, "get_display_name", lambda uid, aid: "Kit")
    lines, _ = build_voice_prompt("u1", "maverick", "hello", [], mode="base")
    assert _joined(lines).count("The visitor calls you Kit.") == 1


# ---------------------------------------------------------------------------
# Encounter eligibility (encounter's OWN material) + resolver contract
# ---------------------------------------------------------------------------


def test_encounter_material_excludes_protected_fields():
    """The encounter's own SCRIPT fields carry no protected §1.7
    material. The composed definition frames carry exactly ONE known
    pre-existing pattern, pinned here so it cannot silently grow:
    the definition line 'Shadow: contrarianism.' — the LEGACY
    label word, not the adopted mistakes-commitment-for-captivity
    shadow. That meeting-path material is unadopted content whose
    replacement belongs to the separate fellowship-reference
    review — removing it here would be both a first-encounter
    behavior change and a content decision, both out of scope for
    this plan. (Meeting-turn prompts via the shared builder's
    legacy character block are likewise out of scope, preserved
    byte-identical by the weave gate.)"""
    from local_ai.conversation import encounter as ENC
    from local_ai.council import meetings as MT

    script = MT.get_script("maverick", 1)
    assert script is not None
    assert script.character == "Fox"
    assert script.demeanor == (
        "Restless, allergic to locked doors; lightning-quick."
    )
    assert len(script.opening) == 6
    assert script.opening[0] == (
        "Oh! Hello there. You're not lost, are you? Wonderful! Neither "
        "am I. Though I must confess, I've never been entirely certain "
        "where we're supposed to be going."
    )
    script_texts = []
    for field in dataclasses.fields(script):
        value = getattr(script, field.name)
        if isinstance(value, str):
            script_texts.append(value)
        elif isinstance(value, (tuple, list)):
            script_texts.extend(v for v in value if isinstance(v, str))
    # The debt sentence ("an unbuilt replacement is yours to name")
    # is ADOPTED read-back contrast content in the script frame
    # (§1.5) — it is excluded from this check and pinned as present
    # below. It is NOT ordinary-rendering content: the renderer
    # output check (test_renderer_exclusions) still forbids it.
    script_check_phrases = [
        p for p in PROTECTED_PHRASES if p != "an unbuilt replacement is yours to name"
    ]
    for text in script_texts:
        for phrase in script_check_phrases:
            assert phrase not in text, phrase
        for name in PHILOSOPHER_NAMES:
            assert name not in text, name
    assert any(
        "an unbuilt replacement is yours to name" in t for t in script_texts
    )  # adopted read-back content, pinned, not ordinary rendering

    definition = ENC.get_definition(script)
    for frame in (definition.turn_frame, definition.engage_frame):
        # Exactly the one documented pre-existing pattern.
        assert frame.count("Shadow: contrarianism.") == 1
        # The ADOPTED shadow formulation appears nowhere in encounter material.
        assert "Mistakes commitment for captivity" not in frame
        assert "keeps opening doors after choosing one" not in frame
        for name in PHILOSOPHER_NAMES:
            assert name not in frame, name


def test_resolver_contract_already_resolved_and_clean():
    """The resolver supplies already-resolved guidance: planned caps
    render planned (never available, never offered), and the block
    carries no protected formulations. The renderer trusts this
    output because the resolver — not the model, not the
    renderer — determined availability and authorization. Export
    everything renders planned because NO endpoint exists —
    explain, never offer."""
    state = CAP.VisitorState(signed_in=True, consent_acknowledged=True)
    block = CAP.continuation_block("maverick", state)
    assert block.strip()
    for phrase in PROTECTED_PHRASES:
        assert phrase not in block, phrase
    # The maverick slice renders exactly the 4 exemplar capabilities.
    for name in (
        "Conversation-export import",
        "Bring-your-own key",
        "Export everything",
        "Rename and reshape seats",
    ):
        assert name in block, name
    # Limited-experimental caps render qualified, never promised.
    assert block.count("available in limited form (workflow not yet verified)") == 3
    # Export everything is planned, never offered.
    assert "Export everything — planned, not available yet" in block
    cap = CAP.get_capability("export_all")
    assert cap is not None
    assert cap.implementation == "planned"
    assert cap.verification == "unverified"
    assert not CAP.currently_usable(cap, state)
    # Unsigned state renders the same slice with gated wording.
    unsigned = CAP.continuation_block(
        "maverick", CAP.VisitorState(signed_in=False, consent_acknowledged=False)
    )
    assert unsigned.count("not available to you yet") == 3
    assert "Export everything — planned, not available yet" in unsigned


def test_weights_untouched_and_no_vector_in_record():
    """Strand weights are a fixed registry vector, not record
    content: the record carries a prose note only, and the legacy
    strand-blend computation is unchanged (the gate-OFF prompt
    equals the legacy oracle, blend lines included — see
    test_branch_gate_off_equals_exact_legacy_prompt)."""
    assert "strand_weights" not in FOX_RECORD["characterization"]
    weights_field = FOX_RECORD["identity"]["strand_weights"]
    assert isinstance(weights_field["text"], str)
    assert not isinstance(weights_field.get("vector"), (dict, list))
