"""
Structured cloud delegation v1: ``core_profile_reconcile`` + OpenAI + routed seam only.

Synthesize → externalize (v1 identity hook) → generate → strict rebind → JSON validate → distribute.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Mapping, Optional

from local_ai.execution_policy.externalization import (
    maybe_externalize_structured_core_profile_reconcile_for_cloud,
)
from local_ai.vision_execution.core_profile_reconcile import (
    CORE_PROFILE_FINAL_OVERRIDE,
    STRUCTURED_KEYS,
    _build_conversation_text,
    profile_training_notes_for_prompt,
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
    CORE_PROFILE_RECONCILE_DELEGATION_SCHEMA_ID,
    CORE_PROFILE_RECONCILE_INTENT,
    STRUCTURED_CLOUD_DELEGATION_V1,
    CoreProfileReconcileDelegationContract,
)

logger = logging.getLogger(__name__)

_MAX_NOTES = 24_000
_MAX_CONVERSATION = 24_000
_MAX_CURRENT_BLOCK = 32_000
_MAX_FIELD_VALUE = 12_000

_ALLOWED_KEYS = frozenset(STRUCTURED_KEYS)


def build_core_profile_reconcile_contract(
    *,
    current_structured: Mapping[str, Any],
    raw_notes: str,
    conversation_turns: list[dict[str, str]],
) -> CoreProfileReconcileDelegationContract:
    notes = profile_training_notes_for_prompt(raw_notes, conversation_turns)
    if len(notes) > _MAX_NOTES:
        notes = notes[:_MAX_NOTES] + "\n… [truncated]"
    conv = _build_conversation_text(conversation_turns or [])
    if len(conv) > _MAX_CONVERSATION:
        conv = conv[:_MAX_CONVERSATION] + "\n… [truncated]"
    cur = current_structured or {}
    lines = []
    for k in STRUCTURED_KEYS:
        v = cur.get(k, "")
        s = v.strip() if isinstance(v, str) else (str(v).strip() if v is not None else "")
        lines.append(f"- {k}: {s}")
    current_block = "\n".join(lines)
    if len(current_block) > _MAX_CURRENT_BLOCK:
        current_block = current_block[:_MAX_CURRENT_BLOCK] + "\n… [truncated]"
    return CoreProfileReconcileDelegationContract(
        task_intent=CORE_PROFILE_RECONCILE_INTENT,
        current_profile_block=current_block,
        raw_notes=notes,
        conversation_text=conv,
        output_schema_id=CORE_PROFILE_RECONCILE_DELEGATION_SCHEMA_ID,
        destination_api_shape="API: { proposed: { 11 string fields matching STRUCTURED_KEYS } }",
    )


def _instruction_framing() -> str:
    return (
        "You are a bounded inference component inside a larger application.\n"
        "You do not choose tools, store data, or change workflow.\n"
        "Follow the contract exactly and output only the requested JSON object."
    )


def _task_block() -> str:
    return (
        f"Task intent: {CORE_PROFILE_RECONCILE_INTENT}\n"
        "Propose an updated structured core profile. Evidence hierarchy: (1) conversation — user turns, "
        "corrections, and emphases are primary; (2) training inputs — profile digest is scaffold only; "
        "(3) raw source in training inputs is lowest priority; (4) current profile is reference baseline. "
        "When there is any contradiction between the conversation and the training inputs, the conversation "
        "is correct and must override the training inputs. "
        "Refine values where intent shifted; keep stable text where training is silent."
    )


def _context_block(contract: CoreProfileReconcileDelegationContract) -> str:
    return "\n".join(
        [
            "Evidence: conversation PRIMARY; digest in notes = scaffold; raw excerpts in notes = lowest. "
            "When there is any contradiction between the conversation and the training inputs, the conversation "
            "is correct and must override the training inputs.",
            "",
            "--- CONVERSATION (PRIMARY) ---",
            contract.conversation_text or "(none)",
            "--- END CONVERSATION ---",
            "",
            "--- CURRENT STRUCTURED PROFILE (REFERENCE) ---",
            contract.current_profile_block,
            "--- END CURRENT ---",
            "",
            "--- TRAINING INPUTS (SECONDARY digest / TERTIARY raw source) ---",
            contract.raw_notes or "(none)",
            "--- END TRAINING INPUTS ---",
        ]
    )


def _json_schema_contract_block() -> str:
    keys_csv = ", ".join(STRUCTURED_KEYS)
    return (
        "--- OUTPUT CONTRACT (JSON ONLY) ---\n"
        f"Return a single JSON object with exactly these keys (no extras, no omissions): {keys_csv}\n"
        "Each value must be a JSON string (use empty string \"\" where the model leaves a field unchanged "
        "or cannot infer — the application may merge empties with the prior snapshot).\n"
        "Rules:\n"
        "- Output nothing before or after the JSON (no markdown fences, no commentary).\n"
        "- Use double quotes for JSON strings.\n"
        "- Do not use null for field values; use \"\" instead.\n"
        "- Do not add extra top-level keys.\n"
        "--- END OUTPUT CONTRACT ---"
    )


def synthesize_structured_core_profile_reconcile_prompt(contract: CoreProfileReconcileDelegationContract) -> str:
    sections = [
        _instruction_framing(),
        "",
        _task_block(),
        "",
        _context_block(contract),
        "",
        CORE_PROFILE_FINAL_OVERRIDE,
        "",
        _json_schema_contract_block(),
        "",
        "Response (JSON object only):",
    ]
    return "\n".join(sections).strip()


def validate_core_profile_reconcile_json(data: Any) -> tuple[Optional[dict[str, str]], Optional[str]]:
    if not isinstance(data, dict):
        return None, "root must be a JSON object"
    keys = set(data.keys())
    if keys != _ALLOWED_KEYS:
        return None, f"keys must be exactly {sorted(_ALLOWED_KEYS)}, got {sorted(keys)}"
    out: dict[str, str] = {}
    for k in STRUCTURED_KEYS:
        v = data.get(k)
        if v is None:
            return None, f"{k} must not be null (use empty string)"
        if not isinstance(v, str):
            return None, f"{k} must be a JSON string, not {type(v).__name__}"
        if len(v) > _MAX_FIELD_VALUE:
            return None, f"{k} exceeds {_MAX_FIELD_VALUE} characters"
        out[k] = v
    return out, None


def distribute_reconcile_api_shape(
    validated: Mapping[str, str],
    current_structured: Mapping[str, Any],
) -> dict[str, Any]:
    """
    Same merge rule as legacy ``reconcile``: empty / whitespace-only model value → keep current field.
    """
    proposed: dict[str, str] = {}
    for key in STRUCTURED_KEYS:
        raw_v = validated[key].strip()
        if raw_v:
            proposed[key] = raw_v
        else:
            cur = current_structured.get(key, "")
            if isinstance(cur, str):
                proposed[key] = cur.strip()
            else:
                proposed[key] = str(cur).strip() if cur is not None else ""
    return {"proposed": proposed}


def execute_structured_openai_core_profile_reconcile_delegation(
    *,
    contract: CoreProfileReconcileDelegationContract,
    provider: Any,
    routing_payload: Mapping[str, Any],
    exec_meta: Mapping[str, Any],
    profile_id: Optional[str],
    user_id_for_externalize: Optional[str],
    privacy_mode: Optional[str],
    current_structured: Mapping[str, Any],
) -> dict[str, Any]:
    internal_prompt = synthesize_structured_core_profile_reconcile_prompt(contract)
    ex = maybe_externalize_structured_core_profile_reconcile_for_cloud(
        routing_context=routing_payload,
        exec_meta=exec_meta,
        internal_prompt=internal_prompt,
        profile_id=profile_id,
        user_id=user_id_for_externalize,
    )
    mapping_active = mapping_active_for_externalize(ex)
    surface = str(routing_payload.get("surface") or "core_profile_reconcile")
    action_intent = str(
        routing_payload.get("action_intent") or contract.task_intent or CORE_PROFILE_RECONCILE_INTENT
    )
    input_snap = f"{contract.current_profile_block}\n{contract.raw_notes}\n{contract.conversation_text}"

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
        raw = provider.generate(ex.external_prompt, timeout=90)
    except Exception as e:
        logger.warning("structured core_profile_reconcile: provider.generate failed: %s", e)
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

    norm, verr = validate_core_profile_reconcile_json(parsed)
    if norm is None:
        rid = _learn(False, f"schema_validation: {verr}", None, mapping_active)
        return _fail(
            f"Structured delegation: schema validation failed: {verr}",
            redact_when_mapping_ok(privacy_mode=privacy_mode, mapping_active=mapping_active),
            learning_record_id=rid,
        )

    out = distribute_reconcile_api_shape(norm, current_structured)
    rid = _learn(True, None, out, mapping_active)
    out["delegation_path"] = STRUCTURED_CLOUD_DELEGATION_V1
    out.update(redact_when_mapping_ok(privacy_mode=privacy_mode, mapping_active=mapping_active))
    if rid:
        out["learning_record_id"] = rid
    return out
