#!/usr/bin/env python3
"""
Safe, deterministic consolidation of local Atria → Zenaf accounts on the Vision Execution SQLite DB.

Default pairs (fixed):
  owner@local.atria  → owner@local.zenaf
  phil@local.atria   → phil@local.zenaf

Modes:
  --dry-run   Audit + print what would happen (no writes).
  --execute   Run inside a single DB transaction (rolls back on error).

  --delete-old-if-safe  After merge/reassign, DELETE the Atria user row only when no FK refs remain.

Discovery:
  Scans sqlite_master + PRAGMA table_info for columns that reference users by id.
  Any (table, column) found that is not in CANONICAL_USER_REF_COLUMNS aborts — update this script when schema grows.

Run from repo root (stop API recommended for --execute):
  python scripts/consolidate_local_users.py --dry-run
  python scripts/consolidate_local_users.py --execute
  python scripts/consolidate_local_users.py --execute --delete-old-if-safe --db data/vision_execution/vision_execution.db
"""
from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

_REPO = Path(__file__).resolve().parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from local_ai.env_legacy_aliases import apply_zenaf_env_legacy_aliases

apply_zenaf_env_legacy_aliases()

# ---------------------------------------------------------------------------
# Canonical FK map: every (table, column) that stores users.id (not persons.id).
# Updated from local_ai/vision_execution/schema.sql + storage.py migrations.
# ---------------------------------------------------------------------------
CANONICAL_USER_REF_COLUMNS: list[tuple[str, str]] = [
    ("arc_detection_candidates", "user_id"),
    ("aspiration_inference_log", "user_id"),
    ("aspiration_profile", "user_id"),
    ("aspiration_proposals", "user_id"),
    ("capability_offers", "user_id"),
    ("content_briefs", "user_id"),
    ("core_profiles", "user_id"),
    ("council_stream_runs", "user_id"),
    ("council_teacher_runs", "user_id"),
    ("decisions", "user_id"),
    ("execution_steps", "user_id"),
    ("ideas", "user_id"),
    ("initiatives", "user_id"),
    ("material_offers", "user_id"),
    ("material_requests", "user_id"),
    ("node_judgment_history", "user_id"),
    ("node_vitality", "user_id"),
    ("projects", "user_id"),
    ("prompt_signals", "user_id"),
    ("seat_requests", "user_id"),
    ("sessions", "user_id"),
    ("tasks", "user_id"),
    ("user_council_workspace", "user_id"),
    ("user_llm_profile", "user_id"),
    ("user_llm_provider_credentials", "user_id"),
    ("user_notification_settings", "user_id"),
    ("user_permissions_settings", "user_id"),
    ("workspace_messages", "from_user_id"),
    ("workspace_messages", "to_user_id"),
]

# Tables where user_id is the PRIMARY KEY (single row per user).
PK_USER_ID_TABLES: frozenset[str] = frozenset(
    {
        "user_llm_profile",
        "user_notification_settings",
        "user_council_workspace",
        "aspiration_profile",
        "user_permissions_settings",
    }
)

EMAIL_PAIRS: list[tuple[str, str]] = [
    ("owner@local.atria", "owner@local.zenaf"),
    ("phil@local.atria", "phil@local.zenaf"),
]



def _default_db_path() -> Path:
    from local_ai.vision_execution.storage import _DB_PATH

    return Path(_DB_PATH)


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def list_user_tables(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").fetchall()
    return [r[0] for r in rows if not str(r[0]).startswith("sqlite_")]


def discover_user_ref_columns(conn: sqlite3.Connection) -> list[tuple[str, str]]:
    """Find (table, column) where column name indicates a users.id FK."""
    out: list[tuple[str, str]] = []
    for table in list_user_tables(conn):
        for row in conn.execute(f"PRAGMA table_info({quote_ident(table)})").fetchall():
            col = row[1]
            cl = col.lower()
            if cl in ("user_id", "from_user_id", "to_user_id"):
                out.append((table, col))
            elif cl.endswith("_user_id"):
                out.append((table, col))
    # de-dupe preserve order
    seen: set[tuple[str, str]] = set()
    uniq: list[tuple[str, str]] = []
    for t in out:
        if t not in seen:
            seen.add(t)
            uniq.append(t)
    return uniq


def quote_ident(name: str) -> str:
    if not name.replace("_", "").isalnum():
        raise ValueError(f"unsafe identifier {name!r}")
    return name


def users_select_sql(conn: sqlite3.Connection) -> str:
    cols = {r[1] for r in conn.execute("PRAGMA table_info(users)").fetchall()}
    base = "id, email, created_at, updated_at"
    return f"{base}, is_admin" if "is_admin" in cols else base


def validate_schema(conn: sqlite3.Connection) -> None:
    discovered = set(discover_user_ref_columns(conn))
    canonical = set(CANONICAL_USER_REF_COLUMNS)
    unknown = sorted(discovered - canonical)
    missing = sorted(canonical - discovered)
    if unknown:
        raise SystemExit(
            "Schema drift: discovered user-ref columns not in CANONICAL_USER_REF_COLUMNS.\n"
            "Add these to the script after verifying they reference users(id):\n  "
            + "\n  ".join(f"{t}.{c}" for t, c in unknown)
        )
    if missing:
        # table might not exist yet in empty DB — skip only if table missing
        tables = set(list_user_tables(conn))
        really_missing: list[tuple[str, str]] = []
        for t, c in missing:
            if t in tables:
                really_missing.append((t, c))
        if really_missing:
            raise SystemExit(
                "CANONICAL_USER_REF_COLUMNS lists columns missing from DB:\n  "
                + "\n  ".join(f"{t}.{c}" for t, c in really_missing)
            )


def count_rows(conn: sqlite3.Connection, table: str, column: str, user_id: str) -> int:
    q = f'SELECT COUNT(*) FROM {quote_ident(table)} WHERE {quote_ident(column)} = ?'
    row = conn.execute(q, (user_id,)).fetchone()
    return int(row[0]) if row else 0


def count_atria_emails(conn: sqlite3.Connection) -> dict[str, int]:
    out: dict[str, int] = {}
    for old, _ in EMAIL_PAIRS:
        n = conn.execute(
            "SELECT COUNT(*) FROM users WHERE lower(email) = lower(?)",
            (old,),
        ).fetchone()
        out[old] = int(n[0]) if n else 0
    return out


@dataclass
class PairPlan:
    source_email: str
    target_email: str
    strategy: str  # "rename_in_place" | "merge_reassign" | "noop" | "abort"
    source_id: str | None = None
    target_id: str | None = None
    reason: str = ""
    updates: list[tuple[str, str, int]] = field(default_factory=list)  # table, col, count
    pk_source_only: list[str] = field(default_factory=list)
    pk_both: list[str] = field(default_factory=list)
    conflicts_node_vitality: int = 0
    conflicts_arc_candidates: int = 0


def plan_pair(conn: sqlite3.Connection, source_email: str, target_email: str) -> PairPlan:
    se = source_email.strip().lower()
    te = target_email.strip().lower()
    plan = PairPlan(source_email=se, target_email=te, strategy="abort", reason="")

    sel = users_select_sql(conn)
    src = conn.execute(
        f"SELECT {sel} FROM users WHERE lower(email) = lower(?)",
        (se,),
    ).fetchone()
    dst = conn.execute(
        f"SELECT {sel} FROM users WHERE lower(email) = lower(?)",
        (te,),
    ).fetchone()

    if not src and not dst:
        plan.strategy = "noop"
        plan.reason = "Neither account exists."
        return plan
    if not src and dst:
        plan.strategy = "noop"
        plan.reason = "Source missing; target already the only account."
        plan.target_id = dst["id"]
        return plan
    if src and not dst:
        plan.strategy = "rename_in_place"
        plan.source_id = src["id"]
        plan.reason = "Target email free - rename users.email in place (id unchanged)."
        return plan

    # both exist → merge
    plan.strategy = "merge_reassign"
    plan.source_id = src["id"]
    plan.target_id = dst["id"]
    plan.reason = "Both exist - reassign FKs from source user id to target user id."

    sid, tid = plan.source_id, plan.target_id
    assert sid and tid

    for table, col in CANONICAL_USER_REF_COLUMNS:
        if not conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            (table,),
        ).fetchone():
            continue
        n = count_rows(conn, table, col, sid)
        if n:
            plan.updates.append((table, col, n))

    # PK tables: both have row?
    for table in PK_USER_ID_TABLES:
        if not conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            (table,),
        ).fetchone():
            continue
        s = conn.execute(
            f"SELECT 1 FROM {quote_ident(table)} WHERE user_id = ?",
            (sid,),
        ).fetchone()
        d = conn.execute(
            f"SELECT 1 FROM {quote_ident(table)} WHERE user_id = ?",
            (tid,),
        ).fetchone()
        if s and not d:
            plan.pk_source_only.append(table)
        elif s and d:
            plan.pk_both.append(table)

    # node_vitality collisions
    plan.conflicts_node_vitality = int(
        conn.execute(
            """
            SELECT COUNT(*) FROM node_vitality s
            INNER JOIN node_vitality d
              ON d.user_id = ? AND d.entity_type = s.entity_type AND d.entity_id = s.entity_id
            WHERE s.user_id = ?
            """,
            (tid, sid),
        ).fetchone()[0]
    )

    # arc_detection_candidates collisions
    plan.conflicts_arc_candidates = int(
        conn.execute(
            """
            SELECT COUNT(*) FROM arc_detection_candidates s
            INNER JOIN arc_detection_candidates d
              ON d.user_id = ? AND d.source_entity_type = s.source_entity_type
              AND d.source_entity_id = s.source_entity_id AND d.heuristic_version = s.heuristic_version
            WHERE s.user_id = ?
            """,
            (tid, sid),
        ).fetchone()[0]
    )

    if plan.conflicts_node_vitality or plan.conflicts_arc_candidates:
        plan.strategy = "abort"
        plan.reason = (
            f"UNIQUE-like collision: node_vitality={plan.conflicts_node_vitality}, "
            f"arc_detection_candidates={plan.conflicts_arc_candidates}. Resolve manually."
        )
    return plan


def _delete_conflicting_source_llm_creds(conn: sqlite3.Connection, sid: str, tid: str, dry_run: bool) -> int:
    """Remove source credential rows that would duplicate (tid, provider)."""
    row = conn.execute(
        """
        SELECT COUNT(*) FROM user_llm_provider_credentials s
        WHERE s.user_id = ?
          AND EXISTS (
            SELECT 1 FROM user_llm_provider_credentials d
            WHERE d.user_id = ? AND d.provider = s.provider
          )
        """,
        (sid, tid),
    ).fetchone()
    n = int(row[0]) if row else 0
    if n and not dry_run:
        conn.execute(
            """
            DELETE FROM user_llm_provider_credentials
            WHERE user_id = ?
              AND provider IN (SELECT provider FROM user_llm_provider_credentials WHERE user_id = ?)
            """,
            (sid, tid),
        )
    return n


def apply_merge(
    conn: sqlite3.Connection,
    plan: PairPlan,
    *,
    dry_run: bool,
    log: list[str],
) -> None:
    sid, tid = plan.source_id, plan.target_id
    assert sid and tid

    n_dup_llm = _delete_conflicting_source_llm_creds(conn, sid, tid, dry_run)
    if n_dup_llm:
        log.append(f"  [merge] Dropped {n_dup_llm} duplicate user_llm_provider_credentials rows on source (provider clash).")

    # PK tables: move or drop source
    for table in PK_USER_ID_TABLES:
        if not conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            (table,),
        ).fetchone():
            continue
        s = conn.execute(
            f"SELECT 1 FROM {quote_ident(table)} WHERE user_id = ?",
            (sid,),
        ).fetchone()
        d = conn.execute(
            f"SELECT 1 FROM {quote_ident(table)} WHERE user_id = ?",
            (tid,),
        ).fetchone()
        if not s:
            continue
        if not d:
            if not dry_run:
                conn.execute(
                    f"UPDATE {quote_ident(table)} SET user_id = ? WHERE user_id = ?",
                    (tid, sid),
                )
            log.append(f"  [merge] {table}: reassign user_id (PK) source->target (1 row moved).")
        else:
            if not dry_run:
                conn.execute(f"DELETE FROM {quote_ident(table)} WHERE user_id = ?", (sid,))
            log.append(f"  [merge] {table}: delete source row (target already had row; prefer target).")

    # Remaining FK columns (skip PK tables already handled user_id — credentials still need update)
    handled_pk = PK_USER_ID_TABLES
    for table, col in CANONICAL_USER_REF_COLUMNS:
        if not conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            (table,),
        ).fetchone():
            continue
        if table in handled_pk and col == "user_id":
            continue
        n = count_rows(conn, table, col, sid)
        if not n:
            continue
        if not dry_run:
            conn.execute(
                f"UPDATE {quote_ident(table)} SET {quote_ident(col)} = ? WHERE {quote_ident(col)} = ?",
                (tid, sid),
            )
        log.append(f"  [merge] {table}.{col}: {n} rows -> target user id")


def apply_rename(conn: sqlite3.Connection, plan: PairPlan, *, dry_run: bool, log: list[str]) -> None:
    assert plan.source_id
    if dry_run:
        log.append(f"  [rename] users.email: {plan.source_email!r} -> {plan.target_email!r} (id={plan.source_id})")
        return
    conn.execute(
        "UPDATE users SET email = ?, updated_at = ? WHERE id = ? AND lower(email) = lower(?)",
        (plan.target_email, _now_iso(), plan.source_id, plan.source_email),
    )
    log.append(f"  [rename] users: email updated for id={plan.source_id}")


def safe_delete_user(conn: sqlite3.Connection, user_id: str, *, dry_run: bool, log: list[str]) -> bool:
    refs = 0
    for table, col in CANONICAL_USER_REF_COLUMNS:
        if not conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            (table,),
        ).fetchone():
            continue
        refs += count_rows(conn, table, col, user_id)
    if refs > 0:
        log.append(f"  [delete] SKIP user id={user_id}: still referenced in {refs} row(s) across FK columns.")
        return False
    if dry_run:
        log.append(f"  [delete] Would DELETE users row id={user_id} (no FK refs).")
        return True
    conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
    log.append(f"  [delete] Removed users row id={user_id}.")
    return True


def audit(conn: sqlite3.Connection) -> None:
    validate_schema(conn)
    print("=== SCHEMA: user reference columns (validated against CANONICAL_USER_REF_COLUMNS) ===")
    for t, c in CANONICAL_USER_REF_COLUMNS:
        exists = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            (t,),
        ).fetchone()
        print(f"  {t}.{c}" + ("" if exists else "  (table missing in this DB)"))
    print()

    print("=== USERS: target accounts ===")
    emails = {e for pair in EMAIL_PAIRS for e in pair}
    usel = users_select_sql(conn)
    for em in sorted(emails):
        rows = conn.execute(
            f"SELECT {usel} FROM users WHERE lower(email) = lower(?)",
            (em,),
        ).fetchall()
        print(f"  {em!r}: {len(rows)} row(s)")
        for r in rows:
            adm = r["is_admin"] if "is_admin" in r.keys() else "?"
            print(
                f"    id={r['id']!r} created_at={r['created_at']!r} updated_at={r['updated_at']!r} is_admin={adm}"
            )
    dup = conn.execute(
        """
        SELECT lower(email) AS e, COUNT(*) AS c FROM users GROUP BY lower(email) HAVING c > 1
        """
    ).fetchall()
    if dup:
        print("\n  WARNING: duplicate emails:")
        for r in dup:
            print(f"    {r['e']!r}: {r['c']} rows")
    print()

    print("=== ROW COUNTS referencing Atria user ids (if present) ===")
    for src_e, _ in EMAIL_PAIRS:
        u = conn.execute(
            "SELECT id FROM users WHERE lower(email) = lower(?)",
            (src_e,),
        ).fetchone()
        if not u:
            print(f"  {src_e}: (no user row)")
            continue
        uid = u["id"]
        total = 0
        for table, col in CANONICAL_USER_REF_COLUMNS:
            if not conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                (table,),
            ).fetchone():
                continue
            n = count_rows(conn, table, col, uid)
            if n:
                print(f"    {table}.{col}: {n}")
                total += n
        print(f"    (subtotal rows touching {src_e} id): {total}")
    print()

    atria_left = count_atria_emails(conn)
    print("=== Atria email row counts (users table) ===")
    for k, v in atria_left.items():
        print(f"  {k!r}: {v}")
    print()


def print_plans(plans: list[PairPlan]) -> None:
    print("=== PAIR PLANS ===")
    for p in plans:
        print(f"\n  {p.source_email} -> {p.target_email}")
        print(f"    strategy: {p.strategy}")
        print(f"    reason: {p.reason}")
        if p.source_id:
            print(f"    source_id: {p.source_id}")
        if p.target_id:
            print(f"    target_id: {p.target_id}")
        if p.updates:
            print("    FK rows to rewrite (merge):")
            for t, c, n in p.updates:
                print(f"      {t}.{c}: {n}")
        if p.pk_source_only:
            print(f"    PK tables with source-only row (will move user_id): {p.pk_source_only}")
        if p.pk_both:
            print(f"    PK tables with BOTH users (source row deleted; prefer target): {p.pk_both}")
        if p.conflicts_node_vitality or p.conflicts_arc_candidates:
            print(f"    conflicts: node_vitality={p.conflicts_node_vitality}, arc_candidates={p.conflicts_arc_candidates}")
    print()


def verify(conn: sqlite3.Connection) -> None:
    print("=== VERIFICATION ===")
    emails = {e for pair in EMAIL_PAIRS for e in pair}
    usel = users_select_sql(conn)
    for em in sorted(emails):
        rows = conn.execute(
            f"SELECT {usel} FROM users WHERE lower(email) = lower(?) ORDER BY created_at",
            (em,),
        ).fetchall()
        print(f"  {em!r}: {len(rows)} user row(s)")
        for r in rows:
            adm = r["is_admin"] if "is_admin" in r.keys() else "?"
            print(f"    id={r['id']!r} is_admin={adm}")

    print("\n  Rows still pointing at Atria user *ids* (should be 0 after merge + delete):")
    for src_e, _ in EMAIL_PAIRS:
        u = conn.execute(
            "SELECT id FROM users WHERE lower(email) = lower(?)",
            (src_e,),
        ).fetchone()
        if not u:
            print(f"    {src_e}: no user row (ok)")
            continue
        uid = u["id"]
        bad = []
        for table, col in CANONICAL_USER_REF_COLUMNS:
            if not conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                (table,),
            ).fetchone():
                continue
            n = count_rows(conn, table, col, uid)
            if n:
                bad.append(f"{table}.{col}={n}")
        if bad:
            print(f"    {src_e} id={uid}: " + ", ".join(bad))
        else:
            print(f"    {src_e} id={uid}: no FK references (or user deleted)")

    atria = count_atria_emails(conn)
    print("\n  users.email still ending with @local.atria (canonical pairs):")
    for k, v in atria.items():
        status = "OK (0)" if v == 0 else f"REMAINING {v}"
        print(f"    {k!r}: {status}")

    print("\n  Login: use owner@local.zenaf and phil@local.zenaf with your chosen passwords.")
    print("         (Renames preserve password_hash on the same user id; merges keep target password.)")
    print()


def main() -> None:
    p = argparse.ArgumentParser(description="Consolidate local Atria → Zenaf users on Vision Execution SQLite DB.")
    p.add_argument("--db", type=Path, default=None, help="Path to vision_execution.db (default: storage _DB_PATH)")
    p.add_argument("--dry-run", action="store_true", help="Audit + plan only (default if neither flag set)")
    p.add_argument("--execute", action="store_true", help="Apply changes in one transaction")
    p.add_argument(
        "--delete-old-if-safe",
        action="store_true",
        help="After merge, DELETE source Atria user row when no FK references remain",
    )
    p.add_argument(
        "--no-backup",
        action="store_true",
        help="Skip copying DB to *.pre-consolidate-<timestamp>.bak beside the file (execute only)",
    )
    args = p.parse_args()

    db_path = Path(args.db).resolve() if args.db else _default_db_path()
    if not db_path.is_file():
        raise SystemExit(f"Database file not found: {db_path}")

    if args.execute and args.dry_run:
        raise SystemExit("Use only one of --execute or --dry-run (not both).")
    dry_run = not args.execute

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")

    validate_schema(conn)
    audit(conn)

    plans: list[PairPlan] = []
    for src, dst in EMAIL_PAIRS:
        plans.append(plan_pair(conn, src, dst))
    print_plans(plans)

    if any(p.strategy == "abort" for p in plans):
        print("ABORT: One or more pairs cannot be applied safely. Fix conflicts or schema, then retry.\n")
        raise SystemExit(2)

    if dry_run:
        print("=== DRY RUN - no changes written ===\n")
        verify(conn)
        raise SystemExit(0)

    # --- execute ---
    if not args.no_backup:
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        bak = db_path.with_name(f"{db_path.name}.pre-consolidate-{ts}.bak")
        shutil.copy2(db_path, bak)
        print(f"Backup written: {bak}\n")

    log: list[str] = []
    try:
        conn.execute("BEGIN IMMEDIATE")
        for plan in plans:
            if plan.strategy == "noop":
                log.append(f"[noop] {plan.source_email} -> {plan.target_email}: {plan.reason}")
                continue
            if plan.strategy == "rename_in_place":
                log.append(f"[pair] RENAME {plan.source_email} -> {plan.target_email}")
                apply_rename(conn, plan, dry_run=False, log=log)
                continue
            if plan.strategy == "merge_reassign":
                log.append(f"[pair] MERGE {plan.source_email} -> {plan.target_email}")
                apply_merge(conn, plan, dry_run=False, log=log)
                continue

        if args.delete_old_if_safe:
            for src_e, _ in EMAIL_PAIRS:
                u = conn.execute(
                    "SELECT id FROM users WHERE lower(email) = lower(?)",
                    (src_e,),
                ).fetchone()
                if not u:
                    continue
                log.append(f"[delete-if-safe] Checking {src_e} id={u['id']}")
                safe_delete_user(conn, u["id"], dry_run=False, log=log)

        conn.commit()
    except Exception as e:
        conn.rollback()
        print(f"ERROR: {e}\nTransaction rolled back.")
        raise SystemExit(1) from e

    print("=== EXECUTION LOG ===")
    for line in log:
        print(line)
    print()
    verify(conn)
    print("Done.")
    print(json.dumps({"ok": True, "db": str(db_path), "lines": len(log)}, indent=2))


if __name__ == "__main__":
    main()
