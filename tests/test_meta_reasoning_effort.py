"""reasoning_effort passthrough on the Meta provider (mocked HTTP)."""

from __future__ import annotations

import json

import local_ai.providers.meta as meta


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


def _capture(monkeypatch):
    captured = {}

    def fake_post(url, headers=None, json=None, timeout=None):
        captured["url"] = url
        captured["json"] = json
        captured["timeout"] = timeout
        return _FakeResponse({"choices": [{"message": {"content": "ok"}}]})

    monkeypatch.setattr(meta.requests, "post", fake_post)
    return captured


def test_reasoning_effort_passed_when_set(monkeypatch):
    captured = _capture(monkeypatch)
    out = meta.generate("k", "hi", reasoning_effort="low")
    assert out == "ok"
    assert captured["json"]["reasoning_effort"] == "low"


def test_reasoning_effort_omitted_by_default(monkeypatch):
    captured = _capture(monkeypatch)
    meta.generate("k", "hi")
    assert "reasoning_effort" not in captured["json"]


def test_provider_class_forwards_reasoning_effort(monkeypatch):
    captured = _capture(monkeypatch)
    p = meta.MetaProvider(api_key="k")
    p.generate("hi", reasoning_effort="minimal")
    assert captured["json"]["reasoning_effort"] == "minimal"


def test_missing_key_still_raises(monkeypatch):
    monkeypatch.delenv("META_API_KEY", raising=False)
    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    try:
        meta.generate("", "hi", reasoning_effort="low")
    except RuntimeError as exc:
        assert "not configured" in str(exc)
    else:
        raise AssertionError("expected RuntimeError")


# --- streaming ---


class _FakeStreamResponse:
    """Minimal context-manager mock of a streaming requests response."""

    def __init__(self, lines):
        self._lines = lines

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def raise_for_status(self):
        pass

    def iter_lines(self, decode_unicode=True):
        # Real requests yields bytes when decode_unicode=False; str otherwise.
        if decode_unicode:
            return iter(self._lines)
        return iter(l.encode("utf-8") for l in self._lines)


def test_generate_stream_yields_chunks_until_done(monkeypatch):
    lines = [
        'data: {"choices": [{"delta": {"content": "hel"}}]}',
        'data: {"choices": [{"delta": {"content": "lo"}}]}',
        'data: {"choices": [{"delta": {}}]}',
        "data: [DONE]",
    ]
    captured = {}

    def fake_post(url, headers=None, json=None, timeout=None, stream=False):
        captured["json"] = json
        captured["stream"] = stream
        return _FakeStreamResponse(lines)

    monkeypatch.setattr(meta.requests, "post", fake_post)
    out = "".join(meta.generate_stream("k", "hi", reasoning_effort="low"))
    assert out == "hello"
    assert captured["json"]["stream"] is True
    assert captured["json"]["reasoning_effort"] == "low"
    assert captured["stream"] is True


def test_generate_stream_missing_key_raises(monkeypatch):
    monkeypatch.delenv("META_API_KEY", raising=False)
    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    try:
        list(meta.generate_stream("", "hi"))
    except RuntimeError as exc:
        assert "not configured" in str(exc)
    else:
        raise AssertionError("expected RuntimeError")


# --- aspirational cast + weave densification ---


def test_philosophy_covers_all_voices():
    from local_ai.council import archetypes as arch

    for vid in arch.stock_archetype_ids():
        lines = arch.philosophy_prompt_lines(vid)
        assert len(lines) == 4, vid
        assert "Foundational ideal" in lines[0]
        assert "Defining question" in lines[1]
        assert "Shadow" in lines[2]
        assert "tension" in lines[3]
    assert arch.philosophy_prompt_lines("nope") == []
    # No celebrity names leak into prompt text — ingredients, not casting.
    for vid in arch.stock_archetype_ids():
        text = "\n".join(arch.philosophy_prompt_lines(vid))
        for name in ("Aurelius", "Roosevelt", "Galileo", "Franklin", "Bernstein", "Socrates", "Rogers"):
            assert name not in text, (vid, name)


def test_philosophy_woven_into_archetype_prompt():
    from local_ai.council import archetypes as arch

    lines = arch.build_archetype_prompt_lines("skeptic")
    text = "\n".join(lines)
    assert "What are we assuming?" in text
    assert "Foundational ideal" in text


def test_weave_instruction_densifies_with_depth():
    from api.routes import demo_routes as dr

    early = dr._weave_instruction(0)
    late = dr._weave_instruction(5)
    assert "[[u]]" in early
    assert "densify" in late
    assert "densify" not in early


def test_demo_prompt_includes_memory_and_philosophy():
    from api.routes import demo_routes as dr

    prompt = dr._build_demo_prompt("mentor", [], memory="* wants direction", exchanges_used=4)
    assert "Council memory" in prompt
    assert "wants direction" in prompt
    assert "What can this teach us?" in prompt
    assert "densify" in prompt
    assert "Aurelius" not in prompt


def test_demo_prompt_speak_mode_invites_voice():
    from api.routes import demo_routes as dr

    transcript = [{"role": "visitor", "content": "I want a raise"}]
    prompt = dr._build_demo_prompt("maverick", transcript, speak=True)
    assert "tapped you to speak" in prompt
    assert "Do not summarize" in prompt

    normal = dr._build_demo_prompt("maverick", transcript, speak=False)
    assert "tapped you to speak" not in normal


# --- weave sanitizer ---


def test_sanitize_weave_fixes_malformed_closings():
    from api.routes import demo_routes as dr

    assert dr._sanitize_weave("to [[u]]show them[/[/u]] now") == "to [[u]]show them[[/u]] now"
    assert dr._sanitize_weave("a [[u]]b[/u]] c") == "a [[u]]b[[/u]] c"
    assert dr._sanitize_weave("keep [[u]]drowning in ideas[[/u]] ok") == "keep [[u]]drowning in ideas[[/u]] ok"


def test_sanitize_weave_drops_orphan_open():
    from api.routes import demo_routes as dr

    assert dr._sanitize_weave("a [[u]]b with no close") == "a b with no close"


def test_sanitize_weave_leaves_plain_text_alone():
    from api.routes import demo_routes as dr

    assert dr._sanitize_weave("no markers here") == "no markers here"


def test_generate_stream_decodes_utf8_bytes(monkeypatch):
    # Regression: decode_unicode=True mojibake'd em-dashes into â€”-style
    # garbage because requests falls back to Latin-1 for text/* without a charset.
    lines = [
        'data: {"choices": [{"delta": {"content": "wait — "}}]}',
        'data: {"choices": [{"delta": {"content": "don’t"}}]}',
        "data: [DONE]",
    ]

    def fake_post(url, headers=None, json=None, timeout=None, stream=False):
        return _FakeStreamResponse(lines)

    monkeypatch.setattr(meta.requests, "post", fake_post)
    out = "".join(meta.generate_stream("k", "hi"))
    assert out == "wait — don’t", repr(out)


def test_demo_prompt_question_mode():
    from api.routes import demo_routes as dr

    transcript = [{"role": "visitor", "content": "I want a raise"}]
    q = dr._build_demo_prompt("skeptic", transcript, speak=True, question_mode=True)
    assert "question them" in q
    assert "ONE penetrating question" in q
    assert "no advice" in q

    r = dr._build_demo_prompt("skeptic", transcript, speak=True, question_mode=False)
    assert "question them" not in r
    assert "tapped you to speak" in r


def test_speak_turn_params_modes():
    from api.routes import demo_routes as dr

    class Body:
        def __init__(self, message, mode="respond"):
            self.message = message
            self.mode = mode

    sess = {"transcript": [{"role": "visitor", "content": "hi"}]}
    assert dr._speak_turn_params(Body("hello"), sess) == (False, False)
    assert dr._speak_turn_params(Body(""), sess) == (True, False)
    assert dr._speak_turn_params(Body("", "question"), sess) == (True, True)
    # question mode ignored for typed messages
    assert dr._speak_turn_params(Body("hello", "question"), sess) == (False, False)
    # unknown mode falls back to respond
    assert dr._speak_turn_params(Body("", "bogus"), sess) == (True, False)

    try:
        dr._speak_turn_params(Body(""), {"transcript": []})
    except Exception as exc:
        assert "Say something first" in str(exc.detail)
    else:
        raise AssertionError("expected 422")
