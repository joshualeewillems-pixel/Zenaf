#!/usr/bin/env python3
"""
Reassign Vision Execution SQLite rows from one users.id (OLD) to another (NEW).

- Inspects all tables that have a user_id column (via PRAGMA).
- Prints row counts per user_id.
- Preflight: detects UNIQUE / PK collisions so apply does not partially corrupt.
- Apply runs in a single transaction; rolls back on any error.

Usage (repo root, API stopped recommended):
  python scripts/migrate_ve_user_id.py inspect
  python scripts/migrate_ve_user_id.py inspect --db path/to/vision_execution.db
  python scripts/migrate_ve_user_id.py dry-run --old OLD_UUID --new NEW_UUID
  python scripts/migrate_ve_user_id.py apply --old OLD_UUID --new NEW_UUID

Environment:
  ZENAF_VE_DB  optional path to SQLite file (default: data/vision_execution/vision_execution.db)

Does NOT update `sessions` (would hijack login cookies). Sign in as NEW after migrate.
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_DB = _REPO_ROOT / "data" / "vision_execution" / "vision_execution.db"

# Tables where user_id is the PRIMARY KEY (cannot have two rows; UPDATE may collide).
_PK_USER_ID_TABLES = frozenset(
    {
        "user_llm_profile",
        "user_notification_settings",
        "user_council_workspace",
        "user_permissions_settings",
        "aspiration_profile",
    }
)

# Never reassign: would re-bind session tokens to another account.
_EXCLUDED_TABLES = frozenset({"sessions"})


def resolve_db_path(explicit: str | None) -> Path:
    if explicit:
        return Path(explicit).expanduser().resolve()
    env = os.environ.get("ZENAF_VE_DB", "").strip()
    if env:
        return Path(env).expanduser().resolve()
    return _DEFAULT_DB.resolve()


def connect(db: Path) -> sqlite3.Connection:
    if not db.is_file():
        raise SystemExit(f"Database not found: {db}")
    conn = sqlite3.connect(str(db))
    conn.row_factory = sqlite3.Row
    return conn


def list_tables(conn: sqlite3.Connection) -> list[str]:
    cur = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
    )
    return [r[0] for r in cur.fetchall()]


def table_has_user_id(conn: sqlite3.Connection, table: str) -> bool:
    cur = conn.execute(f'PRAGMA table_info("{table}")')
    return any(row[1] == "user_id" for row in cur.fetchall())


def migratable_tables(conn: sqlite3.Connection) -> list[str]:
    out: list[str] = []
    for t in list_tables(conn):
        if t in _EXCLUDED_TABLES:
            continue
        if table_has_user_id(conn, t):
            out.append(t)
    return out


def cmd_inspect(conn: sqlite3.Connection) -> None:
    print("=== users ===")
    for row in conn.execute("SELECT id, email, display_name, created_at FROM users ORDER BY created_at"):
        print(f"  {row['id']}\t{row['email']}\t{display_name(row)}")

    tables = migratable_tables(conn)
    print(f"\n=== tables with user_id ({len(tables)}) ===")
    print("  " + ", ".join(tables))

    print("\n=== row counts by user_id (non-zero only) ===")
    for t in tables:
        cur = conn.execute(
            f'SELECT user_id, COUNT(*) AS n FROM "{t}" GROUP BY user_id HAVING n > 0 ORDER BY n DESC'
        )
        rows = cur.fetchall()
        if not rows:
            continue
        print(f"\n{t}:")
        for r in rows:
            uid = r["user_id"]
            label = "(NULL)" if uid is None else uid
            print(f"  {label}\t{r['n']}")


def display_name(row: sqlite3.Row) -> str:
    try:
        return (row["display_name"] or "").strip()
    except (KeyError, IndexError):
        return ""


def count_for_user(conn: sqlite3.Connection, table: str, user_id: str) -> int:
    cur = conn.execute(f'SELECT COUNT(*) AS n FROM "{table}" WHERE user_id = ?', (user_id,))
    return int(cur.fetchone()["n"])


def preflight_pk_tables(conn: sqlite3.Connection, old_uid: str, new_uid: str) -> list[str]:
    """Return list of error messages for PK user_id tables."""
    errors: list[str] = []
    for t in _PK_USER_ID_TABLES:
        if t not in migratable_tables(conn):
            continue
        n_old = count_for_user(conn, t, old_uid)
        n_new = count_for_user(conn, t, new_uid)
        if n_old and n_new:
            errors.append(
                f"{t}: both OLD and NEW have a row (PK user_id). "
                f"Resolve manually (merge or remove one row) before apply."
            )
    return errors


def preflight_node_vitality(conn: sqlite3.Connection, old_uid: str, new_uid: str) -> list[str]:
    errors: list[str] = []
    if "node_vitality" not in migratable_tables(conn):
        return errors
    cur = conn.execute(
        """
        SELECT COUNT(*) AS n FROM node_vitality o
        INNER JOIN node_vitality n
          ON n.user_id = ? AND n.entity_type = o.entity_type AND n.entity_id = o.entity_id
        WHERE o.user_id = ?
        """,
        (new_uid, old_uid),
    )
    n_overlap = int(cur.fetchone()["n"])
    if n_overlap:
        errors.append(
            "node_vitality: UNIQUE(user_id, entity_type, entity_id) — "
            f"{n_overlap} overlapping (entity_type, entity_id) pair(s). "
            "Resolve duplicates for NEW before reassigning OLD."
        )
        cur = conn.execute(
            """
            SELECT o.entity_type, o.entity_id FROM node_vitality o
            INNER JOIN node_vitality n
              ON n.user_id = ? AND n.entity_type = o.entity_type AND n.entity_id = o.entity_id
            WHERE o.user_id = ?
            LIMIT 5
            """,
            (new_uid, old_uid),
        )
        for r in cur.fetchall():
            errors.append(f"    overlap entity_type={r['entity_type']!r} entity_id={r['entity_id']!r}")
    return errors


def preflight_arc_candidates(conn: sqlite3.Connection, old_uid: str, new_uid: str) -> list[str]:
    errors: list[str] = []
    if "arc_detection_candidates" not in migratable_tables(conn):
        return errors
    cur = conn.execute(
        """
        SELECT COUNT(*) AS n FROM arc_detection_candidates o
        INNER JOIN arc_detection_candidates n
          ON n.user_id = ? AND n.source_entity_type = o.source_entity_type
          AND n.source_entity_id = o.source_entity_id AND n.heuristic_version = o.heuristic_version
        WHERE o.user_id = ?
        """,
        (new_uid, old_uid),
    )
    n = int(cur.fetchone()["n"])
    if n:
        errors.append(
            f"arc_detection_candidates: {n} UNIQUE collision(s) for (user_id, source_entity_type, "
            "source_entity_id, heuristic_version). Resolve before apply."
        )
    return errors


def preflight_llm_credentials(conn: sqlite3.Connection, old_uid: str, new_uid: str) -> list[str]:
    if "user_llm_provider_credentials" not in migratable_tables(conn):
        return []
    cur = conn.execute(
        """
        SELECT o.provider FROM user_llm_provider_credentials o
        INNER JOIN user_llm_provider_credentials n ON n.user_id = ? AND n.provider = o.provider
        WHERE o.user_id = ?
        """,
        (new_uid, old_uid),
    )
    provs = [r[0] for r in cur.fetchall()]
    if not provs:
        return []
    return [
        "user_llm_provider_credentials: same provider(s) exist for OLD and NEW: "
        + ", ".join(provs)
        + ". UNIQUE(user_id, provider) will fail on UPDATE. Remove or rename NEW's rows first."
    ]


def cmd_dry_run(conn: sqlite3.Connection, old_uid: str, new_uid: str) -> None:
    tables = migratable_tables(conn)
    print("BEGIN TRANSACTION;")
    for t in tables:
        print(f'UPDATE "{t}" SET user_id = {q(new_uid)} WHERE user_id = {q(old_uid)};')
    print("COMMIT;")
    print("\n-- Preflight checks:")
    for msg in (
        preflight_pk_tables(conn, old_uid, new_uid)
        + preflight_node_vitality(conn, old_uid, new_uid)
        + preflight_arc_candidates(conn, old_uid, new_uid)
        + preflight_llm_credentials(conn, old_uid, new_uid)
    ):
        print(f"-- WARNING: {msg}")


def q(s: str) -> str:
    return "'" + s.replace("'", "''") + "'"


def cmd_apply(conn: sqlite3.Connection, old_uid: str, new_uid: str) -> None:
    if old_uid == new_uid:
        raise SystemExit("OLD and NEW must differ.")

    found = {r[0] for r in conn.execute("SELECT id FROM users WHERE id IN (?, ?)", (old_uid, new_uid))}
    if old_uid not in found:
        raise SystemExit(f"OLD user id not in users table: {old_uid}")
    if new_uid not in found:
        raise SystemExit(f"NEW user id not in users table: {new_uid}")

    issues = (
        preflight_pk_tables(conn, old_uid, new_uid)
        + preflight_node_vitality(conn, old_uid, new_uid)
        + preflight_arc_candidates(conn, old_uid, new_uid)
        + preflight_llm_credentials(conn, old_uid, new_uid)
    )
    if issues:
        print("Preflight failed — fix the following, then retry:\n", file=sys.stderr)
        for m in issues:
            print(f"  - {m}", file=sys.stderr)
        raise SystemExit(1)

    tables = migratable_tables(conn)
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        conn.execute("BEGIN IMMEDIATE")
        total = 0
        for t in tables:
            cur = conn.execute(f'UPDATE "{t}" SET user_id = ? WHERE user_id = ?', (new_uid, old_uid))
            n = cur.rowcount
            if n:
                print(f"  {t}: {n} row(s) updated")
            total += n
        conn.execute("COMMIT")
        print(f"\nDone. Total rows touched: {total}")
        print("Restart API; sign in as NEW user; hard-refresh browser.")
    except sqlite3.Error as e:
        conn.execute("ROLLBACK")
        print(f"Rolled back: {e}", file=sys.stderr)
        raise SystemExit(1) from e


def main() -> None:
    p = argparse.ArgumentParser(description="Migrate Vision Execution user_id between accounts.")
    p.add_argument("--db", help="Path to vision_execution.db (default: env ZENAF_VE_DB or data/.../vision_execution.db)")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("inspect", help="List users and per-table user_id counts")

    dr = sub.add_parser("dry-run", help="Print SQL only (no changes)")
    dr.add_argument("--old", required=True, dest="old_uid", help="users.id that currently owns the data")
    dr.add_argument("--new", required=True, dest="new_uid", help="users.id for the account you log in as")

    ap = sub.add_parser("apply", help="Run migration in one transaction (backup DB first; stop API)")
    ap.add_argument("--old", required=True, dest="old_uid", help="users.id that currently owns the data")
    ap.add_argument("--new", required=True, dest="new_uid", help="users.id for the account you log in as")

    args = p.parse_args()
    db = resolve_db_path(args.db)
    conn = connect(db)
    try:
        if args.cmd == "inspect":
            print(f"Database: {db}\n")
            cmd_inspect(conn)
        elif args.cmd == "dry-run":
            cmd_dry_run(conn, args.old_uid, args.new_uid)
        elif args.cmd == "apply":
            print(f"Database: {db}")
            print("Ensure you copied a backup of this file and stopped the API.\n")
            cmd_apply(conn, args.old_uid, args.new_uid)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
