#!/usr/bin/env python3
"""
Send a short SMS via Twilio Messages API (for CI human-required alerts).

Environment:
  TWILIO_ACCOUNT_SID   required (unless dry-run / skip)
  TWILIO_AUTH_TOKEN    required
  TWILIO_FROM_NUMBER   E.164 from number
  NOTIFY_TO_NUMBER     E.164 destination

If required vars are missing, exits 0 after printing to stderr (workflow can still be green).

Usage:
  python notify_twilio_sms.py --body "Zenaf: wave gate failed"
  echo "text" | python notify_twilio_sms.py
"""
from __future__ import annotations

import argparse
import os
import sys

try:
    import requests
except ImportError:
    requests = None  # type: ignore[assignment]


def main() -> int:
    parser = argparse.ArgumentParser(description="Send SMS via Twilio (optional in CI)")
    parser.add_argument("--body", type=str, default="", help="Message body (default: stdin)")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print body only; do not call API",
    )
    args = parser.parse_args()
    body = (args.body or "").strip()
    if not body and not sys.stdin.isatty():
        body = sys.stdin.read().strip()
    if not body:
        print("notify_twilio_sms: empty body; nothing to send", file=sys.stderr)
        return 0

    if args.dry_run:
        print(f"[dry-run] SMS: {body[:500]}", file=sys.stderr)
        return 0

    sid = (os.environ.get("TWILIO_ACCOUNT_SID") or "").strip()
    token = (os.environ.get("TWILIO_AUTH_TOKEN") or "").strip()
    from_n = (os.environ.get("TWILIO_FROM_NUMBER") or "").strip()
    to_n = (os.environ.get("NOTIFY_TO_NUMBER") or "").strip()

    if not all([sid, token, from_n, to_n]):
        print(
            "notify_twilio_sms: missing Twilio env; skipping send (set TWILIO_* and NOTIFY_TO_NUMBER)",
            file=sys.stderr,
        )
        return 0

    if requests is None:
        print("notify_twilio_sms: requests not installed; pip install requests", file=sys.stderr)
        return 1

    url = f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json"
    try:
        r = requests.post(
            url,
            auth=(sid, token),
            data={"To": to_n, "From": from_n, "Body": body[:1600]},
            timeout=30,
        )
    except requests.RequestException as e:
        print(f"notify_twilio_sms: request failed: {e}", file=sys.stderr)
        return 1

    if r.status_code >= 400:
        print(f"notify_twilio_sms: HTTP {r.status_code} {r.text[:500]}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
