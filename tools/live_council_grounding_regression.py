"""
Live council + teacher_shadow grounding regression (A–D).
Run from repo root: python tools/live_council_grounding_regression.py
Requires Ollama with models from local_ai.config (OLLAMA_MODEL / OLLAMA_COUNCIL_MODEL).
"""
from __future__ import annotations

import re
import uuid
from typing import Any

from local_ai import config as atria_config
from local_ai.council_preflight import (
    CONTEXT_LEGITIMACY_NOTE_MARKER,
    PRIMARY_CONTEXT_MARKER,
    build_enriched_council_context,
    parse_preflight_from_request,
)
from local_ai.council_teacher import CouncilTeacherSettings, run_council_with_teacher
from local_ai.llm.execution_principal import anonymous_account_principal


def _clarify_signals(text: str) -> bool:
    if not text:
        return False
    low = text.lower()
    needles = (
        "clarif",
        "missing",
        "which project",
        "need more",
        "need a",
        "specify",
        "not clear",
        "unclear",
        "ambiguous",
        "what project",
        "brief",
        "more detail",
        "don't know which",
        "do not know which",
        "confirm which",
        "uncertain",
        "if you mean",
        "could you",
        "please share",
        "goal",
        "scope",
        "constraints",
    )
    return any(n in low for n in needles)


def _hedge_signals(text: str) -> bool:
    if not text:
        return False
    low = text.lower()
    return any(
        x in low
        for x in (
            "candidate",
            "if you mean",
            "might mean",
            "not confirmed",
            "options",
            "not authoritative",
            "context note",
            "unclear which",
        )
    )


def _wrong_anchor_vague_case(text: str, secret_title: str, *, case_label: str) -> str | None:
    """Heuristic: vague case A — definitive treatment of UI title without clarify/hedge."""
    if case_label != "A":
        return None
    if not text:
        return None
    low = text.lower()
    st = secret_title.lower()
    if st not in low:
        return None
    if _clarify_signals(text) or _hedge_signals(text):
        return None
    # Strong imperative/definitive coupling (cheap heuristic)
    if re.search(r"\b(next step|should|must|will)\b.*" + re.escape(st[:12]), low):
        return "mentions_secret_title_without_clarify_hedge"
    if "core move:" in low and st in low:
        return "core_move_names_secret_title_without_clarify_hedge"
    return None


def _title_confusion(
    text: str, *, secret: str, linked: str | None, case_label: str
) -> str | None:
    if case_label != "D" or not text or not linked:
        return None
    low = text.lower()
    has_s = secret.lower() in low
    has_l = linked.lower() in low
    if has_s and has_l:
        return "both_secret_and_linked_titles_in_output"
    return None


def _a_clarify_first_issues(text: str) -> list[str]:
    """CONTEXT NOTE mode: expect Clarify/Candidates; forbid superseded Core move / Next action."""
    issues: list[str] = []
    if not text.strip():
        return ["empty"]
    low = text.lower()
    if re.search(r"(?im)^\s*core move:\s*\S", text):
        issues.append("core_move_nonempty")
    if re.search(r"(?im)^\s*pushback:", text):
        issues.append("pushback_label")
    if re.search(r"(?im)^\s*next action:", text):
        issues.append("next_action_label")
    has_clarify = "clarify:" in low
    has_candidates = (
        "candidates:" in low
        or "option a" in low
        or "option b" in low
        or "•" in text and ("option" in low or "interpretation" in low)
    )
    if not (has_clarify or has_candidates):
        issues.append("no_clarify_or_candidates_block")
    return issues


def _strategy_filler_heavy(text: str) -> bool:
    low = text.lower()
    hits = (
        "swot",
        "market analysis",
        "competitive positioning",
        "stakeholder",
        "roadmap",
        "kickoff",
        "align stakeholders",
    )
    return sum(1 for h in hits if h in low) >= 2


def _bc_over_clarify_heuristic(text: str, *, must_mention: str) -> bool:
    """PRIMARY cases: fail if model stays in pure disambiguation without anchoring expected topic."""
    if not text or not must_mention:
        return False
    low = text.lower()
    if must_mention.lower() not in low:
        if "clarify:" in low and "candidates:" in low:
            return True
        if "context failure" in low and "not grounded" in low:
            return False
    return False


def _d_blend_issue(text: str) -> str | None:
    """D: both titles without explicit source-choice language."""
    low = text.lower()
    if "secret initiative x" not in low or "linked project" not in low:
        return None
    ok = (
        "subject under review",
        "assuming",
        "i will treat",
        "i'll treat",
        "which of",
        "choose one",
        "two sources",
        "do not merge",
        "not merge",
        "which source",
        "pick one",
        "either",
    )
    if any(h in low for h in ok):
        return None
    return "blended_both_titles_without_explicit_source_choice"


def _case_payload(name: str) -> tuple[str, dict[str, Any], dict[str, Any] | None]:
    ctx = {
        "council_preflight": {
            "active_surface": "vision_execution",
            "ve_focus": {
                "entity_type": "project",
                "entity_id": "p9",
                "lineage_labels": ["Initiatives", "North star", "Projects"],
            },
            "ve_focus_title": "Secret Initiative X",
            "ve_focus_brief": "Do the thing.",
        }
    }
    if name == "A":
        q = "what's the next step for this project?"
        return q, ctx, None
    if name == "B":
        q = "what's the next step for this project?"
        c2 = {
            "council_preflight": {
                **ctx["council_preflight"],
                "grounding_explicit": True,
            }
        }
        return q, c2, None
    if name == "C":
        q = (
            "Project: Aurora migration\n"
            "Outcome: Cutover with zero data loss\n"
            "Note: API freeze Friday.\n\n"
            "What's the next step for this project?"
        )
        return q, ctx, None
    if name == "D":
        q = "what's the next step for this project?"
        subj = {"entity_type": "project", "entity_id": "p9", "title": "Linked Project"}
        return q, ctx, subj
    raise ValueError(name)


def main() -> None:
    principal = anonymous_account_principal()
    omodel = (getattr(atria_config, "OLLAMA_COUNCIL_MODEL", None) or atria_config.OLLAMA_MODEL or "").strip()
    settings = CouncilTeacherSettings(
        teacher_mode="shadow",
        teacher_provider="ollama",
        teacher_model=omodel,
        teacher_prompt_version="council_teacher_v1",
    )

    print(f"Using Ollama model override: {omodel!r}")
    print(f"Principal: {principal.principal_ref} (anonymous + forced ollama — packet matches auth VE layout)\n")

    for label in ("A", "B", "C", "D"):
        run_id = str(uuid.uuid4())
        question, context_dict, subject_ref = _case_payload(label)
        pre = parse_preflight_from_request(context_dict, question)
        enriched = build_enriched_council_context(
            pre,
            legacy_context_str=None,
            subject_ref=subject_ref,
            object_snapshot=None,
        )
        packet_note = (
            "PRIMARY" if PRIMARY_CONTEXT_MARKER in enriched else "no_PRIMARY"
        ) + " | " + (
            "CONTEXT_NOTE" if CONTEXT_LEGITIMACY_NOTE_MARKER in enriched else "no_NOTE"
        )

        packed = run_council_with_teacher(
            question=question,
            context=enriched,
            included_roles=["strategist", "operator"],
            perspective_definitions=None,
            include_synthesis=False,
            subject_ref=subject_ref,
            object_snapshot=None,
            execution_principal=principal,
            settings=settings,
            native_provider_override="ollama",
            native_model_override=omodel,
            allows_externalization=True,
        )

        native = str(packed.get("native_text") or "")
        teacher = str(packed.get("teacher_text") or "")
        comp = packed.get("comparison") or {}

        n_clar = _clarify_signals(native)
        t_clar = _clarify_signals(teacher)
        n_bad = _wrong_anchor_vague_case(native, "Secret Initiative X", case_label=label)
        t_bad = _wrong_anchor_vague_case(teacher, "Secret Initiative X", case_label=label)
        conf_n = _title_confusion(
            native, secret="Secret Initiative X", linked="Linked Project", case_label=label
        )
        conf_t = _title_confusion(
            teacher, secret="Secret Initiative X", linked="Linked Project", case_label=label
        )

        # Targeted criteria (post clarify-first seat rules)
        if label == "A":
            n_a = _a_clarify_first_issues(native)
            t_a = _a_clarify_first_issues(teacher)
            n_strat = _strategy_filler_heavy(native)
            t_strat = _strategy_filler_heavy(teacher)
            print(f"A: native clarify-first issues: {n_a or 'none'}")
            print(f"A: teacher clarify-first issues: {t_a or 'none'}")
            print(f"A: native heavy strategy filler (2+ hits): {n_strat}")
            print(f"A: teacher heavy strategy filler (2+ hits): {t_strat}")
        elif label in ("B", "C"):
            must = "secret initiative" if label == "B" else "aurora"
            print(
                f"{label}: native over-clarify (Clarify+Candidates w/o anchor {must!r}): "
                f"{_bc_over_clarify_heuristic(native, must_mention=must)}"
            )
            print(
                f"{label}: teacher over-clarify (Clarify+Candidates w/o anchor {must!r}): "
                f"{_bc_over_clarify_heuristic(teacher, must_mention=must)}"
            )
        elif label == "D":
            print(f"D: native blend issue: {_d_blend_issue(native) or 'none'}")
            print(f"D: teacher blend issue: {_d_blend_issue(teacher) or 'none'}")
            print(f"D: native both titles (coarse): {conf_n or 'none'}")
            print(f"D: teacher both titles (coarse): {conf_t or 'none'}")

        def _brief_diff(a: str, b: str) -> str:
            if not a or not b:
                return "missing branch text"
            if a.strip() == b.strip():
                return "identical"
            return f"n_len={len(a)} t_len={len(b)} (see full output in logs if captured)"

        print("=" * 72)
        print(f"CASE {label}  run_id={run_id}")
        print(f"packet: {packet_note}")
        print(f"native asked_clarify/missing_brief (heuristic): {n_clar}")
        print(f"teacher asked_clarify/missing_brief (heuristic): {t_clar}")
        print(f"native possible_wrong_VE_anchor (A-only heuristic): {n_bad or 'none'}")
        print(f"teacher possible_wrong_VE_anchor (A-only heuristic): {t_bad or 'none'}")
        print(f"native subject/title confusion (D): {conf_n or 'none'}")
        print(f"teacher subject/title confusion (D): {conf_t or 'none'}")
        print(f"comparison same_decision: {comp.get('same_decision')}")
        print(f"comparison same_next_move: {comp.get('same_next_move')}")
        print(f"brief diff notes: {_brief_diff(native, teacher)}")
        if packed.get("teacher_error"):
            print(f"teacher_error: {packed['teacher_error']}")
        print("--- native excerpt (600c) ---")
        print(native[:600] + ("…" if len(native) > 600 else ""))
        print("--- teacher excerpt (600c) ---")
        print(teacher[:600] + ("…" if len(teacher) > 600 else ""))
        print()


if __name__ == "__main__":
    main()
