"""Exact offline token counting for measurement (Phase B1).

The production synthesis model is gpt-4o-mini, whose encoding is
``o200k_base`` (resolved via ``tiktoken.encoding_for_model`` and
recorded here, not assumed). Counting is deterministic and offline:
no API call, no key, no live generation.

If tiktoken is not installed, :func:`count_tokens` raises
``RuntimeError`` — it never silently falls back to the chars/4
estimate. That estimate lives in
``local_ai.build_room.meeting.estimate_tokens`` and is labeled
NOT a provider token measurement; the two must never be confused.

Admission role (cap-replacement gates, 2026-10-28): this module
is the token counter for the R2 admission gates in
``local_ai.build_room.meeting.evaluate_admission``. The encoding
is exact for gpt-4o-mini only; every other seat counts under
``o200k_base`` with a provisional +20% margin, and the fallback
estimate is never represented as an exact provider count. The
chars/4 estimate stays OUT of admission.
"""

from __future__ import annotations

MODEL = "gpt-4o-mini"
EXPECTED_ENCODING = "o200k_base"

_cache: dict[str, object] = {}


def encoding_name(model: str = MODEL) -> str:
    """Encoding name tiktoken resolves for the model."""
    import tiktoken

    return tiktoken.encoding_for_model(model).name


def count_tokens(text: str, model: str = MODEL) -> int:
    """Exact token count of ``text`` under the model's encoding."""
    try:
        import tiktoken
    except ImportError as exc:  # never fall back to chars/4 here
        raise RuntimeError(
            "tiktoken is required for exact token measurement "
            "(add it via api/requirements.txt)"
        ) from exc
    if model not in _cache:
        _cache[model] = tiktoken.encoding_for_model(model)
    return len(_cache[model].encode(text or ""))


def tokenizer_info(model: str = MODEL) -> dict:
    """Model, encoding, and availability for measurement reports."""
    try:
        import tiktoken

        name = tiktoken.encoding_for_model(model).name
        return {
            "model": model,
            "encoding": name,
            "expected_encoding": EXPECTED_ENCODING,
            "encoding_matches_expected": name == EXPECTED_ENCODING,
            "tiktoken_version": tiktoken.__version__,
            "available": True,
        }
    except ImportError:
        return {
            "model": model,
            "encoding": None,
            "expected_encoding": EXPECTED_ENCODING,
            "encoding_matches_expected": False,
            "tiktoken_version": None,
            "available": False,
        }
