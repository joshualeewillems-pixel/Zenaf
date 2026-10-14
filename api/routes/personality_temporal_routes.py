"""Phase 5: temporal modeling API — signal decay, snapshots, era addressing.

Snapshots are insert-only archives of published profile versions. They are
created solely by the three sanctioned triggers:
  - manual: POST /personality/snapshots ("snapshot this era")
  - volume: POST /personality/snapshots/check-triggers (or a scheduler
    calling run_temporal_maintenance) after substantial training volume
  - annual: same check path, per the annual-cadence policy

There is no update or delete route for snapshots, by design.

Writes (manual snapshot, check-triggers) need the user's explicit
train:self consent scope (default-deny). Reads need session auth only.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from api.routes.auth_routes import get_current_user
from local_ai.personality.store import PersonalityStore
from local_ai.personality.temporal import (
    SNAPSHOT_TRIGGER_MANUAL,
    ProfileSnapshot,
    run_temporal_maintenance,
)

router = APIRouter(prefix="/personality", tags=["personality"])


class SnapshotBody(BaseModel):
    """User-initiated snapshot ("snapshot this era")."""

    era_name: str | None = Field(
        default=None,
        max_length=120,
        description='Optional era label, e.g. "early Zenaf era". Unique per user.',
    )
    note: str = Field(default="", max_length=2000)


def _store(user_id: str | None):
    return PersonalityStore(user_id=user_id)


def _uid(current_user: dict) -> str:
    return current_user["id"]


def _require_train_self(user_id: str) -> None:
    """Snapshot writes need the user's explicit train:self consent (default-deny)."""
    from local_ai.identity import ScopeDenied
    from local_ai.identity.scopes import require_scope

    try:
        require_scope("train:self", user_id=user_id)
    except ScopeDenied:
        raise HTTPException(
            status_code=403,
            detail="Personality snapshots need your 'train:self' consent scope. Grant it in Settings → Identity.",
        )


def _snapshot_meta(snap: ProfileSnapshot) -> dict:
    return {
        "snapshot_id": snap.snapshot_id,
        "version": snap.version,
        "trigger": snap.trigger,
        "era_name": snap.era_name,
        "auto_label": snap.auto_label,
        "note": snap.note,
        "created_at": snap.created_at.isoformat(),
    }


@router.post("/snapshots", status_code=201, response_model=ProfileSnapshot)
def create_snapshot(body: SnapshotBody, current_user: dict = Depends(get_current_user)):
    """Archive the current published profile version as a named era.

    User-initiated trigger. The snapshot is immutable from birth — there is
    no update or delete path. 404 if the user has never published a profile.
    """
    uid = _uid(current_user)
    _require_train_self(uid)
    store = _store(uid)
    try:
        try:
            return store.create_snapshot(
                trigger=SNAPSHOT_TRIGGER_MANUAL,
                era_name=body.era_name,
                note=body.note,
            )
        except ValueError as exc:
            msg = str(exc)
            if "no published profile version" in msg:
                raise HTTPException(status_code=404, detail=msg)
            raise HTTPException(status_code=422, detail=msg)
    finally:
        store.close()


@router.get("/snapshots")
def list_snapshots(current_user: dict = Depends(get_current_user)):
    """List the user's snapshots (metadata only), oldest first.

    Read needs session auth only.
    """
    uid = _uid(current_user)
    store = _store(uid)
    try:
        return {"snapshots": store.list_snapshots()}
    finally:
        store.close()


@router.get("/snapshots/{snapshot_id_or_era}", response_model=ProfileSnapshot)
def get_snapshot(snapshot_id_or_era: str, current_user: dict = Depends(get_current_user)):
    """Fetch one snapshot by id or by era name (id wins on collision).

    Read needs session auth only. This is the era-addressing primitive the
    future era-rental mechanics will build on.
    """
    uid = _uid(current_user)
    store = _store(uid)
    try:
        snap = store.get_snapshot(snapshot_id_or_era)
        if snap is None:
            snap = store.get_snapshot_by_era(snapshot_id_or_era)
        if snap is None:
            raise HTTPException(
                status_code=404,
                detail=f"no snapshot {snapshot_id_or_era!r} (id or era name) for this user",
            )
        return snap
    finally:
        store.close()


@router.post("/snapshots/check-triggers")
def check_snapshot_triggers(current_user: dict = Depends(get_current_user)):
    """Run the automatic snapshot triggers (volume + annual cadence).

    Idempotent: re-running without new training volume creates nothing.
    This is the function a scheduler (e.g. daily cron) should call;
    exposed here for manual runs. Gated on train:self — it can write.
    """
    uid = _uid(current_user)
    _require_train_self(uid)
    store = _store(uid)
    try:
        report = run_temporal_maintenance(store)
        created_ids = [
            report["volume"].get("snapshot_id"),
            report["annual"].get("snapshot_id"),
        ]
        return {
            "volume": report["volume"],
            "annual": report["annual"],
            "snapshots": [
                _snapshot_meta(store.get_snapshot(sid))
                for sid in created_ids
                if sid is not None
            ],
        }
    finally:
        store.close()
