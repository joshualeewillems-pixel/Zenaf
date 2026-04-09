"""
Core Profile conversation — reflection assistant for profile clarification.

Scope (current, no persistent memory):
- Reflect recurring themes/tensions from raw notes + recent turns.
- Detect recurring loops using only the last 5–10 user turns (temporary simulation).
- Return exactly one assistant reply; does NOT write to storage or call Perspectives.

Future direction (NOT implemented here):
- Persistent pattern tracking across sessions and "returning insights" when patterns repeat over time.
- Integration with the Perspectives system for multi-lens interpretation.
"""
from __future__ import annotations

import logging
from typing import Any, Mapping, Optional

from local_ai.llm.execution_principal import execution_principal_from_legacy_user_id
from local_ai.vision_execution.core_profile_reconcile import (
    CORE_PROFILE_FINAL_OVERRIDE,
    profile_training_notes_for_prompt,
)

logger = logging.getLogger(__name__)


def _zenaf_voice_preamble() -> str:
  """Bias training replies toward the Zenaf (synthesis) seat — developmental, integrative, life-coach orientation."""
  from local_ai.zenaf_tools import _built_in_persona_dict

  z = _built_in_persona_dict("zenaf")
  purpose = str(z.get("purpose") or "").strip()
  tone = str(z.get("tone") or "").strip()
  decision_rule = str(z.get("decisionRule") or "").strip()
  worldview = str(z.get("worldview") or "").strip()
  return (
    "VOICE AND STANCE (Zenaf — synthesis seat):\n"
    f"- Purpose: {purpose}\n"
    f"- Tone: {tone}\n"
    f"- Decision rule: {decision_rule}\n"
    f"- Worldview: {worldview}\n"
    "Honor every OUTPUT SHAPE and HARD CONSTRAINT below; Zenaf only colors how you show up.\n\n"
  )


def _build_conversation_text(turns: list[dict[str, str]]) -> str:
  lines: list[str] = []
  for t in turns or []:
    role = (t.get("role") or "user").strip().lower()
    content = (t.get("content") or "").strip()
    if not content:
      continue
    label = "User" if role == "user" else "Assistant"
    lines.append(f"{label}: {content}")
  return "\n\n".join(lines) if lines else ""


def _build_structured_block(structured: dict[str, Any]) -> str:
  if not structured:
    return "(none)"
  keys = [
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
  ]
  lines = []
  for k in keys:
    v = structured.get(k)
    s = v.strip() if isinstance(v, str) else (str(v).strip() if v is not None else "")
    lines.append(f"- {k}: {s}")
  return "\n".join(lines)


CONVERSATION_PROMPT = (
    """You are a Core Profile reflection assistant. You behave like a high-quality thinking partner: you identify the core tension, compress insight, challenge assumptions, and avoid expanding or decorating the user's idea.

TRAINING CONTEXT HIERARCHY (internal — do not recite this list to the user):
- The user's messages in the thread below are the PRIMARY signal: what they notice, agree or reject, correct, emphasize, reinterpret, and prioritize, including the language they naturally use while engaging material.
- Training inputs may include a distilled digest (scaffold: themes, values, quotes) and/or long raw source (stimulus). Use those only as background to understand what they are reacting to; they must not outweigh the live conversation.
- If the user contradicts or corrects something suggested by notes or digest, always follow the user.
- When there is any contradiction between the conversation and the training inputs, the conversation is correct and must override the training inputs.

TARGET RESPONSE STYLE (match this shape and density):

The user is stacking multiple elements (tools, rituals, structure, symbolism) without a clear primary experience.

The issue is not lack of ideas, but lack of a single dominant center.

The tension: trying to make something simultaneously sacred, practical, and scientifically credible without clearly establishing which one governs the reader's trust.

Instead of adding more, the question becomes: what is the one thing the reader should anchor into? All additions should be evaluated against whether they reinforce that, or dilute it.

---

OUTPUT SHAPE (strict):
- 1–3 short paragraphs only.
- No bullet lists. No numbered lists. No "first / second / third". No "here are three things".
- No "additional ideas" section. No multiple suggestions. One thread only.

PATTERN EXTRACTION (internal reasoning only — do NOT print this as JSON or lists):
- From the latest user turn and recent conversation, infer themes (e.g. freedom, money pressure, meaning, instability), tensions (e.g. freedom vs income, depth vs execution), emotional tone (e.g. urgency, frustration, avoidance), and signals of stuckness (repetition, circling the same tradeoff, deflection).
- Look across the last few user turns: notice repeated tensions, recurring themes, and unresolved loops.

RESPONSE DECISION (choose ONE mode before you write your reply):
- NEW INSIGHT: when a pattern is emerging or being explored for the first time, respond with one clear insight or one sharp question about that pattern.
- REPEATED / STUCK: when the same tension appears again and again, name the loop directly (e.g. "you've circled this tradeoff three times — freedom vs stability; you're not resolving it, just rephrasing it") and stop. Do not add new ideas.
- LOW READINESS: when the user is scattered, deflecting, or not really engaging, keep your response minimal and light — one short reflection or one simple clarifying question.
- HIGH READINESS: when the user is clearly engaging deeply, deliver a sharper, more direct statement of the core tension.

RETURNING INSIGHT + ESCALATION (simulate pattern-aware reflection using only recent turns; no long-term memory):
- Treat the last 5–10 user turns as your entire "working memory."
- If the same underlying tension keeps reappearing, escalate your response level instead of repeating yourself.
  LEVEL 1 — Exploration: first appearance; light, curious; one insight or one sharp question.
  LEVEL 2 — Recognition: pattern repeats; name it clearly; invite confirmation with one focused question.
  LEVEL 3 — Loop: pattern repeats again; compress; no new ideas; highlight that it's looping.
  LEVEL 4 — Avoidance: repeated looping + avoidance/deflection; name the avoidance gently; no moralizing.
  LEVEL 5 — Confrontation (rare): strong repetition + clear avoidance; one sharp, concise statement; no softening, no aggression.

ADAPTIVE TONE (do not use a fixed personality; evolve tone gradually across turns):
- Baseline tone is grounded, reflective, and non-threatening.
- Adjust directness based on user signals in recent turns:
  - If the user engages with challenge (accepts a tension, answers the question, names a cost), increase directness slightly.
  - If the user deflects, disengages, or becomes raw/uncertain, reduce pressure and return to softer tone.
  - If the same pattern repeats and the user keeps engaging, escalate clarity (not volume).
  - If the user is analytical/assertive, you may be sharper and more strategic. If the user is vulnerable/uncertain, stay gentler.
- Never label the mode. Never announce you are being more direct. No abrupt shifts. Tone should feel like a gradual adjustment.

HARD CONSTRAINTS — you must NOT:
- Generate lists of suggestions or improvements.
- Give generic praise ("this is interesting", "you've raised good points").
- Summarize without new insight.
- Attempt to improve the content by adding features or ideas.
- Say "you could also…", "another idea is…", "you might consider…", or similar.

CREATIVE INPUT (when the user shares writing, ideas, or a project):
- Do NOT expand it. Do NOT add new features or possibilities.
- Instead: identify what is structurally unclear, conflicted, or diluted. Name the tension. Name what is missing at the center.

DECISION RULE (apply before writing):
Ask yourself: "What is the single most important thing the user is not seeing?"
Then respond only with that. Nothing else.

TONE: precise, grounded, slightly challenging. Not adversarial. Not overly polite.

Recent conversation (PRIMARY — ground your reply in this thread above training text):
---
{conversation_block}
---

Current structured profile (for context only; do not rewrite it):
{structured_block}

Training inputs (digest and/or raw source — subordinate to conversation above):
---
{raw_notes}
---

Tone guidance (internal; do not mention this line explicitly): {tone_guidance}

{calibration_block}{aspiration_block}
"""
    + CORE_PROFILE_FINAL_OVERRIDE
    + """

Respond in 1–3 short paragraphs. No lists. No additional ideas. No preamble."""
)


def _extract_themes(text: str) -> set[str]:
  s = (text or "").lower()
  themes = set()
  theme_keywords = {
    "freedom": ["freedom", "autonomy", "independence"],
    "stability": ["stability", "security", "steady", "predictable", "safe"],
    "money": ["money", "income", "revenue", "cash", "profit", "pay", "salary"],
    "meaning": ["meaning", "purpose", "impact", "fulfillment", "values"],
    "execution": ["execute", "execution", "ship", "deliver", "finish", "done"],
    "depth": ["depth", "craft", "quality", "rigor", "mastery"],
    "pressure": ["pressure", "urgent", "deadline", "stress", "overwhelmed"],
    "avoidance": ["avoid", "procrast", "stuck", "can't", "spin", "circular"],
    "control": ["control", "certainty", "plan", "structure", "system"],
  }
  for theme, kws in theme_keywords.items():
    if any(k in s for k in kws):
      themes.add(theme)
  return themes


def _extract_tensions(themes: set[str]) -> set[str]:
  tensions = set()
  # Minimal canonical tensions; expanded later with real model-driven extraction.
  if "freedom" in themes and ("stability" in themes or "money" in themes):
    tensions.add("freedom_vs_stability")
  if "depth" in themes and "execution" in themes:
    tensions.add("depth_vs_execution")
  if "meaning" in themes and ("money" in themes or "stability" in themes):
    tensions.add("meaning_vs_money")
  return tensions


def _last_user_messages(turns: list[dict[str, str]], limit: int = 10) -> list[str]:
  msgs = []
  for t in turns or []:
    if (t.get("role") or "").strip().lower() != "user":
      continue
    content = (t.get("content") or "").strip()
    if content:
      msgs.append(content)
  return msgs[-limit:]


def _detect_recurring_loop(conversation_turns: list[dict[str, str]]) -> tuple[str | None, str | None]:
  """
  Heuristic loop detection (temporary simulation).
  Returns (loop_label, loop_phrase) if a tension/theme repeats across recent user turns.
  """
  recent = _last_user_messages(conversation_turns, limit=10)
  if len(recent) < 3:
    return (None, None)
  current = recent[-1]
  current_themes = _extract_themes(current)
  current_tensions = _extract_tensions(current_themes)
  # Count how often current tensions/themes appear in prior turns.
  tension_counts: dict[str, int] = {t: 0 for t in current_tensions}
  theme_counts: dict[str, int] = {th: 0 for th in current_themes}
  for prev in recent[:-1]:
    ths = _extract_themes(prev)
    tens = _extract_tensions(ths)
    for t in tension_counts.keys():
      if t in tens:
        tension_counts[t] += 1
    for th in theme_counts.keys():
      if th in ths:
        theme_counts[th] += 1

  # Prefer tensions; if none, fall back to single strong theme repetition.
  best_tension = None
  best_tension_count = 0
  for t, c in tension_counts.items():
    if c > best_tension_count:
      best_tension = t
      best_tension_count = c
  if best_tension and best_tension_count >= 2:
    phrase = {
      "freedom_vs_stability": "freedom vs stability",
      "depth_vs_execution": "depth vs execution",
      "meaning_vs_money": "meaning vs money",
    }.get(best_tension, best_tension.replace("_", " "))
    return ("tension", phrase)

  best_theme = None
  best_theme_count = 0
  for th, c in theme_counts.items():
    if c > best_theme_count:
      best_theme = th
      best_theme_count = c
  if best_theme and best_theme_count >= 3:
    return ("theme", best_theme)
  return (None, None)


def _avoidance_score(text: str) -> int:
  """Heuristic: higher means more deflection/avoidance language."""
  s = (text or "").lower()
  cues = [
    "not sure", "i don't know", "idk", "maybe", "kind of", "sort of",
    "but", "however", "can't", "stuck", "circular", "spin",
    "later", "someday", "eventually", "should", "wish",
  ]
  return sum(1 for c in cues if c in s)


def _engagement_score(text: str) -> int:
  """Heuristic: higher means action/commitment language."""
  s = (text or "").lower()
  cues = [
    "i will", "i'm going to", "i choose", "decide", "commit", "pick",
    "the tradeoff", "the cost", "i'm willing", "i'm not willing",
    "here's what i want", "here's what i don't want",
  ]
  return sum(1 for c in cues if c in s)


def _receptivity_score(text: str) -> int:
  """Heuristic: higher means user is receptive to challenge/insight."""
  s = (text or "").lower()
  cues = [
    "you're right", "you are right", "fair", "true", "exactly", "spot on",
    "i see", "that makes sense", "i hadn't", "good point", "yes", "okay",
    "i agree", "that's it", "that's the point",
  ]
  return sum(1 for c in cues if c in s)


def _rawness_score(text: str) -> int:
  """Heuristic: higher means user is emotionally raw/uncertain; reduce pressure."""
  s = (text or "").lower()
  cues = [
    "i feel", "scared", "anxious", "overwhelmed", "confused", "lost", "sad",
    "ashamed", "guilty", "fragile", "uncertain", "i don't know",
  ]
  return sum(1 for c in cues if c in s)


def _analytical_score(text: str) -> int:
  """Heuristic: higher means user is analytical/assertive; allow sharper tone."""
  s = (text or "").lower()
  cues = [
    "tradeoff", "constraint", "objective", "therefore", "hypothesis", "model",
    "optimize", "metrics", "data", "analysis", "decision", "i choose", "i will",
  ]
  return sum(1 for c in cues if c in s)


def _infer_tone_guidance(conversation_turns: list[dict[str, str]]) -> tuple[int, str]:
  """
  Infer a soft->sharp directness level using only recent user turns.
  Returns (directness_level 1..5, guidance_text).
  """
  recent = _last_user_messages(conversation_turns, limit=6)
  if not recent:
    return (1, "Default to gentle, reflective tone.")
  # Aggregate signals; weight most recent more.
  total_engage = 0
  total_avoid = 0
  total_receptive = 0
  total_raw = 0
  total_analytic = 0
  for i, msg in enumerate(recent):
    w = 1 + (i / max(1, (len(recent) - 1)))  # 1..2 weight
    total_engage += int(_engagement_score(msg) * w)
    total_avoid += int(_avoidance_score(msg) * w)
    total_receptive += int(_receptivity_score(msg) * w)
    total_raw += int(_rawness_score(msg) * w)
    total_analytic += int(_analytical_score(msg) * w)

  # Base level: gentle.
  level = 2
  # Increase directness when receptive/engaged and not raw.
  if (total_engage + total_receptive) > (total_avoid) and total_raw == 0:
    level = 3
  if (total_engage + total_receptive) >= (total_avoid + 3) and total_raw == 0:
    level = 4
  if (total_engage + total_receptive) >= (total_avoid + 6) and total_raw == 0 and total_analytic >= 2:
    level = 5
  # If raw/uncertain dominates, soften.
  if total_raw >= 2 and total_engage <= 1:
    level = 1
  elif total_raw >= 2:
    level = min(level, 2)

  if level <= 2:
    guidance = "Stay gentle, reflective, and non-threatening. Ask at most one clarifying question; avoid confrontation."
  elif level == 3:
    guidance = "Be direct but calm. Name the tension clearly; one sharp question is allowed."
  elif level == 4:
    guidance = "Be more strategic and precise. Compress the insight; avoid softening language while staying non-accusatory."
  else:
    guidance = "Sharp mode allowed: concise, cutting to the issue, no sarcasm or aggression. Do not over-explain."
  return (level, guidance)


def _detect_loop_info(conversation_turns: list[dict[str, str]]) -> tuple[str | None, str | None, int]:
  """
  Temporary simulation of pattern tracking using only recent turns.
  Returns (loop_kind, loop_phrase, repeat_count_in_window).
  """
  recent = _last_user_messages(conversation_turns, limit=10)
  if not recent:
    return (None, None, 0)
  current = recent[-1]
  current_themes = _extract_themes(current)
  current_tensions = _extract_tensions(current_themes)

  tension_counts: dict[str, int] = {t: 0 for t in current_tensions}
  theme_counts: dict[str, int] = {th: 0 for th in current_themes}
  for msg in recent:
    ths = _extract_themes(msg)
    tens = _extract_tensions(ths)
    for t in tension_counts.keys():
      if t in tens:
        tension_counts[t] += 1
    for th in theme_counts.keys():
      if th in ths:
        theme_counts[th] += 1

  best_tension = None
  best_tension_count = 0
  for t, c in tension_counts.items():
    if c > best_tension_count:
      best_tension = t
      best_tension_count = c
  if best_tension and best_tension_count >= 2:
    phrase = {
      "freedom_vs_stability": "freedom vs stability",
      "depth_vs_execution": "depth vs execution",
      "meaning_vs_money": "meaning vs money",
    }.get(best_tension, best_tension.replace("_", " "))
    return ("tension", phrase, best_tension_count)

  best_theme = None
  best_theme_count = 0
  for th, c in theme_counts.items():
    if c > best_theme_count:
      best_theme = th
      best_theme_count = c
  if best_theme and best_theme_count >= 3:
    return ("theme", best_theme, best_theme_count)

  return (None, None, 1)


def _returning_insight(level: int, tone_level: int, loop_kind: str, loop_phrase: str) -> str:
  # Calm, precise, observational. No lists. One question max.
  gentle = tone_level <= 2
  sharp = tone_level >= 4
  # Level 2: recognition
  if level <= 2:
    if gentle:
      base = f"I’m noticing the same pattern returning — {loop_phrase}." if loop_kind == "tension" else f"This keeps returning: {loop_phrase}."
      q = "Is that the real center of the problem right now, or is it standing in for something else?"
    else:
      base = f"You’ve brought back the same pattern — {loop_phrase}." if loop_kind == "tension" else f"This keeps returning: {loop_phrase}."
      q = "Is that the real center of the problem, or a proxy?"
    return base + "\n\n" + q
  # Level 3: loop/stuckness
  if level == 3:
    base = f"You’ve circled this again — {loop_phrase}. You’re not resolving it; you’re rephrasing it." if sharp else f"You’re circling {loop_phrase} again. It isn’t moving yet; it’s looping."
    q = "What would you have to give up to stop circling it?"
    return base + "\n\n" + q
  # Level 4: avoidance
  if level == 4:
    base = f"Same loop — {loop_phrase} — and you keep staying on the perimeter instead of choosing a cost." if sharp else f"Same loop — {loop_phrase} — and you keep avoiding the part where you choose a cost."
    q = "What cost are you avoiding naming out loud?"
    return base + "\n\n" + q
  # Level 5: confrontation (rare)
  base = f"This isn’t confusion — it’s avoidance. You keep returning to {loop_phrase} to postpone choosing what you’re willing to sacrifice." if sharp else f"You keep returning to {loop_phrase} to postpone choosing what you’ll sacrifice."
  q = "What are you protecting by not deciding?"
  return base + "\n\n" + q


def converse(
  raw_notes: str,
  conversation_turns: list[dict[str, str]],
  current_structured: dict[str, Any] | None = None,
  *,
  routing_context: dict | None = None,
  use_execution_seam: bool = False,
  exec_meta: Optional[Mapping[str, Any]] = None,
  user_id: str | None = None,
) -> dict[str, Any]:
  """
  Return {"reply": str} or {"error": str}. No persistence, no Perspectives wiring.

  Optional ``routing_context`` enables execution policy / privacy_mode before **LLM** calls only.
  Omitted => legacy permissive gate. Heuristic loop replies (no provider) bypass execution policy.

  When ``use_execution_seam`` is True (Vision Execution + ``routing_context``), the LLM path uses
  ``run_general_delegation_custom_prompt`` (tier 1) + policy-driven provider shim; response may
  include ``learning_record_id`` for correlating later ``user_outcome``.
  """
  notes = profile_training_notes_for_prompt(raw_notes, conversation_turns or [])
  turns = conversation_turns or []
  tone_level, tone_guidance = _infer_tone_guidance(turns)
  loop_kind, loop_phrase, repeat_count = _detect_loop_info(turns)
  if loop_kind and loop_phrase and repeat_count >= 2:
    recent_user = _last_user_messages(turns, limit=3)
    last_text = recent_user[-1] if recent_user else ""
    avoid = _avoidance_score(last_text)
    engage = _engagement_score(last_text)
    # Escalation levels: default low; increase with repetition and avoidance.
    level = 2 if repeat_count == 2 else 3
    if repeat_count >= 4:
      level = 4
    if repeat_count >= 5 and avoid >= 2 and engage == 0:
      level = 5
    return {"reply": _enforce_response_shape(_returning_insight(level, tone_level, loop_kind, loop_phrase))}

  from local_ai.vision_execution.core_profile_execution import (
    INTENT_CONVERSATION,
    core_profile_execution_blocked,
  )

  blocked = core_profile_execution_blocked(
    action_intent=INTENT_CONVERSATION,
    routing_context=routing_context,
  )
  if blocked:
    return {"error": blocked, "execution_blocked": True}

  conv_block = _build_conversation_text(conversation_turns or [])
  structured_block = _build_structured_block(current_structured or {})

  calibration_block = ""
  uid_conv = (user_id or "").strip() if user_id else ""
  if uid_conv:
    from local_ai.vision_execution.storage import get_resonance_pattern

    pat = get_resonance_pattern(uid_conv, limit=200)
    esc = pat.get("escalation_signal") if isinstance(pat, dict) else None
    tr = int(pat.get("total_ratings") or 0) if isinstance(pat, dict) else 0
    if (
      isinstance(esc, dict)
      and float(esc.get("confidence") or 0) > 0.4
      and tr >= 5
    ):
      cf = float(esc.get("confidence") or 0)
      approach = str(esc.get("recommended_approach") or "exploration").strip()
      basis = str(esc.get("basis") or "").strip() or "(observed response patterns)"
      calibration_block = (
        "DEVELOPMENTAL CONTEXT (from observed response patterns):\n"
        f"Current interaction level: {approach}\n"
        f"Basis: {basis}\n"
        f"Confidence: {cf:.0%}\n\n"
        "Calibrate your response style to this level. Do not announce or label the level.\n"
        "Do not escalate beyond what the confidence warrants.\n"
        "If confidence is below 0.6, lean toward the softer adjacent level.\n"
      )

  aspiration_block = ""
  if uid_conv:
    from local_ai.aspiration_layer import maybe_core_profile_aspiration_block

    aspiration_block = maybe_core_profile_aspiration_block(uid_conv) or ""

  prompt = _zenaf_voice_preamble() + CONVERSATION_PROMPT.format(
    structured_block=structured_block,
    raw_notes=notes or "(none yet — the user has not written notes)",
    conversation_block=conv_block or "(no prior conversation; you are starting it)",
    tone_guidance=tone_guidance,
    calibration_block=calibration_block,
    aspiration_block=aspiration_block,
  )

  input_snapshot = "\n\n".join(
    [
      structured_block,
      notes or "",
      conv_block or "",
    ]
  )

  privacy_mode: str | None = None
  if routing_context is not None:
    pm = routing_context.get("privacy_mode")
    if isinstance(pm, str) and pm.strip():
      privacy_mode = pm.strip()

  meta = dict(exec_meta or {})
  surface = str((routing_context or {}).get("surface") or "core_profile")
  action_intent = str((routing_context or {}).get("action_intent") or INTENT_CONVERSATION)

  if use_execution_seam:
    from local_ai.delegation.general_lane import run_general_delegation_custom_prompt
    from local_ai.vision_execution.llm_seam import ve_eval_provider_shim

    try:
      provider = ve_eval_provider_shim(
        execution_principal_from_legacy_user_id(user_id),
        use_execution_seam=True,
      )
    except Exception as e:
      logger.warning("core_profile_conversation: provider shim failed: %s", e)
      return {"error": f"Provider not available: {e!s}"}

    pu = meta.get("provider_used")
    mu = meta.get("model_used")
    lane = run_general_delegation_custom_prompt(
      surface=surface,
      action_intent=action_intent,
      compiled_prompt=prompt,
      input_snapshot=input_snapshot,
      privacy_mode=privacy_mode,
      exec_meta=meta,
      run_provider=lambda p: provider.generate(p, timeout=90),
      provider_used=str(pu).strip() if pu else None,
      model_used=str(mu).strip() if mu else None,
      try_parse_json=False,
    )
    out: dict[str, Any] = {}
    if lane.get("learning_record_id"):
      out["learning_record_id"] = lane["learning_record_id"]
    if meta.get("model_used") is not None:
      out["model_used"] = meta.get("model_used")
    if meta.get("provider_used") is not None:
      out["provider_used"] = meta.get("provider_used")
    err = lane.get("error")
    raw = lane.get("text") or ""
    if err and not (isinstance(raw, str) and raw.strip()):
      out["error"] = f"Conversation generation failed: {err}"
      return out
    if not isinstance(raw, str) or not raw.strip():
      out["error"] = out.get("error") or "No response from provider"
      return out
    out["reply"] = _enforce_response_shape(raw.strip())
    return out

  try:
    from local_ai.llm.resolver import get_provider_shim_for_legacy_generate

    provider = get_provider_shim_for_legacy_generate(execution_principal_from_legacy_user_id(user_id))
  except Exception as e:
    logger.warning("core_profile_conversation: provider not available: %s", e)
    return {"error": f"Provider not available: {e!s}"}

  try:
    raw = provider.generate(prompt, timeout=90)
  except Exception as e:
    logger.warning("core_profile_conversation: generate failed: %s", e)
    return {"error": f"Conversation generation failed: {e!s}"}

  if not raw or not isinstance(raw, str):
    return {"error": "No response from provider"}

  reply = _enforce_response_shape(raw.strip())
  return {"reply": reply}


def _enforce_response_shape(reply: str) -> str:
  """Keep at most 3 paragraphs to enforce short, non-list response shape."""
  if not reply:
    return reply
  paragraphs = [p.strip() for p in reply.split("\n\n") if p.strip()]
  if len(paragraphs) <= 3:
    return reply
  return "\n\n".join(paragraphs[:3])

