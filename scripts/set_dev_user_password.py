#!/usr/bin/env python3
"""
Set (or reset) a local dev user's password in vision_execution SQLite.

The hash stored at first bootstrap matches ZENAF_BOOTSTRAP_PASSWORD if set when the user was
created; otherwise it is the dev fallback ``local-dev-owner``. Changing .env later does NOT
update existing users — use this script if login fails after env changes.

Run from repo root (API stopped recommended):
  python scripts/set_dev_user_password.py --email owner@local.zenaf --password local-dev-owner
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
    p = argparse.ArgumentParser(description="Reset a dev user's password (SQLite).")
    p.add_argument("--email", default="owner@local.zenaf", help="User email")
    p.add_argument("--password", required=True, help="New plaintext password")
    args = p.parse_args()

    storage.get_connection()
    out = storage.set_user_password_by_email(args.email, args.password)
    if not out.get("ok"):
        print(out, file=sys.stderr)
        raise SystemExit(1)
    print(f"Updated password for {out['email']} (id={out['user_id']})")


if __name__ == "__main__":
    main()
