#!/usr/bin/env python3
"""
Copy saved LLM profile + encrypted provider API keys from one user to another.

Use when moving from owner@local.atria → owner@local.zenaf (or any two accounts).
Automatic port on API startup only runs when the *destination* has zero credential rows.

Run from repo root (API stopped recommended):
  python scripts/port_user_llm_stack.py inspect
  python scripts/port_user_llm_stack.py apply --from owner@local.atria --to owner@local.zenaf --confirm PORT

Requires the same Fernet settings key as when the source keys were saved (usually ~/.zenaf/settings_encryption.key).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from local_ai.env_legacy_aliases import apply_zenaf_env_legacy_aliases

apply_zenaf_env_legacy_aliases()

from local_ai.vision_execution import storage  # noqa: E402


def main() -> None:
    p = argparse.ArgumentParser(description="Port LLM Settings keys between users.")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("inspect", help="Print credential counts per user email")

    ap = sub.add_parser("apply", help="Copy stack FROM → TO (replaces TO credentials)")
    ap.add_argument("--from", dest="src_email", required=True, help="Source user email")
    ap.add_argument("--to", dest="dst_email", required=True, help="Destination user email")
    ap.add_argument("--confirm", required=True, help='Must be exactly "PORT"')
    ap.add_argument(
        "--if-dest-empty",
        action="store_true",
        help="Abort if destination already has any saved provider credentials",
    )

    args = p.parse_args()
    storage.get_connection()

    if args.cmd == "inspect":
        conn = storage.get_connection()
        print("user_llm_provider_credentials row counts:\n")
        for row in conn.execute(
            "SELECT u.email, COUNT(c.user_id) AS n "
            "FROM users u "
            "LEFT JOIN user_llm_provider_credentials c ON c.user_id = u.id "
            "GROUP BY u.id, u.email ORDER BY u.email"
        ):
            print(f"  {row[0]}\t{row[1]}")
        return

    if args.confirm != "PORT":
        raise SystemExit('Refusing: pass --confirm PORT')

    src = storage.get_user_by_email(args.src_email.strip())
    dst = storage.get_user_by_email(args.dst_email.strip())
    if not src or not dst:
        raise SystemExit("Source or destination user not found.")
    if args.if_dest_empty:
        conn = storage.get_connection()
        n = conn.execute(
            "SELECT COUNT(*) AS c FROM user_llm_provider_credentials WHERE user_id = ?",
            (dst["id"],),
        ).fetchone()
        if n and int(n["c"] or 0) > 0:
            raise SystemExit("Destination already has credentials; omit --if-dest-empty to replace.")

    out = storage.port_user_llm_stack_between_users(src["id"], dst["id"])
    print(out)
    if not out.get("ok"):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
