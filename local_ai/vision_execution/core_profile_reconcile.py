"""

Core Profile reconcile — propose structured profile updates from conversation + training inputs.

Conversation is weighted highest; training inputs may mix digest (scaffold) and raw source (lowest).
Does not persist; returns proposed dict for UI review/apply. See docs/02_ACTIVE_DESIGN/CORE_PROFILE_ARCHITECTURE.md.

"""

import json

import logging

import re

from typing import Any, Mapping, Optional

from local_ai.llm.execution_principal import execution_principal_from_legacy_user_id


logger = logging.getLogger(__name__)


_PROFILE_RAW_NOTES_COMPRESS_CAP = 8000


CORE_PROFILE_FINAL_OVERRIDE = """FINAL OVERRIDE:

The user's most recent statements are the highest authority.

If any training inputs (digest or raw source) conflict with the user's statements, ignore the training inputs.

When the user contradicts the source material, the user is correct.

Always resolve conflicts in favor of the user's explicit or implicit intent as expressed in the conversation."""


def lightly_compress_notes(text: str) -> str:
    if not text:
        return text
    if len(text) <= _PROFILE_RAW_NOTES_COMPRESS_CAP:
        return text
    return text[:_PROFILE_RAW_NOTES_COMPRESS_CAP]


def profile_training_notes_for_prompt(
    raw_notes: str | None,
    conversation_turns: list[dict[str, str]] | None,
) -> str:
    notes = (raw_notes or "").strip()
    turns = conversation_turns or []
    if not turns or len(turns) == 0:
        return notes
    original_len = len(notes)
    compressed = lightly_compress_notes(notes)
    if len(compressed) < original_len:
        logger.debug(
            "profile_notes_compressed original_len=%s new_len=%s",
            original_len,
            len(compressed),
        )
    return compressed


# Keys that must be present in the structured profile (same as API/UI).

STRUCTURED_KEYS = (

    "name",

    "core_definition",

    "current_goals",

    "growth_focus_12_months",

    "economic_engine",

    "non_negotiables",

    "strategic_filter",

    "current_constraints",

    "capacity_limit",

    "kill_philosophy",

    "strength_positioning",

)





def _extract_json_object(raw: str) -> str | None:

    """Return first complete JSON object from raw text (strip markdown etc.)."""

    if not raw or not isinstance(raw, str):

        return None

    s = raw.strip()

    if s.startswith("```"):

        s = re.sub(r"^```(?:json|JSON)?\s*", "", s)

        s = re.sub(r"\s*```\s*$", "", s)

        s = s.strip()

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





def _build_conversation_text(turns: list[dict[str, str]]) -> str:

    if not turns:

        return ""

    lines = []

    for t in turns:

        role = (t.get("role") or "user").strip().lower()

        content = (t.get("content") or "").strip()

        if not content:

            continue

        label = "User" if role == "user" else "Assistant"

        lines.append(f"{label}: {content}")

    return "\n\n".join(lines) if lines else ""





RECONCILE_PROMPT = (
    """You are helping update a strategic "core profile" by synthesizing training evidence (reconcile = synthesis).

Conceptual model: source material in training inputs is stimulus; any profile-oriented digest there is scaffold; the conversation is the signal; your output is an updated structured proposal.

EVIDENCE HIERARCHY — apply strictly when signals conflict (higher overrides lower):
1. PRIMARY — Conversation below: the user's turns, corrections, emphases, agreement, rejection, reinterpretation, priorities, and the language they use while engaging material. This is the main evidence for who they are and what the profile should reflect.
2. SECONDARY — Profile-oriented digest inside training inputs (if present: themes, values, quotes, etc.): use only to structure or organize context. Never let a digest line override an explicit user statement in the conversation.
3. TERTIARY — Raw source text in training inputs (long excerpts, transcripts, pasted documents): background only; lowest priority.
4. REFERENCE — Current structured profile: baseline; change where conversation or clearly consistent training inputs imply it; keep fields where the user has not moved intent.

When there is any contradiction between the conversation and the training inputs, the conversation is correct and must override the training inputs.

Recent conversation (PRIMARY — weigh highest):

---

{conversation}

---

Current structured profile (REFERENCE):

{current_block}

Training inputs (may contain digest + raw source — SECONDARY / TERTIARY only):

---

{notes}

---

"""
    + CORE_PROFILE_FINAL_OVERRIDE
    + """

Propose an updated structured profile that follows the hierarchy above. Keep or refine existing values where they still fit; change them where the user's intent in the conversation (or consistent secondary context) implies it. Output only valid JSON with exactly these keys (use empty string for any you leave unchanged or cannot infer): name, core_definition, current_goals, growth_focus_12_months, economic_engine, non_negotiables, strategic_filter, current_constraints, capacity_limit, kill_philosophy, strength_positioning.

Respond with only the JSON object. No markdown, no code fences, no preamble."""
)





def reconcile(

    raw_notes: str,

    conversation_turns: list[dict[str, str]],

    current_structured: dict[str, str],

    *,

    routing_context: dict | None = None,

    use_execution_seam: bool = False,

    exec_meta: Optional[Mapping[str, Any]] = None,

    profile_id: Optional[str] = None,

    user_id: Optional[str] = None,

) -> dict[str, Any]:

    """

    Propose updated structured profile from notes + conversation. Returns either

    ``{"proposed": {key: str, ...}}`` or ``{"error": str}``. Does not write to DB.



    When ``routing_context`` is set without ``use_execution_seam``, runs

    ``core_profile_execution_blocked`` (legacy). When ``use_execution_seam`` is true, the HTTP

    layer has already applied execution routing; the blocked check is skipped here.



    Compiled delegation (strict JSON) runs only when: ``use_execution_seam``, routing present,

    ``provider_used == openai``, and ``action_intent == core_profile_reconcile``.

    """

    from local_ai.vision_execution.core_profile_execution import (

        INTENT_RECONCILE,

        core_profile_execution_blocked,

    )



    if not use_execution_seam:

        blocked = core_profile_execution_blocked(

            action_intent=INTENT_RECONCILE,

            routing_context=routing_context,

        )

        if blocked:

            return {"error": blocked, "execution_blocked": True}



    notes = profile_training_notes_for_prompt(raw_notes, conversation_turns or [])

    conversation = _build_conversation_text(conversation_turns or [])

    current = current_structured or {}

    current_block = "\n".join(f"- {k}: {current.get(k, '')}" for k in STRUCTURED_KEYS)



    prov = (exec_meta or {}).get("provider_used", "")

    prov_l = prov.strip().lower() if isinstance(prov, str) else ""

    intent_raw = (routing_context or {}).get("action_intent") if routing_context else None

    intent = intent_raw.strip() if isinstance(intent_raw, str) else ""

    structured_branch = (

        use_execution_seam

        and routing_context is not None

        and prov_l == "openai"

        and intent == INTENT_RECONCILE

    )

    if structured_branch:

        from local_ai.delegation.core_profile_reconcile import (

            build_core_profile_reconcile_contract,

            execute_structured_openai_core_profile_reconcile_delegation,

        )



        try:

            from local_ai.vision_execution.llm_seam import ve_eval_provider_shim



            provider = ve_eval_provider_shim(
                execution_principal_from_legacy_user_id(user_id),
                use_execution_seam=True,
            )

        except Exception as e:

            return {"error": f"Provider not available: {e!s}"}



        contract = build_core_profile_reconcile_contract(

            current_structured=current,

            raw_notes=notes,

            conversation_turns=conversation_turns or [],

        )

        privacy_mode: str | None = None

        if routing_context is not None:

            pm = routing_context.get("privacy_mode")

            if isinstance(pm, str) and pm.strip():

                privacy_mode = pm.strip()

        pid = (profile_id or "").strip() or None

        uid = (user_id or "").strip() or None

        return execute_structured_openai_core_profile_reconcile_delegation(

            contract=contract,

            provider=provider,

            routing_payload=routing_context,

            exec_meta=dict(exec_meta or {}),

            profile_id=pid,

            user_id_for_externalize=uid,

            privacy_mode=privacy_mode,

            current_structured=current,

        )



    prompt = RECONCILE_PROMPT.format(

        current_block=current_block,

        notes=notes or "(none)",

        conversation=conversation or "(none)",

    )



    try:

        if use_execution_seam:

            from local_ai.vision_execution.llm_seam import ve_eval_provider_shim



            provider = ve_eval_provider_shim(
                execution_principal_from_legacy_user_id(user_id),
                use_execution_seam=True,
            )

        else:

            from local_ai.llm.resolver import get_provider_shim_for_legacy_generate

            provider = get_provider_shim_for_legacy_generate(execution_principal_from_legacy_user_id(user_id))

    except Exception as e:

        logger.warning("core_profile_reconcile: provider not available: %s", e)

        return {"error": f"Provider not available: {e!s}"}



    try:

        raw = provider.generate(prompt, timeout=90)

    except Exception as e:

        logger.warning("core_profile_reconcile: generate failed: %s", e)

        return {"error": f"Generation failed: {e!s}"}



    if not raw or not isinstance(raw, str):

        return {"error": "No response from provider"}



    json_str = _extract_json_object(raw.strip())

    if not json_str:

        logger.warning("core_profile_reconcile: no JSON object in response (len=%s)", len(raw))

        return {"error": "Could not extract structured proposal from response"}



    try:

        data = json.loads(json_str)

    except json.JSONDecodeError as e:

        logger.warning("core_profile_reconcile: json.loads failed: %s", e)

        return {"error": f"Invalid JSON: {e!s}"}



    if not isinstance(data, dict):

        return {"error": "Proposal must be a JSON object"}



    proposed = {}

    for key in STRUCTURED_KEYS:

        val = data.get(key)

        proposed[key] = (val.strip() if isinstance(val, str) else (str(val).strip() if val is not None else "")) or current.get(key, "")



    return {"proposed": proposed}


