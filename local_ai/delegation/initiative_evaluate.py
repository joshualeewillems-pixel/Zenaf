"""
Structured cloud delegation v1: ``initiative_evaluate`` + OpenAI + routed seam only.

Pipeline: contract → synthesize prompt → provider.generate → extract JSON → strict validate → distribute.
No retry, no field aliases, no score coercion from strings/floats.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Mapping, Optional

from local_ai.execution_policy.externalization import (
    maybe_externalize_structured_initiative_evaluate_for_cloud,
)

from .externalized_inference import (
    INTEGRITY_FAILURE_MESSAGE,
    StrictRebindIntegrityFailure,
    mapping_active_for_externalize,
    redact_when_mapping_ok,
    strict_rebind_cloud_output,
)
from .json_extract import extract_json_object
from .learning_capture import capture_structured_delegation_outcome, exec_meta_provider_model
from .types import (
    INITIATIVE_EVALUATE_DELEGATION_SCHEMA_ID,
    INITIATIVE_EVALUATE_INTENT,
    STRUCTURED_CLOUD_DELEGATION_V1,
    InitiativeEvaluateDelegationContract,
)

logger = logging.getLogger(__name__)

_MAX_TITLE = 500
_MAX_BRIEF = 8_000
_MAX_CORE = 6_000
_MAX_STR_COST = 800
_MAX_STR_TIMEFRAME = 500
_MAX_STR_ALIGN = 1_500
_MAX_STR_RECOMMENDATION = 1_200
_MAX_STEP = 500
_MIN_STEPS = 3
_MAX_STEPS = 5

_ALLOWED_KEYS = frozenset(
    {
        "estimated_cost_ai",
        "estimated_timeframe_ai",
        "philosophical_alignment_ai",
        "recommendation",
        "next_steps",
        "evaluation_priority",
        "strategic_value",
        "energy_impact",
    }
)

# Key-name / fragment garbage (same idea as legacy initiative_evaluate)
_MALFORMED_STRING = re.compile(
    r"^\s*[\r\n]*[\"']?(?:estimated_cost_ai|estimated_cost|estimated_timeframe_ai|estimated_timeframe|"
    r"philosophical_alignment_ai|strategic_alignment|next_steps|next_step_ai|next_step|recommendation|"
    r"evaluation_priority|strategic_value|energy_impact)[\"']?\s*$",
    re.IGNORECASE,
)


def build_initiative_evaluate_contract(
    *,
    title: str,
    brief: str,
    core_profile_summary: str | None,
) -> InitiativeEvaluateDelegationContract:
    t = (title or "").strip()
    if len(t) > _MAX_TITLE:
        t = t[:_MAX_TITLE] + "…"
    b = (brief or "").strip()
    if len(b) > _MAX_BRIEF:
        b = b[:_MAX_BRIEF] + "\n… [brief truncated by server]"
    core = None
    if core_profile_summary and str(core_profile_summary).strip():
        c = str(core_profile_summary).strip()
        if len(c) > _MAX_CORE:
            c = c[:_MAX_CORE] + "\n… [core profile truncated by server]"
        core = c
    return InitiativeEvaluateDelegationContract(
        task_intent=INITIATIVE_EVALUATE_INTENT,
        title=t,
        brief=b,
        core_profile_block=core,
        output_schema_id=INITIATIVE_EVALUATE_DELEGATION_SCHEMA_ID,
        destination_api_shape=(
            "API: four strings, next_steps[3..5], evaluation_priority/strategic_value/energy_impact int 0–5."
        ),
    )


def _instruction_framing() -> str:
    return (
        "You are a bounded inference component inside a larger application.\n"
        "You do not choose tools, store data, or change workflow.\n"
        "Follow the contract exactly and output only the requested JSON object."
    )


def _task_block() -> str:
    return (
        f"Task intent: {INITIATIVE_EVALUATE_INTENT}\n"
        "Propose evaluation fields for this initiative (title + brief). "
        "Be specific; avoid generic filler."
    )


def _initiative_context_block(contract: InitiativeEvaluateDelegationContract) -> str:
    parts = [
        "--- INITIATIVE ---",
        f"Title: {contract.title}",
        f"Brief:\n{contract.brief}",
        "--- END INITIATIVE ---",
    ]
    if contract.core_profile_block:
        parts.extend(
            [
                "--- CORE PROFILE (bounded) ---",
                contract.core_profile_block,
                "--- END CORE PROFILE ---",
            ]
        )
    return "\n".join(parts)


def _json_schema_contract_block() -> str:
    return (
        "--- OUTPUT CONTRACT (JSON ONLY) ---\n"
        "Return a single JSON object with exactly these keys (no extras, no omissions):\n"
        '  "estimated_cost_ai": string, non-empty after trim.\n'
        '  "estimated_timeframe_ai": string, non-empty after trim.\n'
        '  "philosophical_alignment_ai": string, non-empty after trim.\n'
        '  "recommendation": string, non-empty (e.g. Approve / Incubate / Park / Reject with brief reason).\n'
        '  "next_steps": JSON array of 3 to 5 strings; each non-empty after trim; concrete one-sitting steps.\n'
        '  "evaluation_priority": integer from 0 to 5 inclusive (JSON number, not a string).\n'
        '  "strategic_value": integer from 0 to 5 inclusive (JSON number, not a string).\n'
        '  "energy_impact": integer from 0 to 5 inclusive (JSON number, not a string).\n'
        "Rules:\n"
        "- Output nothing before or after the JSON (no markdown fences, no commentary).\n"
        "- Use double quotes for JSON strings.\n"
        "- Scores must be integers (not floats, not quoted numbers).\n"
        "- Do not add extra top-level keys.\n"
        "--- END OUTPUT CONTRACT ---"
    )


def synthesize_structured_initiative_prompt(contract: InitiativeEvaluateDelegationContract) -> str:
    """Modular prompt: framing → task → initiative context → JSON contract."""
    sections = [
        _instruction_framing(),
        "",
        _task_block(),
        "",
        _initiative_context_block(contract),
        "",
        _json_schema_contract_block(),
        "",
        "Response (JSON object only):",
    ]
    return "\n".join(sections).strip()


def _strict_score_0_5(val: Any) -> int | None:
    if val is None or isinstance(val, bool):
        return None
    if type(val) is not int:
        return None
    return val if 0 <= val <= 5 else None


def validate_initiative_evaluate_json(data: Any) -> tuple[Optional[dict[str, Any]], Optional[str]]:
    """
    Exact key set, strict types. No aliases, no string→int scores, no float scores.
    ``next_steps`` length must be in [3, 5]; no padding or truncation.
    """
    if not isinstance(data, dict):
        return None, "root must be a JSON object"
    keys = set(data.keys())
    if keys != _ALLOWED_KEYS:
        return None, f"keys must be exactly {sorted(_ALLOWED_KEYS)}, got {sorted(keys)}"

    def check_str(key: str, max_len: int) -> tuple[str | None, str | None]:
        v = data.get(key)
        if not isinstance(v, str):
            return None, f"{key} must be a string"
        s = v.strip()
        if not s:
            return None, f"{key} must be non-empty"
        if len(s) > max_len:
            return None, f"{key} exceeds {max_len} characters"
        if _MALFORMED_STRING.match(s):
            return None, f"{key} looks like malformed or key-name fragment output"
        return s, None

    cost, e = check_str("estimated_cost_ai", _MAX_STR_COST)
    if e:
        return None, e
    tf, e = check_str("estimated_timeframe_ai", _MAX_STR_TIMEFRAME)
    if e:
        return None, e
    align, e = check_str("philosophical_alignment_ai", _MAX_STR_ALIGN)
    if e:
        return None, e
    rec, e = check_str("recommendation", _MAX_STR_RECOMMENDATION)
    if e:
        return None, e

    ns = data.get("next_steps")
    if not isinstance(ns, list):
        return None, "next_steps must be a JSON array"
    if not (_MIN_STEPS <= len(ns) <= _MAX_STEPS):
        return None, f"next_steps must have between {_MIN_STEPS} and {_MAX_STEPS} items, got {len(ns)}"
    steps: list[str] = []
    for i, item in enumerate(ns):
        if not isinstance(item, str):
            return None, f"next_steps[{i}] must be a string"
        t = item.strip()
        if not t:
            return None, f"next_steps[{i}] must be non-empty"
        if len(t) > _MAX_STEP:
            return None, f"next_steps[{i}] exceeds {_MAX_STEP} characters"
        if _MALFORMED_STRING.match(t):
            return None, f"next_steps[{i}] looks like malformed output"
        steps.append(t)

    ep = _strict_score_0_5(data.get("evaluation_priority"))
    if ep is None:
        return None, "evaluation_priority must be a JSON integer between 0 and 5"
    sv = _strict_score_0_5(data.get("strategic_value"))
    if sv is None:
        return None, "strategic_value must be a JSON integer between 0 and 5"
    ei = _strict_score_0_5(data.get("energy_impact"))
    if ei is None:
        return None, "energy_impact must be a JSON integer between 0 and 5"

    return {
        "estimated_cost_ai": cost,
        "estimated_timeframe_ai": tf,
        "philosophical_alignment_ai": align,
        "recommendation": rec,
        "next_steps": steps,
        "evaluation_priority": ep,
        "strategic_value": sv,
        "energy_impact": ei,
    }, None


def distribute_to_initiative_evaluate_api_shape(validated: Mapping[str, Any]) -> dict[str, Any]:
    """Same success shape as legacy ``evaluate_initiative`` (without trace extras)."""
    return {
        "estimated_cost_ai": validated["estimated_cost_ai"],
        "estimated_timeframe_ai": validated["estimated_timeframe_ai"],
        "philosophical_alignment_ai": validated["philosophical_alignment_ai"],
        "recommendation": validated["recommendation"],
        "next_steps": list(validated["next_steps"]),
        "evaluation_priority": validated["evaluation_priority"],
        "strategic_value": validated["strategic_value"],
        "energy_impact": validated["energy_impact"],
    }


def execute_structured_openai_initiative_delegation(
    *,
    contract: InitiativeEvaluateDelegationContract,
    provider: Any,
    routing_payload: Mapping[str, Any],
    exec_meta: Mapping[str, Any],
    initiative_id: Optional[str],
    user_id_for_externalize: Optional[str],
    privacy_mode: Optional[str],
) -> dict[str, Any]:
    """
    Synthesize → externalize (narrow ids) → generate → rebind → JSON validate → distribute.

    On failure returns ``{"error": "...", "delegation_path": "structured_cloud_v1"}`` and may
    include externalization trace fields when mapping was active.
    """
    internal_prompt = synthesize_structured_initiative_prompt(contract)
    ex = maybe_externalize_structured_initiative_evaluate_for_cloud(
        routing_context=routing_payload,
        exec_meta=exec_meta,
        internal_prompt=internal_prompt,
        initiative_id=initiative_id,
        user_id=user_id_for_externalize,
    )
    mapping_active = mapping_active_for_externalize(ex)
    surface = str(routing_payload.get("surface") or "initiative_evaluate")
    action_intent = str(
        routing_payload.get("action_intent") or contract.task_intent or INITIATIVE_EVALUATE_INTENT
    )
    input_snap = f"{contract.title}\n{contract.brief}\n{contract.core_profile_block or ''}"

    def _learn(
        validation_passed: bool,
        validation_error: Optional[str],
        output_payload: Optional[dict[str, Any]],
        mapping_active_flag: bool,
    ) -> Optional[str]:
        pu, mu = exec_meta_provider_model(exec_meta)
        return capture_structured_delegation_outcome(
            surface=surface,
            action_intent=action_intent,
            privacy_mode=privacy_mode,
            provider_used=pu,
            model_used=mu,
            delegation_tier="strict_secure" if mapping_active_flag else "structured",
            input_snapshot=input_snap,
            compiled_prompt=internal_prompt,
            validation_passed=validation_passed,
            validation_error=validation_error,
            output_payload=output_payload,
            delegation_path=STRUCTURED_CLOUD_DELEGATION_V1,
            externalization_mapping_active=mapping_active_flag,
        )

    def _fail(
        msg: str,
        base_extra: Optional[dict[str, Any]] = None,
        *,
        learning_record_id: Optional[str] = None,
    ) -> dict[str, Any]:
        out: dict[str, Any] = {"error": msg, "delegation_path": STRUCTURED_CLOUD_DELEGATION_V1}
        if base_extra:
            out.update(base_extra)
        if learning_record_id:
            out["learning_record_id"] = learning_record_id
        return out

    try:
        raw = provider.generate(ex.external_prompt, timeout=60)
    except Exception as e:
        logger.warning("structured initiative_evaluate: provider.generate failed: %s", e)
        rid = _learn(False, f"provider_error: {e!s}", None, mapping_active)
        return _fail(
            f"Structured delegation: provider error: {e!s}",
            redact_when_mapping_ok(privacy_mode=privacy_mode, mapping_active=mapping_active),
            learning_record_id=rid,
        )

    if not raw or not isinstance(raw, str):
        rid = _learn(False, "empty_or_non_string_output", None, mapping_active)
        return _fail(
            "Structured delegation: empty or non-string model output",
            redact_when_mapping_ok(privacy_mode=privacy_mode, mapping_active=mapping_active),
            learning_record_id=rid,
        )

    rb_out = strict_rebind_cloud_output(raw, ex, privacy_mode=privacy_mode)
    if isinstance(rb_out, StrictRebindIntegrityFailure):
        rid = _learn(False, "rebind_integrity_failure", None, mapping_active)
        return _fail(INTEGRITY_FAILURE_MESSAGE, rb_out.redaction_extras, learning_record_id=rid)

    text_for_json = rb_out.text
    mapping_active = rb_out.mapping_active
    blob = extract_json_object(text_for_json.strip())
    if not blob:
        rid = _learn(False, "json_extract_failed", None, mapping_active)
        return _fail(
            "Structured delegation: model output is not valid JSON",
            redact_when_mapping_ok(privacy_mode=privacy_mode, mapping_active=mapping_active),
            learning_record_id=rid,
        )

    try:
        parsed = json.loads(blob)
    except json.JSONDecodeError as e:
        rid = _learn(False, f"json_parse_error: {e!s}", None, mapping_active)
        return _fail(
            f"Structured delegation: JSON parse error: {e!s}",
            redact_when_mapping_ok(privacy_mode=privacy_mode, mapping_active=mapping_active),
            learning_record_id=rid,
        )

    norm, verr = validate_initiative_evaluate_json(parsed)
    if norm is None:
        rid = _learn(False, f"schema_validation: {verr}", None, mapping_active)
        return _fail(
            f"Structured delegation: schema validation failed: {verr}",
            redact_when_mapping_ok(privacy_mode=privacy_mode, mapping_active=mapping_active),
            learning_record_id=rid,
        )

    out = distribute_to_initiative_evaluate_api_shape(norm)
    rid = _learn(True, None, out, mapping_active)
    out["delegation_path"] = STRUCTURED_CLOUD_DELEGATION_V1
    out.update(redact_when_mapping_ok(privacy_mode=privacy_mode, mapping_active=mapping_active))
    if rid:
        out["learning_record_id"] = rid
    return out
