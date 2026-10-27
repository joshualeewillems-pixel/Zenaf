"""Build-Council Room runner (R1 + R2 invocation surfaces).

Two endpoints: POST /build-room/meetings runs a single-model (R1)
meeting, and POST /build-room/meetings/r2 runs a multi-participant
(R2) meeting — both for the signed-in OWNER account, returning the
transcript plus the draft artifact.

Owner-gating is load-bearing: a meeting spends the owner's OpenAI
credit, so the endpoint requires the bootstrapped owner account —
never anonymous, never public, never another user. The participant
resolves under the CALLER's account principal (not the system
principal), because that is where the saved key lives.

Boundaries (spec section 4/5, R1 semantics preserved):
- No key values in responses or logs. The artifact carries a key
  SOURCE label only; the participant object is never serialized.
- R1 budget/timeout enforcement applies; failures are recorded in
  the transcript and reflected in ``ok`` — never raised as crashes.
- No execution path: the artifact RECOMMENDS only. Nothing this
  endpoint returns authorizes file changes or PRs.
- This module does not change R1 semantics; it only invokes it.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, field_validator

from api.routes.auth_routes import get_current_user
from local_ai.build_room.harness_fixtures import (
    TELEMETRY,
    fixture_d_state,
    fixture_e_state,
)
from local_ai.build_room.meeting import (
    Budget,
    EvidencePacket,
    _SYNTHESIS_INSTRUCTION,
    _telemetry_block,
    build_synthesis_state,
    parse_synthesis_contract,
    run_multi_model_meeting,
    run_single_model_meeting,
)
from local_ai.build_room.participants import (
    SYNTHESIZER_NAME,
    resolve_openai_participant,
)
from local_ai.llm.execution_principal import authenticated_account_principal
from local_ai.vision_execution import storage as St

router = APIRouter(prefix="/build-room", tags=["build-room"])


def get_build_room_store_dir() -> Path:
    """Production store dir (injection point tests monkeypatch).

    Under the app data dir, which on staging is the persistent
    volume (``/app/data``): transcripts and draft artifacts survive
    redeploys.
    """
    return Path(__file__).resolve().parent.parent.parent / "data" / "build_room"


def get_current_owner_user(current_user: dict = Depends(get_current_user)) -> dict:
    """Owner-only gate. Fail closed: unknown owner row denies."""
    owner_id = St.get_owner_user_id()
    if owner_id is None or current_user.get("id") != owner_id:
        raise HTTPException(
            status_code=403, detail="Build-room meetings are owner-only"
        )
    return current_user


class RunMeetingBody(BaseModel):
    """Work item + question for one R1 meeting."""

    work_item: str
    question: str
    excerpts: list[str] = []
    constraints: list[str] = []
    source_refs: list[str] = []
    context: list[str] = []

    @field_validator("work_item", "question")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        v = (v or "").strip()
        if not v:
            raise ValueError("work_item and question are required")
        return v


@router.post("/meetings")
def run_meeting(
    body: RunMeetingBody, current_user: dict = Depends(get_current_owner_user)
):
    """Run one R1 meeting for the caller and return its record.

    The caller id is authoritative (never trust a client-supplied
    user id): the participant resolves under the caller's own
    account principal, so the spend follows the caller.
    """
    uid = current_user["id"]
    principal = authenticated_account_principal(uid)
    packet = EvidencePacket(
        work_item=body.work_item,
        question=body.question,
        excerpts=tuple(body.excerpts),
        constraints=tuple(body.constraints),
        source_refs=tuple(body.source_refs),
        context=tuple(body.context),
    )
    result = run_single_model_meeting(
        packet, store_dir=get_build_room_store_dir(), principal=principal
    )
    return {
        "meeting_id": result.meeting_id,
        "ok": result.ok,
        "transcript": result.transcript.to_dict(),
        "artifact": result.artifact,
    }


@router.post("/meetings/r2")
def run_meeting_r2(
    body: RunMeetingBody, current_user: dict = Depends(get_current_owner_user)
):
    """Run one R2 multi-participant meeting for the caller.

    Same owner gate, caller-principal key resolution, store dir, and
    no-key-values rules as R1. The meeting stays synchronous; no
    async job queue (a follow-up slice only if sync proves too slow).
    The artifact RECOMMENDS only.
    """
    uid = current_user["id"]
    principal = authenticated_account_principal(uid)
    packet = EvidencePacket(
        work_item=body.work_item,
        question=body.question,
        excerpts=tuple(body.excerpts),
        constraints=tuple(body.constraints),
        source_refs=tuple(body.source_refs),
        context=tuple(body.context),
    )
    result = run_multi_model_meeting(
        packet, store_dir=get_build_room_store_dir(), principal=principal
    )
    return {
        "meeting_id": result.meeting_id,
        "ok": result.ok,
        "transcript": result.transcript.to_dict(),
        "artifact": result.artifact,
    }


# ---------------------------------------------------------------------------
# Synthesis-harness route (test-only staging surface, NOT a meeting).
#
# POST /build-room/harness/synthesis-call runs exactly ONE GPT
# generation per request against a bounded fixture state (D or E) and
# returns the verbatim output plus the production validator's
# evaluation. It exists because the test environment cannot resolve
# the owner's principal (keys live in Zenaf Settings on staging),
# so the model-compliance level of the Phase A harness runs here.
#
# Boundaries (authorized scope, Joshua 2026-10-26):
# - Owner-only, same gate as the meeting routes. Non-owner requests
#   are refused before any work.
# - Fixture selector ONLY ("D" or "E"). No user-supplied prompt text,
#   no arbitrary state, no other inputs — anything else is refused
#   by validation before any work.
# - Exactly ONE participant.generate() call per request, no retries,
#   using the production synthesis timeout (Budget default 120s) and
#   the production cap (Budget max_response_prompt_chars, 40,000).
# - The fixture state is built by the shared harness_fixtures
#   builders (the PR #227 fixtures, unchanged), the prompt is
#   assembled with production's exact expression
#   (state["prompt"] + "\n\n" + telemetry), and the output is
#   evaluated by the production parse_synthesis_contract validator.
#   No repair layer, no second parser, no schema change.
# - NO persistence: no registry writes, no transcript, no meeting
#   record, no stored fixture state. The route is stateless apart
#   from the generation itself.
# - NEVER returns credentials, keys, key material, or the prompt
#   text: the report carries the prompt hash + component sizes only.
# - Budget behavior unchanged: an over-budget state reports the
#   diagnostic verbatim and attempts no generation (fixtures are
#   under budget; the branch is implemented anyway).
# - This route does NOT authorize model calls by itself: each
#   fixture call needs Joshua's separate explicit word, and calls
#   run only after this route is merged and the deploy confirmed.
# ---------------------------------------------------------------------------

HARNESS_FIXTURE_BUILDERS = {
    "D": fixture_d_state,
    "E": fixture_e_state,
}


class HarnessSynthesisBody(BaseModel):
    """Fixture selector only. Nothing else is accepted."""

    fixture: str

    @field_validator("fixture")
    @classmethod
    def _only_d_or_e(cls, v: str) -> str:
        if v not in ("D", "E"):
            raise ValueError("fixture must be exactly 'D' or 'E'")
        return v


def _harness_disclosure_notes(evaluations: dict,
                              unresolved_objections: list,
                              omitted: dict | None) -> dict:
    """Whether each production disclosure note WOULD fire.

    Mirrors the synthesis-phase conditions exactly (same as the
    test-harness helper; a route test asserts parity): the
    disagreements note fires when disagreements evaluates
    synthesized_empty and unresolved objections exist; the
    limitations note fires when limitations evaluates
    synthesized_empty and omitted context exists. Text only, no
    status change, no reclassification.
    """
    omitted_total = 0
    if omitted:
        omitted_total = (omitted.get("superseded_texts", 0)
                         + omitted.get("responded_to_details", 0))
    return {
        "disagreements_note": (
            evaluations.get("disagreements") == "synthesized_empty"
            and bool(unresolved_objections)),
        "limitations_note": (
            evaluations.get("limitations") == "synthesized_empty"
            and bool(omitted_total)),
    }


def _disclosure_chars(state_prompt: str) -> int:
    """Length of the disclosure section inside a built state prompt.

    Measured from the production-built string itself, never
    reconstructed: the prompt ends with disclosure + "\\n\\n" +
    instruction, and the disclosure text contains no blank line, so
    the last "\\n\\n"-separated segment before the instruction is
    the disclosure. build_synthesis_state does not expose this
    figure separately, so it is not fabricated from parts.
    """
    without_instruction = state_prompt[: -len(_SYNTHESIS_INSTRUCTION)]
    assert without_instruction.endswith("\n\n")
    return len(without_instruction[:-2].rsplit("\n\n", 1)[-1])


def _harness_report_sizes(state: dict, prompt: str) -> dict:
    """Prompt hash + component sizes, measured from production objects."""
    return {
        "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
        "mandatory_chars": state.get("mandatory_chars"),
        "instruction_chars": len(_SYNTHESIS_INSTRUCTION),
        "disclosure_chars": _disclosure_chars(state["prompt"]),
        "state_prompt_chars": len(state["prompt"]),
        "assembled_prompt_chars": len(prompt),
        "telemetry_chars": len(prompt) - len(state["prompt"]),
        "cap": Budget().max_response_prompt_chars,
    }


@router.post("/harness/synthesis-call")
def harness_synthesis_call(
    body: HarnessSynthesisBody,
    current_user: dict = Depends(get_current_owner_user),
):
    """One GPT synthesis generation against fixture D or E, evaluated.

    Owner-only; fixture selector only; exactly one generation, no
    retries; no persistence; no credentials or prompt text returned.
    """
    uid = current_user["id"]
    principal = authenticated_account_principal(uid)
    budget = Budget()
    packet, registry, unresolved, chains = HARNESS_FIXTURE_BUILDERS[
        body.fixture]()
    # B1: telemetry is passed so the gate compares the assembled
    # prompt length, exactly as the production meeting path does.
    telemetry = _telemetry_block(**TELEMETRY)
    state = build_synthesis_state(
        packet, registry, unresolved, chains,
        cap_chars=budget.max_response_prompt_chars,
        telemetry=telemetry,
    )
    if state["prompt"] is None:
        # Budget behavior unchanged: diagnostic verbatim, no generation.
        return {
            "fixture_id": body.fixture,
            "ok": False,
            "generated": False,
            "budget_reason": state["reason"],
            "mandatory_chars": state.get("mandatory_chars"),
            "cap": budget.max_response_prompt_chars,
        }
    prompt = state["prompt"] + "\n\n" + telemetry
    sizes = _harness_report_sizes(state, prompt)
    participant, absence = resolve_openai_participant(principal)
    if participant is None:
        # Absence is a visible outcome, not a silent drop; nothing
        # is generated and no key material is involved.
        return {
            "fixture_id": body.fixture,
            "ok": False,
            "generated": False,
            "absence": absence,
            **sizes,
        }
    try:
        text = participant.generate(prompt, timeout=budget.timeout_seconds)
    except Exception as exc:  # generation failure is visible, not a crash
        return {
            "fixture_id": body.fixture,
            "ok": False,
            "generated": False,
            "generation_error": str(exc),
            **sizes,
        }
    structured, evaluations, rejected, block_found = (
        parse_synthesis_contract(text, registry, unresolved,
                                 SYNTHESIZER_NAME))
    return {
        "fixture_id": body.fixture,
        "ok": True,
        "generated": True,
        "generations_used": 1,
        "synthesizer": SYNTHESIZER_NAME,
        **sizes,
        "raw": text,
        "structured": structured,
        "evaluations": evaluations,
        "rejected_entries": rejected,
        "block_found": block_found,
        "disclosure_notes": _harness_disclosure_notes(
            evaluations, unresolved, state.get("omitted")),
    }
