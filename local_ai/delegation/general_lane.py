"""
General / fast delegation lane (tier 1).

**Purpose:** Broad coverage with strong internal prompt compilation, bounded context,
destination hints, and minimal path-specific rules — **not** a full compiled JSON contract.

v1 is a **thin seam**: compile → optional provider call → optional light parse →
non-blocking learning capture. Wire from vision_execution or future routers when
a surface opts into ``general`` tier instead of structured/strict.

Provider execution should use the same policy gates as structured paths
(``exec_meta``, ``privacy_mode``, ``routing_context``); this module does not
call OpenAI directly to avoid duplicate policy logic — pass a ``run_provider`` callable.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Callable, Mapping, Optional

from local_ai.delegation.learning_capture import capture_general_delegation_outcome

logger = logging.getLogger(__name__)


def compile_general_delegation_prompt(
    *,
    surface: str,
    action_intent: str,
    bounded_context: str,
    destination_hint: str,
    task_instruction: str,
) -> str:
    """
    Single internal prompt template for tier-1 surfaces. Keep stable for learning correlation
    (``compiled_prompt_sha256_prefix`` in LearningRecord).
    """
    return (
        "You are assisting the Atria local-first assistant.\n"
        f"Surface: {surface}\n"
        f"Action intent: {action_intent}\n"
        f"Destination / UX hint: {destination_hint}\n\n"
        f"Bounded context (do not invent facts beyond this):\n{bounded_context}\n\n"
        f"Task:\n{task_instruction}\n\n"
        "Respond concisely. If the user needs structured data, prefer a single JSON object "
        "when appropriate; otherwise plain text."
    )


def run_general_delegation_lane(
    *,
    surface: str,
    action_intent: str,
    bounded_context: str,
    destination_hint: str,
    task_instruction: str,
    privacy_mode: Optional[str],
    exec_meta: Mapping[str, Any],
    run_provider: Callable[[str], str],
    provider_used: Optional[str] = None,
    model_used: Optional[str] = None,
    try_parse_json: bool = False,
) -> dict[str, Any]:
    """
    Compile, invoke provider, optionally parse first JSON object from response, capture learning.

    ``run_provider`` must enforce routing/privacy (caller supplies e.g. wrapped OpenAI call).

    Returns:
      ``{ "ok", "text", "parsed", "error", "learning_record_id" }``
    """
    _ = exec_meta  # API symmetry with structured paths; future: trace correlation

    prompt = compile_general_delegation_prompt(
        surface=surface,
        action_intent=action_intent,
        bounded_context=bounded_context,
        destination_hint=destination_hint,
        task_instruction=task_instruction,
    )
    input_snapshot = f"{bounded_context}\n{task_instruction}"
    validation_passed = True
    validation_error: Optional[str] = None
    text = ""
    parsed: Any = None
    try:
        text = run_provider(prompt) or ""
        if try_parse_json:
            t = text.strip()
            if t.startswith("{") or t.startswith("["):
                try:
                    parsed = json.loads(t)
                except json.JSONDecodeError:
                    validation_passed = False
                    validation_error = "json_parse_failed"
            else:
                validation_passed = False
                validation_error = "expected_json_not_found"
    except Exception as e:
        validation_passed = False
        validation_error = str(e)[:500]
        text = ""

    learning_record_id = capture_general_delegation_outcome(
        surface=surface,
        action_intent=action_intent,
        privacy_mode=privacy_mode,
        provider_used=provider_used,
        model_used=model_used,
        input_snapshot=input_snapshot,
        compiled_prompt=prompt,
        validation_passed=validation_passed,
        validation_error=validation_error,
        raw_or_parsed_output=text if parsed is None else json.dumps(parsed, ensure_ascii=False, default=str),
    )
    return {
        "ok": validation_passed and bool(text),
        "text": text,
        "parsed": parsed,
        "error": validation_error,
        "learning_record_id": learning_record_id,
    }


def run_general_delegation_custom_prompt(
    *,
    surface: str,
    action_intent: str,
    compiled_prompt: str,
    input_snapshot: str,
    privacy_mode: Optional[str],
    exec_meta: Mapping[str, Any],
    run_provider: Callable[[str], str],
    provider_used: Optional[str] = None,
    model_used: Optional[str] = None,
    try_parse_json: bool = False,
) -> dict[str, Any]:
    """
    Same as ``run_general_delegation_lane`` but caller supplies the **full** compiled prompt
    (e.g. Core Profile conversation template). Still records tier ``general`` learning artifacts.
    """
    _ = exec_meta
    validation_passed = True
    validation_error: Optional[str] = None
    text = ""
    parsed: Any = None
    try:
        text = run_provider(compiled_prompt) or ""
        if try_parse_json:
            t = text.strip()
            if t.startswith("{") or t.startswith("["):
                try:
                    parsed = json.loads(t)
                except json.JSONDecodeError:
                    validation_passed = False
                    validation_error = "json_parse_failed"
            else:
                validation_passed = False
                validation_error = "expected_json_not_found"
    except Exception as e:
        validation_passed = False
        validation_error = str(e)[:500]
        text = ""

    learning_record_id = capture_general_delegation_outcome(
        surface=surface,
        action_intent=action_intent,
        privacy_mode=privacy_mode,
        provider_used=provider_used,
        model_used=model_used,
        input_snapshot=input_snapshot,
        compiled_prompt=compiled_prompt,
        validation_passed=validation_passed,
        validation_error=validation_error,
        raw_or_parsed_output=text if parsed is None else json.dumps(parsed, ensure_ascii=False, default=str),
    )
    return {
        "ok": validation_passed and bool(text),
        "text": text,
        "parsed": parsed,
        "error": validation_error,
        "learning_record_id": learning_record_id,
    }
