"""Cross-seat fellowship slice consistency (Gardener correction, 2026-11-07).

T5 — Pronoun audit: every first-meeting reference slice names the other
six seats, and the pronoun it uses for each must match that seat's
canonical record (`pronouns["text"]`). The test keys off the record
fields, not hardcoded strings: a regression that reintroduces any of
the 27 corrected words (24 subject pronouns + 3 possessives) fails it.
(Design §4.2's headline says "28 subject" — that overcounts by four:
each slice names only the other six seats, so the four slices whose own
seat is one of Firebrand/Bear/Crane/Raven carry three wrong subject
pronouns, not four. The per-slice lists sum to 24; the word-level
seven-seat diff confirms all 24 + 3.)

T6 — Shadow absence + protection preservation: no `Shadow:` label in any
slice constant, and the canonical protected shadow texts are byte-identical
to their pre-correction values (the label removal must never touch the
records or the registry).

T8 — FC8 fellowship references (2026-11-07, founder ruling): Firebrand
is "he/him/his" in all six other seats' fellowship references, and
Bear/Crane/Raven are correct in Firebrand's own reference. Since the
2026-11-09 pronoun build (founder tap "One bounded build — all 162"),
Bear/Crane/Raven are correct in the OTHER seats' refs too: the
test_fellowship_references_gender_bear_crane_raven test below audits
all three in all seven references.

T9 — CC6 fellowship reference (2026-11-07, founder ruling): Bear is
she and Raven is she in Crane's own fellowship reference; Firebrand
is he there. The all-seven audit of Bear/Crane/Raven lives in
test_fellowship_references_gender_bear_crane_raven below. The two
lowercase "appeasement" prose uses in that reference stay per the
Crane design §12 Q5 residual, so the test pins their count (== 2)
rather than asserting absence.

The Fox has no fixed set (fox.py: "No fixed set — different characters
call the Fox he, she, or they"): the test asserts only that every Fox
pronoun in the slices is one of {he, she, they} — it never requires any
one of them.
"""

import re

from local_ai.conversation import encounter as ENC
from local_ai.council import archetypes as ARCH
from local_ai.council import meetings as MT
from local_ai.council.canonical.bear import BEAR_RECORD
from local_ai.council.canonical.crane import CRANE_RECORD
from local_ai.council.canonical.firebrand import FIREBRAND_RECORD
from local_ai.council.canonical.fox import FOX_RECORD
from local_ai.council.canonical.gardener import GARDENER_RECORD
from local_ai.council.canonical.raven import RAVEN_RECORD
from local_ai.council.canonical.weaver import WEAVER_RECORD

# The seven first-meeting reference slices (design §4.2).
SLICES = {
    "mentor": ENC._MENTOR_REFERENCE_SLICE,
    "champion": ENC._CHAMPION_GUIDANCE,
    "guardian": ENC._GUARDIAN_FIRST_MEETING_GUIDANCE,
    "maverick": ENC._MAVERICK_GUIDANCE,
    "ambassador": ENC._AMBASSADOR_REFERENCE_SLICE,
    "conductor": ENC._WEAVER_FELLOWSHIP_SLICE,
    "skeptic": ENC._SKEPTIC_REFERENCE_GUIDANCE,
}

# arch_id -> (canonical record, display name used in the slices).
RECORDS = {
    "mentor": (GARDENER_RECORD, "Gardener"),
    "champion": (FIREBRAND_RECORD, "Firebrand"),
    "guardian": (BEAR_RECORD, "Bear"),
    "maverick": (FOX_RECORD, "Fox"),
    "ambassador": (CRANE_RECORD, "Crane"),
    "conductor": (WEAVER_RECORD, "Weaver"),
    "skeptic": (RAVEN_RECORD, "Raven"),
}

_POSSESSIVE = {"he": "his", "she": "her", "they": "their"}


def _subject_pronoun(record):
    """The subject pronoun from a record's `pronouns["text"]` ("he / him")."""
    return record["identity"]["pronouns"]["text"].split("/")[0].strip()


def test_slice_pronouns_match_canonical_records():
    """T5: every slice's subject pronoun for a seat matches that seat's
    canonical pronouns field. The Fox is exempt from a fixed pronoun."""
    for arch_id, (record, name) in RECORDS.items():
        if arch_id == "maverick":
            continue  # No fixed set — see test_fox_pronoun_unfixed below.
        expected = _subject_pronoun(record)
        pattern = re.compile(rf"{name}:\s+(he|she|they)\b")
        for other_id, slice_text in SLICES.items():
            if other_id == arch_id:
                continue  # A slice never names its own seat.
            matches = pattern.findall(slice_text)
            assert matches, (
                f"{name} not named in the {other_id} slice"
            )
            assert all(m == expected for m in matches), (
                f"{name} in the {other_id} slice: {matches} != {expected!r} "
                f"(canonical pronouns: {record['identity']['pronouns']['text']!r})"
            )


def test_slice_possessives_match_canonical_records():
    """T5 (possessives): the three corrected possessive words, keyed to
    the same canonical pronouns — he->his, she->her."""
    firebrand_poss = _POSSESSIVE[_subject_pronoun(FIREBRAND_RECORD)]
    bear_poss = _POSSESSIVE[_subject_pronoun(BEAR_RECORD)]
    assert firebrand_poss == "his"
    assert bear_poss == "her"
    assert f"must not call {firebrand_poss} urgency mere impatience" in SLICES["mentor"]
    assert f"I ask what {bear_poss} walls keep out" in SLICES["mentor"]
    assert f"never without {bear_poss} ledger" in SLICES["champion"]
    # The wrong possessives are gone everywhere.
    assert "must not call her urgency mere impatience" not in SLICES["mentor"]
    assert "I ask what his walls keep out" not in SLICES["mentor"]
    assert "never without his ledger" not in SLICES["champion"]


def test_fox_pronoun_unfixed():
    """T5 (Fox): no fixed set — every Fox pronoun in the slices is one
    of {he, she, they}, and the test requires no single one of them."""
    pattern = re.compile(r"Fox:\s+(he|she|they)\b")
    for arch_id, slice_text in SLICES.items():
        if arch_id == "maverick":
            continue
        matches = pattern.findall(slice_text)
        assert matches, f"Fox not named in the {arch_id} slice"
        assert all(m in ("he", "she", "they") for m in matches)


def test_no_shadow_label_in_any_slice():
    """T6: the `Shadow:` label is gone from all seven slices (G4/D1)."""
    for arch_id, slice_text in SLICES.items():
        assert "Shadow:" not in slice_text, arch_id


def test_protected_shadow_texts_unchanged():
    """T6: the canonical protected shadow texts are byte-identical to
    their pre-correction values — the label removal never touched the
    records or the registry."""
    assert GARDENER_RECORD["protected"]["shadow"]["text"] == (
        "Teaching-past-need / dependence — keeping growth on his schedule "
        "until cultivation becomes dependence."
    )
    assert FOX_RECORD["protected"]["shadow"]["text"] == (
        "Mistakes commitment for captivity — keeps opening doors after "
        "choosing one would make something possible."
    )
    assert ARCH.ARCHETYPE_PHILOSOPHY["mentor"]["shadow"] == (
        "Paternalism: withholding the straight answer to stay necessary — "
        "teaching that cultivates dependence, growth kept on the mentor's schedule."
    )


def test_no_fixed_second_move_formula_in_any_frame():
    """T7 (design §10): no first-meeting frame contains formula language
    for a fixed second move — no acknowledgment-plus-contribution, no
    mandated reply structure. (G5: the template rule was struck; each
    seat's second move is its own contribution form, named only for the
    Gardener and the Maverick.)"""
    builders = {
        "mentor": ENC.build_mentor_k1_definition,
        "champion": ENC.build_champion_k1_definition,
        "guardian": ENC.build_guardian_k1_definition,
        "maverick": ENC.build_maverick_k1_definition,
        "ambassador": ENC.build_ambassador_k1_definition,
        "conductor": ENC.build_weaver_k1_definition,
        "skeptic": ENC.build_skeptic_k1_definition,
    }
    scripts = {
        "mentor": MT.MENTOR_FIRST_MEETING,
        "champion": MT.CHAMPION_FIRST_MEETING,
        "guardian": MT.GUARDIAN_FIRST_MEETING,
        "maverick": MT.MAVERICK_FIRST_MEETING,
        "ambassador": MT.AMBASSADOR_FIRST_MEETING,
        "conductor": MT.CONDUCTOR_FIRST_MEETING,
        "skeptic": MT.SKEPTIC_FIRST_MEETING,
    }
    formula = (
        "acknowledgment-plus-contribution",
        "always follow",
        "always end with",
        "always end your reply",
    )
    for arch_id, build in builders.items():
        definition = build(scripts[arch_id])
        runtime = ENC.EncounterRuntime(definition)
        engage = runtime._engage_frame()
        turn, _cue = runtime._turn_frame(ENC.EncounterState(), "hello")
        for frame, text in (("engage", engage), ("turn", turn)):
            for phrase in formula:
                assert phrase not in text, (arch_id, frame, phrase)


# The seven fellowship references (FC8, 2026-11-07) — a separate layer
# from the first-meeting slices: they render as the uncapped
# fellowship-reference section in build_voice_prompt, not inside the
# engage/turn frames, so the seven-seat V4 diff does not capture them.
REFERENCES = {
    "mentor": ENC._GARDENER_FELLOWSHIP_REFERENCE,
    "champion": ENC._CHAMPION_FELLOWSHIP_REFERENCE,
    "guardian": ENC._GUARDIAN_FELLOWSHIP_REFERENCE,
    "maverick": ENC._MAVERICK_FELLOWSHIP_REFERENCE,
    "ambassador": ENC._CRANE_FELLOWSHIP_REFERENCE,
    "conductor": ENC._WEAVER_FELLOWSHIP_REFERENCE,
    "skeptic": ENC._RAVEN_FELLOWSHIP_REFERENCE,
}


def _firebrand_paragraph(reference: str) -> str:
    match = re.search(
        r"- Firebrand \(Champion\): (.*?)(?=\n- |\nMention them|\Z)",
        reference,
        re.S,
    )
    assert match, "reference carries no Firebrand paragraph"
    return match.group(0)


def test_fellowship_references_use_he_for_firebrand():
    """T8 (FC8): Firebrand is he/him/his — never she/her — in all six
    other seats' fellowship references."""
    for arch_id, reference in REFERENCES.items():
        if arch_id == "champion":
            continue
        paragraph = _firebrand_paragraph(reference)
        assert not re.search(
            r"\b(she|her|hers|She|Her|Hers)\b", paragraph
        ), (arch_id, paragraph)
        assert re.search(r"\b(he|him|his|He|Him|His)\b", paragraph), arch_id


def test_champion_fellowship_reference_genders_bear_crane_raven():
    """T8 (FC8): Bear is she, Crane is he, Raven is she in Firebrand's
    own fellowship reference. (Bear/Crane/Raven in the OTHER seats'
    refs are audited in all seven references by
    test_fellowship_references_gender_bear_crane_raven below.)"""
    ref = REFERENCES["champion"]
    assert "She keeps the ledger of what must survive" in ref
    assert "He asks what each side actually needs" in ref
    assert "his ability to tell a genuine enemy" in ref
    assert "He still asks what it needs" in ref
    assert "She audits whether a conviction is earned" in ref
    assert "more than she" in ref
    assert "She checks the conviction; the decision stays mine" in ref


def test_crane_fellowship_reference_genders_bear_raven_firebrand():
    """T9 (CC6): Bear is she and Raven is she in Crane's own
    fellowship reference; Firebrand is he there (FC8). (This test
    audits only Crane's own reference; the all-seven audit lives in
    test_fellowship_references_gender_bear_crane_raven below.)
    The two lowercase "appeasement" prose uses in this reference
    stay per the Crane design §12 Q5 residual — no ruling covers
    them — so this test asserts pronouns, never "appeasement"
    absence; the count == 2 pins the residual exactly.)"""
    ref = REFERENCES["ambassador"]
    assert "She sets the boundary" in ref
    assert "the door she keeps" in ref
    assert "She says I'm confusing" in ref
    assert "Sometimes she's right" in ref
    assert "She says what is actually true" in ref
    assert "her examination" in ref
    assert "She thinks I'm preserving comfort" in ref
    assert "she's confusing examination" in ref
    assert "He names a side plainly" in ref
    assert ref.lower().count("appeasement") == 2


def _seat_paragraph(reference: str, seat: str, role: str) -> str:
    """One seat's paragraph inside a fellowship reference."""
    match = re.search(
        rf"- {seat} \({role}\): (.*?)(?=\n- |\nMention them|\Z)",
        reference,
        re.S,
    )
    assert match, f"reference carries no {seat} paragraph"
    return match.group(0)


# seat -> (role label, pronouns that must appear, pronouns that must not).
_BEAR_CRANE_RAVEN = {
    "Bear": ("Guardian", r"\b(she|her|hers|She|Her|Hers)\b",
             r"\b(he|him|his|He|Him|His)\b"),
    "Crane": ("Ambassador", r"\b(he|him|his|He|Him|His)\b",
              r"\b(she|her|hers|She|Her|Hers)\b"),
    "Raven": ("Skeptic", r"\b(she|her|hers|She|Her|Hers)\b",
              r"\b(he|him|his|He|Him|His)\b"),
}


def test_fellowship_references_gender_bear_crane_raven():
    """T8/T9 extension (2026-11-09 pronoun build, founder tap "One
    bounded build — all 162"): Bear is she/her, Crane is he/him/his,
    Raven is she/her in ALL SEVEN fellowship references — not only in
    Firebrand's and Crane's own. The Fox has no fixed set and is not
    audited here; Gardener/Firebrand/Weaver paragraphs are covered by
    the T8 Firebrand test and the canonical records."""
    for arch_id, reference in REFERENCES.items():
        for seat, (role, good, bad) in _BEAR_CRANE_RAVEN.items():
            paragraph = _seat_paragraph(reference, seat, role)
            assert not re.search(bad, paragraph), (arch_id, seat, paragraph)
            assert re.search(good, paragraph), (arch_id, seat, paragraph)
    # The one gendered noun in the references: Weaver's Raven paragraph
    # says "Irritating woman", never "Irritating man".
    assert "Irritating woman" in _seat_paragraph(
        REFERENCES["conductor"], "Raven", "Skeptic"
    )
    for arch_id, reference in REFERENCES.items():
        assert "Irritating man" not in reference, arch_id
