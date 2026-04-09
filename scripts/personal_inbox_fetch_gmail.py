#!/usr/bin/env python3
"""
Fetch a sample of personal inbox messages directly from Gmail via IMAP and
write them to a JSONL file compatible with scripts/personal_inbox_report.py.

Usage (from repo root):

  python scripts/personal_inbox_fetch_gmail.py --limit 5000

This will:
- Connect to Gmail IMAP (imap.gmail.com) using the existing Zenaf Gmail OAuth
  credentials (XOAUTH2), not a password or app password.
- Read up to N messages from INBOX, newest first.
- Extract: subject, plain-text body (when available), from, date.
- Write one JSON object per line to the output file:
    {"subject": "...", "body": "...", "from": "...", "date": "..."}

Safety:
- Read-only: this script only issues IMAP SELECT and FETCH commands.
- It does not delete, move, or modify any messages.
- If Gmail OAuth is not configured, it fails with a clear message instructing
  you to reconnect Gmail via the existing Zenaf flow.
"""

from __future__ import annotations

import argparse
import imaplib
import json
from email import message_from_bytes
from email.header import decode_header
from email.message import Message
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Optional

import sys

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from local_ai.intake import gmail_oauth  # noqa: E402


IMAP_HOST = "imap.gmail.com"
IMAP_PORT = 993


def _decode_header_value(value: str | None) -> str:
    if not value:
        return ""
    parts = decode_header(value)
    decoded_chunks: list[str] = []
    for text, enc in parts:
        if isinstance(text, bytes):
            try:
                decoded_chunks.append(text.decode(enc or "utf-8", errors="ignore"))
            except Exception:
                decoded_chunks.append(text.decode("utf-8", errors="ignore"))
        else:
            decoded_chunks.append(text)
    return "".join(decoded_chunks).strip()


def _extract_plain_text_body(msg: Message) -> str:
    # Prefer explicit text/plain parts, fall back to best-effort decode.
    if msg.is_multipart():
        parts: list[str] = []
        for part in msg.walk():
            ctype = part.get_content_type()
            disp = str(part.get("Content-Disposition") or "").lower()
            if ctype == "text/plain" and "attachment" not in disp:
                try:
                    payload = part.get_payload(decode=True) or b""
                    charset = part.get_content_charset() or "utf-8"
                    parts.append(payload.decode(charset, errors="ignore"))
                except Exception:
                    continue
        body = "\n".join(parts).strip()
        if body:
            return body
    # Fallback: whole payload as text
    try:
        payload = msg.get_payload(decode=True)
        if isinstance(payload, bytes):
            return payload.decode(msg.get_content_charset() or "utf-8", errors="ignore").strip()
    except Exception:
        pass
    return ""


def _extract_date(msg: Message) -> str:
    raw = msg.get("Date") or ""
    try:
        dt = parsedate_to_datetime(raw)
        return dt.isoformat()
    except Exception:
        return raw


def _open_imap_with_oauth() -> imaplib.IMAP4_SSL:
    """
    Open an IMAP connection to Gmail using the existing Zenaf Gmail OAuth tokens.

    This reuses the same token storage and XOAUTH2 helper as intake. No
    passwords or app passwords are used here.
    """
    if not gmail_oauth.has_gmail_oauth():
        msg = (
            "Gmail OAuth credentials not found.\n"
            "Please reconnect Gmail via the existing Zenaf 'Connect Gmail' flow, "
            "then re-run this script."
        )
        raise RuntimeError(msg)

    token_info = gmail_oauth.get_gmail_oauth_access_token()
    if not token_info:
        msg = (
            "Failed to load or refresh Gmail OAuth access token.\n"
            "Please reconnect Gmail via the existing Zenaf 'Connect Gmail' flow, "
            "then re-run this script."
        )
        raise RuntimeError(msg)

    email, access_token = token_info
    imap = imaplib.IMAP4_SSL(IMAP_HOST, IMAP_PORT)

    def _auth_xoauth2(_unused: bytes) -> bytes:
        return gmail_oauth.build_xoauth2_string(email, access_token).encode("utf-8")

    typ, _ = imap.authenticate("XOAUTH2", _auth_xoauth2)
    if typ != "OK":
        imap.logout()
        raise RuntimeError("Gmail XOAUTH2 authentication failed. Try reconnecting Gmail from Zenaf.")
    return imap


def _fetch_messages(limit: int, mailbox: str = "INBOX") -> list[dict[str, str]]:
    imap = _open_imap_with_oauth()

    # Read-only select to avoid any side effects.
    typ, _ = imap.select(mailbox, readonly=True)
    if typ != "OK":
        imap.logout()
        raise RuntimeError(f"Failed to select mailbox {mailbox!r}")

    typ, data = imap.search(None, "ALL")
    if typ != "OK" or not data or not data[0]:
        imap.close()
        imap.logout()
        return []

    all_ids = data[0].split()
    if not all_ids:
        imap.close()
        imap.logout()
        return []

    # Newest first
    all_ids = all_ids[::-1]
    if limit > 0:
        all_ids = all_ids[:limit]

    messages: list[dict[str, str]] = []
    for msg_id in all_ids:
        typ, msg_data = imap.fetch(msg_id, "(RFC822)")
        if typ != "OK" or not msg_data:
            continue
        # msg_data is a list of (bytes, flags) pairs; the first element contains the message
        raw_bytes: Optional[bytes] = None
        for part in msg_data:
            if isinstance(part, tuple) and isinstance(part[1], (bytes, bytearray)):
                raw_bytes = bytes(part[1])
                break
        if not raw_bytes:
            continue
        msg = message_from_bytes(raw_bytes)
        subject = _decode_header_value(msg.get("Subject"))
        sender = _decode_header_value(msg.get("From"))
        body = _extract_plain_text_body(msg)
        date_str = _extract_date(msg)
        messages.append(
            {
                "subject": subject,
                "body": body,
                "from": sender,
                "date": date_str,
            }
        )

    imap.close()
    imap.logout()
    return messages


def main() -> None:
    ap = argparse.ArgumentParser(description="Fetch a personal inbox sample from Gmail into JSONL")
    ap.add_argument("--limit", type=int, default=5000, help="Maximum number of messages to fetch (newest first)")
    ap.add_argument(
        "--output",
        type=str,
        default="personal_inbox_sample.jsonl",
        help="Path to output JSONL file",
    )
    ap.add_argument(
        "--mailbox",
        type=str,
        default="INBOX",
        help="IMAP mailbox to fetch from (default INBOX)",
    )
    args = ap.parse_args()

    msgs = _fetch_messages(limit=args.limit, mailbox=args.mailbox)
    if not msgs:
        print("No messages fetched.")
        return

    out_path = args.output
    with open(out_path, "w", encoding="utf-8") as f:
        for m in msgs:
            f.write(json.dumps(m, ensure_ascii=False) + "\n")

    print(f"Wrote {len(msgs)} messages to {out_path}")


if __name__ == "__main__":
    main()

