"""Capability context (demonstration spec §6): one shared registry,
per-seat slices to frames, three separate fields, contextual gating.

Pins, against the registry in local_ai/council/capabilities.py:

- Registry integrity: three fields present per entry, no duplicate
  ids, no duplicated definitions (one shared entry serves Mentor and
  Maverick), suggestions unassigned, planned entries unavailable,
  Guardian mechanisms rowed separately, never-observed a policy
  guarantee rather than a toggle.
- Slice correctness: each seat's frame gets ONLY its own slice.
- Frame placement: first-meeting frames carry slice + the ONE shared
  intention line; continuation frames carry the slice as background
  knowledge only — no intention line, no offer instruction.
- Contextual gating: implementation-available but contextually
  unavailable is never presented as immediately usable; unknown
  consent fails closed.
- No hardcoded promises: frames render from the registry — the
  frame-path modules carry no capability-name literals.
- No steward machinery: this PR builds none (design note only).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from local_ai.conversation import encounter as ENC
from local_ai.conversation.reply import build_voice_prompt
from local_ai.council import capabilities as CAP
from local_ai.council import meetings as MT


# ---------------------------------------------------------------------------
# Registry integrity
# ---------------------------------------------------------------------------


def test_registry_ids_unique_and_fields_present():
    seen = set()
    for cap in CAP.CAPABILITIES:
        assert cap.id and cap.id not in seen, f"duplicate id: {cap.id}"
        seen.add(cap.id)
        assert cap.implementation in CAP.IMPLEMENTATION_STATUSES, cap.id
        assert cap.verification in CAP.VERIFICATION_STATUSES, cap.id
        assert cap.prerequisite_note.strip(), f"{cap.id}: empty prerequisite note"
        assert cap.evidence.strip(), f"{cap.id}: empty evidence"
        assert cap.primary_seat is None or cap.primary_seat in CAP.SEAT_IDS, cap.id
        for seat in cap.also_relevant:
            assert seat in CAP.SEAT_IDS, cap.id
            assert seat != cap.primary_seat, f"{cap.id}: seat listed twice"
        for key in cap.prerequisites:
            assert key in CAP.PREREQUISITE_KEYS, cap.id


def test_verified_entries_carry_playtest_evidence():
    verified = [c for c in CAP.CAPABILITIES if c.verification == "verified"]
    assert {c.id for c in verified} == {"first_meetings", "fellowship_attention"}
    for cap in verified:
        assert "playtest" in cap.evidence.lower(), cap.id
    # Nothing else is promoted: the audit's "available" meant code
    # availability, and this registry keeps that distinction in the
    # verification field.
    for cap in CAP.CAPABILITIES:
        if cap.id not in {"first_meetings", "fellowship_attention"}:
            assert cap.verification == "unverified", cap.id


def test_suggestions_unassigned_and_in_no_slice():
    sugg = CAP.get_capability("suggestions")
    assert sugg is not None
    assert sugg.primary_seat is None
    assert sugg.also_relevant == ()
    for seat in CAP.SEAT_IDS:
        assert all(c.id != "suggestions" for c in CAP.seat_slice(seat)), seat


def test_planned_entries_are_planned():
    planned = {
        "convened_council", "marketplace_info", "echo_rentals", "zones",
        "listing_disclosures", "represented_in_councils",
        "review_insights_ui", "export_all",
    }
    for cap_id in planned:
        cap = CAP.get_capability(cap_id)
        assert cap is not None and cap.implementation == "planned", cap_id


def test_guardian_mechanisms_rowed_separately():
    ids = ["redaction", "consent_enforcement", "consent_onboarding",
           "scope_toggles", "never_observed"]
    caps = [CAP.get_capability(i) for i in ids]
    assert all(c is not None for c in caps)
    assert len({c.id for c in caps}) == 5
    assert all(c.primary_seat == "guardian" for c in caps)
    never = CAP.get_capability("never_observed")
    assert "not a configurable setting or toggle" in never.detail
    assert "toggle" not in never.name.lower()
    # Re-audit correction (2026-10-25): the 96e416f audit recorded
    # per-scope toggles as "not verified" from a backend-only grep.
    # The UI exists and is reachable; the WORKFLOW is unverified.
    toggles = CAP.get_capability("scope_toggles")
    assert toggles.implementation == "available"
    assert toggles.verification == "unverified"


def test_import_is_one_shared_definition():
    mentor_slice = CAP.seat_slice("mentor")
    maverick_slice = CAP.seat_slice("maverick")
    mentor_import = [c for c in mentor_slice if c.id == "import_uploads"]
    maverick_import = [c for c in maverick_slice if c.id == "import_uploads"]
    assert len(mentor_import) == 1 and len(maverick_import) == 1
    assert mentor_import[0] is maverick_import[0]
    assert mentor_import[0].primary_seat == "mentor"
    assert "maverick" in mentor_import[0].also_relevant


# ---------------------------------------------------------------------------
# Slice correctness
# ---------------------------------------------------------------------------

EXPECTED_SLICES = {
    "conductor": ["first_meetings", "seat_chat", "fellowship_attention",
                  "tree_view", "convened_council", "marketplace_info",
                  "artifact_provenance"],
    "mentor": ["import_uploads", "training_distillation", "snapshots_eras",
               "signal_decay", "growth_records", "specializations"],
    "champion": ["projects_tasks", "commitments", "followthrough_nudges"],
    "guardian": ["redaction", "consent_enforcement", "consent_onboarding",
                 "scope_toggles", "never_observed"],
    "ambassador": ["voice_chat", "echo_rentals", "zones",
                   "listing_disclosures", "represented_in_councils"],
    "skeptic": ["review_intake", "review_insights_ui", "anchored_evidence",
                "contest_read", "recurrence", "blend_view"],
    "maverick": ["import_uploads", "byo_key", "export_all", "rename_reshape"],
}


def test_each_seat_gets_only_its_own_slice():
    for seat, expected in EXPECTED_SLICES.items():
        assert [c.id for c in CAP.seat_slice(seat)] == expected, seat


def test_unknown_seat_gets_nothing():
    assert CAP.seat_slice("nope") == ()
    assert CAP.seat_slice("") == ()
    assert CAP.seat_slice(None) == ()
    assert CAP.first_meeting_block("nope", CAP.VisitorState()) == ""
    assert CAP.continuation_block("nope", CAP.VisitorState()) == ""


# ---------------------------------------------------------------------------
# Frame placement
# ---------------------------------------------------------------------------

CONSENTED = CAP.VisitorState(signed_in=True, consent_acknowledged=True)
NOT_CONSENTED = CAP.VisitorState(signed_in=True, consent_acknowledged=False)
UNKNOWN_CONSENT = CAP.VisitorState(signed_in=True, consent_acknowledged=None)


def test_first_meeting_block_carries_lead_in_plus_slice_bullets():
    # Level 1 (2026-11-10): the block is the adopted lead-in plus
    # the seat's capability bullets only. The intention line and
    # honesty guard moved to the canonical tier — asserted there by
    # T-L1-2 (tests/test_canonical_tier.py).
    block = CAP.first_meeting_block("conductor", CONSENTED)
    assert CAP.INTENTION_LINE not in block
    assert CAP.HONESTY_GUARD not in block
    assert block.split("\n")[0] == "From your scope:"
    for name in ("First meetings", "Fellowship attention (!)",
                 "Convened multi-seat council", "Artifact provenance"):
        assert name in block
    # Another seat's primary-only capability never leaks in.
    assert "Projects and tasks" not in block
    assert "Echo rentals" not in block
    assert "Training and distillation" not in block
    # Planned stays explicitly unavailable, never aspirational drift.
    assert "Convened multi-seat council — planned, not available yet" in block


def test_continuation_block_is_background_knowledge_only():
    block = CAP.continuation_block("conductor", CONSENTED)
    assert "First meetings" in block
    assert "Convened multi-seat council — planned, not available yet" in block
    assert CAP.INTENTION_LINE not in block
    assert CAP.HONESTY_GUARD not in block
    assert "offer something characteristic" not in block


def test_weaver_definition_carries_the_block_and_turn_frame_renders_it():
    script = MT.get_script("conductor", 1)
    definition = ENC.get_definition(script)
    assert definition.capability_context
    assert definition.capability_context == CAP.first_meeting_block(
        "conductor", CAP.VisitorState()
    )
    runtime = ENC.EncounterRuntime(definition)
    frame, _cue = runtime._turn_frame(ENC.EncounterState(), "hello there")
    assert definition.capability_context in frame
    # Level 1 (2026-11-10): the intention line rides the canonical
    # tier, not the frame — asserted in the tier section of the
    # assembled prompt by T-L1-1 (tests/test_canonical_tier.py).
    assert CAP.INTENTION_LINE not in frame


def test_engage_path_frame_carries_the_block():
    """The engage generation's frame is the engage frame + notes +
    the capability block. Drive one substantive turn with a fake
    host that records the frame it was asked to generate."""

    class FakeHost:
        def __init__(self):
            self.frames: list[str] = []
            self.said: list[str] = []

        def say(self, body):
            self.said.append(body)

        def generate(self, frame):
            self.frames.append(frame)
            return "A plain engaged reply."

        def store_impression(self, claim, strands):
            pass

        def store_response(self, text):
            pass

        def store_dimensions(self, seat_outcome, visitor_response):
            pass

        def close(self, wrap_line):
            pass

    script = MT.get_script("conductor", 1)
    definition = ENC.get_definition(script)
    host = FakeHost()
    state = ENC.EncounterState()
    ENC.EncounterRuntime(definition).handle_turn(
        host, state,
        "I run a small team and two of my projects keep pulling in opposite directions, "
        "and I cannot decide which one gets my mornings.",
        0,
    )
    assert host.frames, "engage path spent no generation"
    # Level 1 (2026-11-10): the intention line rides the canonical
    # tier, not the frames — asserted there by T-L1-1
    # (tests/test_canonical_tier.py). The capability bullets still
    # ride the frames.
    assert not any(CAP.INTENTION_LINE in f for f in host.frames)
    assert any("First meetings" in f for f in host.frames)


def test_continuation_prompt_carries_slice_without_intention_line():
    block = CAP.continuation_block("champion", CONSENTED)
    prompt, _meta = build_voice_prompt(
        "test-user", "champion", "hello", [], mode="base",
        capability_context=block,
    )
    joined = "\n".join(prompt)
    assert block.strip() in joined
    assert CAP.INTENTION_LINE not in joined
    # And without the parameter, no slice leaks in.
    prompt2, _meta2 = build_voice_prompt(
        "test-user", "champion", "hello", [], mode="base",
    )
    assert "Projects and tasks" not in "\n".join(prompt2)


def test_no_hardcoded_promises_in_frame_path_modules():
    """Frames render from the registry: the modules that assemble
    frames must not carry capability-name literals of their own."""
    frame_files = [
        "local_ai/conversation/encounter.py",
        "local_ai/conversation/reply.py",
        "local_ai/conversation/meeting.py",
        "local_ai/conversation/service.py",
        "api/routes/voice_routes.py",
    ]
    distinctive = (
        "Convened multi-seat council",
        "Echo rentals",
        "Export everything",
        "Per-scope toggles",
        "Fellowship attention",
        "Bring-your-own key",
        "Conversation-export import",
    )
    root = Path(__file__).resolve().parent.parent
    for rel in frame_files:
        text = (root / rel).read_text()
        for name in distinctive:
            assert name not in text, f"{rel} hardcodes {name!r}"


def test_no_steward_machinery_in_this_pr():
    public = [n for n in dir(CAP) if not n.startswith("_")]
    for name in public:
        lowered = name.lower()
        assert "steward" not in lowered, name
        assert "tending" not in lowered, name
        assert "driver" not in lowered, name
        assert "negotiat" not in lowered, name


# ---------------------------------------------------------------------------
# Contextual gating
# ---------------------------------------------------------------------------


def test_currently_usable_rules():
    planned = CAP.get_capability("convened_council")
    assert not CAP.currently_usable(planned, CONSENTED)
    assert not CAP.currently_usable(planned, NOT_CONSENTED)
    imp = CAP.get_capability("import_uploads")
    assert CAP.currently_usable(imp, CONSENTED)
    assert not CAP.currently_usable(imp, NOT_CONSENTED)
    assert not CAP.currently_usable(imp, UNKNOWN_CONSENT)
    assert not CAP.currently_usable(
        imp, CAP.VisitorState(signed_in=False, consent_acknowledged=True))
    chat = CAP.get_capability("seat_chat")
    assert CAP.currently_usable(chat, CONSENTED)
    assert CAP.currently_usable(chat, UNKNOWN_CONSENT)
    assert not CAP.currently_usable(
        chat, CAP.VisitorState(signed_in=False, consent_acknowledged=True))


def test_gated_rendering_never_implies_usability():
    consented = CAP.first_meeting_block("mentor", CONSENTED)
    assert "Conversation-export import — available in limited form" in consented
    gated = CAP.first_meeting_block("mentor", NOT_CONSENTED)
    assert (
        "Conversation-export import — not available to you yet — "
        "Consent acknowledged; nothing trains without per-claim review approval."
        in gated
    )
    unknown = CAP.first_meeting_block("mentor", UNKNOWN_CONSENT)
    assert "not available to you yet" in unknown
    # Planned is gated regardless of visitor state.
    for state in (CONSENTED, NOT_CONSENTED, UNKNOWN_CONSENT):
        block = CAP.first_meeting_block("ambassador", state)
        assert "Echo rentals — planned, not available yet" in block


def test_resolve_visitor_state():
    assert CAP.resolve_visitor_state(None) == CAP.VisitorState(
        signed_in=False, consent_acknowledged=None)
    assert CAP.resolve_visitor_state("") == CAP.VisitorState(
        signed_in=False, consent_acknowledged=None)


def test_resolve_visitor_state_reads_consent(monkeypatch):
    import local_ai.vision_execution.storage as ve_store

    class FakeCursor:
        def __init__(self, row):
            self._row = row

        def fetchone(self):
            return self._row

    class FakeConn:
        def __init__(self, row):
            self._row = row

        def execute(self, *args, **kwargs):
            return FakeCursor(self._row)

    monkeypatch.setattr(
        ve_store, "get_connection", lambda: FakeConn({"consent_given": 1}))
    state = CAP.resolve_visitor_state("someone")
    assert state == CAP.VisitorState(signed_in=True, consent_acknowledged=True)

    monkeypatch.setattr(
        ve_store, "get_connection", lambda: FakeConn({"consent_given": 0}))
    state = CAP.resolve_visitor_state("someone")
    assert state == CAP.VisitorState(signed_in=True, consent_acknowledged=False)

    monkeypatch.setattr(
        ve_store, "get_connection", lambda: FakeConn(None))
    state = CAP.resolve_visitor_state("someone")
    assert state == CAP.VisitorState(signed_in=True, consent_acknowledged=None)

    def _boom():
        raise RuntimeError("no db")

    monkeypatch.setattr(ve_store, "get_connection", _boom)
    state = CAP.resolve_visitor_state("someone")
    assert state == CAP.VisitorState(signed_in=True, consent_acknowledged=None)


# ---------------------------------------------------------------------------
# Meeting-service wiring: a live meeting turn's generation carries the
# first-meeting block (slice + intention line), resolved per turn.
# ---------------------------------------------------------------------------


@pytest.fixture()
def ve_ctx(tmp_path, monkeypatch):
    import threading

    import local_ai.vision_execution.storage as ve_store

    monkeypatch.setattr(ve_store, "_DB_PATH", tmp_path / "ve.db")
    monkeypatch.setattr(ve_store, "_DB_DIR", tmp_path)
    monkeypatch.setattr(ve_store, "_init_done_paths", set())
    monkeypatch.setattr(ve_store, "_thread_local", threading.local())
    return {}


def test_meeting_turn_generation_carries_first_meeting_block(
    tmp_path, ve_ctx,
):
    from local_ai.conversation.meeting import MeetingService, MeetingStore
    from local_ai.conversation.store import ConversationStore
    from local_ai.vision_execution import keystone_seeding
    from local_ai.vision_execution import service as ve

    prompts: list[str] = []

    def recording_gen(prompt, **kwargs):
        prompts.append(prompt)
        return "A plain engaged reply, hearing the work."

    svc = MeetingService(
        ConversationStore(tmp_path / "conv.db"),
        MeetingStore(tmp_path / "meetings.db"),
        generate_fn=recording_gen,
    )
    user = ve.create_user_account("capctx@example.com", "pw", "CapCtx")
    uid = user["id"]
    keystone_seeding.seed_meet_your_council(uid)
    svc.start(uid, "conductor", 1)
    svc.turn(
        uid, "conductor",
        "I run a small team and two of my projects keep pulling in opposite "
        "directions, and I cannot decide which one gets my mornings.",
        keystone_index=1,
    )
    assert prompts, "no generation happened on the meeting turn"
    joined = "\n\n".join(prompts)
    assert CAP.INTENTION_LINE in joined
    assert "First meetings" in joined
    assert "Convened multi-seat council — planned, not available yet" in joined


# ---------------------------------------------------------------------------
# FC4 companion: the "naming does not create it" note (Firebrand, 2026-11-07)
# ---------------------------------------------------------------------------
# C1–C3 (design §7.4). The note rides ONLY the commitments line, and
# only when the capability is currently usable (signed-in). The other
# six seats' blocks are pinned byte-identical to the 1589a04 base
# (recorded in the test from a pristine checkout): this build changes
# exactly one line on one seat.
#
# REBASE NOTE: the Maverick S1 build (running) removes "Rename and
# reshape seats" from the registry (its C1 verdict). If it lands
# before this build rebases, the maverick pin below fails at rebase
# time and is updated then — the removal, not this build, owns the
# difference.

_OTHER_SEATS_PRE_CHANGE = {
    "mentor": (
        "What you can introduce, explain, or offer from your scope "
        "(knowledge, not a list to work through):\n"
        "- Conversation-export import — available in limited form "
        "(workflow not yet verified)\n"
        "- Training and distillation — available in limited form "
        "(workflow not yet verified)\n"
        "- Snapshots and eras — available in limited form "
        "(workflow not yet verified)\n"
        "- Signal decay — available in limited form "
        "(workflow not yet verified)\n"
        "- Growth records — available in limited form "
        "(workflow not yet verified)\n"
        "- Specializations (twigs) — available in limited form "
        "(workflow not yet verified)\n"
        "when a natural opportunity arises, offer something "
        "characteristic of what you do here; prefer a real action or "
        "interaction over an abstract description; never force an "
        "example, manufacture a need, or imply that an action occurred "
        "when it didn't\n"
        "Never present a planned capability as available, a "
        "hypothetical as an action, or a gated capability as "
        "immediately usable."
    ),
    "guardian": (
        "What you can introduce, explain, or offer from your scope "
        "(knowledge, not a list to work through):\n"
        "- Redaction at capture — available (workflow not yet verified)\n"
        "- Consent-scope enforcement — available (workflow not yet verified)\n"
        "- Consent onboarding gate — available (workflow not yet verified)\n"
        "- Per-scope toggles — available (workflow not yet verified)\n"
        "- Never observed (a data-handling policy guarantee, not a "
        "configurable setting or toggle) — available (workflow not yet "
        "verified)\n"
        "when a natural opportunity arises, offer something "
        "characteristic of what you do here; prefer a real action or "
        "interaction over an abstract description; never force an "
        "example, manufacture a need, or imply that an action occurred "
        "when it didn't\n"
        "Never present a planned capability as available, a "
        "hypothetical as an action, or a gated capability as "
        "immediately usable."
    ),
    "maverick": (
        "What you can introduce, explain, or offer from your scope "
        "(knowledge, not a list to work through):\n"
        "- Conversation-export import — available in limited form "
        "(workflow not yet verified)\n"
        "- Bring-your-own key — available in limited form "
        "(workflow not yet verified)\n"
        "- Export everything — planned, not available yet\n"
        "- Rename and reshape seats — available in limited form "
        "(workflow not yet verified)\n"
        "when a natural opportunity arises, offer something "
        "characteristic of what you do here; prefer a real action or "
        "interaction over an abstract description; never force an "
        "example, manufacture a need, or imply that an action occurred "
        "when it didn't\n"
        "Never present a planned capability as available, a "
        "hypothetical as an action, or a gated capability as "
        "immediately usable."
    ),
    "ambassador": (
        "What you can introduce, explain, or offer from your scope "
        "(knowledge, not a list to work through):\n"
        "- Voice chat — available (workflow not yet verified)\n"
        "- Echo rentals — planned, not available yet\n"
        "- Zones (rental slicing) — planned, not available yet\n"
        "- Listing disclosures — planned, not available yet\n"
        "- Being represented in other people's councils — planned, "
        "not available yet\n"
        "when a natural opportunity arises, offer something "
        "characteristic of what you do here; prefer a real action or "
        "interaction over an abstract description; never force an "
        "example, manufacture a need, or imply that an action occurred "
        "when it didn't\n"
        "Never present a planned capability as available, a "
        "hypothetical as an action, or a gated capability as "
        "immediately usable."
    ),
    "conductor": (
        "What you can introduce, explain, or offer from your scope "
        "(knowledge, not a list to work through):\n"
        "- First meetings — available\n"
        "- One-on-one seat chat — available (workflow not yet verified)\n"
        "- Fellowship attention (!) — available\n"
        "- Tree view and branch panels (the tree mapping conversations "
        "and artifacts) — available (workflow not yet verified)\n"
        "- Convened multi-seat council — planned, not available yet\n"
        "- Marketplace info via the tree — planned, not available yet\n"
        "- Artifact provenance (recorded origin of an artifact — not "
        "rental or listing disclosure) — available (workflow not yet "
        "verified)\n"
        "when a natural opportunity arises, offer something "
        "characteristic of what you do here; prefer a real action or "
        "interaction over an abstract description; never force an "
        "example, manufacture a need, or imply that an action occurred "
        "when it didn't\n"
        "Never present a planned capability as available, a "
        "hypothetical as an action, or a gated capability as "
        "immediately usable."
    ),
    "skeptic": (
        "What you can introduce, explain, or offer from your scope "
        "(knowledge, not a list to work through):\n"
        "- Review queue — intake candidates — available (workflow not "
        "yet verified)\n"
        "- Review queue — personality claims — planned, not available yet\n"
        "- Anchored evidence — available in limited form "
        "(workflow not yet verified)\n"
        "- Contesting a read — available in limited form "
        "(workflow not yet verified)\n"
        "- Recurrence patterns — available in limited form "
        "(workflow not yet verified)\n"
        "- Blend view — available in limited form "
        "(workflow not yet verified)\n"
        "when a natural opportunity arises, offer something "
        "characteristic of what you do here; prefer a real action or "
        "interaction over an abstract description; never force an "
        "example, manufacture a need, or imply that an action occurred "
        "when it didn't\n"
        "Never present a planned capability as available, a "
        "hypothetical as an action, or a gated capability as "
        "immediately usable."
    ),
}


def test_c1_companion_note_renders_when_usable():
    """C1: for a signed-in, consenting visitor, the champion's
    commitments line carries the note — and keeps its verification
    status."""
    block = CAP.first_meeting_block("champion", CONSENTED)
    assert (
        "- Commitments — available (workflow not yet verified). "
        "Naming one does not create it." in block
    )


def test_c2_no_other_seat_changes():
    """C2: the other six seats' first-meeting blocks are
    byte-identical to the pre-change (1589a04) output. The companion
    rides exactly one line on one seat."""
    for seat, pinned in _OTHER_SEATS_PRE_CHANGE.items():
        assert CAP.first_meeting_block(seat, CONSENTED) == pinned, seat


def test_c3_no_duplication_when_gated():
    """C3: signed-out, the champion's commitments line renders the
    prerequisite note (which already contains 'naming one does not
    create it') exactly once — and the prompt_note form (capital N,
    its own sentence) never appears."""
    block = CAP.first_meeting_block(
        "champion", CAP.VisitorState(signed_in=False)
    )
    assert block.count("naming one does not create it") == 1
    assert "Naming one does not create it." not in block
    assert (
        "- Commitments — not available to you yet — Signed-in account; "
        "the visitor chooses — naming one does not create it." in block
    )
