"""Lens Foundation WI-2 — canonical convergence of the meeting path.

Mechanism A, second surface: meetings (then the demo) assemble their
character layer from the canonical records through the per-seat
renderers, as ordinary Talk already does. Gated per seat by the
MIGRATION CONTROLS in reply.py (_MEETING_CANONICAL_<SEAT>) — migration
controls, not a permanent architectural distinction; they and the
legacy meeting branch they gate are removed together in a separately
authorized cleanup once convergence is accepted.

What this suite pins (scope §5.2, the T-A group):

- T-A1 (per migrated seat, added in that seat's migration commit):
  the flag-driven meeting assembly's character block byte-equals the
  seat's canonical renderer output plus the preserved assembly lines,
  and the full assembled meeting prompt matches its golden hash.
- T-A2: the coverage matrix below is complete — every legacy
  character line the meeting assembly produces is enumerated and
  carries exactly one disposition, and every renderer unit is
  classified by source (record-composed / renderer-authored / mixed).
- T-A3: eligibility regression — the standing x category rule, the
  ceilings, and the fail-loud ladder are unchanged by convergence.
- T-A4: tier/frame invariance — on the meeting path, the canonical
  tier block and the encounter frame are byte-identical whether the
  seat's character layer is legacy or canonical.
- T-A5: full-prompt protected scan — Talk and converged meeting
  assemblies contain no protected-section text and no shadow line.
  (The demo surface's scan lives with the demo swap in
  tests/test_demo_routes.py.)
- T-A6: Talk byte-identity — ordinary Talk assembled prompts for all
  seven seats match goldens pinned before the first WI-2 commit, so
  no WI-2 commit may move the proven path.

Dispositions vocabulary (scope §2.3(a), extended by two honest
labels): "rendered" (the line's content is rendered from the named
canonical-record field by the named renderer), "retired" (not
carried; the retiring ruling is named), "preserved" (carried
verbatim by the canonical assembly itself — the scope's three kinds
do not cover lines that are neither record-rendered nor retired,
e.g. the shared style rule; calling them either would be false),
"structural" (assembly formatting, not character material).

Conduct/frame reconciliation (founder condition on WI-2, recorded
here and in the WI-2 report): before each seat's cutover, its K1
encounter frames (local_ai/council/meetings.py scripts +
local_ai/conversation/encounter.py definitions) were compared
against the seat's rendered canonical block, sentence by sentence.
Findings, uniform across seats: (1) the frames restate several of
the record's conduct rules verbatim or near-verbatim (they were
authored from the same character material; the Gardener record's
invariants field even annotates one "(encounter path)"); the
reconciliation decision is that the RECORD is the authority for
character conduct and the frame passages are encounter restatements
of the identical rules — same words, same rule, no competing
instruction — enumerated per seat in the WI-2 report. (2) The
frames' remaining conduct content is encounter mechanics (turn
shape, the read-back/impression protocol, naming, bookkeeping,
scope) that the record does not govern: the frame is sole authority
there. (3) Two movement-scoped frame rules are stricter than the
record's general rule (Ambassador: the engage reply must not
restate the visitor's answer; Maverick: the engage reply does not
move to a question of the seat's own) — both are sequencing rules
for the engage movement, consonant with the record rules they sit
beside, and are recorded as scoped subordinations, not conflicts.
(4) No frame instruction contradicts a rendered record rule for any
seat. A seat whose frames genuinely conflicted would not migrate
(scope §9.2); none did.

No model calls anywhere here: every test is deterministic prompt
inspection through build_voice_prompt / the meeting wiring seam.
"""

from __future__ import annotations

import copy
import hashlib
import re

import pytest

from local_ai.conversation import meeting as MEETING
from local_ai.conversation import reply as R
from local_ai.conversation.reply import build_voice_prompt, meeting_canonical_enabled
from local_ai.council import meetings as MT
from local_ai.council.archetypes import (
    ANTI_PRESUMPTION_STYLE,
    ARCHETYPE_PHILOSOPHY,
)
from local_ai.council.canonical.bear import BEAR_RECORD
from local_ai.council.canonical.crane import CRANE_RECORD
from local_ai.council.canonical.firebrand import FIREBRAND_RECORD
from local_ai.council.canonical.fox import FOX_RECORD
from local_ai.council.canonical.gardener import GARDENER_RECORD
from local_ai.council.canonical.raven import RAVEN_RECORD
from local_ai.council.canonical.weaver import WEAVER_RECORD
from local_ai.council.jurisdictions import jurisdiction_prompt_lines
from local_ai.council.render import (
    CHARACTER_CEILING,
    _ELIGIBLE_CATEGORIES,
    _FIREBRAND_CHARACTER_CEILING,
    AssemblyError,
    eligible_field,
    render_bear_ordinary,
    render_crane_ordinary,
    render_firebrand_ordinary,
    render_fox_ordinary,
    render_gardener_ordinary,
    render_raven_ordinary,
    render_weaver_ordinary,
)
from local_ai.conversation import encounter as ENC
from local_ai.conversation.canonical_tier import CANONICAL_TIER_L1

SEATS = (
    "mentor", "champion", "guardian", "ambassador",
    "conductor", "skeptic", "maverick",
)

RECORDS = {
    "mentor": GARDENER_RECORD,
    "champion": FIREBRAND_RECORD,
    "guardian": BEAR_RECORD,
    "ambassador": CRANE_RECORD,
    "conductor": WEAVER_RECORD,
    "skeptic": RAVEN_RECORD,
    "maverick": FOX_RECORD,
}


def _renderer_units(seat: str) -> list[str]:
    """The seat's canonical renderer output under the exact inputs
    the meeting call supplies (no resolved capability — meetings
    carry capability context inside the frame — and no visitor-chosen
    name). Mirrors reply.py's canonical branch call for the seat."""
    record = RECORDS[seat]
    if seat == "conductor":
        return render_weaver_ordinary(
            record, visitor_state={}, resolved_capability=None
        )
    fn = {
        "mentor": render_gardener_ordinary,
        "champion": render_firebrand_ordinary,
        "guardian": render_bear_ordinary,
        "ambassador": render_crane_ordinary,
        "skeptic": render_raven_ordinary,
        "maverick": render_fox_ordinary,
    }[seat]
    return fn(record, authorized_name=None, resolved_capability=None)


def _preserved_lines(seat: str, weights: dict) -> list[str]:
    """The assembly lines the canonical branch preserves verbatim,
    in order: the shared style rule, the conductor's jurisdiction
    lines, and the strand blend (recomputed from the same weights
    the legacy builder uses)."""
    lines = [ANTI_PRESUMPTION_STYLE]
    if seat == "conductor":
        lines.extend(jurisdiction_prompt_lines("conductor"))
    lines.extend(R._strand_blend_lines(weights))
    return lines


def _meeting_weights(seat: str) -> dict:
    """The weights build_voice_prompt uses for a base-mode meeting
    call: the stock vector, or the Skeptic's uniform fallback."""
    from local_ai.council.archetypes import get_archetype

    arch = get_archetype(seat)
    if arch is not None and arch.strand_weights is None:
        from local_ai.council.archetypes import compute_skeptic_weights

        return compute_skeptic_weights("u1", mode="base")
    return arch.strand_weights or {}


def _meeting_prompt(seat: str, canonical: bool, frame: str):
    lines, _ = build_voice_prompt(
        "u1", seat, "Hello, I am here to think about my work.", [],
        mode="base", canonical=canonical, canonical_tier=True,
        extra_instructions=frame,
    )
    return lines


def _engage_frame(seat: str) -> str:
    return ENC.get_definition(MT.get_script(seat, 1)).engage_frame


# ---------------------------------------------------------------------------
# The coverage matrix (scope §2.3(a)) — data artefact.
#
# Per seat: (line kind, count in the legacy meeting head, disposition,
# reference). The legacy head is the opener + build_archetype_prompt_
# lines output + separators, exactly as build_voice_prompt assembles
# it for a base-mode meeting call. T-A2 enumerates the real lines,
# classifies each by construction, and requires the multiset of kinds
# to match this matrix exactly — a legacy line with no matrix entry
# (or a matrix entry with no line) fails the suite.
# ---------------------------------------------------------------------------

_R_FRAME = (
    "retired — the registry prompt-frame line is replaced by the "
    "record identity unit under the seat's canonical Talk cutover "
    "(merged on main), extended to the meeting path by the Lens "
    "Foundation WI-2 verdict (2026-11-17)"
)
_R_TENSION = (
    "retired — relationship/tension material is ineligible "
    "character-block content under the canonical eligibility design "
    "(local_ai/council/render.py, module header); meeting "
    "pair-tensions are carried by the encounter frames, unchanged"
)
_R_SHADOW = (
    "retired — shadow-protection rule: the canonical eligibility "
    "rule admits no protected material, and WI-1 closes the legacy "
    "emission on its own branch; the line is not carried on any "
    "canonical path"
)
_R_STYLE = (
    "preserved — ANTI_PRESUMPTION_STYLE (local_ai/council/"
    "archetypes.py), appended verbatim in preserved_lines on the "
    "canonical branch (local_ai/conversation/reply.py)"
)
_R_BLEND = (
    "preserved — recomputed verbatim by reply._strand_blend_lines "
    "from the same weights and strand taglines the legacy builder "
    "uses"
)
_R_JURISDICTION = (
    "preserved — jurisdiction_prompt_lines('conductor') "
    "(local_ai/council/jurisdictions.py), appended verbatim in "
    "preserved_lines on the Weaver canonical branch (reply.py)"
)
_R_WARMTH = (
    "retired — the registry warmth formulation is superseded "
    "character material: the adopted record warmth rides the "
    "renderer's voice units (record characterization fields); "
    "retired by the seat's canonical Talk cutover, extended to "
    "meetings by the WI-2 verdict"
)
_R_STRUCTURAL = "structural — assembly separator, reproduced by the canonical assembly's own formatting"
_R_IDENTITY = (
    "rendered — the seat's renderer identity unit, built "
    "structurally from record identity.character + identity.role "
    "(render.py: identity is structural)"
)

# (kind, count, disposition, reference)
COVERAGE_MATRIX: dict[str, list[tuple[str, int, str, str]]] = {
    "mentor": [
        ("opener", 1, "rendered", _R_IDENTITY),
        ("blank", 2, "structural", _R_STRUCTURAL),
        ("frame_line", 1, "retired", _R_FRAME),
        ("ideal", 1, "rendered",
         "render_gardener_ordinary worldview unit — characterization."
         "ideal_rendering_form (the record's rendering form of the "
         "ideal) with characterization.domain_tension"),
        ("question", 1, "rendered",
         "render_gardener_ordinary worldview unit — philosophy."
         "defining_question (verbatim)"),
        ("shadow", 1, "retired", _R_SHADOW),
        ("tension", 1, "retired", _R_TENSION),
        ("style_rule", 1, "preserved", _R_STYLE),
        ("warmth", 1, "retired", _R_WARMTH),
        ("blend_header", 1, "preserved", _R_BLEND),
        ("blend_line", 5, "preserved", _R_BLEND),
    ],
    "champion": [
        ("opener", 1, "rendered", _R_IDENTITY),
        ("blank", 2, "structural", _R_STRUCTURAL),
        ("frame_line", 1, "retired", _R_FRAME),
        ("ideal", 1, "rendered",
         "render_firebrand_ordinary worldview unit — characterization."
         "conviction_paraphrase (the record's rendering of its "
         "governing conviction)"),
        ("question", 1, "rendered",
         "render_firebrand_ordinary worldview unit — philosophy."
         "defining_question (verbatim)"),
        # No shadow entry: the Champion's table entry has no shadow
        # (FC7, 2026-11-07 — removed, not replaced).
        ("tension", 1, "retired", _R_TENSION),
        ("style_rule", 1, "preserved", _R_STYLE),
        ("warmth", 1, "retired", _R_WARMTH),
        ("blend_header", 1, "preserved", _R_BLEND),
        ("blend_line", 5, "preserved", _R_BLEND),
    ],
    "guardian": [
        ("opener", 1, "rendered", _R_IDENTITY),
        ("blank", 2, "structural", _R_STRUCTURAL),
        ("frame_line", 1, "retired", _R_FRAME),
        ("ideal", 1, "rendered",
         "render_bear_ordinary worldview unit — characterization."
         "ideal_rendering_form with characterization."
         "affirmative_conviction"),
        ("question", 1, "rendered",
         "render_bear_ordinary worldview unit — philosophy."
         "defining_question (verbatim)"),
        # No shadow entry: the guardian renders no Shadow line
        # (BC8, Bear S1, 2026-11-07).
        ("tension", 1, "retired", _R_TENSION),
        ("style_rule", 1, "preserved", _R_STYLE),
        ("warmth", 1, "retired", _R_WARMTH),
        ("blend_header", 1, "preserved", _R_BLEND),
        ("blend_line", 5, "preserved", _R_BLEND),
    ],
    "ambassador": [
        ("opener", 1, "rendered", _R_IDENTITY),
        ("blank", 2, "structural", _R_STRUCTURAL),
        ("frame_line", 1, "retired", _R_FRAME),
        ("ideal", 1, "rendered",
         "render_crane_ordinary worldview unit — philosophy.ideal "
         "(verbatim)"),
        ("question", 1, "rendered",
         "render_crane_ordinary worldview unit — philosophy."
         "defining_question (verbatim)"),
        # No shadow entry: no shadow is adopted for the Crane
        # (§1.7 open — reply.py Crane cutover note).
        ("tension", 1, "retired", _R_TENSION),
        ("style_rule", 1, "preserved", _R_STYLE),
        ("warmth", 1, "retired", _R_WARMTH),
        ("blend_header", 1, "preserved", _R_BLEND),
        ("blend_line", 5, "preserved", _R_BLEND),
    ],
    "conductor": [
        ("opener", 1, "rendered", _R_IDENTITY),
        ("blank", 2, "structural", _R_STRUCTURAL),
        ("frame_line", 1, "retired", _R_FRAME),
        ("ideal", 1, "rendered",
         "render_weaver_ordinary worldview unit — philosophy."
         "core_conviction (the record carries no philosophy.ideal; "
         "core_conviction is its governing conviction: verbatim in "
         "the fuller variant; the compact variant's conviction "
         "sentence is renderer-composed and listed in the "
         "renderer-authored table below)"),
        ("question", 1, "rendered",
         "render_weaver_ordinary worldview unit — philosophy."
         "defining_question (verbatim)"),
        ("shadow", 1, "retired", _R_SHADOW),
        ("tension", 1, "retired", _R_TENSION),
        ("style_rule", 1, "preserved", _R_STYLE),
        # The conductor's warmth register rides inside her
        # jurisdiction lines (registry-sourced), so there is no
        # separate warmth line: all seven are preserved verbatim.
        ("jurisdiction", 7, "preserved", _R_JURISDICTION),
        ("blend_header", 1, "preserved", _R_BLEND),
        ("blend_line", 7, "preserved", _R_BLEND),
    ],
    "skeptic": [
        ("opener", 1, "rendered", _R_IDENTITY),
        ("blank", 2, "structural", _R_STRUCTURAL),
        ("frame_line", 1, "retired", _R_FRAME),
        ("ideal", 1, "rendered",
         "render_raven_ordinary worldview unit — philosophy.ideal "
         "(verbatim) with characterization.domain_tension"),
        ("question", 1, "rendered",
         "render_raven_ordinary worldview unit — philosophy."
         "defining_question (verbatim)"),
        ("shadow", 1, "retired", _R_SHADOW),
        ("tension", 1, "retired", _R_TENSION),
        ("style_rule", 1, "preserved", _R_STYLE),
        ("warmth", 1, "retired", _R_WARMTH),
        ("blend_header", 1, "preserved", _R_BLEND),
        ("blend_line", 7, "preserved", _R_BLEND),
    ],
    "maverick": [
        ("opener", 1, "rendered", _R_IDENTITY),
        ("blank", 2, "structural", _R_STRUCTURAL),
        ("frame_line", 1, "retired", _R_FRAME),
        ("ideal", 1, "rendered",
         "render_fox_ordinary worldview unit — philosophy.ideal "
         "(verbatim)"),
        ("question", 1, "rendered",
         "render_fox_ordinary worldview unit — philosophy."
         "defining_question (verbatim)"),
        ("shadow", 1, "retired", _R_SHADOW),
        ("tension", 1, "retired", _R_TENSION),
        ("style_rule", 1, "preserved", _R_STYLE),
        ("warmth", 1, "retired", _R_WARMTH),
        ("blend_header", 1, "preserved", _R_BLEND),
        ("blend_line", 5, "preserved", _R_BLEND),
    ],
}

# ---------------------------------------------------------------------------
# Renderer-authored prose listing (scope §2.2 item 4).
#
# Per seat, one entry per renderer unit (meeting-call inputs, compact
# detail — the reply path's form): (source, record fields whose text
# verifies verbatim inside the unit, note). "record" = the unit's
# text is composed from the named record fields; "renderer" = the
# unit's prose is authored in render.py and states character with no
# record source (named, so the founder can see exactly which
# character claims have no record source); "mixed" = both.
# ---------------------------------------------------------------------------

UNIT_SOURCES: dict[str, list[tuple[str, tuple[str, ...], str]]] = {
    "mentor": [
        ("record", (), "identity unit — structural (identity.role + identity.character)"),
        ("record", ("characterization.personality",), ""),
        ("record", ("characterization.ideal_rendering_form",
                    "characterization.domain_tension",
                    "philosophy.defining_question"), "worldview unit"),
        ("record", ("characterization.cultivation_practice",), ""),
        ("record", ("characterization.voice_and_humor",
                    "characterization.warmth"), "voice close"),
    ],
    "champion": [
        ("record", (), "identity unit — structural (identity.role + identity.character)"),
        ("record", ("characterization.personality",), ""),
        ("record", ("characterization.conviction_paraphrase",
                    "philosophy.defining_question",
                    "characterization.temperament_sentence",
                    "characterization.humanism_sentence"), "worldview unit"),
        ("mixed", ("characterization.voice_and_humor",
                   "characterization.warmth"),
         "voice unit — _FIREBRAND_COMPACT_VOICE_MID (render.py): "
         "prose authored for the rung condensing the named record "
         "fields, carrying verbatim sentences from encounter.py "
         "_CHAMPION_GUIDANCE / _SHARED_NATURE_RULE"),
        ("renderer", (),
         "principles unit — _FIREBRAND_TALK_PRINCIPLES (render.py): "
         "the Q9 sentence quoted verbatim from encounter.py "
         "_CHAMPION_GUIDANCE and the Q6 nature rule from "
         "_SHARED_NATURE_RULE, riding every assembly under founder "
         "rulings 2026-11-07 ~19:21/~19:23 PT; no record source"),
    ],
    "guardian": [
        ("record", (), "identity unit — structural (identity.role + identity.character)"),
        ("record", ("characterization.personality",), ""),
        ("record", ("characterization.ideal_rendering_form",
                    "characterization.affirmative_conviction",
                    "philosophy.defining_question"), "worldview unit"),
        ("record", ("characterization.voice_and_humor",
                    "characterization.warmth"), "voice close"),
    ],
    "ambassador": [
        ("record", (), "identity unit — structural (identity.role + identity.character)"),
        ("record", ("characterization.personality",), ""),
        ("record", ("philosophy.ideal",
                    "philosophy.defining_question"), "worldview unit"),
        ("record", ("characterization.hearing",), ""),
        ("record", ("characterization.humanitarian",), ""),
        ("record", ("characterization.voice",), "voice close"),
    ],
    "conductor": [
        ("record", (), "identity unit — structural (identity.role + identity.character)"),
        ("renderer", (),
         "personality unit — _personality_unit (render.py): authored "
         "prose; record characterization.temperament / demeanor are "
         "eligibility-gated by the caller but do not supply its text"),
        ("mixed", ("philosophy.defining_question",),
         "worldview unit — _worldview_unit (render.py): the compact "
         "conviction sentence is renderer-authored; the defining "
         "question is the record's, verbatim; the fuller variant "
         "renders philosophy.core_conviction"),
        ("renderer", (),
         "voice close — _voice_close_unit (render.py): authored "
         "voice guidance; no record source"),
    ],
    "skeptic": [
        ("record", (), "identity unit — structural (identity.role + identity.character)"),
        ("record", ("characterization.personality",), ""),
        ("record", ("philosophy.ideal",
                    "characterization.domain_tension",
                    "philosophy.defining_question"), "worldview unit"),
        ("record", ("characterization.voice_and_humor",
                    "characterization.warmth"), "voice close"),
    ],
    "maverick": [
        ("record", (), "identity unit — structural (identity.role + identity.character)"),
        ("record", ("characterization.lead_compact",), ""),
        ("record", ("philosophy.ideal",
                    "philosophy.defining_question"), "worldview unit"),
        ("record", ("characterization.middle_compact",), ""),
        ("record", ("characterization.voice_compact",
                    "characterization.warmth"), "voice unit"),
    ],
}


# ---------------------------------------------------------------------------
# Helpers for the T-A tests
# ---------------------------------------------------------------------------

_NO_TRAINING_PREFIX = "Note: this user has no published training data"


def _head(lines: list[str]) -> list[str]:
    """The assembly head: everything before the no-training note —
    the opener + character lines + separator on the legacy path, the
    renderer units + preserved lines + separator on the canonical
    path."""
    idx = next(
        i for i, x in enumerate(lines) if x.startswith(_NO_TRAINING_PREFIX)
    )
    return lines[:idx]


def _classify_legacy_line(seat: str, line: str) -> str:
    if line == "":
        return "blank"
    if line.startswith("You are ") and "a voice in the user's Zenaf council" in line:
        return "opener"
    if line.startswith("Archetype: "):
        return "frame_line"
    if line.startswith("Foundational ideal: "):
        return "ideal"
    if line.startswith("Defining question"):
        return "question"
    if line.startswith("Shadow —"):
        return "shadow"
    if line.startswith("Live tension with the other seats: "):
        return "tension"
    if line == ANTI_PRESUMPTION_STYLE:
        return "style_rule"
    if seat == "conductor" and line in jurisdiction_prompt_lines("conductor"):
        return "jurisdiction"
    if line.startswith("Your warmth register: "):
        return "warmth"
    if line == "Strand blend (faculties this seat draws on, by weight):":
        return "blend_header"
    if line.startswith("- "):
        return "blend_line"
    raise AssertionError(f"unclassified legacy line for {seat}: {line[:80]!r}")


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip().lower()


# ---------------------------------------------------------------------------
# T-A2 — coverage-matrix completeness + renderer-unit classification
# ---------------------------------------------------------------------------


def test_t_a2_coverage_matrix_complete():
    from collections import Counter

    for seat in SEATS:
        legacy = _meeting_prompt(seat, canonical=False, frame="FRAME")
        kinds = Counter(
            _classify_legacy_line(seat, line) for line in _head(legacy)
        )
        expected = Counter()
        for kind, count, disposition, reference in COVERAGE_MATRIX[seat]:
            assert disposition in (
                "rendered", "retired", "preserved", "structural",
            ), (seat, kind, disposition)
            assert reference.strip(), (seat, kind)
            expected[kind] += count
        assert kinds == expected, (seat, kinds, expected)


def test_t_a2_renderer_units_classified_by_source():
    for seat in SEATS:
        record = RECORDS[seat]
        units = _renderer_units(seat)
        listing = UNIT_SOURCES[seat]
        assert len(units) == len(listing), seat
        for idx, ((source, fields, _note), unit) in enumerate(
            zip(listing, units)
        ):
            assert source in ("record", "renderer", "mixed"), (seat, idx)
            if idx == 0:
                # Identity unit: structural, built from the record's
                # identity values — verified by construction.
                identity = record["identity"]
                expected = (
                    f"You are the {identity['character']['text']}, who "
                    f"occupies the {identity['role']['text']} seat in "
                    "the Fellowship."
                )
                assert unit == expected, (seat, unit)
                continue
            for dotted in fields:
                section, key = dotted.split(".", 1)
                text = eligible_field(record, section, key)
                assert text is not None, (seat, idx, dotted)
                assert _norm(text) in _norm(unit), (seat, idx, dotted)
            if source == "record":
                assert fields, (seat, idx, "record unit with no verified field")


# ---------------------------------------------------------------------------
# T-A3 — eligibility regression
# ---------------------------------------------------------------------------


def test_t_a3_eligibility_rule_unchanged():
    assert _ELIGIBLE_CATEGORIES == frozenset({"conviction", "characterization"})
    assert CHARACTER_CEILING == 1500
    assert _FIREBRAND_CHARACTER_CEILING == 1758
    for seat in SEATS:
        record = RECORDS[seat]
        # A protected field never renders through the eligibility
        # helper; an open-standing field never renders either.
        for section, fields in record.items():
            if not isinstance(fields, dict):
                continue
            for key, field in fields.items():
                if not isinstance(field, dict) or "standing" not in field:
                    continue
                if field.get("category") == "protected" or (
                    field.get("standing") != "adopted"
                ):
                    assert eligible_field(record, section, key) is None, (
                        seat, section, key,
                    )


def test_t_a3_over_budget_fails_loud_never_truncates():
    record = copy.deepcopy(GARDENER_RECORD)
    record["characterization"]["personality"]["text"] = "x " * 3000
    with pytest.raises(AssemblyError):
        render_gardener_ordinary(
            record, authorized_name=None, resolved_capability=None
        )


# ---------------------------------------------------------------------------
# T-A4 — tier/frame invariance on the meeting path
# ---------------------------------------------------------------------------


def test_t_a4_tier_and_frame_invariant_across_character_layer():
    for seat in SEATS:
        frame = _engage_frame(seat)
        legacy = _meeting_prompt(seat, canonical=False, frame=frame)
        canon = _meeting_prompt(seat, canonical=True, frame=frame)
        # Everything from the no-training note onward — note, reply
        # guidance, canonical tier, frame, history, trailer — is
        # byte-identical; only the character head changes.
        def tail(lines):
            idx = next(
                i for i, x in enumerate(lines)
                if x.startswith(_NO_TRAINING_PREFIX)
            )
            return lines[idx:]

        assert tail(legacy) == tail(canon), seat
        joined = "\n".join(canon)
        assert CANONICAL_TIER_L1 in joined, seat
        assert frame.strip() in joined, seat


# ---------------------------------------------------------------------------
# T-A5 — full-prompt protected scan (Talk + converged meeting)
# ---------------------------------------------------------------------------


def _protected_corpus(seat: str) -> list[str]:
    corpus: list[str] = []
    record = RECORDS[seat]
    for section, fields in record.items():
        if not isinstance(fields, dict):
            continue
        for _key, field in fields.items():
            if not isinstance(field, dict):
                continue
            if field.get("category") != "protected":
                continue
            text = field.get("text")
            if isinstance(text, str) and len(text) >= 40:
                corpus.append(text)
    phil = ARCHETYPE_PHILOSOPHY.get(seat) or {}
    if phil.get("shadow"):
        corpus.append(phil["shadow"])
    if seat == "conductor":
        from local_ai.council import steward_records as SR

        corpus.append(SR.PHILOSOPHY_SHADOW)
    return corpus


def test_t_a5_no_protected_material_on_talk_or_converged_meeting():
    for seat in SEATS:
        corpus = _protected_corpus(seat)
        talk, _ = build_voice_prompt("u1", seat, "hello", [], mode="base")
        meeting = _meeting_prompt(
            seat, canonical=True, frame=_engage_frame(seat)
        )
        for label, lines in (("talk", talk), ("meeting", meeting)):
            joined = "\n".join(lines)
            assert "Shadow — your characteristic failure mode" not in joined, (
                seat, label,
            )
            for text in corpus:
                assert text not in joined, (seat, label, text[:60])


# ---------------------------------------------------------------------------
# T-A6 — Talk byte-identity goldens (pinned pre-WI-2, fc1616a tree)
# ---------------------------------------------------------------------------

TALK_GOLDENS = {
    "mentor": "1e7c54273e043773f630cc24820ae02d0e0aeb6168f2e764857978c115f482ee",
    "champion": "a74ed842b1352cde09ea2f0761fd099945c0c4529c35afe063cd654625bd38df",
    "guardian": "ed2be3b55746fd18e2a3e4a0501d522e020070dd573385276cfab4ccba00528c",
    "ambassador": "d745e8d0459653092d4b8c4d37e7409e44de0771d9c6f700a7e4726182812140",
    "conductor": "e6df6df1fd37d8863fe578c2308c67dd4328e054cb077ebb2b5620c3f7a1fddc",
    "skeptic": "c9aa4f1fe9b5bafe9f523c6b57d2c10cc8a43083b4f65c03af88db607fbb0887",
    "maverick": "caaf46f90304203d9daae67fbac149a6640802b5df6e6292acd99a7f33959906",
}


def test_t_a6_talk_byte_identity():
    for seat in SEATS:
        lines, _ = build_voice_prompt("u1", seat, "hello", [], mode="base")
        digest = hashlib.sha256("\n".join(lines).encode()).hexdigest()
        assert digest == TALK_GOLDENS[seat], seat


# ---------------------------------------------------------------------------
# Wiring — the migration controls drive the meeting path's flag
# ---------------------------------------------------------------------------


def test_meeting_canonical_enabled_unknown_seat_is_false():
    assert meeting_canonical_enabled("nobody") is False
    assert meeting_canonical_enabled("") is False
    assert meeting_canonical_enabled(None) is False


def test_generate_framed_passes_canonical_per_migration_control(
    tmp_path, monkeypatch
):
    from types import SimpleNamespace

    from local_ai.conversation.meeting import MeetingService, MeetingStore
    from local_ai.conversation.store import ConversationStore

    svc = MeetingService(
        ConversationStore(tmp_path / "conv.db"),
        MeetingStore(tmp_path / "meet.db"),
    )
    monkeypatch.setattr(
        svc, "_history_for_reply",
        lambda user_id, cid: [{"role": "user", "content": "hello"}],
    )
    captured: dict = {}

    def fake_generate(*args, **kwargs):
        captured.update(kwargs)
        return SimpleNamespace(reply="ok")

    monkeypatch.setattr(MEETING, "generate_voice_reply", fake_generate)
    try:
        for seat in SEATS:
            for value in (False, True):
                monkeypatch.setitem(
                    R._MEETING_CANONICAL_CUTOVERS, seat, value
                )
                captured.clear()
                out = svc._generate_framed("u1", seat, 1, "FRAME")
                assert out == "ok"
                assert captured["canonical"] is value, (seat, value)
                assert captured["canonical_tier"] is True
                assert captured["extra_instructions"] == "FRAME"
                assert captured["mode"] == "base"
    finally:
        svc.close()


# ---------------------------------------------------------------------------
# T-A1 — per-seat meeting fixtures. Each seat's assertions activate
# in its migration commit (the seat is skipped until its migration
# control stands True); the golden hashes were pinned on the
# pre-migration tree, since the converged assembly already exists —
# a migration commit changes only which assembly the meeting path
# selects, never the converged assembly's bytes.
# ---------------------------------------------------------------------------

MEETING_GOLDENS = {
    "mentor": "e9542af83751bdd4941bb92d531b81cc99b7d3e36bf1b7ca88fecccd8d6dd463",
    "champion": "a64a2e12b45ee26d5f0b886fe3287ed4fc698b3979639e5ac4a4db9eb776f737",
    "guardian": "a4576ef191f3489e6cb6feb29a3b0847c3f0c9db95d2d76c33cb2b21bedaaa63",
    "ambassador": "2c01c4599d2405ed2f7cd2dac179efce078d137ab5a45dada3967b8e8a091f13",
    "conductor": "a46027918535d1b33126c03b2bf0a633c4b5e8da3af62fed55c19317baf4359c",
    "skeptic": "f84a4e30df6b75d5310c551db764953b9c77bed16bb0f8961096ea9007ead940",
    "maverick": "9c8cb518f9d0eb1911d1b4276784332e8d760d4f2b376e591a4bf377d102d895",
}


def _assert_seat_meeting_converged(seat: str):
    assert meeting_canonical_enabled(seat), (
        f"{seat}: migration control does not stand True"
    )
    lines = _meeting_prompt(
        seat,
        canonical=meeting_canonical_enabled(seat),
        frame=_engage_frame(seat),
    )
    units = _renderer_units(seat)
    preserved = _preserved_lines(seat, _meeting_weights(seat))
    head = _head(lines)
    assert head == [*units, *preserved, ""], seat
    digest = hashlib.sha256("\n".join(lines).encode()).hexdigest()
    assert digest == MEETING_GOLDENS[seat], seat
    joined = "\n".join(lines)
    assert "Foundational ideal:" not in joined, seat
    assert not any(line.startswith("Archetype: ") for line in lines), seat
