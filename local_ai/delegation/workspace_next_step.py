"""
Structured cloud delegation v1: ``workspace_next_step`` + OpenAI only.

Pipeline: contract → synthesize prompt → externalize (existing hook) → generate → rebind → JSON validate → distribute.
"""

from __future__ import annotations

import json
from typing import Any, Mapping, Optional

from local_ai.zenaf_tools import generate_next_step_raw
from local_ai.execution_policy.externalization import (
    WORKSPACE_NEXT_STEP_INTENT,
    maybe_externalize_for_cloud,
)

from .externalized_inference import (
    INTEGRITY_FAILURE_MESSAGE,
    StrictRebindIntegrityFailure,
    mapping_active_for_externalize,
    redact_when_mapping_ok,
    strict_rebind_cloud_output,
)
from .learning_capture import capture_structured_delegation_outcome, exec_meta_provider_model
from .json_extract import extract_json_object
from .types import (
    STRUCTURED_CLOUD_DELEGATION_V1,
    WORKSPACE_NEXT_STEP_DELEGATION_SCHEMA_ID,
    WorkspaceNextStepDelegationContract,
)

_MAX_CONTEXT_CHARS = 12_000
_MAX_QUESTION_CHARS = 4_000
_MAX_RECOMMENDATION = 600
_MAX_RATIONALE = 2_500
_MAX_CAUTION = 800
_MAX_ALTERNATIVES = 12
_MAX_ALT_ITEM = 400

_ALLOWED_JSON_KEYS = frozenset({"recommendation", "rationale", "alternatives", "caution"})


def build_workspace_next_step_contract(
    *,
    bounded_context: str,
    question_goal: str | None,
    subject_id_hint: str | None,
) -> WorkspaceNextStepDelegationContract:
    ctx = (bounded_context or "").strip()
    if len(ctx) > _MAX_CONTEXT_CHARS:
        ctx = ctx[:_MAX_CONTEXT_CHARS] + "\n… [context truncated by server]"
    q = (question_goal or "").strip() or None
    if q and len(q) > _MAX_QUESTION_CHARS:
        q = q[:_MAX_QUESTION_CHARS] + "…"
    return WorkspaceNextStepDelegationContract(
        task_intent=WORKSPACE_NEXT_STEP_INTENT,
        bounded_context=ctx,
        question_goal=q,
        output_schema_id=WORKSPACE_NEXT_STEP_DELEGATION_SCHEMA_ID,
        destination_api_shape=(
            "Maps to API fields: recommendation (string), rationale (string), "
            "alternatives (string[]), caution (string|null)."
        ),
        subject_id_hint=(subject_id_hint.strip() if subject_id_hint else None) or None,
    )


def _instruction_framing() -> str:
    return (
        "You are a bounded inference component inside a larger application.\n"
        "You do not choose tools, store data, or change workflow.\n"
        "Follow the contract exactly and output only the requested JSON object."
    )


def _task_block(contract: WorkspaceNextStepDelegationContract) -> str:
    return (
        f"Task intent: {contract.task_intent}\n"
        "Suggest the single most useful next step given the context and optional goal."
    )


def _context_block(contract: WorkspaceNextStepDelegationContract) -> str:
    parts = ["--- BEGIN BOUNDED CONTEXT ---", contract.bounded_context or "(empty)", "--- END BOUNDED CONTEXT ---"]
    if contract.question_goal:
        parts.extend(
            [
                "--- USER GOAL ---",
                contract.question_goal,
                "--- END USER GOAL ---",
            ]
        )
    return "\n".join(parts)


def _json_schema_contract_block() -> str:
    return (
        "--- OUTPUT CONTRACT (JSON ONLY) ---\n"
        "Return a single JSON object with exactly these keys:\n"
        '  "recommendation": string, one concrete actionable sentence, non-empty.\n'
        '  "rationale": string, brief reason.\n'
        '  "alternatives": array of strings (zero or more short options).\n'
        '  "caution": string or null, one sentence risk/caveat or null if none.\n'
        "Rules:\n"
        "- Output nothing before or after the JSON (no markdown fences, no commentary).\n"
        "- Use double quotes for JSON strings.\n"
        "- Do not add extra top-level keys.\n"
        "--- END OUTPUT CONTRACT ---"
    )


def synthesize_structured_cloud_prompt(contract: WorkspaceNextStepDelegationContract) -> str:
    """
    Modular prompt assembly: framing → task → bounded context → schema contract.
    Not provider-specific; no network I/O.
    """
    sections = [
        _instruction_framing(),
        "",
        _task_block(contract),
        "",
        _context_block(contract),
        "",
        _json_schema_contract_block(),
        "",
        "Response (JSON object only):",
    ]
    return "\n".join(sections).strip()


def validate_workspace_next_step_json(data: Any) -> tuple[Optional[dict[str, Any]], Optional[str]]:
    """
    Strict validation: exact key set, types, bounds. No coercion of alternatives from string.
    Returns ``(normalized_dict, None)`` or ``(None, error_message)``.
    """
    if not isinstance(data, dict):
        return None, "root must be a JSON object"
    keys = set(data.keys())
    if keys != _ALLOWED_JSON_KEYS:
        return None, f"keys must be exactly {sorted(_ALLOWED_JSON_KEYS)}, got {sorted(keys)}"

    rec = data.get("recommendation")
    if not isinstance(rec, str) or not rec.strip():
        return None, "recommendation must be a non-empty string"
    rec = rec.strip()
    if len(rec) > _MAX_RECOMMENDATION:
        return None, f"recommendation exceeds {_MAX_RECOMMENDATION} characters"

    rat = data.get("rationale")
    if not isinstance(rat, str):
        return None, "rationale must be a string"
    rat = rat.strip()
    if len(rat) > _MAX_RATIONALE:
        return None, f"rationale exceeds {_MAX_RATIONALE} characters"

    alts = data.get("alternatives")
    if not isinstance(alts, list):
        return None, "alternatives must be a JSON array"
    if len(alts) > _MAX_ALTERNATIVES:
        return None, f"at most {_MAX_ALTERNATIVES} alternatives"
    norm_alts: list[str] = []
    for i, a in enumerate(alts):
        if not isinstance(a, str):
            return None, f"alternatives[{i}] must be a string"
        t = a.strip()
        if len(t) > _MAX_ALT_ITEM:
            return None, f"alternatives[{i}] exceeds {_MAX_ALT_ITEM} characters"
        if t:
            norm_alts.append(t)

    caut = data.get("caution")
    if caut is not None and not isinstance(caut, str):
        return None, "caution must be a string or null"
    caut_s = caut.strip() if isinstance(caut, str) else None
    if caut_s is not None and len(caut_s) > _MAX_CAUTION:
        return None, f"caution exceeds {_MAX_CAUTION} characters"
    if caut_s == "":
        caut_s = None

    return {
        "recommendation": rec,
        "rationale": rat,
        "alternatives": norm_alts,
        "caution": caut_s,
    }, None


def distribute_to_next_step_api_shape(validated: Mapping[str, Any]) -> dict:
    """Map validated JSON to the existing ``POST /run`` next_step result dict."""
    return {
        "recommendation": validated["recommendation"],
        "rationale": validated["rationale"],
        "alternatives": list(validated["alternatives"]),
        "caution": validated.get("caution"),
    }


def _trace_extra(base: dict[str, Any], *, learning_record_id: str | None = None) -> dict[str, Any]:
    m = dict(base)
    m["delegation_path"] = STRUCTURED_CLOUD_DELEGATION_V1
    if learning_record_id:
        m["learning_record_id"] = learning_record_id
    return m


def execute_structured_openai_delegation(
    *,
    contract: WorkspaceNextStepDelegationContract,
    exec_meta: Mapping[str, Any],
    routing_payload: Mapping[str, Any],
    privacy_mode: Optional[str],
    subject_id: Optional[str],
) -> tuple[dict, dict]:
    """
    Full compiled path: synthesize → externalize → generate → rebind → parse JSON → validate → distribute.

    Returns ``(result_or_error_dict, response_extra)``.
    """
    internal_prompt = synthesize_structured_cloud_prompt(contract)
    ex = maybe_externalize_for_cloud(
        mode="next_step",
        routing_context=routing_payload,
        exec_meta=exec_meta,
        internal_prompt=internal_prompt,
        subject_id=subject_id,
    )
    mapping_pre = mapping_active_for_externalize(ex)
    surface = str(routing_payload.get("surface") or "workspace_next_step")
    action_intent = str(routing_payload.get("action_intent") or contract.task_intent or "")
    input_snap = f"{contract.bounded_context}\n{contract.question_goal or ''}"

    def _learn(
        *,
        validation_passed: bool,
        validation_error: str | None,
        output_payload: dict[str, Any] | None,
        mapping_active: bool,
    ) -> str | None:
        pu, mu = exec_meta_provider_model(exec_meta)
        tier = "strict_secure" if mapping_active else "structured"
        return capture_structured_delegation_outcome(
            surface=surface,
            action_intent=action_intent,
            privacy_mode=privacy_mode,
            provider_used=pu,
            model_used=mu,
            delegation_tier=tier,
            input_snapshot=input_snap,
            compiled_prompt=internal_prompt,
            validation_passed=validation_passed,
            validation_error=validation_error,
            output_payload=output_payload,
            delegation_path=STRUCTURED_CLOUD_DELEGATION_V1,
            externalization_mapping_active=mapping_active,
        )

    raw, err = generate_next_step_raw(ex.external_prompt)
    if err is not None:
        rid = _learn(
            validation_passed=False,
            validation_error="provider_generate_failed",
            output_payload=None,
            mapping_active=mapping_pre,
        )
        return err, _trace_extra({}, learning_record_id=rid)

    rb_out = strict_rebind_cloud_output(raw, ex, privacy_mode=privacy_mode)
    if isinstance(rb_out, StrictRebindIntegrityFailure):
        rid = _learn(
            validation_passed=False,
            validation_error="rebind_integrity_failure",
            output_payload=None,
            mapping_active=mapping_pre,
        )
        return {
            "recommendation": "",
            "rationale": "",
            "alternatives": [],
            "caution": None,
            "error": INTEGRITY_FAILURE_MESSAGE,
        }, _trace_extra(rb_out.redaction_extras, learning_record_id=rid)

    text_for_json = rb_out.text
    mapping_active = rb_out.mapping_active
    blob = extract_json_object(text_for_json)
    if not blob:
        rid = _learn(
            validation_passed=False,
            validation_error="json_extract_failed",
            output_payload=None,
            mapping_active=mapping_active,
        )
        return {
            "recommendation": "",
            "rationale": "",
            "alternatives": [],
            "caution": None,
            "error": "Structured delegation: model output is not valid JSON.",
        }, _trace_extra(
            redact_when_mapping_ok(privacy_mode=privacy_mode, mapping_active=mapping_active),
            learning_record_id=rid,
        )

    try:
        parsed = json.loads(blob)
    except json.JSONDecodeError as e:
        rid = _learn(
            validation_passed=False,
            validation_error=f"json_parse_error: {e!s}",
            output_payload=None,
            mapping_active=mapping_active,
        )
        return {
            "recommendation": "",
            "rationale": "",
            "alternatives": [],
            "caution": None,
            "error": f"Structured delegation: JSON parse error: {e!s}",
        }, _trace_extra(
            redact_when_mapping_ok(privacy_mode=privacy_mode, mapping_active=mapping_active),
            learning_record_id=rid,
        )

    norm, verr = validate_workspace_next_step_json(parsed)
    if norm is None:
        rid = _learn(
            validation_passed=False,
            validation_error=f"schema_validation: {verr}",
            output_payload=None,
            mapping_active=mapping_active,
        )
        return {
            "recommendation": "",
            "rationale": "",
            "alternatives": [],
            "caution": None,
            "error": f"Structured delegation: schema validation failed: {verr}",
        }, _trace_extra(
            redact_when_mapping_ok(privacy_mode=privacy_mode, mapping_active=mapping_active),
            learning_record_id=rid,
        )

    out = distribute_to_next_step_api_shape(norm)
    rid = _learn(
        validation_passed=True,
        validation_error=None,
        output_payload=out,
        mapping_active=mapping_active,
    )
    extra = redact_when_mapping_ok(privacy_mode=privacy_mode, mapping_active=mapping_active)
    return out, _trace_extra(extra, learning_record_id=rid)
