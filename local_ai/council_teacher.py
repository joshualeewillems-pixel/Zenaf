from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from local_ai.judgment_substrate import CouncilRunArtifact
from local_ai.llm.execution_principal import ExecutionPrincipal
from local_ai.studio.bakeoff_scoring import compute_heuristic_hints

_TEACHER_ENFORCEMENT_MODES = frozenset({"off", "shadow", "warn", "veto", "replace"})

TEACHER_VETO_REFUSAL_FALLBACK = (
    "Supervisory review flagged this council output as high-risk under current grounding. "
    "Do not rely on the prior draft for action. Provide missing constraints, sources, or scope; then re-run council."
)


TEACHER_PROMPT_VERSIONS: dict[str, str] = {
    "council_teacher_v1": (
        "Teacher mode: produce supervisory-quality council output. Be concrete, decisive, and object-grounded. "
        "Avoid generic playbook language. Name one direction, reject weak alternatives, and include one executable next move. "
        "When PRIMARY CONTEXT (authoritative) appears in the prompt, every seat—including Operator—must reuse "
        "identifiable words or phrases from PRIMARY **Title** or **Brief** in the seat body (verbatim substring), "
        "not only generic system words (packet, streaming, seats); tie the next move to that named object."
    )
}


@dataclass
class CouncilTeacherSettings:
    teacher_mode: str = "shadow"  # off|shadow|warn|veto|replace
    teacher_provider: str | None = None
    teacher_model: str | None = None
    teacher_prompt_version: str = "council_teacher_v1"
    teacher_prompt_overlay: str | None = None

    @staticmethod
    def from_dict(d: dict[str, Any] | None) -> CouncilTeacherSettings:
        raw = d or {}
        mode = str(raw.get("teacher_mode") or "shadow").strip().lower()
        if mode not in _TEACHER_ENFORCEMENT_MODES:
            mode = "shadow"
        pv = raw.get("teacher_provider")
        if pv is not None:
            pv = str(pv).strip().lower() or None
        model = raw.get("teacher_model")
        if model is not None:
            model = str(model).strip() or None
        ver = str(raw.get("teacher_prompt_version") or "council_teacher_v1").strip() or "council_teacher_v1"
        ov = raw.get("teacher_prompt_overlay")
        overlay = str(ov).strip() if isinstance(ov, str) and ov.strip() else None
        return CouncilTeacherSettings(
            teacher_mode=mode,
            teacher_provider=pv,
            teacher_model=model,
            teacher_prompt_version=ver,
            teacher_prompt_overlay=overlay,
        )

    def explicit_cloud_provider(self) -> bool:
        tp = (self.teacher_provider or "").strip().lower()
        return bool(tp and tp != "ollama")

    def prompt_overlay(self) -> str:
        base = TEACHER_PROMPT_VERSIONS.get(self.teacher_prompt_version, TEACHER_PROMPT_VERSIONS["council_teacher_v1"])
        if self.teacher_prompt_overlay:
            return f"{base}\n\n{self.teacher_prompt_overlay}"
        return base


def _artifact_to_dict(artifact: CouncilRunArtifact | None) -> dict[str, Any]:
    if artifact is None:
        return {}
    if hasattr(artifact, "model_dump"):
        return artifact.model_dump()
    if hasattr(artifact, "dict"):
        return artifact.dict()
    return {}


def _extract_next_step(text: str | None) -> str | None:
    if not text:
        return None
    low = text.lower()
    marker = "next step:"
    i = low.find(marker)
    if i == -1:
        return None
    rem = text[i + len(marker) :].strip()
    if not rem:
        return None
    return rem.splitlines()[0].strip() or None


def _short_summary(text: str | None) -> str | None:
    if not text:
        return None
    t = text.strip()
    if not t:
        return None
    return t[:220]


def evaluate_teacher_enforcement_v1(
    *,
    teacher_mode: str,
    question: str,
    native_text: str,
    teacher_text: str | None,
    teacher_ok: bool,
    comparison: dict[str, Any],
) -> dict[str, Any]:
    """
    Minimal council-only heuristics: reuse bakeoff-style hints + teacher/native disagreement.
    Does not call an LLM classifier.
    """
    mode = (teacher_mode or "off").strip().lower()
    out: dict[str, Any] = {
        "teacher_vetoed": False,
        "teacher_warning": False,
        "teacher_final_source": "native",
        "teacher_reason_codes": [],
        "teacher_notes": None,
    }
    if mode in ("off", "shadow"):
        return out
    if mode == "replace":
        out["teacher_final_source"] = "native"
        return out

    hints = compute_heuristic_hints(question, native_text, True)
    risk_hints = frozenset(
        {
            "secrets_leaked_suspected",
            "suspected_wrong_domain_electrical",
            "hallucination_risk_claims_made",
            "secret_requested_but_not_obviously_handled",
            "adversarial_grounding_security_combo",
        }
    )
    matched_risk = [h for h in hints if h in risk_hints]

    disagree = comparison.get("same_decision") is False or comparison.get("same_next_move") is False
    teacher_present = bool(comparison.get("teacher_present"))

    veto_codes: list[str] = []
    if "secrets_leaked_suspected" in hints:
        veto_codes.append("privacy_secret_externalization")
    if "suspected_wrong_domain_electrical" in hints:
        veto_codes.append("wrong_domain_grounding")
    if "hallucination_risk_claims_made" in hints and disagree and teacher_present:
        veto_codes.append("fabricated_facts_citations_risk")
    # Weak grounding + native did not clarify when prompt carried clarify/secret pressure
    if "secret_requested_but_not_obviously_handled" in hints and not bool(
        re.search(r"\b(clarif|cannot|can't|refus|not allowed|need more)\b", (native_text or "").lower())
    ):
        veto_codes.append("clarify_first_violation")

    notes_bits: list[str] = []
    if matched_risk:
        notes_bits.append("Native risk hints: " + ", ".join(matched_risk))
    if disagree and teacher_present:
        notes_bits.append("Teacher disagreed with native summary or next-step alignment (see comparison).")
    teacher_notes = "; ".join(notes_bits) if notes_bits else None
    if teacher_text and teacher_notes:
        ts = (teacher_text or "").strip()
        if len(ts) > 400:
            ts = ts[:399] + "…"
        teacher_notes = f"{teacher_notes} | Teacher excerpt: {ts}"

    if mode == "veto" and veto_codes:
        out["teacher_vetoed"] = True
        out["teacher_reason_codes"] = veto_codes
        out["teacher_notes"] = teacher_notes
        if teacher_ok and (teacher_text or "").strip():
            out["teacher_final_source"] = "teacher"
        else:
            out["teacher_final_source"] = "teacher_refusal"
        return out

    if mode == "warn" and (matched_risk or (disagree and teacher_present)):
        out["teacher_warning"] = True
        out["teacher_reason_codes"] = matched_risk or (["teacher_native_disagreement"] if disagree else [])
        out["teacher_notes"] = teacher_notes
        return out

    return out


def build_comparison(native_text: str, teacher_text: str | None) -> dict[str, Any]:
    ns = _short_summary(native_text)
    ts = _short_summary(teacher_text)
    nnext = _extract_next_step(native_text)
    tnext = _extract_next_step(teacher_text)
    same_next = None
    if nnext and tnext:
        same_next = (nnext.lower() == tnext.lower())
    same_decision = None
    if ns and ts:
        same_decision = (ns.lower() == ts.lower())
    return {
        "teacher_present": bool(teacher_text and teacher_text.strip()),
        "native_summary": ns,
        "teacher_summary": ts,
        "same_decision": same_decision,
        "same_next_move": same_next,
        "notes": None,
    }


def run_council_with_teacher(
    *,
    question: str,
    seat_question: str | None = None,
    context: str | None,
    included_roles: list[str] | None,
    perspective_definitions: list[dict] | None,
    include_synthesis: bool | None,
    subject_ref: dict | None,
    object_snapshot: dict | None,
    execution_principal: ExecutionPrincipal,
    settings: CouncilTeacherSettings,
    native_provider_override: str | None = None,
    native_model_override: str | None = None,
    allows_externalization: bool = True,
    context_for_cloud: str | None = None,
    council_wash_trace: dict[str, Any] | None = None,
    force_full_council: bool | None = None,
    council_preflight_dict: dict[str, Any] | None = None,
    conversation_subject_dict: dict[str, Any] | None = None,
    integration_packet_suffix: str | None = None,
    integration_event_dict: dict[str, Any] | None = None,
    pending_integration_dict: dict[str, Any] | None = None,
    last_integration_commit_dict: dict[str, Any] | None = None,
) -> dict[str, Any]:
    from local_ai.atria_tools import run_council
    from local_ai.conversation_trunk import (
        conversation_subject_to_json,
        merge_conversation_subject,
        parse_conversation_subject,
        select_output_contract,
    )
    from local_ai.integration_commit import (
        deterministic_integration_ack_text,
        integration_event_requires_deterministic_ack,
        thinking_partner_meta_for_terminal_integration_event,
    )

    if integration_event_requires_deterministic_ack(integration_event_dict):
        txt = deterministic_integration_ack_text(integration_event_dict or {})
        meta = thinking_partner_meta_for_terminal_integration_event(
            integration_event_dict,
            council_preflight_dict=council_preflight_dict,
        )
        prev = (
            parse_conversation_subject(conversation_subject_dict)
            if isinstance(conversation_subject_dict, dict)
            else None
        )
        merged = merge_conversation_subject(
            previous=prev,
            question=question,
            question_kind="integration_confirm",
            output_contract=select_output_contract("integration_confirm"),
            capture_target=None,
            council_preflight_dict=council_preflight_dict,
            packet=None,
        )
        if merged:
            meta["conversation_subject"] = conversation_subject_to_json(merged)
        native_debug: dict[str, Any] = {
            "run_meta": meta,
            "selection": {
                "selected_source": "deterministic_integration",
                "final_selection_policy": "native",
                "teacher_enforcement_mode": settings.teacher_mode,
                "teacher_vetoed": False,
                "teacher_warning": False,
                "teacher_final_source": "native",
                "teacher_reason_codes": [],
            },
        }
        return {
            "selected_text": txt,
            "native_text": txt,
            "teacher_text": None,
            "teacher_skipped_reason": "deterministic_integration",
            "native_artifact": {},
            "teacher_artifact": {},
            "native_provider": None,
            "native_model": None,
            "teacher_provider_effective": None,
            "teacher_model_effective": None,
            "teacher_succeeded": False,
            "teacher_error": None,
            "comparison": build_comparison(txt, None),
            "final_selection_policy": "native",
            "selected_source": "native",
            "native_run_debug": native_debug,
            "teacher_run_debug": {},
            "teacher_enforcement_mode": settings.teacher_mode,
            "teacher_vetoed": False,
            "teacher_warning": False,
            "teacher_final_source": "native",
            "teacher_reason_codes": [],
            "teacher_notes": None,
        }

    native_res = run_council(
        question,
        context=context,
        included_roles=included_roles,
        perspective_definitions=perspective_definitions,
        include_synthesis=include_synthesis,
        subject_ref=subject_ref,
        object_snapshot=object_snapshot,
        execution_principal=execution_principal,
        return_artifact=True,
        provider_override_id=native_provider_override,
        provider_override_model=native_model_override,
        allows_externalization=allows_externalization,
        context_for_cloud=context_for_cloud,
        council_wash_trace=council_wash_trace,
        force_full_council=force_full_council,
        seat_question=seat_question,
        council_preflight_dict=council_preflight_dict,
        conversation_subject_dict=conversation_subject_dict,
        integration_packet_suffix=integration_packet_suffix,
        integration_event_dict=integration_event_dict,
        pending_integration_dict=pending_integration_dict,
        last_integration_commit_dict=last_integration_commit_dict,
    )
    native_debug: dict[str, Any] = {}
    if isinstance(native_res, tuple):
        if len(native_res) >= 3:
            native_text, native_art, native_debug = native_res[0], native_res[1], native_res[2] or {}
        else:
            native_text, native_art = native_res
    else:
        native_text, native_art = str(native_res), None
    teacher_text: str | None = None
    teacher_art: CouncilRunArtifact | None = None
    teacher_debug: dict[str, Any] = {}
    teacher_error: str | None = None
    teacher_ok = False
    teacher_skipped_reason: str | None = None
    if settings.teacher_mode in ("shadow", "warn", "veto", "replace"):
        if not allows_externalization and settings.explicit_cloud_provider():
            teacher_skipped_reason = "privacy_requires_local"
            teacher_error = "Teacher pass skipped: cloud provider disabled (externalization not allowed)."
            teacher_ok = False
        else:
            try:
                t_res = run_council(
                    question,
                    context=context,
                    included_roles=included_roles,
                    perspective_definitions=perspective_definitions,
                    include_synthesis=include_synthesis,
                    subject_ref=subject_ref,
                    object_snapshot=object_snapshot,
                    execution_principal=execution_principal,
                    return_artifact=True,
                    provider_override_id=settings.teacher_provider,
                    provider_override_model=settings.teacher_model,
                    seat_prompt_overlay=settings.prompt_overlay(),
                    allows_externalization=allows_externalization,
                    context_for_cloud=context_for_cloud,
                    council_wash_trace=council_wash_trace,
                    force_full_council=force_full_council,
                    seat_question=seat_question,
                    council_preflight_dict=council_preflight_dict,
                    conversation_subject_dict=conversation_subject_dict,
                    integration_packet_suffix=integration_packet_suffix,
                    integration_event_dict=integration_event_dict,
                    pending_integration_dict=pending_integration_dict,
                    last_integration_commit_dict=last_integration_commit_dict,
                )
                if isinstance(t_res, tuple):
                    if len(t_res) >= 3:
                        teacher_text, teacher_art, teacher_debug = t_res[0], t_res[1], t_res[2] or {}
                    else:
                        teacher_text, teacher_art = t_res
                else:
                    teacher_text, teacher_art = str(t_res), None
                teacher_ok = True
            except Exception as e:
                teacher_error = str(e)
                teacher_ok = False
    final_policy = "native"
    selected_source = "native"
    selected_text = native_text
    comparison = build_comparison(native_text, teacher_text)

    enf = evaluate_teacher_enforcement_v1(
        teacher_mode=settings.teacher_mode,
        question=question,
        native_text=native_text,
        teacher_text=teacher_text,
        teacher_ok=teacher_ok,
        comparison=comparison,
    )
    teacher_vetoed = bool(enf.get("teacher_vetoed"))
    teacher_warning = bool(enf.get("teacher_warning"))
    teacher_reason_codes = list(enf.get("teacher_reason_codes") or [])
    teacher_notes = enf.get("teacher_notes")
    teacher_final_source = str(enf.get("teacher_final_source") or "native")

    if settings.teacher_mode == "veto" and teacher_vetoed:
        final_policy = "teacher_veto"
        if teacher_ok and (teacher_text or "").strip():
            selected_text = str(teacher_text)
            selected_source = "teacher"
            teacher_final_source = "teacher"
        else:
            selected_text = TEACHER_VETO_REFUSAL_FALLBACK
            selected_source = "teacher_refusal"
            teacher_final_source = "teacher_refusal"
    elif settings.teacher_mode == "replace":
        final_policy = "teacher"
        if teacher_ok and teacher_text:
            selected_text = teacher_text
            selected_source = "teacher"
            teacher_final_source = "teacher"
        else:
            selected_text = native_text
            final_policy = "native_fallback"
            selected_source = "fallback"
            teacher_final_source = "native"
    elif settings.teacher_mode in ("shadow", "warn", "off"):
        teacher_final_source = "native"
        if settings.teacher_mode == "off":
            teacher_vetoed = False
            teacher_warning = False
            teacher_reason_codes = []
            teacher_notes = None
    if isinstance(native_debug, dict):
        native_debug.setdefault("selection", {})
        native_debug["selection"]["selected_source"] = selected_source
        native_debug["selection"]["final_selection_policy"] = final_policy
        native_debug["selection"]["teacher_enforcement_mode"] = settings.teacher_mode
        native_debug["selection"]["teacher_vetoed"] = teacher_vetoed
        native_debug["selection"]["teacher_warning"] = teacher_warning
        native_debug["selection"]["teacher_final_source"] = teacher_final_source
        native_debug["selection"]["teacher_reason_codes"] = teacher_reason_codes
    if isinstance(teacher_debug, dict):
        teacher_debug.setdefault("selection", {})
        teacher_debug["selection"]["selected_source"] = selected_source
        teacher_debug["selection"]["final_selection_policy"] = final_policy
        teacher_debug["selection"]["teacher_prompt_version"] = settings.teacher_prompt_version
        teacher_debug["selection"]["teacher_overlay"] = settings.prompt_overlay()
        teacher_debug["selection"]["teacher_enforcement_mode"] = settings.teacher_mode
        teacher_debug["selection"]["teacher_vetoed"] = teacher_vetoed
        teacher_debug["selection"]["teacher_warning"] = teacher_warning
        teacher_debug["selection"]["teacher_final_source"] = teacher_final_source
        teacher_debug["selection"]["teacher_reason_codes"] = teacher_reason_codes
    return {
        "selected_text": selected_text,
        "native_text": native_text,
        "teacher_text": teacher_text,
        "teacher_skipped_reason": teacher_skipped_reason,
        "native_artifact": _artifact_to_dict(native_art),
        "teacher_artifact": _artifact_to_dict(teacher_art),
        "native_provider": getattr(native_art, "provider_name", None),
        "native_model": getattr(native_art, "model_name", None),
        "teacher_provider_effective": getattr(teacher_art, "provider_name", None) if teacher_art else None,
        "teacher_model_effective": getattr(teacher_art, "model_name", None) if teacher_art else None,
        "teacher_succeeded": teacher_ok,
        "teacher_error": teacher_error,
        "comparison": comparison,
        "final_selection_policy": final_policy,
        "selected_source": selected_source,
        "native_run_debug": native_debug,
        "teacher_run_debug": teacher_debug,
        "teacher_enforcement_mode": settings.teacher_mode,
        "teacher_vetoed": teacher_vetoed,
        "teacher_warning": teacher_warning,
        "teacher_final_source": teacher_final_source,
        "teacher_reason_codes": teacher_reason_codes,
        "teacher_notes": teacher_notes,
    }
