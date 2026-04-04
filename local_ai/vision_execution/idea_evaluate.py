"""
Evaluate Idea — single-pass AI proposal for idea-stage decision fields.
Returns the MVP contract from docs/04_REFERENCE/IDEA_EVALUATION_SPEC.md; no persistence.
Contract: either a valid normalized response dict or a single "error" key.
"""
import json
import logging
import re
from typing import Any, Mapping, Optional

logger = logging.getLogger(__name__)
DEBUG_PREFIX = "[idea-eval]"

IDEA_EVALUATE_PROMPT = """You are an idea evaluator. This is a raw idea under consideration—not yet a committed initiative. The user will decide whether to Promote it to an initiative, Incubate it, Shelve it, or Reject it. Base every value on this idea's title and brief; be specific and decision-useful. Avoid generic filler.

Respond with exactly one JSON object. No markdown, no code fences, no preamble, no explanation outside the JSON. Valid JSON only with exactly these keys:
{{
  "estimated_cost_range": "cost or range specific to this idea (e.g. low / 2–3 weeks budget)",
  "time_to_build": "time to deliver or implement, specific to this idea (e.g. 2–4 weeks / Q2)",
  "time_to_roi": "when value or ROI is expected for this idea (e.g. 3 months / within quarter)",
  "roi_potential": "one of: conservative | expected | speculative",
  "required_roles": "concrete roles or team seats needed for this idea (e.g. 1 eng, 0.5 PM)",
  "likely_dependencies": "what this idea depends on—other work, systems, or decisions—specific to this idea",
  "major_risks": "key risks specific to this idea (delivery, fit, capacity, or other)",
  "strategic_alignment": "one sentence on how this idea fits strategic direction; be specific, not generic",
  "suggested_next_step": "one concrete next action for this idea (e.g. clarify scope, prototype, promote to initiative, shelve)",
  "recommendation": "Exactly one of: Promote | Incubate | Shelve | Reject, then a brief reason (e.g. 'Promote — fits Q2 goals and capacity is available')"
}}

Idea:
Title: {title}
Brief: {brief}
{fcore}

JSON:"""

# Suffix for retry: reinforce JSON-only output.
IDEA_EVALUATE_RETRY_SUFFIX = "\n\nRemember: respond with only the JSON object. No markdown, no code fences, no preamble, no explanation."

CONTRACT_KEYS = (
    "estimated_cost_range",
    "time_to_build",
    "time_to_roi",
    "roi_potential",
    "required_roles",
    "likely_dependencies",
    "major_risks",
    "strategic_alignment",
    "suggested_next_step",
    "recommendation",
)

ROI_VALUES = frozenset({"conservative", "expected", "speculative"})

CANONICAL_RECOMMENDATIONS = frozenset({"promote", "incubate", "shelve", "reject"})

# Patterns that indicate malformed / fragment content (e.g. parser dump), not valid proposal text
MALFORMED_VALUE_PATTERN = re.compile(
    r"^\s*[\r\n]+\s*[\"']?(?:estimated_cost_range|time_to_build|roi_potential|required_roles|likely_dependencies|major_risks|strategic_alignment|suggested_next_step|recommendation)[\"']?\s*$",
    re.IGNORECASE,
)

# First-word (or phrase) synonyms -> canonical. Lowercase.
RECOMMENDATION_SYNONYMS: dict[str, str] = {
    "approve": "promote",
    "proceed": "promote",
    "advance": "promote",
    "explore": "incubate",
    "refine": "incubate",
    "refinement": "incubate",
    "develop": "incubate",
    "hold": "incubate",
    "park": "shelve",
    "defer": "shelve",
    "save": "shelve",
    "decline": "reject",
    "drop": "reject",
    "not": "reject",
}


def _extract_json_object(raw: str) -> str | None:
    """Strip markdown/code fences and leading/trailing junk; return first complete JSON object."""
    if not raw or not isinstance(raw, str):
        return None
    s = raw.strip()
    # Remove markdown code fences (optional language tag)
    if s.startswith("```"):
        s = re.sub(r"^```(?:json|JSON)?\s*", "", s)
        s = re.sub(r"\s*```\s*$", "", s)
        s = s.strip()
    # Find first { and then matching closing }
    start = s.find("{")
    if start < 0:
        return None
    depth = 0
    in_string = False
    escape = False
    quote = None
    for i in range(start, len(s)):
        c = s[i]
        if escape:
            escape = False
            continue
        if c == "\\" and in_string:
            escape = True
            continue
        if not in_string:
            if c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    return s[start : i + 1]
            elif c in ("'", '"'):
                in_string = True
                quote = c
        else:
            if c == quote:
                in_string = False
    return None


def _safe_string(val: Any) -> str:
    """Coerce to string and strip; never return None."""
    if val is None:
        return ""
    if isinstance(val, str):
        return val.strip()
    if isinstance(val, (int, float, bool)):
        return str(val).strip()
    return ""


def _build_contract(data: Any) -> dict[str, str] | None:
    """Build normalized contract dict from parsed data. Returns None if invalid."""
    if not isinstance(data, dict):
        return None
    out: dict[str, str] = {}
    for key in CONTRACT_KEYS:
        val = data.get(key)
        out[key] = _safe_string(val)
    roi = out.get("roi_potential", "").strip().lower()
    out["roi_potential"] = roi if roi in ROI_VALUES else "expected"
    out["recommendation"] = _normalize_recommendation(out.get("recommendation") or "")
    return out


def _validate_contract(out: dict[str, str]) -> bool:
    """Ensure every value is a string and none look like parser fragments."""
    if set(out.keys()) != set(CONTRACT_KEYS):
        return False
    for k, v in out.items():
        if not isinstance(v, str):
            return False
        if MALFORMED_VALUE_PATTERN.match(v):
            return False
    return True


def _normalize_recommendation(raw: str) -> str:
    """Resolve recommendation to one of Promote | Incubate | Shelve | Reject; preserve reason."""
    if not raw or not raw.strip():
        return "Incubate"
    s = raw.strip()
    # Split on first separator to get verb-like part and optional reason
    for sep in (" — ", " – ", ": ", " - "):
        if sep in s:
            verb_part, rest = s.split(sep, 1)
            verb_part = verb_part.strip()
            rest = rest.strip()
            break
    else:
        verb_part = s
        rest = ""
    if not verb_part:
        return "Incubate"
    low = verb_part.lower()
    words = low.split()
    first_word = words[0] if words else low
    # Exact canonical (whole verb part or first word)
    if low in CANONICAL_RECOMMENDATIONS:
        canonical = verb_part[0].upper() + verb_part[1:].lower()
    elif first_word in CANONICAL_RECOMMENDATIONS:
        canonical = first_word[0].upper() + first_word[1:]
    else:
        canonical_key = RECOMMENDATION_SYNONYMS.get(first_word)
        if canonical_key:
            canonical = canonical_key[0].upper() + canonical_key[1:]
        else:
            canonical = "Incubate"
    # Preserve reason: after separator, or remainder of verb_part if no separator (e.g. "Reject (out of scope)")
    if rest:
        return f"{canonical} — {rest}"
    if len(words) > 1 and first_word in (CANONICAL_RECOMMENDATIONS | set(RECOMMENDATION_SYNONYMS)):
        remainder = verb_part[len(words[0]):].strip()
        if remainder:
            return f"{canonical} — {remainder}"
    return canonical


CLEAN_ERROR_MESSAGE = "Evaluation failed — the AI could not generate a valid structured response."


def _idea_evaluate_should_capture_learning(
    *,
    use_execution_seam: bool,
    routing_context: dict | None,
    exec_meta: Mapping[str, Any] | None,
) -> bool:
    """Routed seam + OpenAI primary only; no capture on legacy Ollama-only paths."""
    if not use_execution_seam:
        return False
    if routing_context is None or not isinstance(routing_context, dict):
        return False
    prov = (exec_meta or {}).get("provider_used", "")
    if not isinstance(prov, str) or prov.strip().lower() != "openai":
        return False
    return True


def _attach_idea_evaluate_learning_record(
    result: dict[str, Any],
    *,
    capture: bool,
    last_prompt_sent: str,
    title: str,
    brief: str,
    fcore_block: str,
    routing_context: dict | None,
    exec_meta: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Tier-general learning row: one HTTP evaluation → one record (multi-attempt tolerant UX unchanged)."""
    if not capture:
        return result
    from local_ai.delegation.learning_capture import capture_general_delegation_outcome

    rc = routing_context or {}
    surface = str(rc.get("surface") or "vision_execution").strip() or "vision_execution"
    action_intent = str(rc.get("action_intent") or "idea_evaluate").strip() or "idea_evaluate"
    privacy_mode: str | None = None
    pm = rc.get("privacy_mode")
    if isinstance(pm, str) and pm.strip():
        privacy_mode = pm.strip()
    meta = dict(exec_meta or {})
    pu = meta.get("provider_used")
    mu = meta.get("model_used")
    input_snap = "\n\n".join(
        [
            f"title:{title}",
            f"brief:{brief}",
            fcore_block.strip() if fcore_block else "",
        ]
    )
    val_ok = "error" not in result
    verr = result.get("error") if not val_ok else None
    if val_ok:
        try:
            raw_out = json.dumps({k: result.get(k, "") for k in CONTRACT_KEYS}, ensure_ascii=False)
        except Exception:
            raw_out = json.dumps(result, ensure_ascii=False, default=str)
    else:
        raw_out = str(verr or "")

    rid = capture_general_delegation_outcome(
        surface=surface,
        action_intent=action_intent,
        privacy_mode=privacy_mode,
        provider_used=str(pu).strip() if pu else None,
        model_used=str(mu).strip() if mu else None,
        input_snapshot=input_snap,
        compiled_prompt=last_prompt_sent,
        validation_passed=val_ok,
        validation_error=(str(verr)[:500] if verr else None),
        raw_or_parsed_output=raw_out,
    )
    if rid:
        out = dict(result)
        out["learning_record_id"] = rid
        return out
    return result


def _run_evaluation(prompt: str, provider: Any) -> dict[str, str] | None:
    """Call provider, extract JSON, build and validate contract. Returns contract or None."""
    logger.info("%s strict: provider.generate start", DEBUG_PREFIX)
    try:
        raw = provider.generate(prompt, timeout=60)
    except Exception as e:
        logger.warning("%s strict: provider.generate exception: %s", DEBUG_PREFIX, e)
        return None
    if not raw or not isinstance(raw, str):
        logger.warning("%s strict: provider returned empty or non-string", DEBUG_PREFIX)
        return None
    raw = raw.strip()
    logger.info("%s strict: provider raw length=%s sample=%s", DEBUG_PREFIX, len(raw), (raw[:400] + "..." if len(raw) > 400 else raw))
    json_str = _extract_json_object(raw)
    if not json_str:
        logger.warning("%s strict: extract_json_object returned None", DEBUG_PREFIX)
        return None
    logger.info("%s strict: extract_json ok length=%s", DEBUG_PREFIX, len(json_str))
    try:
        data = json.loads(json_str)
    except json.JSONDecodeError as e:
        logger.warning("%s strict: json.loads failed: %s", DEBUG_PREFIX, e)
        return None
    logger.info("%s strict: json.loads ok", DEBUG_PREFIX)
    out = _build_contract(data)
    if out is None:
        logger.warning("%s strict: build_contract returned None", DEBUG_PREFIX)
        return None
    logger.info("%s strict: build_contract ok", DEBUG_PREFIX)
    if not _validate_contract(out):
        logger.warning("%s strict: validate_contract failed (keys=%s, malformed check)", DEBUG_PREFIX, list(out.keys()))
        return None
    logger.info("%s strict: validate_contract ok -> success", DEBUG_PREFIX)
    return out


def _sanitize_partial(out: dict[str, str]) -> dict[str, str]:
    """Replace any malformed fragment values with empty string. Does not relax parsing."""
    for key in list(out.keys()):
        if MALFORMED_VALUE_PATTERN.match(out.get(key) or ""):
            out[key] = ""
    return out


def _run_evaluation_relaxed(prompt: str, provider: Any) -> dict[str, str] | None:
    """Like _run_evaluation but returns partial contract: accept build output, sanitize fragments, return if any field non-empty."""
    logger.info("%s relaxed: provider.generate start", DEBUG_PREFIX)
    try:
        raw = provider.generate(prompt, timeout=60)
    except Exception as e:
        logger.warning("%s relaxed: provider.generate exception: %s", DEBUG_PREFIX, e)
        return None
    if not raw or not isinstance(raw, str):
        logger.warning("%s relaxed: provider returned empty or non-string", DEBUG_PREFIX)
        return None
    raw = raw.strip()
    logger.info("%s relaxed: provider raw length=%s sample=%s", DEBUG_PREFIX, len(raw), (raw[:400] + "..." if len(raw) > 400 else raw))
    json_str = _extract_json_object(raw)
    if not json_str:
        logger.warning("%s relaxed: extract_json_object returned None", DEBUG_PREFIX)
        return None
    try:
        data = json.loads(json_str)
    except json.JSONDecodeError as e:
        logger.warning("%s relaxed: json.loads failed: %s", DEBUG_PREFIX, e)
        return None
    out = _build_contract(data)
    if out is None:
        logger.warning("%s relaxed: build_contract returned None", DEBUG_PREFIX)
        return None
    out = _sanitize_partial(out)
    non_empty = sum(1 for k in CONTRACT_KEYS if out.get(k))
    if non_empty == 0:
        logger.warning("%s relaxed: no non-empty fields after sanitize", DEBUG_PREFIX)
        return None
    logger.info("%s relaxed: success with %s non-empty fields", DEBUG_PREFIX, non_empty)
    return out


def evaluate_idea(
    title: str,
    brief: str,
    core_profile_summary: str | None = None,
    relaxed: bool = False,
    user_id: str | None = None,
    *,
    use_execution_seam: bool = False,
    routing_context: dict | None = None,
    exec_meta: Optional[Mapping[str, Any]] = None,
) -> dict[str, Any]:
    """
    Single-pass LLM call for idea evaluation. Returns either:
    - A valid normalized response with CONTRACT_KEYS (no "error" key), or
    - Exactly {"error": "<message>"}.
    Never returns partial or malformed content.

    When ``use_execution_seam`` + ``routing_context`` + policy OpenAI: appends tier-general
    ``learning_record_id`` after the existing multi-attempt (strict / relaxed) flow.
    """
    title = (title or "").strip()
    brief = (brief or "").strip()
    brief_empty = not brief
    fcore = ""
    if core_profile_summary and core_profile_summary.strip():
        fcore = f"Core Profile Context:\n{core_profile_summary.strip()}\n"

    logger.info(
        "%s evaluate_idea called title=%r title_len=%s brief_len=%s brief_empty=%s relaxed=%s",
        DEBUG_PREFIX, title, len(title), len(brief), brief_empty, relaxed,
    )
    if brief_empty:
        logger.warning("%s idea has almost no useful brief/description — evaluation may be generic or fail", DEBUG_PREFIX)

    capture_learning = _idea_evaluate_should_capture_learning(
        use_execution_seam=use_execution_seam,
        routing_context=routing_context,
        exec_meta=exec_meta,
    )

    try:
        from local_ai.llm.execution_principal import execution_principal_from_legacy_user_id
        from local_ai.vision_execution.llm_seam import ve_eval_provider_shim

        provider = ve_eval_provider_shim(
            execution_principal_from_legacy_user_id(user_id),
            use_execution_seam=use_execution_seam,
        )
    except Exception as e:
        logger.warning("%s provider not available: %s", DEBUG_PREFIX, e)
        return {"error": f"Provider not available: {e!s}"}

    prompt = IDEA_EVALUATE_PROMPT.format(title=title, brief=brief, fcore=fcore)
    last_prompt_sent = prompt
    out = _run_evaluation(prompt, provider)
    if out is not None:
        logger.info("%s strict attempt 1 result=success returning contract", DEBUG_PREFIX)
        return _attach_idea_evaluate_learning_record(
            out,
            capture=capture_learning,
            last_prompt_sent=last_prompt_sent,
            title=title,
            brief=brief,
            fcore_block=fcore,
            routing_context=routing_context,
            exec_meta=exec_meta,
        )
    logger.info("%s strict attempt 1 result=fail", DEBUG_PREFIX)

    retry_prompt = prompt + IDEA_EVALUATE_RETRY_SUFFIX
    last_prompt_sent = retry_prompt
    out = _run_evaluation(retry_prompt, provider)
    if out is not None:
        logger.info("%s strict attempt 2 (retry) result=success returning contract", DEBUG_PREFIX)
        return _attach_idea_evaluate_learning_record(
            out,
            capture=capture_learning,
            last_prompt_sent=last_prompt_sent,
            title=title,
            brief=brief,
            fcore_block=fcore,
            routing_context=routing_context,
            exec_meta=exec_meta,
        )
    logger.info("%s strict attempt 2 result=fail", DEBUG_PREFIX)

    if relaxed:
        last_prompt_sent = prompt
        out = _run_evaluation_relaxed(prompt, provider)
        if out is not None:
            logger.info("%s relaxed attempt 1 result=success returning partial contract", DEBUG_PREFIX)
            return _attach_idea_evaluate_learning_record(
                out,
                capture=capture_learning,
                last_prompt_sent=last_prompt_sent,
                title=title,
                brief=brief,
                fcore_block=fcore,
                routing_context=routing_context,
                exec_meta=exec_meta,
            )
        logger.info("%s relaxed attempt 1 result=fail", DEBUG_PREFIX)
        last_prompt_sent = retry_prompt
        out = _run_evaluation_relaxed(retry_prompt, provider)
        if out is not None:
            logger.info("%s relaxed attempt 2 result=success returning partial contract", DEBUG_PREFIX)
            return _attach_idea_evaluate_learning_record(
                out,
                capture=capture_learning,
                last_prompt_sent=last_prompt_sent,
                title=title,
                brief=brief,
                fcore_block=fcore,
                routing_context=routing_context,
                exec_meta=exec_meta,
            )
        logger.info("%s relaxed attempt 2 result=fail", DEBUG_PREFIX)
    else:
        logger.info("%s relaxed fallback not attempted (relaxed=False)", DEBUG_PREFIX)

    logger.warning("%s final: returning error (no contract)", DEBUG_PREFIX)
    err_result: dict[str, Any] = {"error": CLEAN_ERROR_MESSAGE}
    return _attach_idea_evaluate_learning_record(
        err_result,
        capture=capture_learning,
        last_prompt_sent=last_prompt_sent,
        title=title,
        brief=brief,
        fcore_block=fcore,
        routing_context=routing_context,
        exec_meta=exec_meta,
    )
