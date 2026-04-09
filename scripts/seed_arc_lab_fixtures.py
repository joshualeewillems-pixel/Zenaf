#!/usr/bin/env python3
"""
Seed synthetic arc-detector fixtures under a dedicated lab user (NOT real user truth).

Creates:
  - User arc_lab_synthetic@local.zenaf (display name marks synthetic lane)
  - One holder initiative + ARC-LAB:* projects with backdated execution_flow_reading rows

Does not touch production owner data except adding the lab user row.

Run from repo root:
  python scripts/seed_arc_lab_fixtures.py
  python scripts/seed_arc_lab_fixtures.py --wipe   # remove prior ARC-LAB projects + judgments for lab user

Env:
  ARC_LAB_SEED_PASSWORD — optional password for new lab user (default dev placeholder)

See: docs/02_ACTIVE_DESIGN/ARC_DETECTION_FIXTURE_SPEC.md
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from local_ai.judgment_substrate import (
    JudgmentMechanism,
    JudgmentObservation,
    JudgmentTrunk,
    JudgmentVerdict,
    SubjectRef,
)
from local_ai.vision_execution import models as M
from local_ai.vision_execution import storage

LAB_EMAIL = "arc_lab_synthetic@local.zenaf"
LAB_DISPLAY = "ARC LAB (synthetic — not real user truth)"
TITLE_PREFIX = "ARC-LAB:"

# Fixed past anchor so stability window vs real "now" passes in eval.
_BASE = datetime(2025, 6, 1, 12, 0, 0, tzinfo=timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


def _flow_trunk(
    *,
    entity_type: str,
    entity_id: str,
    pointer: str,
    impact: str,
    dimension: str,
    confidence: float,
) -> JudgmentTrunk:
    payload = {
        "type": "execution_flow_reading",
        "impact": impact,
        "dimension": dimension,
        "confidence": float(confidence),
    }
    return JudgmentTrunk(
        subject=SubjectRef(entity_type=entity_type, entity_id=entity_id),
        observation=JudgmentObservation(
            pointer=pointer,
            context={
                "pointer_kind": "activity_event",
                "coordination_evidence_source": "zenaf-client-trace",
            },
        ),
        verdict=JudgmentVerdict(kind="execution_flow_reading", payload=payload),
        mechanism=JudgmentMechanism(mode="llm"),
        effect="proposal",
        state="proposed",
    )


def _insert_efr(
    conn,
    *,
    user_id: str,
    entity_type: str,
    entity_id: str,
    at: datetime,
    impact: str,
    dimension: str,
    confidence: float,
    label: str,
) -> str:
    jid = M.new_id()
    ptr = f"arc-lab-{label}-{jid[:8]}"
    trunk = _flow_trunk(
        entity_type=entity_type,
        entity_id=entity_id,
        pointer=ptr,
        impact=impact,
        dimension=dimension,
        confidence=confidence,
    )
    trunk_json = json.dumps(trunk.model_dump(mode="json"), ensure_ascii=False)
    created = _iso(at)
    conn.execute(
        """
        INSERT INTO node_judgment_history (
          id, user_id, entity_type, entity_id, created_at, verdict_kind, effect, state, mechanism_mode,
          observation_pointer, council_stream_run_id, decision_id, intake_judgment_id, trunk_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, NULL, ?)
        """,
        (
            jid,
            user_id,
            entity_type,
            entity_id,
            created,
            "execution_flow_reading",
            trunk.effect,
            trunk.state,
            trunk.mechanism.mode,
            trunk.observation.pointer,
            trunk_json,
        ),
    )
    return jid


def _wipe_lab(conn, user_id: str) -> None:
    rows = conn.execute(
        "SELECT id FROM projects WHERE user_id = ? AND title LIKE ?",
        (user_id, f"{TITLE_PREFIX}%"),
    ).fetchall()
    for (pid,) in rows:
        conn.execute(
            "DELETE FROM node_judgment_history WHERE user_id = ? AND entity_type = 'project' AND entity_id = ?",
            (user_id, pid),
        )
    conn.execute(
        "DELETE FROM projects WHERE user_id = ? AND title LIKE ?",
        (user_id, f"{TITLE_PREFIX}%"),
    )
    conn.commit()


def _ensure_lab_user() -> str:
    u = storage.get_user_by_email(LAB_EMAIL)
    if u:
        return str(u["id"])
    pw = (os.environ.get("ARC_LAB_SEED_PASSWORD") or "arc-lab-dev-not-secret").strip()
    out = storage.create_user_account(LAB_EMAIL, pw, LAB_DISPLAY, is_admin=False)
    uid = str(out["id"])
    conn = storage.get_connection()
    conn.execute(
        "UPDATE users SET display_name = ? WHERE id = ?",
        (LAB_DISPLAY, uid),
    )
    conn.commit()
    return uid


def _create_project(uid: str, initiative_id: str, title: str, status: str) -> str:
    p = storage.create_project(
        M.ProjectCreate(
            initiative_id=initiative_id,
            title=title,
            brief="Synthetic fixture — see ARC_DETECTION_FIXTURE_SPEC.md",
            status=status,
            notes=f"lane=synthetic fixture={title}",
        ),
        uid,
    )
    return str(p["id"])


def _set_project_time(conn, project_id: str, user_id: str, *, updated_at: datetime, status: str | None = None) -> None:
    if status is not None:
        conn.execute(
            "UPDATE projects SET status = ?, updated_at = ? WHERE id = ? AND user_id = ?",
            (status, _iso(updated_at), project_id, user_id),
        )
    else:
        conn.execute(
            "UPDATE projects SET updated_at = ? WHERE id = ? AND user_id = ?",
            (_iso(updated_at), project_id, user_id),
        )
    conn.commit()


def main() -> int:
    p = argparse.ArgumentParser(description="Seed ARC-LAB synthetic detector fixtures.")
    p.add_argument("--wipe", action="store_true", help="Remove existing ARC-LAB:* projects for lab user first")
    args = p.parse_args()

    storage.get_connection()
    conn = storage.get_connection()
    uid = _ensure_lab_user()

    if args.wipe:
        _wipe_lab(conn, uid)

    row = conn.execute(
        "SELECT id FROM initiatives WHERE user_id = ? AND title = ? LIMIT 1",
        (uid, "ARC LAB synthetic holder"),
    ).fetchone()
    if row:
        iid = str(row[0])
    else:
        init = storage.create_initiative(
            M.InitiativeCreate(
                title="ARC LAB synthetic holder",
                brief="Holds ARC-LAB fixture projects only",
                status="Draft",
                notes="lane=synthetic",
            ),
            uid,
        )
        iid = str(init["id"])

    manifest: dict[str, str] = {"user_id": uid, "user_email": LAB_EMAIL, "lane": "synthetic", "projects": {}}

    # --- clean_hit ---
    pid = _create_project(uid, iid, f"{TITLE_PREFIX}clean_hit", "Complete")
    _insert_efr(conn, user_id=uid, entity_type="project", entity_id=pid, at=_BASE, impact="negative", dimension="friction", confidence=0.6, label="avoid")
    _insert_efr(
        conn,
        user_id=uid,
        entity_type="project",
        entity_id=pid,
        at=_BASE + timedelta(days=3),
        impact="positive",
        dimension="capacity",
        confidence=0.6,
        label="pivot",
    )
    _set_project_time(conn, pid, uid, updated_at=_BASE + timedelta(days=10), status="Complete")
    manifest["projects"]["clean_hit"] = pid

    # --- insufficient_span ---
    pid = _create_project(uid, iid, f"{TITLE_PREFIX}insufficient_span", "Complete")
    _insert_efr(conn, user_id=uid, entity_type="project", entity_id=pid, at=_BASE, impact="negative", dimension="friction", confidence=0.6, label="a")
    _insert_efr(
        conn,
        user_id=uid,
        entity_type="project",
        entity_id=pid,
        at=_BASE + timedelta(days=1),
        impact="positive",
        dimension="capacity",
        confidence=0.6,
        label="b",
    )
    _set_project_time(conn, pid, uid, updated_at=_BASE + timedelta(hours=36), status="Complete")
    manifest["projects"]["insufficient_span"] = pid

    # --- unstable_after_completion ---
    pid = _create_project(uid, iid, f"{TITLE_PREFIX}unstable", "Complete")
    _insert_efr(conn, user_id=uid, entity_type="project", entity_id=pid, at=_BASE, impact="negative", dimension="friction", confidence=0.6, label="a")
    _insert_efr(
        conn,
        user_id=uid,
        entity_type="project",
        entity_id=pid,
        at=_BASE + timedelta(days=3),
        impact="positive",
        dimension="capacity",
        confidence=0.6,
        label="b",
    )
    _set_project_time(conn, pid, uid, updated_at=_BASE + timedelta(days=7), status="Complete")
    _insert_efr(
        conn,
        user_id=uid,
        entity_type="project",
        entity_id=pid,
        at=_BASE + timedelta(days=9),
        impact="negative",
        dimension="friction",
        confidence=0.6,
        label="postbad",
    )
    manifest["projects"]["unstable_after_completion"] = pid

    # --- rapid ---
    pid = _create_project(uid, iid, f"{TITLE_PREFIX}rapid", "Complete")
    t0 = _BASE + timedelta(days=40)
    _insert_efr(conn, user_id=uid, entity_type="project", entity_id=pid, at=t0, impact="negative", dimension="friction", confidence=0.6, label="r1")
    _insert_efr(
        conn,
        user_id=uid,
        entity_type="project",
        entity_id=pid,
        at=t0 + timedelta(minutes=20),
        impact="positive",
        dimension="capacity",
        confidence=0.6,
        label="r2",
    )
    _set_project_time(conn, pid, uid, updated_at=t0 + timedelta(hours=2), status="Complete")
    manifest["projects"]["rapid_false_positive_trap"] = pid

    # --- sparse ---
    pid = _create_project(uid, iid, f"{TITLE_PREFIX}sparse", "Complete")
    _set_project_time(conn, pid, uid, updated_at=_BASE + timedelta(days=20), status="Complete")
    manifest["projects"]["sparse_no_flow"] = pid

    # --- not_terminal ---
    pid = _create_project(uid, iid, f"{TITLE_PREFIX}not_terminal", "Draft")
    _insert_efr(conn, user_id=uid, entity_type="project", entity_id=pid, at=_BASE, impact="negative", dimension="friction", confidence=0.6, label="nt1")
    _insert_efr(
        conn,
        user_id=uid,
        entity_type="project",
        entity_id=pid,
        at=_BASE + timedelta(days=4),
        impact="positive",
        dimension="capacity",
        confidence=0.6,
        label="nt2",
    )
    _set_project_time(conn, pid, uid, updated_at=_BASE + timedelta(days=10), status="Draft")
    manifest["projects"]["not_terminal"] = pid

    # --- missing_pivot ---
    pid = _create_project(uid, iid, f"{TITLE_PREFIX}missing_pivot", "Complete")
    _insert_efr(conn, user_id=uid, entity_type="project", entity_id=pid, at=_BASE, impact="negative", dimension="friction", confidence=0.6, label="only")
    _set_project_time(conn, pid, uid, updated_at=_BASE + timedelta(days=8), status="Complete")
    manifest["projects"]["missing_pivot"] = pid

    # --- mixed ---
    pid = _create_project(uid, iid, f"{TITLE_PREFIX}mixed", "Complete")
    _insert_efr(conn, user_id=uid, entity_type="project", entity_id=pid, at=_BASE, impact="negative", dimension="friction", confidence=0.6, label="m1")
    _insert_efr(
        conn,
        user_id=uid,
        entity_type="project",
        entity_id=pid,
        at=_BASE + timedelta(days=1),
        impact="neutral",
        dimension="clarity",
        confidence=0.5,
        label="m_neutral",
    )
    _insert_efr(
        conn,
        user_id=uid,
        entity_type="project",
        entity_id=pid,
        at=_BASE + timedelta(days=5),
        impact="positive",
        dimension="capacity",
        confidence=0.6,
        label="m_pos",
    )
    _set_project_time(conn, pid, uid, updated_at=_BASE + timedelta(days=12), status="Complete")
    manifest["projects"]["mixed_council_shape"] = pid

    out_dir = _REPO / "reports" / "arc_lab"
    out_dir.mkdir(parents=True, exist_ok=True)
    man_path = out_dir / "manifest.json"
    man_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"ARC lab user: {LAB_EMAIL} id={uid}")
    print(f"Wrote {man_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
