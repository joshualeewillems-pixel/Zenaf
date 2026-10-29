"""Conductor conversational-agency refinement (2026-10-28).

Refines Weaver's EXISTING K1 first meeting; no new meeting, no other
seat touched. What this pins:

- P1 rewrites (audit §6.2, approved proposal): initiative bans become
  permission + judgment-based yielding; no-checklist becomes the
  feature-checklist principle; the read-back formula becomes grounding
  + attribution + correctability with contrast / doubt-point / sentence
  count as available shapes; the anti-presumption / no-restatement
  conflict resolves (anti-presumption governs substance, no-double-read
  governs structure); length mandates collapse to one brevity line; the
  fallback rotates; the frame's duplicate focus line is dropped; the
  capability intention-line contradiction is resolved explicitly (kept
  as a deliberate offer instruction).
- Integrity invariants survive verbatim: naming, direct-answer-first,
  honesty guard, grounding, reveal timing, no invented training,
  recognition note, trailer instruction; the parser contract
  (--- delimiter + Strands: line) survives.
- The Conductor reference slice rides both frames prompt-locally
  (#252 pattern), draft-marked, system slice PROPOSED-marked.
- Recomputed budget: both composed frames fit the 8,000-char
  extra-instructions cap with at least 300 chars headroom, and the
  honesty guard is the last content of the engage frame (never the
  first content lost).
- Triple-source sync: steward record == meetings.py rollback source ==
  encounter.py old-path homes, on both steward-flag paths.
- Fallback rotation cycles in order without advancing the encounter.

No model calls anywhere: generation functions are capturing stubs.
"""

from __future__ import annotations

from local_ai.conversation import encounter as ENC
from local_ai.council import capabilities as CAP
from local_ai.council import meetings as MT
from local_ai.council import steward_records as SR

CAP_LIMIT = 8000
MIN_HEADROOM = 300


def _weaver_definition():
    return ENC.get_definition(MT.get_script("conductor", 1))


def _composed_frames():
    definition = _weaver_definition()
    runtime = ENC.EncounterRuntime(definition)
    turn_frame, _cue = runtime._turn_frame(
        ENC.EncounterState(), "Hello.")
    engage_frame = definition.engage_frame
    engage_frame += "\n\n" + ENC._ZENAF_QUESTION_NOTE
    engage_frame += "\n\n" + ENC._naming_note(definition)
    if definition.capability_context:
        engage_frame += "\n\n" + definition.capability_context
    return definition, turn_frame, engage_frame


# ---------------------------------------------------------------------------
# P1 rewrites: the choreography is gone, the permission is present.
# ---------------------------------------------------------------------------

def test_initiative_bans_replaced_by_permission_and_yield():
    definition = _weaver_definition()
    for text in (definition.turn_frame, definition.engage_frame):
        assert "may volunteer a topic" in text
        assert "you yield when the visitor redirects" in text
        assert "judgment about rhythm, not a procedure" in text
    for text in (definition.turn_frame, definition.engage_frame):
        assert "never resume an agenda of your own" not in text
        assert "not to steer it back" not in text
        assert "Do not move on to some other question of your own" not in text
        assert "the work in front of you is theirs" not in text


def test_no_checklist_is_now_the_principle():
    definition = _weaver_definition()
    for text in (definition.turn_frame, definition.engage_frame):
        assert "don't reduce your friends to a feature checklist" in text
        assert "no checklist of seats" not in text


def test_readback_formula_is_shapes_not_mandatory_moves():
    definition = _weaver_definition()
    readback = SR.SCRIPT_READBACK_FRAME
    # Grounding + attribution + correctability stay.
    assert "Ground the impression ONLY in their substantive material" in readback
    assert "Say it in YOUR OWN words" in readback
    assert "invite correction of it specifically" in readback
    # Contrast / doubt-point are available shapes, never mandates.
    assert "neither is required" in readback
    assert "Then contrast the read with your own tendency" not in readback
    assert "Hold the impression at the exact point of doubt" not in readback
    assert "Three to five sentences" not in readback
    # The same softening is visible on the engage path.
    assert "neither is required" in definition.engage_frame


def test_anti_presumption_governs_substance_no_double_read_structure():
    # Anti-presumption (archetype style rule) still says reflect their
    # words; the frame's blanket no-restatement ban is gone, replaced
    # by the structural rule: one read per breath.
    from local_ai.council import archetypes as A
    style = A.ANTI_PRESUMPTION_STYLE
    assert "reflect the speaker's OWN words back to them" in style
    encounter = SR.SCRIPT_ENCOUNTER_FRAME
    assert "Do NOT restate, summarize, or interpret" not in encounter
    assert "do not weave their words back in this reply" not in encounter
    assert "don't deliver it twice" in encounter


def test_length_mandates_collapsed_to_one_brevity_line():
    definition = _weaver_definition()
    for text in (definition.turn_frame, definition.engage_frame):
        assert "Keep replies brief and conversational." in text
    assert "One to three short sentences" not in SR.TURN_FRAME
    assert "ONE or TWO short sentences" not in SR.SCRIPT_ENCOUNTER_FRAME
    assert "Three to five sentences" not in SR.SCRIPT_READBACK_FRAME


def test_show_one_real_thing_is_permission_not_mandate():
    assert "you may show them one real thing" in SR.TURN_FRAME
    assert "you may show one real thing concretely" in SR.SCRIPT_ENCOUNTER_FRAME
    # The v3 scope note survives alongside the permission.
    assert "not responsible for teaching every feature" in SR.TURN_FRAME
    assert "not a tour" in SR.SCRIPT_ENCOUNTER_FRAME


def test_duplicate_focus_line_dropped_from_turn_composition():
    # The focus text still rides the identity block; the frame copy
    # is gone, so the composed turn frame carries it exactly once
    # (via the archetype lines in the full voice prompt, not here).
    _definition, turn_frame, _engage = _composed_frames()
    assert "Your ground — what naturally draws your attention" not in turn_frame


def test_capability_intention_line_kept_as_deliberate_offer():
    # Resolution, not removal: the intention line stays in the
    # first-meeting block, and the honesty guard stays last.
    block = CAP.first_meeting_block("conductor", CAP.VisitorState())
    assert CAP.INTENTION_LINE in block
    assert block.rstrip().endswith(CAP.HONESTY_GUARD)
    _definition, _turn, engage = _composed_frames()
    assert CAP.INTENTION_LINE in engage
    assert engage.rstrip().endswith(CAP.HONESTY_GUARD)


# ---------------------------------------------------------------------------
# Integrity invariants, verbatim; parser contract intact.
# ---------------------------------------------------------------------------

def test_integrity_invariants_verbatim():
    definition = _weaver_definition()
    # Reveal timing.
    assert "Do not reveal your name yet" in SR.TURN_FRAME
    assert "Do not reveal your name yet" in SR.SCRIPT_READBACK_FRAME
    # Direct-answer-first (C38) in the guidance on both paths.
    for text in (definition.turn_frame, definition.engage_frame):
        assert "Answer a direct question first, in plain words" in text
        assert "before any interpretation of it" in text
    # Grounding invariants in the read-back frame.
    readback = SR.SCRIPT_READBACK_FRAME
    assert "Never ground it in the courtesies of the meeting" in readback
    assert "Never assemble your sentences around extracted phrases" in readback
    assert "never let their first-person words come out of your mouth" in readback
    # Recognition note + trailer instruction are untouched runtime text.
    assert "completes the recognition in itself" in ENC._RECOGNITION_NOTE
    assert "[[thread:open]]" in ENC._THREAD_TRAILER_INSTRUCTION
    assert "[[thread:settled]]" in ENC._THREAD_TRAILER_INSTRUCTION


def test_no_invented_training_note_in_voice_builder():
    # The base-mode honesty note in reply.py is untouched by this PR:
    # meetings run mode "base", so the note always appears.
    import inspect
    from local_ai.conversation import reply
    source = inspect.getsource(reply.build_voice_prompt)
    assert "never invent training they don't have" in source


def test_parser_contract_delimiter_and_strands():
    # The engage glue still demands the --- delimiter line; the
    # read-back frame still demands the Strands: bookkeeping line.
    assert "place a line containing only ---" in ENC._ENGAGE_GLUE
    assert "Strands: <names>" in SR.SCRIPT_READBACK_FRAME
    # The runtime still splits on both signals.
    runtime = ENC.EncounterRuntime(_weaver_definition())
    reply, impression, had_delim = runtime._split_reply_and_impression(
        "That tracks.\n---\nA first read of you.\nStrands: Logic")
    assert had_delim is True
    assert "That tracks." in reply
    body, strands = ENC.split_strands_trailer(impression)
    assert strands == ["Logic"]
    assert "Strands:" not in body


def test_opening_beats_unchanged():
    definition = _weaver_definition()
    assert definition.opening == MT.WEAVER_INTRODUCTION
    assert definition.opening == tuple(SR.SCRIPT_OPENING)
    assert definition.reveal == tuple(SR.SCRIPT_REVEAL)


# ---------------------------------------------------------------------------
# Reference slice: prompt-local, draft-marked, both frames, Weaver only.
# ---------------------------------------------------------------------------

def test_slice_on_both_frames_weaver_only():
    definition = _weaver_definition()
    for text in (definition.turn_frame, definition.engage_frame):
        assert "Fellowship reference (DRAFT" in text
        assert "canonical text awaits verdict" in text
        assert "Coherence through orchestration that preserves" in text
        # All three dimensions: orientation, relational, agency.
        assert "How can these parts become a whole?" in text
        assert "(Pair 5.)" in text and "(Pair 21.)" in text
        assert "never impose resolution" in text
        # System slice, PROPOSED-marked, never decided.
        assert "System slice (PROPOSED, not decided)" in text
        assert "how the parts of a life and work fit together" in text
    generic = ENC.build_definition(MT.get_script("conductor", 1))
    assert "Fellowship reference" not in generic.turn_frame
    assert "Fellowship reference" not in generic.engage_frame


def test_opportunity_wording_no_mandatory_sequence():
    # The meeting gives the visitor an opportunity to encounter her;
    # knowledge is available, character decides relevance — no
    # mandatory introduction sequence, no checklist objectives (the
    # feature-checklist principle, asserted above), no coverage
    # obligation.
    definition = _weaver_definition()
    for text in (definition.turn_frame, definition.engage_frame):
        assert "opportunity to encounter your distinctive personality" in text
        assert "knowledge available, character decides relevance" in text
        assert "never a mandatory introduction sequence" in text
        assert "coverage obligation" in text
        assert "never as a tour" in text
        assert "no required order" in text


# ---------------------------------------------------------------------------
# Budget: recomputed, both paths, guard never truncatable.
# ---------------------------------------------------------------------------

def test_recomputed_budget_fits_with_headroom():
    _definition, turn_frame, engage_frame = _composed_frames()
    assert len(turn_frame) < CAP_LIMIT
    assert len(engage_frame) < CAP_LIMIT
    assert CAP_LIMIT - len(turn_frame) >= MIN_HEADROOM
    assert CAP_LIMIT - len(engage_frame) >= MIN_HEADROOM
    # The honesty guard is the last content of the engage frame.
    assert engage_frame.rstrip().endswith(CAP.HONESTY_GUARD)


def test_budget_identical_on_steward_and_rollback_paths(monkeypatch):
    sizes = {}
    for flag in (True, False):
        monkeypatch.setattr(SR, "WEAVER_STEWARD_ACTIVE", flag)
        _d, turn_frame, engage_frame = _composed_frames()
        sizes[flag] = (len(turn_frame), len(engage_frame))
    assert sizes[True] == sizes[False]


# ---------------------------------------------------------------------------
# Triple-source sync: steward == meetings == encounter old-path homes.
# ---------------------------------------------------------------------------

def test_dual_source_sync_steward_vs_meetings_vs_encounter():
    script = MT.get_script("conductor", 1)
    assert SR.TURN_FRAME == ENC.WEAVER_TURN_FRAME
    assert SR.SCRIPT_ENCOUNTER_FRAME == script.encounter_frame
    assert SR.SCRIPT_READBACK_FRAME == script.readback_frame
    assert SR.SCRIPT_CORRECTION_FRAME == script.correction_frame
    assert SR.SCRIPT_READBACK_REPLY_FRAME == script.readback_reply_frame
    assert SR.SCRIPT_OPENING == MT.WEAVER_INTRODUCTION
    assert SR.FALLBACK_LINE == ENC._WEAVER_FALLBACK_LINE
    assert SR.WRAP_LINE == ENC._WEAVER_WRAP_LINE


def test_steward_and_rollback_definitions_identical(monkeypatch):
    # Same definition object content on both read paths (frames,
    # fallback pool, slice) — rollback restores behavior exactly.
    monkeypatch.setattr(SR, "WEAVER_STEWARD_ACTIVE", False)
    old = _weaver_definition()
    monkeypatch.setattr(SR, "WEAVER_STEWARD_ACTIVE", True)
    new = _weaver_definition()
    assert old.turn_frame == new.turn_frame
    assert old.engage_frame == new.engage_frame
    assert old.fallback_line == new.fallback_line
    assert old.fallback_lines == new.fallback_lines
    assert old.opening == new.opening


# ---------------------------------------------------------------------------
# Fallback rotation: cycles, never advances the encounter.
# ---------------------------------------------------------------------------

def test_fallback_rotates_in_order():
    definition = _weaver_definition()
    assert len(definition.fallback_lines) == 3
    assert definition.fallback_lines[0] == definition.fallback_line
    state = ENC.EncounterState()
    spoken = [ENC._fallback_line(definition, state) for _ in range(4)]
    assert spoken[0] == definition.fallback_line
    assert len(set(spoken[:3])) == 3
    assert spoken[3] == spoken[0]
    assert state.fallback_uses == 4
    # Rotation touches nothing else: no engagements, no close.
    assert state.engagements == 0
    assert state.closed is False


def test_fallback_counter_round_trips_and_legacy_defaults():
    state = ENC.EncounterState()
    state.fallback_uses = 2
    restored = ENC.EncounterState.from_json(state.to_json())
    assert restored.fallback_uses == 2
    legacy = ENC.EncounterState.from_json('{"user_turns": 3}')
    assert legacy.fallback_uses == 0


def test_generic_definitions_have_no_rotation_pool():
    generic = ENC.build_definition(MT.get_script("conductor", 1))
    assert generic.fallback_lines == ()
    assert generic.fallback_line == ""
    assert ENC._has_fallback(generic) is False
    assert ENC._fallback_line(generic, ENC.EncounterState()) == ""


def test_fallback_spoken_on_empty_generation():
    # Runtime-level: an empty generation on the conversational path
    # speaks variant 1, then variant 2 on the next empty generation.
    from tests.test_first_meeting_intentions import _FakeHost
    runtime = ENC.EncounterRuntime(_weaver_definition())
    host = _FakeHost(gen_output="")
    state = ENC.EncounterState()
    runtime.handle_turn(host, state, "Hello there.", 0)
    assert host.said == [ENC._WEAVER_FALLBACK_LINES[0]]
    host2 = _FakeHost(gen_output="")
    runtime.handle_turn(host2, state, "Hello again.", 0)
    assert host2.said == [ENC._WEAVER_FALLBACK_LINES[1]]
