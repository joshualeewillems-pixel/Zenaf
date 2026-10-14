"""PersonalityProfile API (Phase 1: the user-defined side).

Pipeline: POST /personality/candidates -> GET /personality/candidates ->
POST /personality/publish (or reject). Nothing becomes a profile version
without an explicit publish — propose() never writes versions.

Writes (propose/publish/reject/seed) need the user's explicit train:self
consent scope (default-deny). Reads need session auth only.

The aspirational defaults (BUILT_IN_PERSONA_DEFINITIONS) are never read,
written, or referenced here.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from api.routes.auth_routes import get_current_user
from local_ai.personality.schema import (
    CandidateOp,
    CandidateStatus,
    PersonalityProfile,
    ProfileCandidate,
)

router = APIRouter(prefix="/personality", tags=["personality"])


class ProposeBody(BaseModel):
    """Propose a candidate profile diff (inert until published)."""

    strand_key: str | None = Field(default=None, description="None = profile-global (voice)")
    ops: list[CandidateOp] = Field(min_length=1)
    source: str = Field(
        min_length=1,
        description=(
            "Where this insight came from — required, so the user sees it when asked "
            'to approve. Canonical values: "distillation", "council_interaction", '
            '"correction", "manual"; namespaced forms allowed, e.g. '
            '"seed:signal:<signal_id>".'
        ),
    )
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    rationale: str = ""


class IdsBody(BaseModel):
    candidate_ids: list[str] = Field(min_length=1)


class PublishBody(BaseModel):
    candidate_ids: list[str] = Field(min_length=1)
    source_summary: str = ""


def _store(user_id: str | None):
    from local_ai.personality.store import PersonalityStore

    return PersonalityStore(user_id=user_id)


def _uid(current_user: dict) -> str:
    return current_user["id"]


def _require_train_self(user_id: str) -> None:
    """Profile writes need the user's explicit train:self consent (default-deny)."""
    from local_ai.identity import ScopeDenied
    from local_ai.identity.scopes import require_scope

    try:
        require_scope("train:self", user_id=user_id)
    except ScopeDenied:
        raise HTTPException(
            status_code=403,
            detail="Personality profile writes need your 'train:self' consent scope. Grant it in Settings → Identity.",
        )


@router.post("/candidates", status_code=201, response_model=ProfileCandidate)
def propose_candidate(body: ProposeBody, current_user: dict = Depends(get_current_user)):
    """Queue a candidate diff for review. Creates no profile version."""
    uid = _uid(current_user)
    _require_train_self(uid)
    try:
        cand = ProfileCandidate(
            candidate_id=f"pc_{uuid.uuid4().hex[:12]}",
            user_id=uid,
            strand_key=body.strand_key,
            ops=body.ops,
            source=body.source,
            confidence=body.confidence,
            rationale=body.rationale,
            created_at=datetime.now(timezone.utc),
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return _store(uid).propose(cand)


@router.get("/candidates", response_model=list[ProfileCandidate])
def list_candidates(
    status: CandidateStatus | None = None,
    current_user: dict = Depends(get_current_user),
):
    uid = _uid(current_user)
    return _store(uid).list_candidates(status=status)


@router.post("/candidates/reject")
def reject_candidates(body: IdsBody, current_user: dict = Depends(get_current_user)):
    uid = _uid(current_user)
    _require_train_self(uid)
    n = _store(uid).reject(body.candidate_ids)
    return {"rejected": n}


@router.post("/publish", response_model=PersonalityProfile)
def publish_profile(body: PublishBody, current_user: dict = Depends(get_current_user)):
    """Publish accepted candidates as a NEW immutable profile version.

    This is the ONLY path that creates profile versions.
    """
    uid = _uid(current_user)
    _require_train_self(uid)
    try:
        profile = _store(uid).publish(
            body.candidate_ids,
            approved_by="user",
            source_summary=body.source_summary,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return profile


@router.get("/profile", response_model=PersonalityProfile | None)
def get_current_profile(current_user: dict = Depends(get_current_user)):
    uid = _uid(current_user)
    return _store(uid).get_current()


@router.get("/versions")
def list_versions(current_user: dict = Depends(get_current_user)):
    uid = _uid(current_user)
    return _store(uid).list_versions()


@router.get("/versions/{version}", response_model=PersonalityProfile | None)
def get_version(version: int, current_user: dict = Depends(get_current_user)):
    uid = _uid(current_user)
    return _store(uid).get_version(version)


@router.post("/seed")
def seed_from_approved_signals(current_user: dict = Depends(get_current_user)):
    """Propose candidates from approved training signals. Never publishes.

    Scoped to import sessions re-anchored under the user's active license.
    """
    uid = _uid(current_user)
    _require_train_self(uid)
    from local_ai.identity.service import get_license
    from local_ai.personality.seed import seed_from_signals
    from local_ai.presence_ingest.store import PresenceStore

    lic = get_license()
    if lic is None or lic.status != "active":
        raise HTTPException(status_code=403, detail="An active identity license is required.")
    signals_store = PresenceStore()

    # Scope to this license's sessions (default-deny: unknown sessions skipped).
    sessions = {s.session_id: s for s in signals_store.list_sessions()}

    class _ScopedSignals:
        def list_signals(self, status: str = "approved"):
            out = []
            for sig in signals_store.list_signals(status=status):
                sess = sessions.get(sig.session_id)
                prov = (sess.provenance if sess else {}) or {}
                if prov.get("license_id") == lic.license_id:
                    out.append(sig)
            return out

    made = seed_from_signals(_store(uid), _ScopedSignals(), uid)
    return {"proposed": len(made), "candidate_ids": [c.candidate_id for c in made]}


class WeightsBody(BaseModel):
    """Per-strand user-side blend weights. null = auto (evidence-scaled)."""

    weights: dict[str, float | None] = Field(
        description="strand_key -> weight in [0.0, 1.0], or null to clear back to auto"
    )


@router.get("/weights")
def get_seat_weights(current_user: dict = Depends(get_current_user)):
    """Per-strand blend weights: configured override, effective weight, evidence depth.

    Reads need session auth only. With no published profile every strand
    reports effective 0.0 (pure aspirational seats).
    """
    from local_ai.personality.blend import default_weight_for_strand, strand_evidence_depth
    from local_ai.strands import strand_keys

    uid = _uid(current_user)
    store = _store(uid)
    try:
        overrides = store.get_weight_overrides()
        profile = store.get_current()
        out: dict[str, dict] = {}
        for key in strand_keys():
            ov = overrides.get(key)
            if profile is None:
                depth, effective = 0.0, 0.0
            else:
                depth = round(strand_evidence_depth(profile, key), 4)
                effective = (
                    default_weight_for_strand(profile, key)
                    if ov is None
                    else max(0.0, min(1.0, float(ov)))
                )
            out[key] = {"configured": ov, "effective": effective, "evidence_depth": depth}
        return {
            "weights": out,
            "profile_version": profile.version if profile else None,
            "version_count": store.version_count(),
        }
    finally:
        store.close()


@router.put("/weights")
def set_seat_weights(body: WeightsBody, current_user: dict = Depends(get_current_user)):
    """Set per-strand user-side blend weight overrides (null = back to auto).

    Gated on train:self like other personality writes — these weights shape
    how much of the user's trained self appears in council seats.
    """
    uid = _uid(current_user)
    _require_train_self(uid)
    store = _store(uid)
    try:
        try:
            return {"overrides": store.set_weight_overrides(body.weights)}
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
    finally:
        store.close()


class CouncilModeBody(BaseModel):
    council_mode: str = Field(description='One of "base", "mirror", "blend"')


@router.get("/council-mode")
def get_council_mode(current_user: dict = Depends(get_current_user)):
    """The user's default council personality mode (which seat version to use).

    Read needs session auth only. System default is "blend".
    """
    uid = _uid(current_user)
    store = _store(uid)
    try:
        return {"council_mode": store.get_council_mode()}
    finally:
        store.close()


@router.put("/council-mode")
def set_council_mode(body: CouncilModeBody, current_user: dict = Depends(get_current_user)):
    """Set the user's default council personality mode.

    Which version of a council seat to use is the user's decision, per
    purpose: "base" (pure aspirational), "mirror" (their trained version),
    or "blend" (weighted). A per-run `council_personality_mode` overrides
    this default. Gated on train:self like other personality writes.
    """
    uid = _uid(current_user)
    _require_train_self(uid)
    store = _store(uid)
    try:
        try:
            return {"council_mode": store.set_council_mode(body.council_mode)}
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
    finally:
        store.close()


@router.get("/builtin-personas")
def get_builtin_personas(current_user: dict = Depends(get_current_user)):
    """The aspirational default persona definitions (single source of truth).

    Read-only. The frontend generates its built-in actor content from these
    at build time (see scripts/codegen_builtin_personas.py) instead of
    carrying a hand-maintained copy. Never mutated by training.
    """
    from local_ai.zenaf_tools import BUILT_IN_PERSONA_DEFINITIONS

    return {
        "personas": {
            key: dict(defn) for key, defn in BUILT_IN_PERSONA_DEFINITIONS.items()
        }
    }


@router.get("/context-dimensions")
def get_context_dimensions(current_user: dict = Depends(get_current_user)):
    """The canonical decision-context envelope: six dimensions, levels each.

    Context conditions the seven strands; it is not a strand itself.
    Every dimension defaults to "unknown" — honest gaps stay visible.
    Internal states (tired, grieving, stressed) are deliberately excluded.
    """
    from local_ai.personality.context import DIMENSIONS, LEVELS

    return {
        "dimensions": {dim: ["unknown", *LEVELS[dim]] for dim in DIMENSIONS},
        "unknown_default": True,
        "note": (
            "Attach to decision-type signals via context_ref['decision_context'], "
            "or pass as 'decision_context' on council runs."
        ),
    }


@router.post("/seed/contextual")
def seed_contextual_fingerprints(current_user: dict = Depends(get_current_user)):
    """Propose context-conditional fingerprint candidates from decision signals.

    Groups approved decision-layer signals carrying a decision_context
    envelope by (strand, envelope) and proposes one candidate per group.
    Never publishes. Scoped to import sessions re-anchored under the
    user's active license.
    """
    uid = _uid(current_user)
    _require_train_self(uid)
    from local_ai.identity.service import get_license
    from local_ai.personality.seed import seed_contextual_fingerprints as _seed_ctx
    from local_ai.presence_ingest.store import PresenceStore

    lic = get_license()
    if lic is None or lic.status != "active":
        raise HTTPException(status_code=403, detail="An active identity license is required.")
    signals_store = PresenceStore()
    sessions = {s.session_id: s for s in signals_store.list_sessions()}

    class _ScopedSignals:
        def list_signals(self, status: str = "approved"):
            out = []
            for sig in signals_store.list_signals(status=status):
                sess = sessions.get(sig.session_id)
                prov = (sess.provenance if sess else {}) or {}
                if prov.get("license_id") == lic.license_id:
                    out.append(sig)
            return out

    store = _store(uid)
    try:
        made = _seed_ctx(store, _ScopedSignals(), uid)
    finally:
        store.close()
    return {"proposed": len(made), "candidate_ids": [c.candidate_id for c in made]}


class DeriveContextBody(BaseModel):
    """Derive a coarse decision envelope from free text (explicit cues only)."""

    text: str = Field(min_length=1, max_length=4000)


@router.post("/context/derive")
def derive_context(body: DeriveContextBody, current_user: dict = Depends(get_current_user)):
    """Derive a decision envelope from text. Conservative: unknown unless
    explicitly cued. Derived metadata — always overridable by an explicit
    context; never a form field."""
    from local_ai.personality.context import derive_decision_context

    ctx = derive_decision_context(body.text)
    return {"decision_context": ctx.model_dump(), "is_empty": ctx.is_empty()}


def _user_approved_signals() -> list:
    """Approved training signals re-anchored under the user's active license.

    Same scoping as the seed endpoints (default-deny: unknown sessions are
    skipped). Read-only difference: no active license yields [] — honest
    zeros, not a 403 — because this feeds a read, and the user's own
    published profile still counts toward depth without a license.
    """
    from local_ai.identity.service import get_license
    from local_ai.presence_ingest.store import PresenceStore

    lic = get_license()
    if lic is None or lic.status != "active":
        return []
    signals_store = PresenceStore()
    sessions = {s.session_id: s for s in signals_store.list_sessions()}
    out = []
    for sig in signals_store.list_signals(status="approved"):
        sess = sessions.get(sig.session_id)
        prov = (sess.provenance if sess else {}) or {}
        if prov.get("license_id") == lic.license_id:
            out.append(sig)
    return out


@router.get("/training-depth")
def get_training_depth(current_user: dict = Depends(get_current_user)):
    """Per-strand visible training depth — the trust metric for future rentals.

    For each of the seven strands: a 0..100 score plus the evidence behind
    it (approved-signal count, published versions touching the strand,
    distinct decision contexts observed, last-evidence timestamp, and the
    four formula components). Zero evidence renders as zero — "not yet
    trained" — never a placeholder. Reads need session auth only.

    Read-only: computes from live stores and mutates nothing. See
    local_ai/personality/depth.py for the documented formula; per-zone
    rollups attach there when the zone taxonomy formalizes.
    """
    from local_ai.personality.depth import compute_training_depth

    uid = _uid(current_user)
    store = _store(uid)
    try:
        profile = store.get_current()
        versions: list = []
        for meta in store.list_versions():
            v = store.get_version(meta["version"])
            if v is not None:
                versions.append((meta["version"], v))
        depths = compute_training_depth(
            signals=_user_approved_signals(),
            profile=profile,
            versions=versions,
        )
        strands = {k: d.to_dict() for k, d in depths.items()}
        voice_published = bool(
            profile is not None
            and (
                (profile.voice.description or "").strip() or profile.voice.tags
            )
        )
        return {
            "strands": strands,
            "voice_published": voice_published,
            "profile_version": profile.version if profile else None,
            "version_count": store.version_count(),
            "computed_at": datetime.now(timezone.utc).isoformat(),
        }
    finally:
        store.close()
