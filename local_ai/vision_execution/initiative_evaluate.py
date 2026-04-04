"""
Evaluate Initiative — single-pass AI proposal for AI-suggested fields.
Returns proposed values only; no write. User must approve before applying.

Structured output (API field names):
  Strings: estimated_cost_ai, estimated_timeframe_ai, philosophical_alignment_ai, recommendation
  next_steps: list of 3–5 short, concrete, one-sitting actions (JSON array of strings)
  Integers (0–5, evaluation-derived): evaluation_priority, strategic_value, energy_impact
"""
import json
import logging
import re
from typing import Any, Mapping, Optional

from local_ai.delegation.types import INITIATIVE_EVALUATE_INTENT
from local_ai.vision_execution.idea_evaluate import _extract_json_object

logger = logging.getLogger(__name__)
LOG_PREFIX = "[initiative-eval]"

CONTRACT_STRING_KEYS = (
    "estimated_cost_ai",
    "estimated_timeframe_ai",
    "philosophical_alignment_ai",
    "recommendation",
)

# Accept LLM aliases → canonical API keys (same semantic shape as product spec).
_FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "estimated_cost_ai": ("estimated_cost_ai", "estimated_cost"),
    "estimated_timeframe_ai": ("estimated_timeframe_ai", "estimated_timeframe"),
    "philosophical_alignment_ai": ("philosophical_alignment_ai", "strategic_alignment"),
    "recommendation": ("recommendation",),
}

_NUMERIC_ALIASES: dict[str, tuple[str, ...]] = {
    "evaluation_priority": ("evaluation_priority", "priority_ai", "evaluation_priority_ai"),
    "strategic_value": ("strategic_value", "strategic_value_ai"),
    "energy_impact": ("energy_impact", "energy_impact_ai"),
}

EVALUATE_PROMPT = """You are an initiative evaluator. Given an initiative (title and brief), propose values for the fields below.

You MUST respond with exactly one JSON object and nothing else.
Rules:
- Valid JSON only: double-quoted keys, no trailing commas.
- A complete object with ALL keys listed below.
- The four text fields must be non-empty strings (use a short placeholder like "TBD" only if truly unknown).
- next_steps must be a JSON array of 3 to 5 strings: each step is one sitting, concrete (verb + object), no vague goals.
- The three score fields must be integers from 0 to 5 (inclusive). Use JSON numbers, not strings.
- No markdown, no code fences (no ```), no preamble, no explanation outside the JSON.
- Do not output key names alone, partial JSON, or quoted identifiers as values.

Required keys (exact spelling):
{{
  "estimated_cost_ai": "short cost estimate or range (e.g. low / medium / 2–3 weeks budget)",
  "estimated_timeframe_ai": "short timeframe (e.g. 2–4 weeks / Q2 / 3 months)",
  "philosophical_alignment_ai": "one sentence on fit with strategic direction",
  "recommendation": "one sentence: Approve / Incubate / Park / Reject, with brief reason",
  "next_steps": ["First concrete micro-step", "Second step after that", "Third step"],
  "evaluation_priority": 0,
  "strategic_value": 0,
  "energy_impact": 0
}}

Replace the three zeros with your integer scores 0–5:
- evaluation_priority: how urgently this initiative should rank vs other work
- strategic_value: alignment with long-term direction / payoff
- energy_impact: expected load or drag on people and attention

Initiative:
Title: {title}
Brief: {brief}
{fcore}

JSON:"""

EVALUATE_RETRY_SUFFIX = (
    "\n\nRemember: output only one complete JSON object with all nine keys. "
    "Four string fields, next_steps as array of 3–5 short strings, three integers 0–5. No markdown or code fences."
)

# Values that look like parser/model garbage (key names / fragments), not real content
_MALFORMED_VALUE = re.compile(
    r"^\s*[\r\n]*[\"']?(?:estimated_cost_ai|estimated_cost|estimated_timeframe_ai|estimated_timeframe|"
    r"philosophical_alignment_ai|strategic_alignment|next_steps|next_step_ai|next_step|recommendation)[\"']?\s*$",
    re.IGNORECASE,
)

INVALID_RESPONSE_MSG = "Evaluation failed — invalid AI response"


def _safe_str(val: Any) -> str:
    if val is None:
        return ""
    if isinstance(val, str):
        return val.strip()
    if isinstance(val, (int, float, bool)):
        return str(val).strip()
    return ""


def _parse_score_0_5(val: Any) -> int | None:
    if val is None:
        return None
    if isinstance(val, bool):
        return None
    if isinstance(val, (int, float)):
        x = int(round(float(val)))
        return x if 0 <= x <= 5 else None
    if isinstance(val, str):
        s = val.strip()
        if not s:
            return None
        try:
            x = int(round(float(s)))
            return x if 0 <= x <= 5 else None
        except (TypeError, ValueError):
            return None
    return None


def _pick_raw(data: dict[str, Any], canonical: str) -> Any:
    for name in _FIELD_ALIASES.get(canonical, (canonical,)):
        if name in data and data[name] is not None:
            return data[name]
    return None


def _pick_numeric(data: dict[str, Any], canonical: str) -> int | None:
    for name in _NUMERIC_ALIASES.get(canonical, (canonical,)):
        if name in data and data[name] is not None:
            s = _parse_score_0_5(data[name])
            if s is not None:
                return s
    return None


def _build_string_contract(data: dict[str, Any]) -> dict[str, str]:
    out: dict[str, str] = {}
    for key in CONTRACT_STRING_KEYS:
        out[key] = _safe_str(_pick_raw(data, key))
    return out


def _validate_string_contract(out: dict[str, str]) -> bool:
    for _k, v in out.items():
        if not isinstance(v, str):
            return False
        if _MALFORMED_VALUE.match(v):
            return False
    filled = sum(1 for k in CONTRACT_STRING_KEYS if (out.get(k) or "").strip())
    if filled < 2:
        return False
    return True


def _extract_next_steps(data: dict[str, Any]) -> list[str] | None:
    """3–5 non-empty concrete steps from next_steps (or legacy next_step_ai as a list)."""
    raw: Any = None
    for key in ("next_steps", "next_step_ai"):
        if key in data and data[key] is not None:
            raw = data[key]
            break
    if raw is None:
        return None
    if isinstance(raw, str):
        return None
    if not isinstance(raw, list):
        return None
    out: list[str] = []
    for item in raw:
        s = _safe_str(item)
        if s and not _MALFORMED_VALUE.match(s):
            out.append(s)
    if 3 <= len(out) <= 5:
        return out
    return None


def _build_full_contract(data: dict[str, Any]) -> dict[str, Any] | None:
    strings = _build_string_contract(data)
    if not _validate_string_contract(strings):
        return None
    next_steps = _extract_next_steps(data)
    if next_steps is None:
        return None
    ep = _pick_numeric(data, "evaluation_priority")
    sv = _pick_numeric(data, "strategic_value")
    ei = _pick_numeric(data, "energy_impact")
    if ep is None or sv is None or ei is None:
        return None
    out: dict[str, Any] = {
        **strings,
        "next_steps": next_steps,
        "evaluation_priority": ep,
        "strategic_value": sv,
        "energy_impact": ei,
    }
    return out


def _evaluate_once(prompt: str, provider: Any) -> dict[str, Any] | None:
    logger.info("%s calling provider.generate", LOG_PREFIX)
    try:
        raw = provider.generate(prompt, timeout=60)
    except Exception as e:
        logger.warning("%s provider.generate exception: %s", LOG_PREFIX, e)
        return None
    if not raw or not isinstance(raw, str):
        logger.warning("%s provider returned empty or non-string", LOG_PREFIX)
        return None
    raw_stripped = raw.strip()
    logger.info(
        "%s raw LLM response (len=%s): %s",
        LOG_PREFIX,
        len(raw_stripped),
        raw_stripped if len(raw_stripped) <= 8000 else raw_stripped[:8000] + "…[truncated]",
    )
    json_str = _extract_json_object(raw_stripped)
    if not json_str:
        logger.warning("%s _extract_json_object failed; raw sample=%r", LOG_PREFIX, raw_stripped[:500])
        return None
    logger.info("%s extracted JSON slice (len=%s): %s", LOG_PREFIX, len(json_str), json_str[:1200])
    try:
        data = json.loads(json_str)
    except json.JSONDecodeError as e:
        logger.warning("%s json.loads failed: %s | raw=%r", LOG_PREFIX, e, raw_stripped[:800])
        return None
    if not isinstance(data, dict):
        logger.warning("%s parsed JSON is not an object: %s", LOG_PREFIX, type(data).__name__)
        return None
    out = _build_full_contract(data)
    if out is None:
        logger.warning("%s full contract validation failed strings=%s", LOG_PREFIX, _build_string_contract(data))
        return None
    return out


def evaluate_initiative(
    title: str,
    brief: str,
    core_profile_summary: str | None = None,
    user_id: str | None = None,
    *,
    use_execution_seam: bool = False,
    routing_payload: Optional[Mapping[str, Any]] = None,
    exec_meta: Optional[Mapping[str, Any]] = None,
    initiative_id: Optional[str] = None,
) -> dict[str, Any]:
    """
    Single-pass LLM call to propose initiative evaluation fields (strings + 0–5 scores).
    Returns a dict with those keys or {"error": "<message>"}; does not write to storage.

    When ``routing_payload`` + ``exec_meta`` indicate OpenAI + ``initiative_evaluate`` intent
    and ``use_execution_seam`` is true, uses structured compiled delegation (strict JSON, no retry).
    """
    title = (title or "").strip()
    brief = (brief or "").strip()
    fcore = ""
    if core_profile_summary and core_profile_summary.strip():
        fcore = f"Core Profile Context:\n{core_profile_summary.strip()}\n"

    try:
        from local_ai.llm.execution_principal import execution_principal_from_legacy_user_id
        from local_ai.vision_execution.llm_seam import ve_eval_provider_shim

        provider = ve_eval_provider_shim(
            execution_principal_from_legacy_user_id(user_id),
            use_execution_seam=use_execution_seam,
        )
    except Exception as e:
        return {"error": f"Provider not available: {e!s}"}

    prov = (exec_meta or {}).get("provider_used", "")
    prov_l = prov.strip().lower() if isinstance(prov, str) else ""
    intent_raw = (routing_payload or {}).get("action_intent") if routing_payload else None
    intent = intent_raw.strip() if isinstance(intent_raw, str) else ""
    structured_branch = (
        use_execution_seam
        and routing_payload is not None
        and prov_l == "openai"
        and intent == INITIATIVE_EVALUATE_INTENT
    )
    if structured_branch:
        from local_ai.delegation.initiative_evaluate import (
            build_initiative_evaluate_contract,
            execute_structured_openai_initiative_delegation,
        )

        contract = build_initiative_evaluate_contract(
            title=title,
            brief=brief,
            core_profile_summary=core_profile_summary,
        )
        privacy_mode: str | None = None
        if routing_payload is not None:
            pm = routing_payload.get("privacy_mode")
            if isinstance(pm, str) and pm.strip():
                privacy_mode = pm.strip()
        uid_ext = (user_id or "").strip() or None
        iid_ext = (initiative_id or "").strip() or None
        return execute_structured_openai_initiative_delegation(
            contract=contract,
            provider=provider,
            routing_payload=routing_payload,
            exec_meta=dict(exec_meta or {}),
            initiative_id=iid_ext,
            user_id_for_externalize=uid_ext,
            privacy_mode=privacy_mode,
        )

    prompt = EVALUATE_PROMPT.format(title=title, brief=brief, fcore=fcore)
    out = _evaluate_once(prompt, provider)
    if out is not None:
        return out
    out = _evaluate_once(prompt + EVALUATE_RETRY_SUFFIX, provider)
    if out is not None:
        return out
    return {"error": INVALID_RESPONSE_MSG}
