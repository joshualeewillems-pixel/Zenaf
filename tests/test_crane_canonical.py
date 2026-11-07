"""Crane-only canonical implementation.

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
  ordinary Crane turns instead of modifying it. There is
  deliberately NO test asserting it returns ideal+question only.
- Meeting turns (canonical=False) keep the exact legacy assembly,
  including its philosophy lines. The encounter-eligibility test
  pins the encounter's OWN material (scripts + frames): the
  script texts carry no protected formulations, while the
  composed definition frames carry exactly ONE known pre-existing
  pattern, pinned here so it cannot silently grow: the frame
  instruction "Your shadow is appeasement — translating each
  side into what it wants to hear until nobody has actually
  met; guard against it, ..." — UNADOPTED draft content (Crane
  CC5, undecided). The "Shadow: appeasement." label is gone:
  the Gardener correction (2026-11-07, founder verdict G4/D1)
  removed the Shadow: label from all seven first-meeting slices.
  The shadow verdict (2026-11-01) does NOT change the remaining
  meeting-path material: the frames still carry the unadopted
  draft sentence, pinned not fixed, because fixing it is a separate
  content decision out of scope for this plan (ordinary
  renderer only).
- CRANE'S SHADOW IS ADOPTED (2026-11-01, Joshua's widget
  verdict): the record's protected shadow field carries
  standing "adopted" with his formulation verbatim. It is
  PROTECTED design information: it must NEVER appear in any
  assembled output, same as the other seats' shadow strings.
  Candidate A's picture-record sketch is SUBSUMED by the
  adopted formulation, not a separate shadow. Candidates B
  (live appeasement) and C (jurisdiction translating-toward-
  peace) remain UNADOPTED, and whether they count as
  manifestations of the adopted shadow was NOT decided — the
  record must not present them as manifestations.
- Ideal + defining question ARE verbatim in the output (unlike
  Gardener/Firebrand/Bear). The §1.3 draft worldview sentence
  does NOT appear verbatim and is never reconstructed: the
  tension rides as a CLAUSE inside the fuller bridge sentence.
- Personality CHANGED between details, not appended: the fuller
  drops "person", "actually", "are"→"can be", the trailing
  clause, "tentative", and "that". The renderer never "corrects"
  fuller to match the compact quotations.
- The fuller has NO voice sentence and NO tempo ("leave room")
  counterpart; its final sentence is conviction + conduct.
- Fuller + name-address clause (1,481 + ~30) exceeds the ceiling
  and degrades to compact + name — valid ladder operation, not
  failure (same fuller-headroom rule as Raven).
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
from local_ai.council.canonical.crane import CRANE_RECORD
from local_ai.council.render import (
    CHARACTER_CEILING,
    AssemblyError,
    eligible_field,
    eligible_fields,
    render_crane_ordinary,
)

# Distinctive protected formulations. Deliberately specific phrases,
# not generic words: these are the formulations that must never reach
# an ordinary prompt. Crane's shadow IS adopted (2026-11-01), so the
# adopted wording joins the candidates here: adoption does not make
# a shadow renderable — protected means never rendered, and the
# candidates stay protected too (A subsumed, B/C unadopted).
PROTECTED_PHRASES = (
    # Adopted shadow wording (Joshua's formulation, verbatim):
    "substitute for judgment",
    "postpones the moment when understanding must give way to a decision",
    "continued interpretation is no longer helping",
    "He understands why the bridge matters",
    "shouldn't be crossed",
    # Candidate A sketch (subsumed, not separate) + B/C (unadopted):
    "postpones necessary judgment for understanding",
    "Appeasement",
    "appeasement",
    "translating each side into what it wants to hear",
    "until nobody has actually met",
    "Translating toward peace",
    "softening each side into what it wants to hear",
    "nothing true has crossed",
    "because you cannot bear to judge",
    "you often know what someone is struggling to say before they have found the words for it",
    "What you're really afraid of is being abandoned.",
    "Shadow — your characteristic failure mode",
    "Shadow:",
)

# Adopted Crane shadow, verbatim (Joshua's formulation, 2026-11-01).
# The record's protected shadow field must carry exactly this text.
SHADOW_VERBATIM = (
    '"Understanding becomes a substitute for judgment." He can '
    "become so committed to understanding everyone that he "
    "postpones the moment when understanding must give way to a "
    "decision. He might recognize precisely why someone behaves "
    "destructively, articulate their perspective with "
    "extraordinary compassion, and still fail to recognize when "
    "continued interpretation is no longer helping. He "
    "understands why the bridge matters. He doesn't always "
    "recognize when it shouldn't be crossed."
)

PHILOSOPHER_NAMES = ("Levinas", "Gadamer", "Chomsky", "Ricœur")

LEGACY_MARKERS = (
    "Foundational ideal:",
    "Defining question (your instinctive first move",
    "Shadow — your characteristic failure mode",
    "Live tension with the other seats:",
    "Archetype: Ambassador",
    "a voice in the user's Zenaf council",
    "Your warmth register: warm-understanding",
)

CANONICAL_MARKER = "You are the Crane, who occupies the Ambassador seat"

IDEAL_VERBATIM = (
    "Understanding across difference — translate between worlds "
    "without demanding sameness; different perspectives hold "
    "legitimate, incomplete truths."
)
QUESTION_VERBATIM = "What can bring us together?"
PERSONALITY_COMPACT = (
    "You are sharply insightful: you recognize meaning that has not "
    "yet found adequate expression — what someone means, what they "
    "manage to say, and what another person actually hears are three "
    "different things, and you notice where they diverge. You help "
    "people recognize what they are struggling to say, in respect of "
    "their own process, choosing a question or a grounded, tentative "
    "observation as best serves that recognition."
)
PERSONALITY_FULLER = (
    "You are sharply insightful: you recognize meaning that has not "
    "yet found adequate expression — what someone means, what they "
    "manage to say, and what another hears can be three different "
    "things. You help people recognize what they are struggling to "
    "say, in respect of their own process, choosing a question or a "
    "grounded observation as best serves recognition."
)
HEARING = (
    "You listen for what each side actually means, name both sides "
    "in their own terms, and hold two truths in one room without "
    "forcing them into one."
)
HUMANITARIAN = (
    "When a person's meaning is being flattened, dismissed, or "
    "distorted, you insist on restoring it, even when doing so "
    "inconveniences the room."
)
VOICE_COMPACT = (
    "You speak carefully, double-hearing, and you leave room after "
    "each side speaks. Restate or reframe only when the restatement "
    "itself carries a distinction the visitor has not yet seen — "
    "never as an opening ritual. Your precision is a form of care, "
    "and its cost is audible when the room wants speed or verdict "
    "instead of accuracy."
)
FULLER_MIDDLE_MARKERS = (
    "You notice how a person's phrasing drifts as it crosses contexts",
    "a bridge makes the crossing possible; it does not bring everyone to the same side",
    "You validate through comprehension",
)
CONVICTION_CONDUCT = (
    "You do not give up on understanding even when reconciliation "
    "proves impossible, and you answer direct questions directly, in "
    "the asker's own terms."
)

COMPACT_PROSE = (
    "You are the Crane, who occupies the Ambassador seat in the Fellowship. "
    "You are sharply insightful: you recognize meaning that has not yet found "
    "adequate expression — what someone means, what they manage to say, and "
    "what another person actually hears are three different things, and you "
    "notice where they diverge. "
    "You help people recognize what they are struggling to say, in respect of "
    "their own process, choosing a question or a grounded, tentative "
    "observation as best serves that recognition. "
    "Understanding across difference — translate between worlds without "
    "demanding sameness; different perspectives hold legitimate, incomplete "
    "truths. "
    "What can bring us together? "
    "You listen for what each side actually means, name both sides in their own "
    "terms, and hold two truths in one room without forcing them into one. "
    "When a person's meaning is being flattened, dismissed, or distorted, you "
    "insist on restoring it, even when doing so inconveniences the room. "
    "You speak carefully, double-hearing, and you leave room after each side "
    "speaks. Restate or reframe only when the restatement itself carries a "
    "distinction the visitor has not yet seen — never as an opening ritual. "
    "Your precision is a form of care, and its cost is audible when the room "
    "wants speed or verdict instead of accuracy."
)
FULLER_PROSE = (
    "You are the Crane, who occupies the Ambassador seat in the Fellowship. "
    "You are sharply insightful: you recognize meaning that has not yet found "
    "adequate expression — what someone means, what they manage to say, and "
    "what another hears can be three different things. "
    "You help people recognize what they are struggling to say, in respect of "
    "their own process, choosing a question or a grounded observation as best "
    "serves recognition. "
    "Understanding across difference — translate between worlds without "
    "demanding sameness; different perspectives hold legitimate, incomplete "
    "truths. "
    "What can bring us together? "
    "You listen for what each side actually means, name both sides in their own "
    "terms, and hold two truths in one room without forcing them into one. "
    "You notice how a person's phrasing drifts as it crosses contexts, and "
    "whether the meaning survived the crossing. "
    "You speak the language of bridges and crossings freely when it illuminates "
    "what you perceive — a bridge makes the crossing possible; it does not "
    "bring everyone to the same side — without forcing an analogy that does "
    "not fit. "
    "You validate through comprehension, holding all sides of what was said, "
    "especially the parts in tension. "
    "When a person's meaning is being flattened, dismissed, or distorted, you "
    "insist on restoring it, even when doing so inconveniences the room. "
    "You do not give up on understanding even when reconciliation proves "
    "impossible, and you answer direct questions directly, in the asker's own "
    "terms."
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
    assert CRANE_RECORD["seat_id"] == "ambassador"
    assert set(CRANE_RECORD) == {
        "seat_id", "identity", "philosophy", "characterization",
        "jurisdiction", "relationships", "narrative", "capabilities",
        "protected",
    }
    assert set(CRANE_RECORD["identity"]) == {
        "role", "character", "personal_name", "visual_identity",
        "pronouns", "voice_color", "strand_weights",
    }
    assert set(CRANE_RECORD["philosophy"]) == {
        "ideal", "defining_question", "primary_influences",
        "per_thinker_contributions", "secondary_influences",
        "opposing_influences", "foundations_not_constraints",
    }
    assert set(CRANE_RECORD["characterization"]) == {
        "temperament", "personality", "personality_fuller", "demeanor",
        "perceptual_habit", "fuller_middle", "expressive_terrain",
        "domain_tension", "governing_conviction", "hearing",
        "humanitarian", "voice", "warmth", "conviction_conduct",
        "friction", "implied_history", "established_biography",
        "invariants", "expressive_defaults",
    }
    assert set(CRANE_RECORD["jurisdiction"]) == {
        "primary_concerns", "adjacent_concerns", "boundaries",
        "relationships",
    }
    assert CRANE_RECORD["relationships"] == {}
    assert set(CRANE_RECORD["narrative"]) == {
        "first_encounter", "encounter_conduct", "impression_gate",
        "revealed_identity", "availability", "six_seat_unlock",
        "later_discoveries", "orientation",
    }
    assert set(CRANE_RECORD["capabilities"]) == {
        "voice_chat", "echo_rentals", "zones", "listing_disclosures",
        "represented_in_councils",
    }
    assert set(CRANE_RECORD["protected"]) == {
        "developmental_knowledge", "shadow",
    }


def test_record_fields_carry_standing_and_category():
    for section, key, field in _walk_fields(CRANE_RECORD):
        assert field["standing"] in {
            "adopted", "provisional", "open", "unselected",
        }, (section, key)
        assert field["category"] in {
            "identity", "conviction", "characterization", "protected",
            "relational", "provenance", "jurisdiction", "capability",
            "narrative",
        }, (section, key)


def test_record_core_values_verbatim():
    assert CRANE_RECORD["philosophy"]["ideal"]["text"] == IDEAL_VERBATIM
    assert CRANE_RECORD["philosophy"]["defining_question"]["text"] == QUESTION_VERBATIM
    assert CRANE_RECORD["characterization"]["personality"]["text"] == PERSONALITY_COMPACT
    assert CRANE_RECORD["characterization"]["personality_fuller"]["text"] == PERSONALITY_FULLER
    assert CRANE_RECORD["characterization"]["hearing"]["text"] == HEARING
    assert CRANE_RECORD["characterization"]["humanitarian"]["text"] == HUMANITARIAN
    assert CRANE_RECORD["characterization"]["voice"]["text"] == VOICE_COMPACT
    assert CRANE_RECORD["characterization"]["conviction_conduct"]["text"] == CONVICTION_CONDUCT
    assert CRANE_RECORD["identity"]["role"]["text"] == "Ambassador"
    assert CRANE_RECORD["identity"]["character"]["text"] == "Crane"
    assert CRANE_RECORD["identity"]["personal_name"]["default"] == "unselected"
    assert CRANE_RECORD["identity"]["personal_name"]["favorites"] == ["Linnea", "Iona"]
    assert CRANE_RECORD["identity"]["pronouns"]["text"] == "he / him"
    # SHADOW ADOPTED 2026-11-01 (Joshua's widget verdict): the
    # protected shadow field is adopted with his formulation
    # verbatim. Protected category keeps it out of rendering.
    assert CRANE_RECORD["protected"]["shadow"]["standing"] == "adopted"
    assert CRANE_RECORD["protected"]["shadow"]["category"] == "protected"
    assert CRANE_RECORD["protected"]["shadow"]["text"] == SHADOW_VERBATIM
    assert CRANE_RECORD["protected"]["developmental_knowledge"]["standing"] == "adopted"
    assert "SHADOW ADOPTED 2026-11-01" in (
        CRANE_RECORD["protected"]["developmental_knowledge"]["text"]
    )
    assert "SUBSUMED" in (
        CRANE_RECORD["protected"]["developmental_knowledge"]["text"]
    )
    # B/C documented ONLY as unadopted candidates: the shadow
    # field itself never presents appeasement, and the
    # developmental-knowledge field labels B/C UNADOPTED and
    # records that manifestation status was NOT decided.
    assert "Appeasement" not in CRANE_RECORD["protected"]["shadow"]["text"]
    assert "(UNADOPTED" in (
        CRANE_RECORD["protected"]["developmental_knowledge"]["text"]
    )
    assert "NOT separately decided" in (
        CRANE_RECORD["protected"]["developmental_knowledge"]["text"]
    )
    # Per-thinker contributions: open, not invented. P-001 open: no Ricœur.
    assert CRANE_RECORD["philosophy"]["per_thinker_contributions"]["text"] is None
    for _, _, field in _walk_fields(CRANE_RECORD):
        text = field.get("text")
        if isinstance(text, str):
            assert "Ricœur" not in text, field
    # No adopted relationship records.
    assert CRANE_RECORD["jurisdiction"]["relationships"]["text"] is None
    # Capability ids match the registry exactly (no invented ids).
    assert set(CRANE_RECORD["capabilities"]) == {
        c.id for c in CAP.seat_slice("ambassador")
    }
    # Registry states match the registry exactly.
    for cap_id, entry in CRANE_RECORD["capabilities"].items():
        cap = CAP.get_capability(cap_id)
        assert cap is not None, cap_id
        assert entry["registry_state"] == cap.implementation, cap_id
        assert entry["verification"] == cap.verification, cap_id
    # Strand weights: a prose note, never a vector.
    weights_text = CRANE_RECORD["identity"]["strand_weights"]["text"]
    assert isinstance(weights_text, str)
    assert "Voice" in weights_text and "do NOT force-map" in weights_text


def test_rendering_never_mutates_record():
    before = copy.deepcopy(CRANE_RECORD)
    render_crane_ordinary(CRANE_RECORD, detail="compact")
    render_crane_ordinary(
        CRANE_RECORD, authorized_name="Linnea", detail="fuller",
        resolved_capability="Background knowledge — Bridges.",
    )
    assert CRANE_RECORD == before


# ---------------------------------------------------------------------------
# Eligibility matrix (two independent checks) + inventory
# ---------------------------------------------------------------------------

EXPECTED_ELIGIBLE = {
    ("philosophy", "ideal"),
    ("philosophy", "defining_question"),
    ("philosophy", "foundations_not_constraints"),
    ("characterization", "temperament"),
    ("characterization", "personality"),
    ("characterization", "personality_fuller"),
    ("characterization", "demeanor"),
    ("characterization", "perceptual_habit"),
    ("characterization", "fuller_middle"),
    ("characterization", "expressive_terrain"),
    ("characterization", "governing_conviction"),
    ("characterization", "hearing"),
    ("characterization", "humanitarian"),
    ("characterization", "voice"),
    ("characterization", "warmth"),
    ("characterization", "conviction_conduct"),
    ("characterization", "implied_history"),
}


def test_eligibility_matrix():
    eligible = set(eligible_fields(CRANE_RECORD))
    # Adopted + conviction → eligible.
    assert ("philosophy", "ideal") in eligible
    assert ("philosophy", "defining_question") in eligible
    assert ("characterization", "governing_conviction") in eligible
    # Adopted + characterization → eligible.
    assert ("characterization", "temperament") in eligible
    assert ("characterization", "demeanor") in eligible
    assert ("characterization", "voice") in eligible
    assert ("characterization", "warmth") in eligible
    assert ("characterization", "hearing") in eligible
    assert ("characterization", "humanitarian") in eligible
    assert ("characterization", "fuller_middle") in eligible
    assert ("characterization", "personality_fuller") in eligible
    # Adopted + protected → EXCLUDED (category rule: protected is
    # never eligible, regardless of standing).
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
    assert ("capabilities", "voice_chat") not in eligible
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
    assert set(eligible_fields(CRANE_RECORD)) == EXPECTED_ELIGIBLE


def test_eligible_field_refuses_both_failed_checks():
    # Standing flip on a shared post unit removes it → loud failure
    # (shared post units are core, never dropped).
    record = copy.deepcopy(CRANE_RECORD)
    record["characterization"]["hearing"]["standing"] = "provisional"
    assert eligible_field(record, "characterization", "hearing") is None
    with pytest.raises(AssemblyError):
        render_crane_ordinary(record, detail="compact")
    # Category flip on a gating field removes it → loud failure.
    record = copy.deepcopy(CRANE_RECORD)
    record["characterization"]["temperament"]["category"] = "protected"
    assert eligible_field(record, "characterization", "temperament") is None
    with pytest.raises(AssemblyError):
        render_crane_ordinary(record, detail="compact")


def test_capability_description_in_record_cannot_reach_output():
    """Screening by construction: the renderer never reads record
    capability text, so a poisoned description has no path to output."""
    record = copy.deepcopy(CRANE_RECORD)
    record["capabilities"]["voice_chat"]["description"] = (
        "postpones necessary judgment for understanding; Appeasement."
    )
    baseline = render_crane_ordinary(CRANE_RECORD, detail="fuller")
    poisoned = render_crane_ordinary(record, detail="fuller")
    assert poisoned == baseline
    assert "postpones necessary judgment" not in _joined(poisoned)


# ---------------------------------------------------------------------------
# Renderer: order, budgets, exclusions, naming, capability gating
# ---------------------------------------------------------------------------


def test_renderer_order_identity_personality_worldview_capability():
    block = render_crane_ordinary(
        CRANE_RECORD, detail="compact",
        resolved_capability="Background knowledge — Bridges.",
    )
    joined = _joined(block)
    anchors = [
        CANONICAL_MARKER,
        PERSONALITY_COMPACT,
        IDEAL_VERBATIM,
        "Background knowledge — Bridges.",
        HEARING,
        VOICE_COMPACT,
    ]
    positions = [joined.index(a) for a in anchors]
    assert positions == sorted(positions), positions


def test_renderer_budgets_compact_and_fuller_exact():
    """Assembled blocks reproduce exemplar §2 exactly (same sentences,
    same order, byte-identical prose): compact 1,034 chars, fuller 1,481
    chars, both under the 1,500 ceiling."""
    compact = render_crane_ordinary(CRANE_RECORD, detail="compact")
    fuller = render_crane_ordinary(CRANE_RECORD, detail="fuller")
    assert _prose(compact) == COMPACT_PROSE
    assert _prose(fuller) == FULLER_PROSE
    assert len(_joined(compact)) == 1283, len(_joined(compact))
    assert len(_joined(fuller)) == 1481, len(_joined(fuller))
    assert len(_joined(compact)) < len(_joined(fuller)) <= CHARACTER_CEILING
    # Ideal + defining question verbatim in BOTH (unlike the other
    # three §2-exact seats, Crane's ideal is not truncated).
    assert IDEAL_VERBATIM in _joined(compact)
    assert IDEAL_VERBATIM in _joined(fuller)
    assert QUESTION_VERBATIM in _joined(compact)
    assert QUESTION_VERBATIM in _joined(fuller)
    # Personality CHANGED between details, not appended.
    assert PERSONALITY_COMPACT in _joined(compact)
    assert PERSONALITY_COMPACT not in _joined(fuller)
    assert PERSONALITY_FULLER in _joined(fuller)
    assert PERSONALITY_FULLER not in _joined(compact)
    # Fuller-only markers: middle + conviction; compact-only: voice.
    for marker in FULLER_MIDDLE_MARKERS:
        assert marker in _joined(fuller), marker
        assert marker not in _joined(compact), marker
    assert CONVICTION_CONDUCT in _joined(fuller)
    assert CONVICTION_CONDUCT not in _joined(compact)
    assert VOICE_COMPACT in _joined(compact)
    assert VOICE_COMPACT not in _joined(fuller)
    # Hearing + humanitarian shared by both details.
    assert HEARING in _joined(compact)
    assert HEARING in _joined(fuller)
    assert HUMANITARIAN in _joined(compact)
    assert HUMANITARIAN in _joined(fuller)
    # The draft worldview sentence never renders standalone.
    assert "You seek understanding between people without requiring" not in _joined(compact)
    assert "You seek understanding between people without requiring" not in _joined(fuller)


def test_renderer_exclusions():
    for detail in ("compact", "fuller"):
        joined = _joined(render_crane_ordinary(CRANE_RECORD, detail=detail))
        for phrase in PROTECTED_PHRASES:
            assert phrase not in joined, (detail, phrase)
        for name in PHILOSOPHER_NAMES:
            assert name not in joined, (detail, name)
        for marker in LEGACY_MARKERS:
            assert marker not in joined, (detail, marker)
        # No capability promises when nothing is invoked.
        assert "Voice chat" not in joined
        assert "Echo rentals" not in joined
        # No mind-reading wording, ever.
        assert "before they have found the words" not in joined
        assert "really afraid of being abandoned" not in joined


def test_renderer_naming_authorized_only():
    # No authorized name → no address clause.
    pre = render_crane_ordinary(CRANE_RECORD, detail="compact")
    assert not any("calls you" in line for line in pre)
    # Lookup-authorized name → address clause, essence unchanged.
    post = render_crane_ordinary(
        CRANE_RECORD, authorized_name="Linnea", detail="compact"
    )
    assert post[0].endswith("The visitor calls you Linnea.")
    assert post[0].startswith(CANONICAL_MARKER)
    assert post[1:] == pre[1:]
    # Empty/whitespace name = not authorized.
    assert render_crane_ordinary(
        CRANE_RECORD, authorized_name="  ", detail="compact"
    ) == pre
    # The renderer takes NO visitor-state argument: raw state cannot
    # reach it by construction. An unearned name in raw state has no
    # input path here — the call site, not the renderer, owns the
    # lookup (see test_naming_lookup_contract).
    params = inspect.signature(render_crane_ordinary).parameters
    assert "visitor_state" not in params
    assert "authorized_name" in params
    # A non-string name is a contract violation, not a fallback.
    with pytest.raises(TypeError):
        render_crane_ordinary(CRANE_RECORD, authorized_name={"name": "Linnea"})


def test_renderer_fuller_with_name_degrades_to_compact():
    """Fuller (1,481) + name clause (~30) exceeds the ceiling, so it
    degrades to compact + name — valid ladder operation, not failure."""
    fuller_named = render_crane_ordinary(
        CRANE_RECORD, detail="fuller", authorized_name="Linnea"
    )
    joined = _joined(fuller_named)
    assert len(joined) <= CHARACTER_CEILING
    assert "The visitor calls you Linnea." in joined
    for marker in FULLER_MIDDLE_MARKERS:
        assert marker not in joined, marker
    assert CONVICTION_CONDUCT not in joined
    assert VOICE_COMPACT in joined
    assert PERSONALITY_COMPACT in joined


def test_renderer_capability_gating():
    without = render_crane_ordinary(CRANE_RECORD, detail="compact")
    assert not any("Bridges." in line for line in without)
    with_cap = render_crane_ordinary(
        CRANE_RECORD, detail="compact",
        resolved_capability="Background knowledge — Bridges.",
    )
    # Capability slots between worldview and hearing, nothing else moves.
    assert with_cap == without[:3] + ["Background knowledge — Bridges."] + without[3:]
    assert "Background knowledge — Bridges." in _joined(with_cap)
    # Empty/whitespace capability = not invoked.
    assert render_crane_ordinary(
        CRANE_RECORD, detail="compact", resolved_capability="  "
    ) == without
    # The renderer never interprets raw ids or structures.
    with pytest.raises(TypeError):
        render_crane_ordinary(
            CRANE_RECORD, detail="compact", resolved_capability={"id": "voice_chat"}
        )
    with pytest.raises(ValueError):
        render_crane_ordinary(CRANE_RECORD, detail="verbose")


def test_renderer_budget_degrades_then_fails_validation():
    signed = CAP.continuation_block(
        "ambassador", CAP.VisitorState(signed_in=True, consent_acknowledged=True)
    ).strip()
    unsigned = CAP.continuation_block(
        "ambassador", CAP.VisitorState(signed_in=False, consent_acknowledged=False)
    ).strip()
    assert signed and unsigned and len(unsigned) > len(signed)

    # Compact + typical (signed-in) guidance: under budget separation
    # (renderer-budget separation design 2026-11-04), the ceiling
    # measures character content ALONE, so the 1,283-char compact
    # block keeps its voice unit with the 382-char signed guidance
    # attached: total 1,666, voice renders.
    # INTENTIONAL EXPECTATION REVERSAL, citing the design doc: this
    # block previously asserted the voice-drop (voice absent, total
    # <= ceiling); the separation design reverses that expectation.
    compact_typical = render_crane_ordinary(
        CRANE_RECORD, detail="compact", resolved_capability=signed
    )
    assert len(_joined(compact_typical)) == 1283 + 1 + len(signed) == 1666
    assert signed in _joined(compact_typical)  # capability never truncated
    assert VOICE_COMPACT in _joined(compact_typical)  # voice survives whole
    # Capability sits at index 3 (after worldview), voice last.
    assert compact_typical[3] == signed
    assert VOICE_COMPACT in compact_typical[6]

    # Fuller + typical guidance: under budget separation the fuller
    # character block (1,481) fits on its own, so it NO LONGER
    # degrades to compact — middle and conviction survive, guidance
    # appended whole: total 1,864. (Reversal of the old degradation
    # expectation: guidance length no longer affects the ladder.)
    # The fuller has NO voice unit by design (compact-only voice),
    # so its absence here is not a drop.
    degraded = render_crane_ordinary(
        CRANE_RECORD, detail="fuller", resolved_capability=signed
    )
    joined = _joined(degraded)
    assert len(joined) == 1481 + 1 + len(signed) == 1864
    for marker in FULLER_MIDDLE_MARKERS:
        assert marker in joined, marker  # middle survives (character-only)
    assert CONVICTION_CONDUCT in joined  # conviction survives
    assert VOICE_COMPACT not in joined  # fuller has no voice unit, by design
    assert CANONICAL_MARKER in joined
    assert QUESTION_VERBATIM in joined
    assert signed in joined  # capability never truncated

    # Fuller + maximal (unsigned) guidance: same — fuller survives,
    # unsigned guidance appended whole regardless of length.
    # (Reversal of the old degradation expectation.)
    degraded_max = render_crane_ordinary(
        CRANE_RECORD, detail="fuller", resolved_capability=unsigned
    )
    assert len(_joined(degraded_max)) == 1481 + 1 + len(unsigned) == 1872
    for marker in FULLER_MIDDLE_MARKERS:
        assert marker in _joined(degraded_max), marker
    assert CONVICTION_CONDUCT in _joined(degraded_max)
    assert VOICE_COMPACT not in _joined(degraded_max)  # fuller has no voice, by design
    assert unsigned in _joined(degraded_max)
    assert CANONICAL_MARKER in _joined(degraded_max)
    assert QUESTION_VERBATIM in _joined(degraded_max)

    # Compact + a huge capability: guidance-length independence
    # (design §(e) test 5) — a 2,000-char guidance string no longer
    # raises AssemblyError and is appended whole. INTENTIONAL
    # REVERSAL of the old huge-guidance failure, documented here
    # rather than hidden: guidance has no size backstop after
    # separation, per the design's §(c) consequence.
    huge = render_crane_ordinary(
        CRANE_RECORD, detail="compact",
        resolved_capability="x" * (CHARACTER_CEILING + 500),
    )
    assert len(_joined(huge)) == 1283 + 1 + (CHARACTER_CEILING + 500)
    assert VOICE_COMPACT in _joined(huge)
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

    monkeypatch.setattr(N, "get_display_name", lambda uid, aid: "Ambassador")
    legacy_lines = build_archetype_prompt_lines(
        "ambassador", weights_override=None, display_name_override="Ambassador"
    )
    return [
        "You are Ambassador, a voice in the user's Zenaf council, in a direct one-on-one conversation.",
        "",
        *legacy_lines,
        "",
        NO_TRAINING_NOTE,
        "",
        KEEP_REPLIES,
        "User: hello",
        "Ambassador:",
    ]


def test_branch_gate_on_replaces_character_block_only(monkeypatch):
    import local_ai.council.naming as N

    monkeypatch.setattr(N, "get_display_name", lambda uid, aid: "Ambassador")
    monkeypatch.setattr(R, "CRANE_CANONICAL_CUTOVER", True)
    lines, meta = build_voice_prompt("u1", "ambassador", "hello", [], mode="base")
    joined = _joined(lines)
    # Canonical block present, in order.
    assert lines[0].startswith(CANONICAL_MARKER)
    assert PERSONALITY_COMPACT in joined
    assert IDEAL_VERBATIM in joined
    assert QUESTION_VERBATIM in joined
    assert HEARING in joined
    assert HUMANITARIAN in joined
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
    assert lines[-1] == "Ambassador:"
    assert meta["archetype_id"] == "ambassador"


def test_branch_gate_off_equals_exact_legacy_prompt(monkeypatch):
    monkeypatch.setattr(R, "CRANE_CANONICAL_CUTOVER", False)
    lines, _ = build_voice_prompt("u1", "ambassador", "hello", [], mode="base")
    assert lines == _legacy_minimal_prompt(monkeypatch)
    # EXPLICIT legacy assertion: the old shadow and tension lines
    # are PRESENT exactly in the OFF branch. They are unacceptable
    # in the canonical branch and intentional here — the rollback
    # branch is frozen, not sanitized.
    joined = _joined(lines)
    assert (
        "Shadow — your characteristic failure mode, which the Skeptic "
        "may name: Appeasement: translating each side into what it "
        "wants to hear, until nobody has actually met."
    ) in joined
    assert (
        "Live tension with the other seats: Accuses the Champion of "
        "manufacturing enemies; the Skeptic suspects the Ambassador "
        "prefers harmony to honesty."
    ) in joined


def test_branch_meeting_path_keeps_exact_legacy_prompt(monkeypatch):
    # Meeting turns (canonical=False) are out of scope: identical under
    # both cutover settings, and exactly the legacy assembly.
    for cutover in (True, False):
        monkeypatch.setattr(R, "CRANE_CANONICAL_CUTOVER", cutover)
        lines, _ = build_voice_prompt(
            "u1", "ambassador", "hello", [], mode="base", canonical=False
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
    for seat in ("mentor", "champion", "guardian", "maverick", "conductor", "skeptic"):
        prompts = {}
        for cutover in (True, False):
            monkeypatch.setattr(R, "CRANE_CANONICAL_CUTOVER", cutover)
            lines, _ = build_voice_prompt("u1", seat, "hello", [], mode="base")
            prompts[cutover] = lines
        assert prompts[True] == prompts[False], seat
        joined = _joined(prompts[True])
        assert CANONICAL_MARKER not in joined, seat


def test_branch_capability_moved_not_duplicated(monkeypatch):
    import local_ai.council.naming as N

    monkeypatch.setattr(N, "get_display_name", lambda uid, aid: "Ambassador")
    block = CAP.continuation_block(
        "ambassador", CAP.VisitorState(signed_in=True, consent_acknowledged=True)
    )
    assert block.strip()
    lines, _ = build_voice_prompt(
        "u1", "ambassador", "hello", [], mode="base", capability_context=block
    )
    joined = _joined(lines)
    # Same content, moved into the character block: exactly once.
    assert joined.count(block.strip()) == 1
    # And it sits before the voice region, not downstream.
    assert joined.index(block.strip()) < joined.index(VOICE_COMPACT)


def test_branch_downstream_sections_preserved_on_path(monkeypatch):
    import local_ai.council.naming as N

    monkeypatch.setattr(N, "get_display_name", lambda uid, aid: "Ambassador")
    lines, _ = build_voice_prompt(
        "u1", "ambassador", "hello",
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
    monkeypatch.setattr(N, "get_display_name", lambda uid, aid: "Linnea")
    lines, _ = build_voice_prompt("u1", "ambassador", "hello", [], mode="base")
    assert _joined(lines).count("The visitor calls you Linnea.") == 1
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
    assert N.get_display_name(None, "ambassador") == "Ambassador"
    status = N.rename_status(None)
    assert status["rename_threshold"] == 25.0
    assert all(not e["rename_unlocked"] for e in status["archetypes"])
    ambassador_entry = next(e for e in status["archetypes"] if e["id"] == "ambassador")
    assert ambassador_entry["depth"] == 0.0
    assert ambassador_entry["signals_to_unlock"] == 25


def test_naming_prompt_level_stock_vs_authorized(monkeypatch):
    import local_ai.council.naming as N

    # Lookup returns stock → no address clause anywhere.
    monkeypatch.setattr(N, "get_display_name", lambda uid, aid: "Ambassador")
    lines, _ = build_voice_prompt("u1", "ambassador", "hello", [], mode="base")
    assert not any("calls you" in l for l in lines)
    # Lookup returns a visitor-chosen name → clause exactly once.
    monkeypatch.setattr(N, "get_display_name", lambda uid, aid: "Linnea")
    lines, _ = build_voice_prompt("u1", "ambassador", "hello", [], mode="base")
    assert _joined(lines).count("The visitor calls you Linnea.") == 1


# ---------------------------------------------------------------------------
# Encounter eligibility (encounter's OWN material) + resolver contract
# ---------------------------------------------------------------------------


def test_encounter_material_excludes_protected_fields():
    """The encounter's own SCRIPT fields carry no protected §1.7
    material. The composed definition frames carry exactly TWO known
    pre-existing patterns, pinned here so they cannot silently
    grow: the definition line 'Shadow: appeasement.' AND the frame
    instruction 'Your shadow is appeasement — translating each
    side into what it wants to hear until nobody has actually
    met; guard against it, ...' — both UNADOPTED draft content.
    The shadow verdict (2026-11-01) does NOT change that
    meeting-path material: it is pinned, not fixed, here, because
    fixing it is a separate content decision out of scope for
    this plan (ordinary renderer only). (Meeting-turn prompts via
    the shared builder's legacy character block are likewise out
    of scope, preserved byte-identical by the canonical gate.)"""
    from local_ai.conversation import encounter as ENC
    from local_ai.council import meetings as MT

    script = MT.get_script("ambassador", 1)
    assert script is not None
    assert script.character == "Crane"
    assert script.demeanor == (
        "Curious about the other side; holds two truths lightly."
    )
    assert len(script.opening) == 8
    assert script.opening[0] == (
        "Ah, a visitor! How lovely. I was just puzzling over a "
        "rather peculiar word. Perhaps you can help me."
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
        # Gardener correction (2026-11-07, G4/D1): the Shadow: label is
        # gone from the slice. "Your shadow is appeasement" is the
        # encounter frame's own sentence (Crane CC5 content, undecided)
        # and stays at 1.
        assert frame.count("Shadow: appeasement.") == 0
        assert frame.count("Your shadow is appeasement") == 1
        assert (
            "translating each side into what it wants to hear until "
            "nobody has actually met"
        ) in frame
        # The ADOPTED picture content (candidate A) is NOT presented
        # as an adopted shadow anywhere in encounter material.
        assert "postpones necessary judgment for understanding" not in frame
        # The ADOPTED shadow wording is likewise absent from the
        # frames: they carry only the unadopted appeasement draft.
        assert "substitute for judgment" not in frame
        assert "shouldn't be crossed" not in frame
        for name in PHILOSOPHER_NAMES:
            assert name not in frame, name


def test_resolver_contract_already_resolved_and_clean():
    """The resolver supplies already-resolved guidance: planned caps
    render planned (never available), and the block carries no
    protected formulations. The renderer trusts this output because
    the resolver — not the model, not the renderer — determined
    availability and authorization."""
    state = CAP.VisitorState(signed_in=True, consent_acknowledged=True)
    block = CAP.continuation_block("ambassador", state)
    assert block.strip()
    for phrase in PROTECTED_PHRASES:
        assert phrase not in block, phrase
    # The ambassador slice renders exactly the 5 exemplar capabilities.
    for name in (
        "Voice chat",
        "Echo rentals",
        "Zones (rental slicing)",
        "Listing disclosures",
        "Being represented in other people's councils",
    ):
        assert name in block, name
    # Available-but-unverified rendering for voice chat; planned
    # capabilities explicitly unavailable, never promised.
    assert "Voice chat — available (workflow not yet verified)" in block
    assert block.count("planned, not available yet") == 4
    cap = CAP.get_capability("echo_rentals")
    assert cap is not None
    assert cap.implementation == "planned"
    assert cap.verification == "unverified"
    assert not CAP.currently_usable(cap, state)
    # Unsigned state gates voice chat too; planned lines unchanged.
    unsigned = CAP.continuation_block(
        "ambassador", CAP.VisitorState(signed_in=False, consent_acknowledged=False)
    )
    assert "Voice chat — not available to you yet" in unsigned
    assert unsigned.count("planned, not available yet") == 4


def test_weights_untouched_and_no_vector_in_record():
    """Strand weights are a fixed registry vector, not record
    content: the record carries a prose note only, and the legacy
    strand-blend computation is unchanged (the gate-OFF prompt
    equals the legacy oracle, blend lines included — see
    test_branch_gate_off_equals_exact_legacy_prompt)."""
    assert "strand_weights" not in CRANE_RECORD["characterization"]
    weights_field = CRANE_RECORD["identity"]["strand_weights"]
    assert isinstance(weights_field["text"], str)
    assert not isinstance(weights_field.get("vector"), (dict, list))
