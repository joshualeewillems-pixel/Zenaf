#!/usr/bin/env python3
"""
Safe fresh-start reset for Vision Execution SQLite data (per user).

Does NOT touch: users, sessions, persons, assets, capacity_profiles,
user_llm_profile, user_llm_provider_credentials, user_notification_settings,
user_permissions_settings (unless you add a future flag).

Database file (default): data/vision_execution/vision_execution.db
Override: --db PATH or env ZENAF_VE_DB

Usage (repo root, API stopped recommended):
  python scripts/reset_vision_execution.py --mode graph --user-email owner@local.zenaf --dry-run
  python scripts/reset_vision_execution.py --mode workspace --user-email owner@local.zenaf --apply --confirm RESET

Phil (local dev emails are phil@local.zenaf / phil@local.atria — not phil@zenaf):
  python scripts/reset_vision_execution.py --mode workspace --user-email phil@local.zenaf --apply --confirm RESET --reseed doc

After reset, reseed (pick one), with optional --user-email on each seed script:
  python scripts/seed_vision_execution_from_repo_docs.py --user-email phil@local.zenaf
  python scripts/seed_vision_execution_active_now.py --user-email phil@local.zenaf
  python scripts/seed_vision_execution.py --user-email phil@local.zenaf

Or pass --reseed doc|active|demo with --apply: the seed runs as the same account you reset,
unless you override with --reseed-user-email EMAIL.

LLM API keys live in user_llm_provider_credentials (not wiped by this script). To copy keys between accounts:
  python scripts/port_user_llm_stack.py inspect
  python scripts/port_user_llm_stack.py apply --from owner@local.atria --to owner@local.zenaf --confirm PORT
"""
from __future__ import annotations

import argparse
import os
import shutil
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_DB = _REPO_ROOT / "data" / "vision_execution" / "vision_execution.db"
_BACKUP_DIR = _REPO_ROOT / "data" / "vision_execution" / "backups"

def resolve_db_path(explicit: str | None) -> Path:
    if explicit:
        return Path(explicit).expanduser().resolve()
    env = os.environ.get("ZENAF_VE_DB", "").strip()
    if env:
        return Path(env).expanduser().resolve()
    return _DEFAULT_DB.resolve()


def resolve_user_id(conn: sqlite3.Connection, email: str | None, user_id: str | None) -> str:
    if user_id:
        row = conn.execute("SELECT id FROM users WHERE id = ?", (user_id,)).fetchone()
        if not row:
            raise SystemExit(f"No users.id = {user_id!r}")
        return user_id
    if not email:
        raise SystemExit("Provide --user-email or --user-id")
    row = conn.execute("SELECT id FROM users WHERE email = ?", (email.strip(),)).fetchone()
    if not row:
        raise SystemExit(f"No user with email {email!r}")
    return str(row[0])


def _count(conn: sqlite3.Connection, sql: str, params: tuple) -> int:
    return int(conn.execute(sql, params).fetchone()[0])


# (label, delete_sql, count_sql) — all use single param (user_id,)
MODE_GRAPH_STEPS: list[tuple[str, str, str]] = [
    (
        "execution_steps",
        "DELETE FROM execution_steps WHERE user_id = ?",
        "SELECT COUNT(*) FROM execution_steps WHERE user_id = ?",
    ),
    (
        "tasks",
        "DELETE FROM tasks WHERE user_id = ?",
        "SELECT COUNT(*) FROM tasks WHERE user_id = ?",
    ),
    (
        "projects",
        "DELETE FROM projects WHERE user_id = ?",
        "SELECT COUNT(*) FROM projects WHERE user_id = ?",
    ),
    (
        "initiative_seats (for user's initiatives)",
        "DELETE FROM initiative_seats WHERE initiative_id IN (SELECT id FROM initiatives WHERE user_id = ?)",
        "SELECT COUNT(*) FROM initiative_seats WHERE initiative_id IN (SELECT id FROM initiatives WHERE user_id = ?)",
    ),
    (
        "initiatives",
        "DELETE FROM initiatives WHERE user_id = ?",
        "SELECT COUNT(*) FROM initiatives WHERE user_id = ?",
    ),
    (
        "ideas",
        "DELETE FROM ideas WHERE user_id = ?",
        "SELECT COUNT(*) FROM ideas WHERE user_id = ?",
    ),
    (
        "core_profiles",
        "DELETE FROM core_profiles WHERE user_id = ?",
        "SELECT COUNT(*) FROM core_profiles WHERE user_id = ?",
    ),
]

# Extra steps for mode workspace (user-scoped adjunct + council workspace JSON)
MODE_WORKSPACE_EXTRA: list[tuple[str, str, str]] = [
    (
        "node_vitality",
        "DELETE FROM node_vitality WHERE user_id = ?",
        "SELECT COUNT(*) FROM node_vitality WHERE user_id = ?",
    ),
    (
        "node_judgment_history",
        "DELETE FROM node_judgment_history WHERE user_id = ?",
        "SELECT COUNT(*) FROM node_judgment_history WHERE user_id = ?",
    ),
    (
        "arc_detection_candidates",
        "DELETE FROM arc_detection_candidates WHERE user_id = ?",
        "SELECT COUNT(*) FROM arc_detection_candidates WHERE user_id = ?",
    ),
    (
        "council_stream_runs",
        "DELETE FROM council_stream_runs WHERE user_id = ?",
        "SELECT COUNT(*) FROM council_stream_runs WHERE user_id = ?",
    ),
    (
        "council_teacher_runs",
        "DELETE FROM council_teacher_runs WHERE user_id = ?",
        "SELECT COUNT(*) FROM council_teacher_runs WHERE user_id = ?",
    ),
    (
        "prompt_signals",
        "DELETE FROM prompt_signals WHERE user_id = ?",
        "SELECT COUNT(*) FROM prompt_signals WHERE user_id = ?",
    ),
    (
        "decisions",
        "DELETE FROM decisions WHERE user_id = ?",
        "SELECT COUNT(*) FROM decisions WHERE user_id = ?",
    ),
    (
        "content_briefs",
        "DELETE FROM content_briefs WHERE user_id = ?",
        "SELECT COUNT(*) FROM content_briefs WHERE user_id = ?",
    ),
    (
        "aspiration_inference_log",
        "DELETE FROM aspiration_inference_log WHERE user_id = ?",
        "SELECT COUNT(*) FROM aspiration_inference_log WHERE user_id = ?",
    ),
    (
        "aspiration_proposals",
        "DELETE FROM aspiration_proposals WHERE user_id = ?",
        "SELECT COUNT(*) FROM aspiration_proposals WHERE user_id = ?",
    ),
    (
        "aspiration_profile",
        "DELETE FROM aspiration_profile WHERE user_id = ?",
        "SELECT COUNT(*) FROM aspiration_profile WHERE user_id = ?",
    ),
    (
        "seat_requests",
        "DELETE FROM seat_requests WHERE user_id = ?",
        "SELECT COUNT(*) FROM seat_requests WHERE user_id = ?",
    ),
    (
        "capability_offers",
        "DELETE FROM capability_offers WHERE user_id = ?",
        "SELECT COUNT(*) FROM capability_offers WHERE user_id = ?",
    ),
    (
        "material_requests",
        "DELETE FROM material_requests WHERE user_id = ?",
        "SELECT COUNT(*) FROM material_requests WHERE user_id = ?",
    ),
    (
        "material_offers",
        "DELETE FROM material_offers WHERE user_id = ?",
        "SELECT COUNT(*) FROM material_offers WHERE user_id = ?",
    ),
    (
        "user_council_workspace",
        "DELETE FROM user_council_workspace WHERE user_id = ?",
        "SELECT COUNT(*) FROM user_council_workspace WHERE user_id = ?",
    ),
]


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    r = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (table,),
    ).fetchone()
    return r is not None


def _filter_steps(conn: sqlite3.Connection, steps: list[tuple[str, str, str]]) -> list[tuple[str, str, str]]:
    out: list[tuple[str, str, str]] = []
    for label, del_sql, cnt_sql in steps:
        # Infer table name from DELETE line (first token after FROM)
        parts = del_sql.split()
        try:
            fi = parts.index("FROM")
            tname = parts[fi + 1]
        except (ValueError, IndexError):
            tname = ""
        if tname and not _table_exists(conn, tname):
            continue
        out.append((label, del_sql, cnt_sql))
    return out


def backup_db(db: Path) -> Path:
    _BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    dest = _BACKUP_DIR / f"vision_execution_pre_reset_{ts}.db"
    shutil.copy2(db, dest)
    return dest


def run_reseed(kind: str, seed_user_email: str) -> None:
    scripts = {
        "doc": _REPO_ROOT / "scripts" / "seed_vision_execution_from_repo_docs.py",
        "active": _REPO_ROOT / "scripts" / "seed_vision_execution_active_now.py",
        "demo": _REPO_ROOT / "scripts" / "seed_vision_execution.py",
    }
    path = scripts.get(kind)
    if not path or not path.is_file():
        raise SystemExit(f"Unknown reseed {kind!r}")
    email = (seed_user_email or "").strip()
    if not email:
        raise SystemExit(
            "Reseed needs a target email: use --user-email on reset, or pass --reseed-user-email."
        )
    print(f"\nRunning reseed: {path.name} --user-email {email!r}")
    r = subprocess.run(
        [sys.executable, str(path), "--user-email", email],
        cwd=str(_REPO_ROOT),
    )
    if r.returncode != 0:
        raise SystemExit(f"Reseed failed with exit code {r.returncode}")


def main() -> None:
    p = argparse.ArgumentParser(description="Reset Vision Execution data for one user (with backup).")
    p.add_argument("--db", help="Path to vision_execution.db")
    p.add_argument(
        "--mode",
        choices=("graph", "workspace"),
        required=True,
        help="graph = ideas/initiatives/projects/tasks/steps/core_profiles only; "
        "workspace = graph + vitality/judgments/council/prompts/decisions/briefs/aspiration/collab/user_council_workspace",
    )
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--user-email", help="User email (e.g. owner@local.zenaf)")
    g.add_argument("--user-id", help="users.id UUID")
    p.add_argument("--dry-run", action="store_true", help="Show row counts only; no backup or writes")
    p.add_argument("--apply", action="store_true", help="Perform reset (requires --confirm RESET)")
    p.add_argument(
        "--confirm",
        help='Must be exactly "RESET" when using --apply',
    )
    p.add_argument(
        "--reseed",
        choices=("doc", "active", "demo", "none"),
        default="none",
        help="After successful --apply, run a seed script for the same user as --user-email (default: none)",
    )
    p.add_argument(
        "--reseed-user-email",
        help="Override which account receives --reseed (default: same as reset target)",
    )
    p.add_argument("--no-backup", action="store_true", help="Skip file copy backup (not recommended)")
    args = p.parse_args()

    if args.apply and args.confirm != "RESET":
        raise SystemExit('Refusing to apply without --confirm RESET')

    db = resolve_db_path(args.db)
    if not db.is_file():
        raise SystemExit(f"Database not found: {db}")

    conn = sqlite3.connect(str(db))
    try:
        uid = resolve_user_id(conn, args.user_email, args.user_id)
        email_row = conn.execute("SELECT email FROM users WHERE id = ?", (uid,)).fetchone()
        email_disp = email_row[0] if email_row else "?"

        steps = list(MODE_GRAPH_STEPS)
        if args.mode == "workspace":
            steps.extend(MODE_WORKSPACE_EXTRA)
        steps = _filter_steps(conn, steps)

        print(f"Database: {db}")
        print(f"Target user: {uid} ({email_disp})")
        print(f"Mode: {args.mode}")
        print()

        total = 0
        for label, _del_sql, cnt_sql in steps:
            n = _count(conn, cnt_sql, (uid,))
            print(f"  {label}: {n} row(s)")
            total += n

        if args.dry_run:
            print(f"\nDry-run only — would delete {total} row(s) total.")
            return

        if not args.apply:
            raise SystemExit("Specify --dry-run or --apply --confirm RESET")

        if not args.no_backup:
            dest = backup_db(db)
            print(f"\nBackup written: {dest}")
        else:
            print("\nWARNING: --no-backup set; no file copy made.")

        conn.execute("PRAGMA foreign_keys = ON")
        try:
            conn.execute("BEGIN IMMEDIATE")
            deleted = 0
            for label, del_sql, _cnt_sql in steps:
                cur = conn.execute(del_sql, (uid,))
                n = cur.rowcount
                if n:
                    print(f"  deleted {label}: {n}")
                deleted += n
            conn.execute("COMMIT")
            print(f"\nDone. Rows deleted (reported): {deleted}")
        except sqlite3.Error as e:
            conn.execute("ROLLBACK")
            print(f"Rolled back: {e}", file=sys.stderr)
            raise SystemExit(1) from e
    finally:
        conn.close()

    if args.reseed != "none":
        seed_email = (args.reseed_user_email or "").strip() or str(email_disp)
        if not seed_email or seed_email == "?":
            raise SystemExit(
                "Cannot --reseed without a target email: set --reseed-user-email or reset with --user-email."
            )
        run_reseed(args.reseed, seed_email)


if __name__ == "__main__":
    main()
