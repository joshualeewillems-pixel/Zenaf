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

import json
import threading
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator

from api.routes.auth_routes import get_current_user
from local_ai.build_room import moneyball_program
from local_ai.build_room.meeting import (
    EvidencePacket,
    run_multi_model_meeting,
    run_single_model_meeting,
)
from local_ai.build_room.migration import execute_migration, inventory_store_dir
from local_ai.build_room.program_runner import (
    CAP_PRICING_DEFAULT_EXPIRY,
    pricing_expired,
    run_program,
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


class RunMeetingR2Body(RunMeetingBody):
    """Work item + question for one R2 meeting.

    Tool-access stage-1 increment B: ``tools_enabled`` turns on the
    per-meeting tool flag (default OFF, never default-on) and
    ``nominated_paths`` names the packet-nominated set the GPT seat
    may read. Both are inert unless the snapshot verifies: a failed
    verification disables tools and the meeting runs packet-only.
    """

    tools_enabled: bool = False
    nominated_paths: list[str] = []


@router.post("/meetings/r2")
def run_meeting_r2(
    body: RunMeetingR2Body, current_user: dict = Depends(get_current_owner_user)
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
        packet, store_dir=get_build_room_store_dir(), principal=principal,
        tools_enabled=body.tools_enabled,
        nominated_paths=body.nominated_paths,
    )
    return {
        "meeting_id": result.meeting_id,
        "ok": result.ok,
        "transcript": result.transcript.to_dict(),
        "artifact": result.artifact,
    }


@router.get("/artifacts/inventory")
def inventory_artifacts(current_user: dict = Depends(get_current_owner_user)):
    """Read-only dry-run inventory of stored draft artifacts.

    Owner-only, same gate as the meeting endpoints. Reports what the
    stage-4 migration *would* do per stored artifact (would migrate
    / already present / unmigrated / failed) with counts only — no
    claim texts, registries, or tables. This endpoint cannot write:
    it calls only the pure inventory function, which has no write
    code path. Migration execution is a separate authorization and
    never happens through this route.
    """
    return inventory_store_dir(get_build_room_store_dir())


class MigrateBody(BaseModel):
    """Explicit confirmation gate for migration execution."""

    confirm: bool = False


@router.post("/artifacts/migrate")
def migrate_artifacts(
    body: MigrateBody, current_user: dict = Depends(get_current_owner_user)
):
    """Execute the stage-4 migration against stored draft artifacts.

    Owner-only, same gate as the meeting endpoints, plus an
    explicit ``{"confirm": true}`` body — without it, 400 and
    nothing happens. The execution itself (design v2) is
    backup-first with a verified SHA-256 manifest, exclusive
    lock, pre-write and post-write invariant verification, and
    collection-level fail-closed reporting; it never touches the
    feature flag and never deletes anything. A held lock answers
    409; a completed, aborted, or partially completed run answers
    200 with its top-level ``status`` carrying the outcome — HTTP
    200 alone never means every artifact migrated.
    """
    if body.confirm is not True:
        raise HTTPException(
            status_code=400,
            detail="migration requires explicit confirmation: {\"confirm\": true}",
        )
    report = execute_migration(get_build_room_store_dir())
    if report.get("lock_held"):
        raise HTTPException(status_code=409, detail=report)
    return report


# ---------------------------------------------------------------- Moneyball
# program run (role-only comparison, code PR #272 program runner).
#
# The program runner is an in-process harness with no CLI: this endpoint
# is its ONLY invocation surface. Six meetings take far longer than one
# synchronous HTTP request, so POST starts a daemon thread (the
# codebase's established background pattern, e.g. demo_routes council
# memory refresh) and returns a run id immediately; GET /program/status
# reports progress from the persistent ProgramLedger, which is the sole
# source of truth for cumulative reservations. The ledger is single-shot
# by design: a second start after any meeting is recorded answers 409,
# because re-running under the same ledger would double-count the cap.
# A fresh program needs a fresh ledger path, which is a new review, not
# something this endpoint does on its own.
#
# Single-process assumption: the active-run guard is in-memory. Staging
# runs one uvicorn process (no --workers flag in the Dockerfile CMD),
# so the guard is sound there; a multi-worker deployment would need a
# shared lock before this endpoint is used. After a server restart the
# in-memory record is gone by design and status derives state from the
# ledger alone (completed / interrupted / not_started).
#
# This endpoint runs NOTHING on deploy, on import, or on any GET. It
# does not change the /meetings or /meetings/r2 routes.


def _program_ledger_path(store: Path) -> Path:
    return store / "moneyball_program_ledger.json"


def _read_program_ledger(ledger_path: Path) -> dict | None:
    """The ledger JSON, or None when no program has recorded anything.

    A present-but-unreadable ledger is a server problem, not a client
    error: 500, never a silent fresh start (which would reset the cap).
    """
    if not ledger_path.exists():
        return None
    try:
        data = json.loads(ledger_path.read_text(encoding="utf-8"))
    except (ValueError, OSError) as exc:
        raise HTTPException(
            status_code=500,
            detail=f"moneyball program ledger unreadable: {exc}",
        )
    if not isinstance(data, dict):
        raise HTTPException(
            status_code=500,
            detail="moneyball program ledger is not a JSON object",
        )
    return data


def _run_moneyball_program_thread(specs, *, cap_usd: float, ledger_path: Path, store_dir: Path) -> None:
    """Background thread body: run the program, record how it ended."""
    try:
        result = run_program(
            specs,
            cap_usd=cap_usd,
            ledger_path=ledger_path,
            store_dir=store_dir,
        )
        moneyball_program.PROGRAM_TRACKER.finish(
            result_status=result.status, reason=result.reason
        )
    except Exception as exc:  # never die silently; status reports it
        moneyball_program.PROGRAM_TRACKER.finish(
            error=f"{type(exc).__name__}: {exc}"
        )


class ProgramRunBody(BaseModel):
    """Start the fixed six-meeting program. cap_usd is REQUIRED: pydantic
    refuses a missing cap (422) and a non-positive cap (422); there is
    no default and no hardcoded figure anywhere in this module."""

    cap_usd: float = Field(..., gt=0)
    confirm: bool = False


@router.post("/program/run", status_code=202)
def run_moneyball_program_route(
    body: ProgramRunBody, current_user: dict = Depends(get_current_owner_user)
):
    """Start the Moneyball role-only program in the background.

    Owner-only, caller principal (spend follows the caller, exactly
    like the existing routes), explicit ``{"confirm": true}`` required.
    Returns a run id immediately; the six meetings run sequentially in
    a daemon thread under the caller-supplied cap. No key values appear
    in the response (work-item titles only).
    """
    if body.confirm is not True:
        raise HTTPException(
            status_code=400,
            detail="program run requires explicit confirmation: {\"confirm\": true}",
        )
    if pricing_expired(CAP_PRICING_DEFAULT_EXPIRY):
        raise HTTPException(
            status_code=400,
            detail=(
                f"pricing table expired {CAP_PRICING_DEFAULT_EXPIRY}; "
                "admission fails closed until the table is refreshed. "
                "No meeting started."
            ),
        )
    store = get_build_room_store_dir()
    ledger_path = _program_ledger_path(store)
    ledger = _read_program_ledger(ledger_path)
    if ledger is not None:
        recorded = ledger.get("meetings") or []
        if recorded:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"moneyball program already run: ledger holds "
                    f"{len(recorded)} meeting(s); refusing a second run "
                    "under the same ledger"
                ),
            )
        if float(ledger.get("cap_usd", body.cap_usd)) != float(body.cap_usd):
            raise HTTPException(
                status_code=409,
                detail=(
                    "moneyball program ledger cap mismatch: refusing to "
                    "mix programs under different caps"
                ),
            )
    run_id = moneyball_program.new_run_id()
    if not moneyball_program.PROGRAM_TRACKER.try_start(run_id):
        raise HTTPException(
            status_code=409,
            detail="a moneyball program run is already active",
        )
    try:
        specs = moneyball_program.build_program_specs(
            authenticated_account_principal(current_user["id"])
        )
    except ValueError as exc:
        moneyball_program.PROGRAM_TRACKER.finish(error=f"ValueError: {exc}")
        raise HTTPException(
            status_code=500,
            detail=f"moneyball program packet invalid: {exc}",
        )
    thread = threading.Thread(
        target=_run_moneyball_program_thread,
        args=(specs,),
        kwargs={
            "cap_usd": body.cap_usd,
            "ledger_path": ledger_path,
            "store_dir": store,
        },
        name="moneyball-program-run",
        daemon=True,
    )
    thread.start()
    return {
        "run_id": run_id,
        "state": "started",
        "cap_usd": body.cap_usd,
        "meetings": moneyball_program.program_plan(),
    }


@router.get("/program/status")
def moneyball_program_status(
    current_user: dict = Depends(get_current_owner_user),
):
    """Report the Moneyball program's progress from the ledger.

    Owner-only. No key values, no server paths: meeting ids, conditions,
    and dollar figures only. State derivation: a live thread means
    running; a finished thread reports its outcome; with no in-memory
    record (e.g. after a restart) the ledger alone decides — 6 meetings
    means completed, 1–5 means interrupted, none means not started.
    """
    store = get_build_room_store_dir()
    ledger = _read_program_ledger(_program_ledger_path(store))
    recorded = (ledger or {}).get("meetings") or []
    cap_usd = (ledger or {}).get("cap_usd")
    cumulative = float((ledger or {}).get("cumulative_reserved_usd", 0.0))
    tracker = moneyball_program.PROGRAM_TRACKER.snapshot()
    meetings = [
        {
            "meeting_id": m.get("meeting_id"),
            "packet_work_item": m.get("packet_work_item"),
            "condition": m.get("condition"),
            "ok": m.get("ok"),
            "allocation_usd": m.get("allocation_usd"),
            "committed_usd": m.get("committed_usd"),
        }
        for m in recorded
    ]
    if tracker is not None and tracker["state"] == "running":
        state = "running"
        run_id = tracker["run_id"]
        result_status = None
        reason = None
        error = None
    elif tracker is not None and tracker["state"] == "finished":
        run_id = tracker["run_id"]
        result_status = tracker["result_status"]
        reason = tracker["reason"]
        error = tracker["error"]
        if error:
            state = "error"
        elif result_status == "completed":
            state = "completed"
        elif result_status == "stopped":
            state = "stopped"
        elif result_status == "refused":
            state = "refused"
        else:
            state = "finished"
    elif not recorded:
        state = "not_started"
        run_id = None
        result_status = None
        reason = None
        error = None
    elif len(recorded) >= moneyball_program.PROGRAM_MEETING_COUNT:
        state = "completed"
        run_id = None
        result_status = "completed"
        reason = None
        error = None
    else:
        state = "interrupted"
        run_id = None
        result_status = None
        reason = None
        error = None
    return {
        "state": state,
        "run_id": run_id,
        "cap_usd": cap_usd,
        "cumulative_reserved_usd": cumulative,
        "remaining_usd": (
            round(float(cap_usd) - cumulative, 6) if cap_usd is not None else None
        ),
        "meetings_completed": len(recorded),
        "meetings": meetings,
        "result_status": result_status,
        "reason": reason,
        "error": error,
    }


# Convener-only capture retrieval (Moneyball program, code PR: captures
# endpoint). GET /program/captures returns this program's ledger
# meetings in ledger order, each with its deterministic capture record
# (claim_registry, base_prompt_hashes, role_brief_version, cap_budget,
# transcript serialization) as written by the program runner.
#
# Why this route exists: GET /program/status returns ids, conditions,
# and dollars only, and no other route serves capture contents, so the
# blind evaluation (comparison_eval.py: strip + sheet + views) could
# not retrieve the claim sets it scores. This route is the unblocker.
#
# Paging extension (why: the full response is ~2 MB and a browser
# text view caps at 256 KB, so the full pull cannot be read; a
# per-meeting pull alone is still ~200-280 KB for the largest
# meeting). Optional query parameters, backward compatible — a
# request with no parameters returns exactly the shape this route
# has always returned:
# - ?meeting_id=<id>: return only that meeting's entry, same fields
#   as the unfiltered entry, full capture intact. Unknown id -> 404
#   naming the id. A filtered request reads ONLY the selected
#   meeting's capture; a missing capture for an unselected meeting
#   does not fail it (the no-params request still reads all and
#   still fails on any missing capture — see below).
# - ?claim_offset=<n>&claim_limit=<m>, only together with
#   meeting_id (without it -> 400): paginate WITHIN that meeting's
#   claim_registry only. The returned capture is a copy with
#   claim_registry replaced by the requested slice; every other
#   capture field stays complete. Either parameter may be given
#   alone: a missing offset defaults to 0, a missing limit defaults
#   to the rest of the registry. The entry additionally carries
#   claim_total, claim_offset, and claim_limit (the EFFECTIVE
#   values after defaulting), so the caller can page to completion
#   deterministically. Offset beyond the total -> an empty slice
#   with the total, not an error. Negative offset/limit -> 400.
#   Recommended page size: ~40 claims (see the paging tests: the
#   largest staging meeting holds 113 claims, so 40/40/33 pages it
#   in three reads, each far under the 256 KB view cap; any page
#   size reconstructs the registry exactly, so shrink freely if a
#   page still clips).
# - meetings_completed always equals len(meetings) in the response,
#   filtered or not; cap_usd and cumulative_reserved_usd always
#   describe the whole program ledger.
#
# Boundaries, all load-bearing:
# - Owner-only via the SAME gate as /program/status and /program/run
#   (get_current_owner_user, 403 "Build-room meetings are owner-only").
#   Captures carry condition and brief seats, which must never reach
#   judges unblinded — this route serves the CONVENER's retrieval only.
#   Blinded judge sheets are produced separately by comparison_eval.py,
#   never by this route.
# - Read-only by construction: GET only, no writes, no run/start/stop
#   capability, no ledger mutation, no file writes. Calling it twice
#   returns the same bytes and changes nothing.
# - This program's ledger only: no cross-program reads. Capture paths
#   are DERIVED from the ledger's meeting_id under the store dir (the
#   runner's naming scheme), never taken from ledger path strings —
#   a ledger path value is never opened, so no server path leaks
#   into the response either. A filtered meeting_id is looked up in
#   the ledger first, so only ledger-recorded ids ever reach path
#   derivation.
# - Transcript/artifact files are NOT read: no transcript.json or
#   draft_artifact.json contents appear here, only the capture
#   record the runner wrote.
# - Failure is explicit, never partial: a missing ledger is 404; a
#   missing, unreadable, or malformed capture for ANY recorded meeting
#   is 500 naming that meeting on the unfiltered request, and for the
#   SELECTED meeting on a filtered request — the response never
#   silently omits a meeting or substitutes another program's data.


def _capture_path_for(store: Path, meeting_id: str) -> Path:
    """The runner's capture filename for one ledger meeting_id.

    Meeting ids are runner-generated hex; anything containing a path
    separator is ledger corruption, not a meeting — refuse it rather
    than resolving a path outside the store dir.
    """
    if not meeting_id or "/" in meeting_id or "\\" in meeting_id:
        raise HTTPException(
            status_code=500,
            detail=f"moneyball program ledger has invalid meeting_id: {meeting_id!r}",
        )
    return store / f"meeting_{meeting_id}.comparison_capture.json"


def _read_meeting_capture(capture_path: Path, meeting_id: str) -> dict:
    """One meeting's parsed capture record, or an explicit 500."""
    if not capture_path.exists():
        raise HTTPException(
            status_code=500,
            detail=(
                f"moneyball program capture missing for meeting "
                f"{meeting_id}: {capture_path.name} not found"
            ),
        )
    try:
        data = json.loads(capture_path.read_text(encoding="utf-8"))
    except (ValueError, OSError) as exc:
        raise HTTPException(
            status_code=500,
            detail=(
                f"moneyball program capture unreadable for meeting "
                f"{meeting_id}: {exc}"
            ),
        )
    if not isinstance(data, dict):
        raise HTTPException(
            status_code=500,
            detail=(
                f"moneyball program capture is not a JSON object for "
                f"meeting {meeting_id}"
            ),
        )
    return data


@router.get("/program/captures")
def moneyball_program_captures(
    meeting_id: str | None = None,
    claim_offset: int | None = None,
    claim_limit: int | None = None,
    current_user: dict = Depends(get_current_owner_user),
):
    """Return this program's meetings with their capture records.

    Owner-only, read-only. No parameters: ledger order, ledger
    summary fields per meeting, plus each meeting's full
    comparison_capture.json contents under "capture" — exactly the
    shape this route has always returned. With ?meeting_id: only
    that meeting's entry (404 naming an unknown id). With
    claim_offset/claim_limit (meeting_id required, else 400): the
    returned capture's claim_registry holds just that slice, and
    the entry additionally carries claim_total, claim_offset, and
    claim_limit (effective values after defaulting). A missing
    ledger is 404; any missing or broken capture fails the whole
    request (500) rather than returning partial data.
    """
    paging = claim_offset is not None or claim_limit is not None
    if paging and meeting_id is None:
        raise HTTPException(
            status_code=400,
            detail=(
                "claim_offset/claim_limit require meeting_id: paging "
                "applies within one meeting's claim_registry"
            ),
        )
    if claim_offset is not None and claim_offset < 0:
        raise HTTPException(
            status_code=400,
            detail=f"claim_offset must not be negative: {claim_offset}",
        )
    if claim_limit is not None and claim_limit < 0:
        raise HTTPException(
            status_code=400,
            detail=f"claim_limit must not be negative: {claim_limit}",
        )
    store = get_build_room_store_dir()
    ledger = _read_program_ledger(_program_ledger_path(store))
    if ledger is None:
        raise HTTPException(
            status_code=404,
            detail="moneyball program ledger not found: no program recorded",
        )
    recorded = ledger.get("meetings") or []
    if not isinstance(recorded, list):
        raise HTTPException(
            status_code=500,
            detail="moneyball program ledger meetings is not a list",
        )
    if meeting_id is not None:
        recorded = [m for m in recorded if m.get("meeting_id") == meeting_id]
        if not recorded:
            raise HTTPException(
                status_code=404,
                detail=(
                    "moneyball program meeting not found in ledger: "
                    f"{meeting_id}"
                ),
            )
    meetings = []
    for m in recorded:
        selected_id = m.get("meeting_id")
        capture = _read_meeting_capture(
            _capture_path_for(store, selected_id), selected_id
        )
        entry = {
            "meeting_id": selected_id,
            "packet_work_item": m.get("packet_work_item"),
            "condition": m.get("condition"),
            "ok": m.get("ok"),
            "allocation_usd": m.get("allocation_usd"),
            "committed_usd": m.get("committed_usd"),
            "capture": capture,
        }
        if paging:
            registry = capture.get("claim_registry")
            if not isinstance(registry, list):
                raise HTTPException(
                    status_code=500,
                    detail=(
                        "moneyball program capture has no claim_registry "
                        f"list for meeting {selected_id}"
                    ),
                )
            total = len(registry)
            offset = claim_offset if claim_offset is not None else 0
            limit = (
                claim_limit
                if claim_limit is not None
                else max(0, total - offset)
            )
            sliced = dict(capture)
            sliced["claim_registry"] = registry[offset:offset + limit]
            entry["capture"] = sliced
            entry["claim_total"] = total
            entry["claim_offset"] = offset
            entry["claim_limit"] = limit
        meetings.append(entry)
    return {
        "cap_usd": ledger.get("cap_usd"),
        "cumulative_reserved_usd": float(
            ledger.get("cumulative_reserved_usd", 0.0)
        ),
        "meetings_completed": len(meetings),
        "meetings": meetings,
    }


