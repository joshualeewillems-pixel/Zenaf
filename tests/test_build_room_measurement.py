"""Build-room measurement primitives + generation measurement tests.

Live tests preserved through synthesis removal stage 3 (2026-10-27):
- Generation measurement (latency, cost, tripwire, fallback paths)
  moved verbatim from tests/test_build_room_coverage.py §G.5 — the
  coverage verdicts that file tested are removed with coverage.py,
  but measurement.py is live (meeting.py imports it).
- Tokenizer / exact-count / budget-cap primitives moved from
  tests/test_build_room_b1.py — B1's gate subject is removed, but
  these pin live primitives (local_ai.llm.tokenizer, meeting
  count_tokens_exact, Budget defaults).
"""

from local_ai.build_room import measurement as measurement_mod
from local_ai.build_room.measurement import (
    compute_generation_cost,
    evaluate_tripwire,
    measure_generation,
)
from local_ai.build_room.meeting import Budget, count_tokens_exact
from local_ai.llm.tokenizer import count_tokens, tokenizer_info


TEST_PRICE_TABLE = {
    "model": "gpt-4o-mini-test",
    "per_1m_input_usd": 2.0,
    "per_1m_output_usd": 4.0,
    "provenance": "test table (not a provider price)",
    "retrieved_date": "2026-10-26",
}


def test_tokenizer_resolves_expected_encoding():
    info = tokenizer_info()
    assert info["available"] is True
    assert info["model"] == "gpt-4o-mini"
    assert info["encoding"] == "o200k_base"
    assert info["encoding_matches_expected"] is True

def test_token_counts_deterministic_and_pinned():
    assert count_tokens("") == 0
    assert count_tokens("Hello world") == 2
    text = "The council recommends only; Joshua decides."
    assert count_tokens(text) == count_tokens(text)

def test_count_tokens_exact_returns_none_free_int():
    assert count_tokens_exact("hello world") == 2

def test_budget_response_cap_default_unchanged():
    # Moved from B1 (whose gate subject is removed in stage 3):
    # the live response-prompt cap default is still 40000 chars.
    assert Budget().max_response_prompt_chars == 40000

# §G.5 Latency tests (stubbed participant + controlled monotonic clock)
# ---------------------------------------------------------------------------

class _Clock:
    def __init__(self, values):
        self._it = iter(values)

    def __call__(self):
        return next(self._it)


class _StubParticipant:
    def __init__(self, text="ok", error=None, usage=None):
        self.text = text
        self.error = error
        self.usage = usage
        self.generate_calls = 0
        self.with_usage_calls = 0

    def generate(self, prompt, *, timeout=120):
        self.generate_calls += 1
        if self.error is not None:
            raise self.error
        return self.text


class _StubWithUsage(_StubParticipant):
    def generate_with_usage(self, prompt, *, timeout=120):
        self.with_usage_calls += 1
        if self.error is not None:
            raise self.error
        return self.text, self.usage


def test_latency_boundary_and_derived_threshold(monkeypatch):
    # 95.999s at 120s timeout: within margin (threshold 96.0).
    monkeypatch.setattr(measurement_mod.time, "monotonic",
                        _Clock([100.0, 195.999]))
    out = measure_generation(_StubParticipant(), "prompt", timeout=120)
    assert out["generation"]["duration_seconds"] == 95.999
    assert out["generation"]["margin_threshold_seconds"] == 96.0
    assert out["generation"]["within_margin"] is True
    assert out["generation"]["timed_out"] is False
    # 96.001s: outside margin.
    monkeypatch.setattr(measurement_mod.time, "monotonic",
                        _Clock([100.0, 196.001]))
    out = measure_generation(_StubParticipant(), "prompt", timeout=120)
    assert out["generation"]["within_margin"] is False
    # Threshold moves with timeout: 0.8 * 200 = 160.
    monkeypatch.setattr(measurement_mod.time, "monotonic",
                        _Clock([0.0, 159.999]))
    out = measure_generation(_StubParticipant(), "prompt", timeout=200)
    assert out["generation"]["margin_threshold_seconds"] == 160.0
    assert out["generation"]["within_margin"] is True


def test_latency_unrounded_comparison():
    # Rounds to 96.0 at ms precision but is strictly below the
    # threshold unrounded: still within margin.
    import local_ai.build_room.measurement as mm
    orig = mm.time.monotonic
    mm.time.monotonic = _Clock([0.0, 95.9999])
    try:
        out = measure_generation(_StubParticipant(), "prompt", timeout=120)
    finally:
        mm.time.monotonic = orig
    assert out["generation"]["duration_seconds"] == 96.0
    assert out["generation"]["within_margin"] is True


def test_latency_timeout_exception_path(monkeypatch):
    monkeypatch.setattr(measurement_mod.time, "monotonic",
                        _Clock([10.0, 130.0]))
    out = measure_generation(
        _StubParticipant(error=TimeoutError("timed out")),
        "prompt", timeout=120)
    assert out["text"] is None
    assert out["error"] == "timed out"
    assert out["generation"]["duration_seconds"] == 120.0
    assert out["generation"]["timed_out"] is True
    assert out["generation"]["within_margin"] is False
    # Non-timeout failure, short duration: timed_out False.
    monkeypatch.setattr(measurement_mod.time, "monotonic",
                        _Clock([0.0, 5.0]))
    out = measure_generation(
        _StubParticipant(error=RuntimeError("boom")),
        "prompt", timeout=120)
    assert out["generation"]["timed_out"] is False
    assert out["generation"]["within_margin"] is True


# ---------------------------------------------------------------------------
# §G.6 Cost tests
# ---------------------------------------------------------------------------

def test_cost_measured_path_and_tripwire():
    cost = compute_generation_cost(
        "prompt", "response",
        {"prompt_tokens": 1_000_000, "completion_tokens": 500_000,
         "total_tokens": 1_500_000},
        TEST_PRICE_TABLE)
    assert cost["source"] == "measured"
    assert cost["prompt_tokens"] == 1_000_000
    assert cost["completion_tokens"] == 500_000
    assert cost["charge_usd"] == 4.0  # 1M*2 + 0.5M*4
    assert cost["charge_basis"] == "measured_tokens_x_stated_price"
    trip = evaluate_tripwire(cost)
    assert trip["tripped"] is True
    assert trip["label"] == "measured"
    # Below tripwire: not tripped.
    small = compute_generation_cost(
        "p", "r", {"prompt_tokens": 1000, "completion_tokens": 1000},
        TEST_PRICE_TABLE)
    assert evaluate_tripwire(small)["tripped"] is False


def test_cost_estimated_path_labeled_and_separate():
    prompt, response = "hello world, this is a prompt", "a short reply here"
    cost = compute_generation_cost(prompt, response, None, TEST_PRICE_TABLE)
    assert cost["source"] == "estimated"
    assert cost["prompt_tokens"] == count_tokens(prompt)
    assert cost["completion_tokens"] == count_tokens(response)
    assert cost["charge_basis"] == "estimated_tokens_x_stated_price"
    assert cost["reason"] is not None
    trip = evaluate_tripwire(cost)
    assert trip["label"] == "estimate-based"


def test_cost_no_price_table_never_invented():
    cost = compute_generation_cost(
        "prompt", "response",
        {"prompt_tokens": 1000, "completion_tokens": 1000}, None)
    assert cost["source"] == "measured"  # tokens ARE provider-reported
    assert cost["price_table"] is None
    assert cost["charge_usd"] is None
    assert cost["charge_basis"] is None
    assert "price table" in cost["reason"]
    trip = evaluate_tripwire(cost)
    assert trip["tripped"] is None
    assert trip["label"] == "unassessable"


def test_cost_unavailable_when_neither_source(monkeypatch):
    monkeypatch.setattr(measurement_mod, "_count_tokens_exact",
                        lambda text: None)
    cost = compute_generation_cost("prompt", "response", None,
                                   TEST_PRICE_TABLE)
    assert cost["source"] == "unavailable"
    assert cost["charge_usd"] is None
    assert evaluate_tripwire(cost)["label"] == "unassessable"


def test_no_second_generation_on_any_fallback_path():
    # Participant WITH generate_with_usage returning no usage:
    # exactly one with-usage call, zero generate() calls.
    fake = _StubWithUsage(text="hello", usage=None)
    out = measure_generation(fake, "prompt", timeout=120)
    assert fake.with_usage_calls == 1
    assert fake.generate_calls == 0
    cost = compute_generation_cost("prompt", out["text"], out["usage"],
                                   TEST_PRICE_TABLE)
    assert cost["source"] == "estimated"
    # Participant WITHOUT generate_with_usage: exactly one generate().
    fake2 = _StubParticipant(text="hello")
    out2 = measure_generation(fake2, "prompt", timeout=120)
    assert fake2.generate_calls == 1
    assert out2["used_generate_with_usage"] is False
    # Participant WITH usage: exactly one call, usage carried.
    fake3 = _StubWithUsage(
        text="hello",
        usage={"prompt_tokens": 10, "completion_tokens": 5})
    out3 = measure_generation(fake3, "prompt", timeout=120)
    assert fake3.with_usage_calls == 1
    assert fake3.generate_calls == 0
    assert out3["usage"] == {"prompt_tokens": 10, "completion_tokens": 5}
    assert out3["used_generate_with_usage"] is True
