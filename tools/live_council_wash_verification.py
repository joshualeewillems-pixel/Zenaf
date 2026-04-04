"""
End-to-end council wash verification: native raw (Ollama) vs cloud-washed (OpenAI teacher).

Run from repo root (requires OPENAI_API_KEY for an authenticated principal and Ollama):
  PYTHONPATH=<repo> python tools/live_council_wash_verification.py

Uses a synthetic authenticated account id so cloud OpenAI follows Option B (anonymous does not use OPENAI_API_KEY).

Exits non-zero if teacher does not resolve to a cloud provider shim or verification fails.
"""
from __future__ import annotations

import os
import sys
import uuid
from types import SimpleNamespace

from local_ai import config as atria_config
from local_ai.atria_tools import _council_provider_shim_is_cloud
from local_ai.council_preflight import build_enriched_council_context, parse_preflight_from_request
from local_ai.council_teacher import CouncilTeacherSettings, run_council_with_teacher
from local_ai.council_wash import prepare_council_contexts
from local_ai.execution_policy.provider_default_inspect import build_provider_resolution_for_run
from local_ai.llm.execution_principal import authenticated_account_principal
from local_ai.llm.resolver import get_council_provider_for_principal


SECRET_UUID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
SECRET_EMAIL = "council.wash.verify@example.com"
SECRET_API = "sk-abcdefghijklmnopqrstuvwxyz1234567890abcd"


def _build_sensitive_enriched() -> str:
    ctx = {
        "council_preflight": {
            "active_surface": "vision_execution",
            "ve_focus": {
                "entity_type": "project",
                "entity_id": "p9",
                "lineage_labels": ["Initiatives", "North star", "Projects"],
            },
            "ve_focus_title": "Secret Initiative X",
            "ve_focus_brief": (
                f"North star: ship the analytics export on time. "
                f"Escalation contact: {SECRET_EMAIL} before production cutover. "
                "Dependencies: data warehouse team sign-off and staging parity checks."
            ),
            "grounding_explicit": True,
        },
        "context_block": (
            f"External ticket: {SECRET_UUID}\n"
            f"Integration probe token (synthetic): {SECRET_API}\n"
            "Thread:\n"
            "User: We need the next concrete step for Secret Initiative X — "
            "prefer something we can do this week without expanding scope.\n"
            "Prior decision: keep council packets under 5k chars."
        ),
    }
    q = (
        "What's the next step for this project? "
        "Name one bottleneck in the current council/context path if you see it."
    )
    pre = parse_preflight_from_request(ctx, q)
    return build_enriched_council_context(
        pre, legacy_context_str=None, subject_ref=None, object_snapshot=None
    )


def _prompt_has_raw_leaks(prompt: str) -> dict[str, bool]:
    return {
        "uuid": SECRET_UUID in prompt,
        "email": SECRET_EMAIL in prompt,
        "token": SECRET_API in prompt,
    }


def main() -> int:
    run_id = str(uuid.uuid4())
    enriched = _build_sensitive_enriched()
    native_ctx, cloud_ctx, wash_trace = prepare_council_contexts(enriched)
    allows_ext = bool(wash_trace.get("safety_allow_cloud_with_wash"))

    omodel = (
        (getattr(atria_config, "OLLAMA_COUNCIL_MODEL", None) or atria_config.OLLAMA_MODEL or "")
        .strip()
        or "qwen2:7b-instruct"
    )
    teacher_provider = "openai"
    teacher_model = "gpt-4o-mini"

    if not (os.environ.get("OPENAI_API_KEY") or "").strip():
        print("STOP: OPENAI_API_KEY is not set; cannot run a real cloud teacher path for authenticated principal.")
        print(f"run_id={run_id} (planned; no council run executed)")
        return 2

    principal = authenticated_account_principal("council-wash-verify")
    native_p = get_council_provider_for_principal(principal, allows_externalization=allows_ext)
    teacher_p = get_council_provider_for_principal(
        principal,
        force_provider=teacher_provider,
        force_model=teacher_model,
        allows_externalization=allows_ext,
    )

    if _council_provider_shim_is_cloud(native_p):
        print("STOP: Native provider resolved as cloud shim; expected local Ollama for this check.")
        print(f"native council_provider_id={getattr(native_p, 'council_provider_id', None)!r}")
        return 3

    if not _council_provider_shim_is_cloud(teacher_p):
        print("STOP: Teacher provider did not resolve to a cloud shim (openai expected).")
        print(f"teacher council_provider_id={getattr(teacher_p, 'council_provider_id', None)!r}")
        print("Check credentials, blocked adapter, or resolver policy for anonymous principal.")
        return 4

    settings = CouncilTeacherSettings(
        teacher_mode="shadow",
        teacher_provider=teacher_provider,
        teacher_model=teacher_model,
        teacher_prompt_version="council_teacher_v1",
    )

    packed = run_council_with_teacher(
        question=(
            "What's the next step for this project? "
            "Name one bottleneck in the current council/context path if you see it."
        ),
        context=native_ctx,
        included_roles=["strategist"],
        perspective_definitions=None,
        include_synthesis=False,
        subject_ref=None,
        object_snapshot=None,
        execution_principal=principal,
        settings=settings,
        native_provider_override="ollama",
        native_model_override=omodel,
        allows_externalization=True,
        context_for_cloud=cloud_ctx,
        council_wash_trace=wash_trace,
    )

    native_debug = packed.get("native_run_debug") or {}
    teacher_debug = packed.get("teacher_run_debug") or {}
    native_rm = native_debug.get("run_meta") or {}
    native_seats = native_debug.get("seats") or []
    teacher_seats = teacher_debug.get("seats") or []
    np0 = (native_seats[0] or {}).get("full_compiled_prompt") or "" if native_seats else ""
    tp0 = (teacher_seats[0] or {}).get("full_compiled_prompt") or "" if teacher_seats else ""

    native_leaks = _prompt_has_raw_leaks(np0)
    teacher_leaks = _prompt_has_raw_leaks(tp0)
    teacher_has_redacted = (
        "[REDACTED_UUID]" in tp0 or "[REDACTED_EMAIL]" in tp0 or "[REDACTED_TOKEN]" in tp0
    )

    teacher_meta = {
        "native_provider": packed.get("native_provider"),
        "native_model": packed.get("native_model"),
        "teacher_provider": settings.teacher_provider,
        "teacher_model": settings.teacher_model,
        "teacher_provider_effective": packed.get("teacher_provider_effective"),
        "teacher_model_effective": packed.get("teacher_model_effective"),
        "teacher_succeeded": packed.get("teacher_succeeded"),
        "teacher_skipped_reason": packed.get("teacher_skipped_reason"),
        "council_wash_trace": native_rm.get("council_wash_trace"),
        "council_native_attachment_trace": native_rm.get("council_native_attachment_trace"),
    }
    params = SimpleNamespace(
        native_provider="ollama",
        native_model=omodel,
        teacher_provider=settings.teacher_provider,
        teacher_model=settings.teacher_model,
    )
    provider_resolution = build_provider_resolution_for_run(
        mode="council",
        params=params,
        principal=principal,
        exec_meta=None,
        routing_context=None,
        teacher_meta=teacher_meta,
        wash_trace=wash_trace,
    )

    eff_prov = packed.get("teacher_provider_effective")
    eff_model = packed.get("teacher_model_effective")
    teacher_ok = bool(packed.get("teacher_succeeded"))
    teacher_err = packed.get("teacher_error")

    print("=== Final cloud wash verification report ===")
    print(f"1. run_id={run_id}")
    print(f"2. teacher_effective_provider={eff_prov!r} teacher_effective_model={eff_model!r}")
    print(f"3. council_wash_trace={wash_trace!r}")
    print(f"4. provider_resolution.council.wash={provider_resolution.get('council', {}).get('wash')!r}")
    print(f"5. native_prompt_raw_markers: uuid={native_leaks['uuid']} email={native_leaks['email']} token={native_leaks['token']}")
    print(
        f"6. teacher_prompt_redacted_markers_present={teacher_has_redacted} "
        f"(washed context should include [REDACTED_*] placeholders)"
    )
    print(f"7. teacher_prompt_raw_leaks: uuid={teacher_leaks['uuid']} email={teacher_leaks['email']} token={teacher_leaks['token']}")
    print(f"8. teacher_output_completed_successfully={teacher_ok} teacher_error={teacher_err!r}")

    ok = (
        native_leaks["uuid"]
        and native_leaks["email"]
        and not teacher_leaks["uuid"]
        and not teacher_leaks["email"]
        and not teacher_leaks["token"]
        and teacher_has_redacted
        and teacher_ok
        and (eff_prov or "").lower() == "openai"
    )
    if not ok:
        print("\nVERIFICATION: FAILED (see fields above)")
        return 1
    print("\nVERIFICATION: PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
