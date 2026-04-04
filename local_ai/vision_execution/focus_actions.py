"""
Context Action Bar — focused field actions (Phase 1.1+).

Mediation-oriented prompts; no auto-apply on the server.
"""

from __future__ import annotations

import re
from typing import Any, Literal

from local_ai.llm.adapter import LLMRequest
from local_ai.llm.execution_principal import principal_for_vision_execution_user
from local_ai.llm.resolver import get_llm_adapter_for_principal
from local_ai.vision_execution import service as S

FocusEntity = Literal["initiative", "idea"]

ALLOWED_FIELDS: set[tuple[str, str]] = {
    ("initiative", "brief"),
    ("initiative", "recommendation"),
    ("initiative", "philosophical_alignment_ai"),
    ("initiative", "dependencies"),
    ("idea", "description"),
    ("idea", "title"),
    ("idea", "summary"),
    ("task", "title"),
    ("task", "description"),
}


def _load_stored_field_text(entity_type: str, entity_id: str, field_key: str, user_id: str) -> str | None:
    if (entity_type, field_key) not in ALLOWED_FIELDS:
        return None
    if entity_type == "initiative":
        row = S.get_initiative(entity_id, user_id)
    elif entity_type == "idea":
        row = S.get_idea(entity_id, user_id)
    elif entity_type == "task":
        row = S.get_task(entity_id, user_id)
    else:
        return None
    if not row:
        return None
    raw = row.get(field_key)
    text = (str(raw) if raw is not None else "").strip()
    return text or None


def resolve_text_for_rewrite(
    *,
    entity_type: str,
    entity_id: str,
    field_key: str,
    user_id: str,
    text_override: str | None,
) -> tuple[str, Literal["override", "stored"]]:
    o = (text_override or "").strip()
    if o:
        return o[:12000], "override"
    stored = _load_stored_field_text(entity_type, entity_id, field_key, user_id)
    if not stored:
        raise ValueError("NO_TEXT_FOR_REWRITE")
    return stored[:12000], "stored"


def _looks_like_source_citation_note(t: str) -> bool:
    """Heuristic: doc pointer lines (Source: … .md, section markers §). Local to rewrite prompts only."""
    s = t.strip()
    if not s:
        return False
    low = s.lower()
    if "§" in s:
        return True
    if ".md" in s and re.search(r"\bsource\s*:", low):
        return True
    return False


def _rewrite_prompt(*, field_key: str, text: str) -> tuple[str, Literal["title", "body"]]:
    """
    Title vs body/description: same anti-meta guardrails; body mode allows a bit more
    rephrasing and expansion for terse or note-style input.
    """
    shared = """Rewrite the following text.

Your task applies ONLY to the user text in the block below. Do not describe the field. Only rewrite the provided text.

Rules (always):
- Output ONLY the rewritten text: no title, no preamble, no meta-commentary, no labels (do not write "Rewritten:" or explain your edits).
- Never describe the field, the form, or the app (e.g. do not write "The field '…'" or "This expanded description …").
- Do not introduce new concepts, system explanations, or commentary about what the text is for.
- Do not invent facts, numbers, names, or commitments not present in the original.
- If the original expresses uncertainty, keep that uncertainty visible; do not falsely sharpen.
"""

    if field_key == "title":
        mode: Literal["title", "body"] = "title"
        mode_rules = """Mode — title (short label):
- Keep the result brief (typically one line). Do not add supporting sentences or implied backstory.
- Polish for clarity and concreteness; stay close to the original length — no expansion into a paragraph.
"""
    else:
        mode = "body"
        mode_rules = """Mode — description / body (paragraph-style fields):
- Rewrite for clarity and usefulness, not only light punctuation or spacing fixes: make the idea easier to read and use while preserving meaning.
- You may turn terse notes, fragments, or citation-style lines into clearer sentence(s) or phrases, as long as every substantive detail in the input is still reflected (paths, section markers, names, numbers — keep them accurate; you may rephrase for grammar only).
- You may use slightly more words than the input when it is very short or telegraphic, but stay concise — no padding, no essay, no new claims or stakeholders not stated in the text.

Citation / source-reference / document-pointer lines:
- If the input is a citation, source reference, or pointer to a document (e.g. "Source:", a path ending in .md, or a § section marker), rewrite it into a natural phrase or full sentence that a reader can use — do not merely relabel or reformat the same structure.
- Do NOT output patterns that only swap labels or punctuation, such as: "Source: <path>, Section: <name>." or "Source: X, Section: Y." — that is forbidden. Write fluent prose instead (e.g. lead with "Grounded in …", "Drawn from …", "See …").
- Keep every path, filename, and section token that appears in the input; do not invent different files or sections.

Examples (input → good rewrite; your output must be ONLY the rewritten line, like the right-hand side):
- Source: docs/MATERIAL_ENTITY_NODE_DIRECTION.md §NOW. → Grounded in docs/MATERIAL_ENTITY_NODE_DIRECTION.md, section "NOW."
- vendor api SLA unclear — could bite us in prod → The vendor API SLA is unclear, which could cause problems in production.
- q4 ship theme: cut triage time 30% → In Q4, aim to cut triage time by 30%.
"""
        if _looks_like_source_citation_note(text):
            mode_rules += """\nStronger instruction for this input: it matches a source/citation-style note — produce one clear sentence (or short phrase) in plain language; absolutely avoid "Source: …, Section: …" style outputs.\n"""

    tail = f"""Rewrite the following text:

---
{text}
---
"""
    return shared + mode_rules + tail, mode


def rewrite_focus_field(body: dict[str, Any], user_id: str) -> dict[str, Any]:
    """
    Returns {"rewritten_text": str, "error": str | None, "source": "override"|"stored"}.
    """
    entity_type = (body.get("entity_type") or "").strip()
    entity_id = (body.get("entity_id") or "").strip()
    field_key = (body.get("field_key") or "").strip()
    text_override = body.get("text_override")

    if entity_type not in ("initiative", "idea", "task"):
        return {"rewritten_text": "", "error": "Invalid entity_type", "source": "stored"}
    if not entity_id or not field_key:
        return {"rewritten_text": "", "error": "Missing entity_id or field_key", "source": "stored"}

    try:
        text, src = resolve_text_for_rewrite(
            entity_type=entity_type,
            entity_id=entity_id,
            field_key=field_key,
            user_id=user_id,
            text_override=text_override if isinstance(text_override, str) else None,
        )
    except ValueError as e:
        if str(e) == "NO_TEXT_FOR_REWRITE":
            return {"rewritten_text": "", "error": "No text to rewrite (empty field or not allowed).", "source": "stored"}
        return {"rewritten_text": "", "error": str(e), "source": "stored"}

    if not text.strip():
        return {"rewritten_text": "", "error": "No text to rewrite.", "source": src}

    try:
        adapter = get_llm_adapter_for_principal(principal_for_vision_execution_user(user_id))
    except Exception as e:
        return {"rewritten_text": "", "error": f"LLM unavailable: {e}", "source": src}

    prompt, rewrite_mode = _rewrite_prompt(field_key=field_key, text=text)

    try:
        out = adapter.generate_text(
            LLMRequest(
                task="vision_focus_rewrite",
                prompt=prompt,
                timeout=90,
                metadata={
                    "entity_type": entity_type,
                    "field_key": field_key,
                    "rewrite_mode": rewrite_mode,
                    "chars": len(text),
                },
            )
        ).strip()
        if not out:
            return {"rewritten_text": "", "error": "Model returned empty text.", "source": src}
        return {"rewritten_text": out[:12000], "error": None, "source": src}
    except Exception as e:
        return {"rewritten_text": "", "error": str(e)[:500], "source": src}
