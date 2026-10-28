"""Weaver consolidation Phases 2–3 — parity, network-boundary, rollback tests.

Mandate acceptance A1/A2/A4/A6/A7 (bounded mandate plan, authorized
2026-10-28). Every parity assertion compares the OLD read path
(switch off) against the STEWARD read path (switch on) under identical
deterministic fixtures; outputs must be byte-for-byte identical —
ordering, whitespace, duplicated instructions, surrounding context.
No model calls anywhere: generation functions are capturing stubs,
and the network-boundary tests intercept the prompt string that WOULD
be delivered to the model request constructor, without sending it.

The switch under test is local_ai.council.steward_records'
WEAVER_STEWARD_ACTIVE (default on; merge activates the steward path).
Old scattered homes stay in place as the rollback source.
"""

import os
import subprocess
import sys
from types import SimpleNamespace

import pytest

from local_ai.council import archetypes as A
from local_ai.council import capabilities as CAP
from local_ai.council import jurisdictions as J
from local_ai.council import meetings as MT
from local_ai.council import steward_records as S
from local_ai.conversation import encounter as ENC
from local_ai.conversation.reply import build_voice_prompt, generate_voice_reply

OTHER_SEATS = ("mentor", "champion", "guardian", "maverick", "ambassador",
               "skeptic")


@pytest.fixture
def steward_off(monkeypatch):
    """Run the test body with the OLD read path active."""
    monkeypatch.setattr(S, "WEAVER_STEWARD_ACTIVE", False)
    yield


@pytest.fixture
def steward_on(monkeypatch):
    """Run the test body with the STEWARD read path active."""
    monkeypatch.setattr(S, "WEAVER_STEWARD_ACTIVE", True)
    yield


def run_both(monkeypatch, fn):
    """Run fn() under old, then steward, returning (old_out, steward_out)."""
    monkeypatch.setattr(S, "WEAVER_STEWARD_ACTIVE", False)
    old = fn()
    monkeypatch.setattr(S, "WEAVER_STEWARD_ACTIVE", True)
    new = fn()
    return old, new


def assert_parity(monkeypatch, fn):
    old, new = run_both(monkeypatch, fn)
    assert old == new
    return old


# ---------------------------------------------------------------------------
# A2 — weave parity (P1) across the fixture matrix
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("display_override", [None, "Renamed"])
@pytest.mark.parametrize("weights_override", [
    None,
    {"Compass": 0.4, "Logic": 0.3, "Voice": 0.1, "Heart": 0.1,
     "Eye": 0.05, "Hands": 0.03, "Ear": 0.02},
])
def test_weave_parity_matrix(monkeypatch, display_override, weights_override):
    assert_parity(
        monkeypatch,
        lambda: "\n".join(A.build_archetype_prompt_lines(
            "conductor", weights_override=weights_override,
            display_name_override=display_override)),
    )


def test_weave_components_parity(monkeypatch):
    assert_parity(monkeypatch,
                  lambda: "\n".join(A.philosophy_prompt_lines("conductor")))
    assert_parity(monkeypatch,
                  lambda: "\n".join(J.jurisdiction_prompt_lines("conductor")))


# ---------------------------------------------------------------------------
# A2 — full voice-prompt parity (P1 consumer path, incl. meeting shape)
# ---------------------------------------------------------------------------

VOICE_CASES = [
    # (kwargs to build_voice_prompt, label)
    (dict(mode="base"), "base-default"),
    (dict(mode="trained"), "trained-no-data"),
    (dict(mode="base", question=True), "question-mode"),
    (dict(mode="base", weave=False,
          extra_instructions="FRAME: encounter instructions here."),
     "meeting-shape-frame"),
    (dict(mode="base",
          capability_context="Background knowledge — things in your scope."),
     "capability-context-held-constant"),
    (dict(mode="base", thread_summary="Prior thread summary.",
          context_hint="evening, low battery",
          history=[{"role": "user", "content": "Earlier message."},
                   {"role": "assistant", "content": "Earlier reply."}]),
     "thread-history-context"),
]


@pytest.mark.parametrize("kwargs,label", VOICE_CASES,
                         ids=[c[1] for c in VOICE_CASES])
def test_voice_prompt_parity(monkeypatch, kwargs, label):
    def build():
        kw = dict(kwargs)
        kw.setdefault("history", [])
        lines, _meta = build_voice_prompt(
            "parity-nobody", "conductor", "Hello, I need to sort my week.",
            **kw)
        return "\n".join(lines)
    assert_parity(monkeypatch, build)


# ---------------------------------------------------------------------------
# A2 — first-meeting definition + turn frames (P2/P3)
# ---------------------------------------------------------------------------

def _definition_snapshot():
    d = ENC.get_definition(MT.CONDUCTOR_FIRST_MEETING)
    return {
        "opening": tuple(d.opening),
        "question_bank": tuple(d.question_bank),
        "objectives": tuple((o.id, o.description, o.satisfied_when)
                            for o in d.objectives),
        "engage_frame": d.engage_frame,
        "turn_frame": d.turn_frame,
        "impression_frame": d.impression_frame,
        "correction_frame": d.correction_frame,
        "impression_reply_frame": d.impression_reply_frame,
        "orientation_frame": d.orientation_frame,
        "orientation_facts": d.orientation_facts,
        "pause_intro": tuple(d.pause_intro),
        "pause_body": tuple(d.pause_body),
        "pulled_item_template": d.pulled_item_template,
        "pulled_where_template": d.pulled_where_template,
        "reveal": tuple(d.reveal),
        "wrap_line": d.wrap_line,
        "fallback_line": d.fallback_line,
        "allusion_pool": tuple((c.seat, c.text, c.fixture) for c in d.allusion_pool),
        "capability_context": d.capability_context,
    }


def test_meeting_definition_parity(monkeypatch):
    assert_parity(monkeypatch, _definition_snapshot)


TURN_MESSAGES = [
    ("I run a small bakery and keep losing track of orders.", "plain"),
    ("I keep setting things aside for later and they pile up.", "trace-cue"),
    ("Tell me about this workshop and its seven parts.", "pause-cue"),
]


@pytest.mark.parametrize("message,label", TURN_MESSAGES,
                         ids=[m[1] for m in TURN_MESSAGES])
def test_meeting_turn_frame_parity(monkeypatch, message, label):
    def frame():
        d = ENC.get_definition(MT.CONDUCTOR_FIRST_MEETING)
        runtime = ENC.EncounterRuntime(d)
        text, _cue = runtime._turn_frame(ENC.EncounterState(), message)
        return text
    assert_parity(monkeypatch, frame)


def test_turn_frame_shapes_differ():
    """The three fixture messages must exercise distinct frame branches
    (no cue / trace cue / pause cue) — otherwise the matrix is vacuous."""
    d = ENC.get_definition(MT.CONDUCTOR_FIRST_MEETING)
    runtime = ENC.EncounterRuntime(d)
    frames = []
    for message, _label in TURN_MESSAGES:
        text, cue = runtime._turn_frame(ENC.EncounterState(), message)
        frames.append(text)
        assert ("passes near" in text) == (cue is not None)
    assert len(set(frames)) == 3


# ---------------------------------------------------------------------------
# A2 — indirect prompt consumers (P4–P8)
# ---------------------------------------------------------------------------

def test_story_prompt_parity(monkeypatch):
    from local_ai.journal.story import _build_story_prompt
    assert_parity(
        monkeypatch,
        lambda: _build_story_prompt(
            "An entry about a week of tangled projects.",
            [("conductor", 0.9), ("mentor", 0.4)], user_id=None),
    )


def test_fellowship_observation_parity(monkeypatch):
    from local_ai.fellowship.derivation import _interpret
    event = SimpleNamespace(
        summary="A decision about the user's work was recorded.",
        kind="decision_recorded",
        evidence_text="We chose the slower path.",
        user_id=None,
    )
    captured = {}

    def gen(prompt, **_kw):
        captured["prompt"] = prompt
        return "An observation."
    assert_parity(
        monkeypatch,
        lambda: (_interpret(event, "conductor", gen), captured["prompt"])[1],
    )


def test_twig_parent_frame_parity(monkeypatch):
    def frame():
        parent = A.get_archetype("conductor")
        return (f"{parent.prompt_frame} When the conversation turns to "
                "cooking, speak from the kitchen.")
    assert_parity(monkeypatch, frame)


def test_avatar_prompt_parity(monkeypatch):
    from api.routes.council_archetype_routes import _avatar_generation_prompt
    assert_parity(monkeypatch,
                  lambda: _avatar_generation_prompt("conductor"))


@pytest.mark.parametrize("kwargs,transcript", [
    ({}, []),
    ({"question_mode": True}, []),
    ({"speak": True},
     [{"role": "conductor",
       "content": "We will find your sound soon enough."}]),
])
def test_demo_prompt_parity(monkeypatch, kwargs, transcript):
    from api.routes.demo_routes import _build_demo_prompt
    assert_parity(monkeypatch,
                  lambda: _build_demo_prompt("conductor", transcript,
                                            **kwargs))


# ---------------------------------------------------------------------------
# A2 — capability blocks (shared rendering, steward slice for conductor)
# ---------------------------------------------------------------------------

VISITOR_STATES = [
    (CAP.VisitorState(), "default-unknown"),
    (CAP.VisitorState(signed_in=True), "signed-in"),
    (CAP.VisitorState(signed_in=True, consent_acknowledged=True), "full"),
]


@pytest.mark.parametrize("state,label", VISITOR_STATES,
                         ids=[s[1] for s in VISITOR_STATES])
def test_capability_blocks_parity(monkeypatch, state, label):
    assert_parity(monkeypatch,
                  lambda: CAP.first_meeting_block("conductor", state))
    assert_parity(monkeypatch,
                  lambda: CAP.continuation_block("conductor", state))


# ---------------------------------------------------------------------------
# A6 — other six seats untouched
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("seat", OTHER_SEATS)
def test_other_seat_parity(monkeypatch, seat):
    assert_parity(monkeypatch,
                  lambda: "\n".join(A.build_archetype_prompt_lines(seat)))
    assert_parity(monkeypatch,
                  lambda: "\n".join(J.jurisdiction_prompt_lines(seat)))
    assert_parity(monkeypatch, lambda: (
        (lambda a: (a.display_name, a.prompt_frame,
                    dict(a.strand_weights) if a.strand_weights else None)
         )(A.get_archetype(seat))))
    assert_parity(monkeypatch, lambda: (
        (lambda r: (r.focus, r.register.warmth)
         )(J.get_jurisdiction(seat))))


# ---------------------------------------------------------------------------
# A2 — network-boundary assertions (prompt actually delivered to the
# model request constructor; no model call is made)
# ---------------------------------------------------------------------------

def test_network_boundary_chat(monkeypatch):
    """generate_voice_reply's constructor argument IS the assembled prompt."""
    captured = {}

    def gen(prompt, **_kw):
        captured["prompt"] = prompt
        return "A reply."

    def run():
        captured.clear()
        reply = generate_voice_reply(
            "parity-nobody", "conductor", "Hello, I need to sort my week.",
            [], mode="base", generate_fn=gen,
            extra_instructions="FRAME: encounter instructions here.",
            weave=False)
        assert reply.reply == "A reply."
        return captured["prompt"]

    old, new = run_both(monkeypatch, run)
    assert old == new
    # And the captured constructor argument equals the builder output.
    lines, _meta = build_voice_prompt(
        "parity-nobody", "conductor", "Hello, I need to sort my week.",
        [], mode="base", extra_instructions="FRAME: encounter instructions here.",
        weave=False)
    assert old == "\n".join(lines)


def test_network_boundary_meeting_framed(monkeypatch, tmp_path):
    """MeetingService._generate_framed — the exact seam host.generate calls —
    delivers the framed prompt to the constructor argument."""
    from local_ai.conversation.meeting import (
        MeetingService, MeetingStore, conversation_id_for)
    from local_ai.conversation.store import ConversationStore

    conv = ConversationStore(tmp_path / "conv.db")
    meet = MeetingStore(tmp_path / "meet.db")
    try:
        cid = conversation_id_for("conductor", 1)
        conv.ensure_conversation("parity-nobody", cid)
        conv.append_message("parity-nobody", cid, "conductor", "user",
                            "I run a small bakery.", mode="base")
        captured = {}

        def gen(prompt, **_kw):
            captured["prompt"] = prompt
            return "A framed reply."

        svc = MeetingService(conv, meet, generate_fn=gen)

        def run():
            captured.clear()
            svc._generate_framed("parity-nobody", "conductor", 1,
                                 "FRAME: encounter instructions here.")
            return captured["prompt"]

        old, new = run_both(monkeypatch, run)
        assert old == new
        # The framed prompt carries both the weave lines and the frame.
        assert "FRAME: encounter instructions here." in old
        assert "Synthesizes after the others speak." in old
        assert "How can these parts become a whole?" in old
    finally:
        conv.close()
        meet.close()


# ---------------------------------------------------------------------------
# A7 — reversible rollback transitions (in-process + subprocess/env)
# ---------------------------------------------------------------------------

def _source_probes():
    """Which source each accessor reads from: 'old' or 'steward'.
    Identity probes (frozen dataclasses / stock table) — never text,
    because the texts are identical by design."""
    arch = A.get_archetype("conductor")
    jur = J.get_jurisdiction("conductor")
    return {
        "archetype": "old" if arch is A._BY_ID["conductor"] else "steward",
        "jurisdiction": ("old" if jur is J.SEAT_JURISDICTIONS["conductor"]
                         else "steward"),
    }


def test_rollback_transitions(monkeypatch):
    """Old -> Steward -> Old -> Steward: source, output, agreement, repeat."""
    steps = []
    for active in (False, True, False, True):
        monkeypatch.setattr(S, "WEAVER_STEWARD_ACTIVE", active)
        weave = "\n".join(A.build_archetype_prompt_lines("conductor"))
        definition = _definition_snapshot()
        probes = _source_probes()
        expected = "steward" if active else "old"
        assert probes == {"archetype": expected, "jurisdiction": expected}, (
            f"mixed sources at active={active}: {probes}")
        steps.append((weave, definition))
    assert steps[0] == steps[1] == steps[2] == steps[3]


def test_rollback_subprocess_env(tmp_path):
    """Production mechanism: env var at process start selects the source;
    outputs identical either way."""
    probe = (
        "import sys; sys.path.insert(0, '.');"
        "from local_ai.council import steward_records as S;"
        "from local_ai.council import archetypes as A;"
        "from local_ai.council import jurisdictions as J;"
        "arch = A.get_archetype('conductor');"
        "jur = J.get_jurisdiction('conductor');"
        "print('steward' if arch is not A._BY_ID['conductor'] else 'old');"
        "print('steward' if jur is not J.SEAT_JURISDICTIONS['conductor'] else 'old');"
        "print('\\n'.join(A.build_archetype_prompt_lines('conductor')))"
    )
    results = {}
    for label, env_value in (("unset", None), ("on", "1"), ("off", "0")):
        env = dict(os.environ)
        env.pop("ZENAF_WEAVER_STEWARD", None)
        if env_value is not None:
            env["ZENAF_WEAVER_STEWARD"] = env_value
        proc = subprocess.run(
            [sys.executable, "-c", probe], capture_output=True, text=True,
            cwd=str(__import__("pathlib").Path(__file__).parent.parent), env=env)
        assert proc.returncode == 0, proc.stderr
        lines = proc.stdout.splitlines()
        results[label] = (lines[0], lines[1], "\n".join(lines[2:]))
    assert results["unset"][0:2] == ("steward", "steward")  # default on
    assert results["on"][0:2] == ("steward", "steward")
    assert results["off"][0:2] == ("old", "old")
    assert results["unset"][2] == results["on"][2] == results["off"][2]


# ---------------------------------------------------------------------------
# A2/A4 — drift sensitivity: the tests must actually read the steward
# ---------------------------------------------------------------------------

def test_drift_steward_value_changes_output(monkeypatch):
    """If a steward value drifts, the wired output must change (tests are
    not vacuous)."""
    monkeypatch.setattr(S, "WEAVER_STEWARD_ACTIVE", True)
    baseline = "\n".join(A.build_archetype_prompt_lines("conductor"))
    monkeypatch.setattr(S, "ARCHETYPE_PROMPT_FRAME", "DRIFTED FRAME")
    drifted = "\n".join(A.build_archetype_prompt_lines("conductor"))
    assert drifted != baseline
    assert "DRIFTED FRAME" in drifted


def test_old_home_not_consumed_when_steward_active(monkeypatch):
    """With the steward path on, mutating an old home must NOT change
    output; with it off, it must (proving which source is live)."""
    monkeypatch.setattr(S, "WEAVER_STEWARD_ACTIVE", True)
    baseline = "\n".join(A.philosophy_prompt_lines("conductor"))
    monkeypatch.setitem(A.ARCHETYPE_PHILOSOPHY["conductor"], "ideal",
                        "DRIFTED IDEAL")
    assert "\n".join(A.philosophy_prompt_lines("conductor")) == baseline
    monkeypatch.setattr(S, "WEAVER_STEWARD_ACTIVE", False)
    assert "DRIFTED IDEAL" in "\n".join(A.philosophy_prompt_lines("conductor"))
