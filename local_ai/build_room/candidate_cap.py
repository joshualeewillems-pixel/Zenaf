"""B2 candidate token cap for controlled verification (NOT production).

The amended B2 design (Section 2) proposes a 12,500-prompt-token
synthesis cap with a 4,000-token output reservation (16,500 total).
This module implements that cap as a CANDIDATE: it governs only the
controlled-verification path (the harness route's B2 fixtures).
Production meetings are untouched — they still enforce the
40,000-character gate in ``Budget.max_response_prompt_chars``
via ``build_synthesis_state`` (see ``meeting.py`` Phase 4).
Adoption of the candidate as the production cap is a separate
decision (proposal Section 5, M1–M6) and is NOT made here.

Gate-migration specification (proposal Section 2.4), as mapped
to this module:

1. The token cap governs the ACTUAL ASSEMBLED synthesis prompt —
   mandatory + optional + disclosure + instruction + telemetry +
   join separators — counted exactly under ``o200k_base``.
   The diagnostic below reports every component in both chars
   and tokens.
2. No legacy character gate remains active ON THE VERIFICATION
   PATH: the harness route builds B2 fixture states with an
   effectively unbounded character cap so the token gate is the
   sole gate there. The production path keeps its character gate
   until adoption — migration of production is a future,
   separately authorized change, and this module never touches
   the production path.
3. Other character budgets are unchanged: nothing in this module
   references ``max_prompt_chars``, contribution caps, or any
   per-participant budget.
4. The diagnostic reports BOTH character and token counts, with
   TOKENS identified as the enforcement unit
   (``enforcement_unit == "tokens"``). Character counts are for
   log readability and cross-checking, never the gate.
5. Model/tokenizer agreement is verified, not assumed, by
   :func:`verify_model_tokenizer_agreement`: the tokenizer's
   model must equal the synthesizer participant's default model
   and tiktoken must resolve that model to ``o200k_base``.
   The route refuses to treat the candidate gate as enabled
   when agreement fails, and the gate itself fails closed when
   no exact token measurement is available (``count_tokens_exact``
   returns None) — a missing measurement is never disguised as
   an estimate.

Token-count note: the TOTAL is the exact count of the assembled
prompt string. Per-component token counts are counted on each
component string separately for readability; because tokenization
merges across component boundaries, component tokens may not sum
exactly to the total. Character components sum exactly
(``total_chars == sum(component chars)``), and that arithmetic
is asserted by tests. The gate decision uses the total only.
"""

from __future__ import annotations

import hashlib

from local_ai.build_room.meeting import (
    _SYNTHESIS_INSTRUCTION,
    count_tokens_exact,
)
from local_ai.build_room.participants import OpenAIParticipant
from local_ai.llm.tokenizer import EXPECTED_ENCODING, MODEL as TOKENIZER_MODEL

# Proposal Section 2: candidate cap + output reservation + total.
CANDIDATE_SYNTHESIS_PROMPT_TOKENS = 12500
CANDIDATE_OUTPUT_RESERVATION_TOKENS = 4000
CANDIDATE_TOTAL_BUDGET_TOKENS = (
    CANDIDATE_SYNTHESIS_PROMPT_TOKENS + CANDIDATE_OUTPUT_RESERVATION_TOKENS
)

# Production synthesis gate, unchanged by this module. Kept as a
# named reference (pinned equal to Budget's default by test) so
# the candidate-vs-production distinction is explicit in code.
PRODUCTION_SYNTHESIS_PROMPT_CHARS = 40000

# Join separators in the assembled prompt: 3 joins inside the state
# prompt (mandatory/optional/disclosure/instruction) + 1 before
# telemetry, 2 chars each (B1 diagnostic convention).
SEPARATOR_CHARS = 8

# Character cap used ONLY to build B2 verification states: the
# state builder's character gate is suspended on the verification
# path so the token gate is the sole gate there. Never used by
# the production meeting path.
VERIFICATION_BUILD_CHAR_CAP = 10 ** 9


def _split_components(state_prompt: str, mandatory_chars: int) -> dict | None:
    """Split a built state prompt into its named components.

    Returns None when the prompt is not in the shape
    ``build_synthesis_state`` produces (mandatory + optional +
    disclosure + instruction), so callers fail closed instead of
    reporting a fabricated breakdown.
    """
    instruction = _SYNTHESIS_INSTRUCTION
    if not state_prompt.endswith(instruction):
        return None
    without_instruction = state_prompt[: -len(instruction)]
    if not without_instruction.endswith("\n\n"):
        return None
    body = without_instruction[:-2]
    if len(body) < mandatory_chars:
        return None
    mandatory = body[:mandatory_chars]
    rest = body[mandatory_chars:]
    if not rest.startswith("\n\n"):
        return None
    rest = rest[2:]
    if "\n\n" not in rest:
        return None
    optional, disclosure = rest.rsplit("\n\n", 1)
    return {
        "mandatory": mandatory,
        "optional": optional,
        "disclosure": disclosure,
        "instruction": instruction,
    }


def evaluate_candidate_gate(state: dict, telemetry: str, *,
                            cap_tokens: int = CANDIDATE_SYNTHESIS_PROMPT_TOKENS
                            ) -> dict:
    """Apply the candidate token gate to an assembled verification prompt.

    ``state`` is a ``build_synthesis_state`` result; ``telemetry``
    is the exact block appended to the prompt. The assembled prompt
    is ``state["prompt"] + "\\n\\n" + telemetry`` — the same
    expression the production meeting path uses.
    """
    prompt = state.get("prompt")
    if prompt is None:
        return {
            "admitted": False,
            "enabled": True,
            "enforcement_unit": "tokens",
            "cap_tokens": cap_tokens,
            "total_tokens": None,
            "total_chars": None,
            "excess_tokens": None,
            "components": None,
            "prompt_sha256": None,
            "measurement_available": False,
            "reason": "no state prompt assembled; nothing to gate",
        }
    parts = _split_components(prompt, state.get("mandatory_chars", 0))
    assembled = prompt + "\n\n" + telemetry
    if parts is None:
        return {
            "admitted": False,
            "enabled": True,
            "enforcement_unit": "tokens",
            "cap_tokens": cap_tokens,
            "total_tokens": None,
            "total_chars": len(assembled),
            "excess_tokens": None,
            "components": None,
            "prompt_sha256": hashlib.sha256(assembled.encode()).hexdigest(),
            "measurement_available": False,
            "reason": "state prompt not in expected component shape; "
                      "refusing rather than reporting a fabricated breakdown",
        }
    component_strs = {
        "mandatory": parts["mandatory"],
        "optional": parts["optional"],
        "disclosure": parts["disclosure"],
        "instruction": parts["instruction"],
        "telemetry": telemetry,
        "separators": "\n\n" * 4,
    }
    component_chars = {k: len(v) for k, v in component_strs.items()}
    if sum(component_chars.values()) != len(assembled):
        return {
            "admitted": False,
            "enabled": True,
            "enforcement_unit": "tokens",
            "cap_tokens": cap_tokens,
            "total_tokens": None,
            "total_chars": len(assembled),
            "excess_tokens": None,
            "components": None,
            "prompt_sha256": hashlib.sha256(assembled.encode()).hexdigest(),
            "measurement_available": False,
            "reason": "component chars do not sum to assembled length; "
                      "refusing rather than reporting inconsistent arithmetic",
        }
    total_tokens = count_tokens_exact(assembled)
    if total_tokens is None:
        return {
            "admitted": False,
            "enabled": True,
            "enforcement_unit": "tokens",
            "cap_tokens": cap_tokens,
            "total_tokens": None,
            "total_chars": len(assembled),
            "excess_tokens": None,
            "components": {k: {"chars": c, "tokens": None}
                           for k, c in component_chars.items()},
            "prompt_sha256": hashlib.sha256(assembled.encode()).hexdigest(),
            "measurement_available": False,
            "reason": "exact token measurement unavailable (tiktoken "
                      "missing); candidate gate cannot admit without an "
                      "exact count and never falls back to an estimate",
        }
    components = {
        k: {"chars": component_chars[k],
            "tokens": count_tokens_exact(v)}
        for k, v in component_strs.items()
    }
    admitted = total_tokens <= cap_tokens
    return {
        "admitted": admitted,
        "enabled": True,
        "enforcement_unit": "tokens",
        "cap_tokens": cap_tokens,
        "total_tokens": total_tokens,
        "total_chars": len(assembled),
        "excess_tokens": max(0, total_tokens - cap_tokens),
        "components": components,
        "prompt_sha256": hashlib.sha256(assembled.encode()).hexdigest(),
        "measurement_available": True,
        "reason": None if admitted else (
            f"candidate_cap_exceeded: assembled prompt of {total_tokens} "
            f"tokens exceeds candidate cap={cap_tokens} tokens "
            f"(excess {total_tokens - cap_tokens}); no generation attempted "
            f"and nothing was truncated to fit"),
    }


def verify_model_tokenizer_agreement(
        *, tokenizer_model: str | None = None,
        synthesizer_model: str | None = None) -> dict:
    """Verify the production model and tokenizer agree (Section 2.4.5).

    Defaults are the live values: the tokenizer module's model and
    the synthesizer participant's default model (no key needed —
    the default is a constructor constant, never a live resolution).
    Overrides exist only so tests can exercise disagreement.
    Agreement requires: same model string, and tiktoken resolving
    that model to the expected encoding. Anything else — including
    a missing tiktoken — is disagreement, and the candidate gate
    must not be treated as enabled.
    """
    tokenizer_model = tokenizer_model if tokenizer_model is not None else TOKENIZER_MODEL
    if synthesizer_model is None:
        synthesizer_model = OpenAIParticipant("").model
    try:
        from local_ai.llm.tokenizer import encoding_name
        encoding = encoding_name(tokenizer_model)
        tiktoken_available = True
    except Exception:
        encoding = None
        tiktoken_available = False
    agrees = (
        tiktoken_available
        and tokenizer_model == synthesizer_model
        and encoding == EXPECTED_ENCODING
    )
    return {
        "agrees": agrees,
        "tokenizer_model": tokenizer_model,
        "synthesizer_model": synthesizer_model,
        "encoding": encoding,
        "expected_encoding": EXPECTED_ENCODING,
        "tiktoken_available": tiktoken_available,
        "reason": None if agrees else (
            "model/tokenizer disagreement: tokenizer_model="
            f"{tokenizer_model!r}, synthesizer_model="
            f"{synthesizer_model!r}, encoding={encoding!r}, expected="
            f"{EXPECTED_ENCODING!r}; candidate gate must not be enabled"),
    }
