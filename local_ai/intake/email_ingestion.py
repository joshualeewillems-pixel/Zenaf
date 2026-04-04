"""
Live email ingestion: IMAP → fetch unread/recent messages → normalize body → pipeline → queue.

MIRROR-ONLY (read-only): This integration does not modify mailbox state. We do not move, archive,
label, mark read, reply, or draft. We only read enough content to classify and create queue items.
Anything that is unread when we touch it stays unread.
- SELECT with readonly=True.
- FETCH with BODY.PEEK[] so the server does not set \\Seen (unread stays unread).
No STORE, COPY, MOVE, or other write operations are used.

Raw email stays internal; only queue-safe metadata (subject, external_id, source_label) is stored.
Duplicate prevention: external_id (Message-ID or uid+date hash) checked before adding.
Designed for one mailbox in MVP; config is a list so multiple inbox sources can be added later.
"""
from __future__ import annotations

import hashlib
import html
import imaplib
import json
import os
import re
from dataclasses import dataclass
from email import policy
from email.parser import BytesParser
from email.utils import parsedate_to_datetime

from .pipeline import run_pipeline
from .queue_store import add_item, get_by_external_id


@dataclass
class MailboxConfig:
    """Single mailbox to poll. Extension point: use a list of these for multiple inboxes."""
    host: str
    user: str
    password: str
    mailbox: str = "INBOX"
    label: str = ""
    use_ssl: bool = True
    use_oauth_gmail: bool = False

    def __post_init__(self) -> None:
        if not self.label:
            self.label = self.mailbox or "INBOX"


def _imap_config_path() -> str:
    """Path to saved IMAP config file (one mailbox). Do not commit this file; it may contain a password."""
    return os.environ.get("INTAKE_IMAP_CONFIG_FILE", "").strip() or os.path.join(
        os.getcwd(), "intake_imap_config.json"
    )


def get_imap_config_from_env() -> list[MailboxConfig]:
    """
    Build mailbox config(s) from environment. MVP: one mailbox from INTAKE_IMAP_*.
    Later: extend with INTAKE_IMAP_2_*, ... or a config file to return multiple configs.
    """
    host = os.environ.get("INTAKE_IMAP_HOST", "").strip()
    user = os.environ.get("INTAKE_IMAP_USER", "").strip()
    password = os.environ.get("INTAKE_IMAP_PASSWORD", "").strip()
    mailbox = (os.environ.get("INTAKE_IMAP_MAILBOX") or "INBOX").strip() or "INBOX"
    label = os.environ.get("INTAKE_IMAP_LABEL", "").strip() or mailbox
    if not host or not user or not password:
        return []
    return [MailboxConfig(host=host, user=user, password=password, mailbox=mailbox, label=label, use_ssl=True)]


def get_imap_config_from_file() -> list[MailboxConfig]:
    """Load one mailbox config from saved file. Returns [] if file missing or invalid."""
    path = _imap_config_path()
    if not path or not os.path.isfile(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return []
    host = (data.get("host") or "").strip()
    user = (data.get("user") or "").strip()
    password = (data.get("password") or "").strip()
    if not host or not user or not password:
        return []
    mailbox = (data.get("mailbox") or "INBOX").strip() or "INBOX"
    label = (data.get("label") or "").strip() or mailbox
    return [MailboxConfig(host=host, user=user, password=password, mailbox=mailbox, label=label, use_ssl=True)]


def _looks_like_gmail_app_password(password: str) -> bool:
    """Gmail app passwords are 16 chars, alphanumeric (often shown with spaces)."""
    s = (password or "").replace(" ", "").strip()
    return len(s) == 16 and s.isalnum()


def get_imap_config() -> list[MailboxConfig]:
    """Env vars override; if unset, use saved config file. Gmail via IMAP only if app-password-shaped or OAuth."""
    configs = get_imap_config_from_env()
    if not configs:
        configs = get_imap_config_from_file()
    # Gmail IMAP with a normal password always fails (Google requires app password or OAuth).
    # Skip Gmail IMAP entries unless password looks like a 16-char app password, so Poll doesn't spam errors.
    filtered: list[MailboxConfig] = []
    for c in configs:
        if "gmail" in (c.host or "").lower() and not getattr(c, "use_oauth_gmail", False):
            if _looks_like_gmail_app_password(c.password):
                filtered.append(c)
            # else: skip — would fail with Application-specific password required
        else:
            filtered.append(c)
    configs = filtered
    # Append Gmail OAuth mailbox when connected
    try:
        from . import gmail_oauth
        if gmail_oauth.has_gmail_oauth():
            tok = gmail_oauth.get_gmail_oauth_access_token()
            if tok:
                email, _ = tok
                configs = list(configs) + [
                    MailboxConfig(
                        host="imap.gmail.com",
                        user=email,
                        password="",
                        mailbox="INBOX",
                        label=email or "Gmail",
                        use_ssl=True,
                        use_oauth_gmail=True,
                    )
                ]
    except Exception:
        pass
    return configs


def save_imap_config(
    host: str,
    user: str,
    password: str,
    mailbox: str = "INBOX",
    label: str = "",
) -> None:
    """Save one mailbox config to file (for UI). Password is stored in plain text; keep file out of version control."""
    path = _imap_config_path()
    label = (label or "").strip() or (mailbox or "INBOX")
    data = {
        "host": (host or "").strip(),
        "user": (user or "").strip(),
        "password": (password or "").strip(),
        "mailbox": (mailbox or "INBOX").strip() or "INBOX",
        "label": label,
    }
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def _clean_html_to_text(raw: str) -> str:
    """
    Strip HTML to plain text for previews/summaries. Removes doctype/head/script/style
    and their contents, strips tag attributes, then tags, decodes entities, collapses
    whitespace. Raw HTML should not appear in output.
    """
    if not raw or not isinstance(raw, str):
        return ""
    text = raw
    # Remove DOCTYPE and declarations
    text = re.sub(r"<!DOCTYPE[^>]*>", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"<\?[\s\S]*?\?>", " ", text)
    # Remove entire <head>...</head> (often contains no readable content)
    text = re.sub(r"<head[^>]*>[\s\S]*?</head>", " ", text, flags=re.IGNORECASE)
    # Remove <script>...</script> and <style>...</style> and their contents
    text = re.sub(r"<script[^>]*>[\s\S]*?</script>", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"<style[^>]*>[\s\S]*?</style>", " ", text, flags=re.IGNORECASE)
    # Remove HTML comments
    text = re.sub(r"<!--[\s\S]*?-->", " ", text)
    # Strip style, class, id (and other common) attributes so we don't leak long strings
    text = re.sub(r'\s+(?:style|class|id|data-[a-zA-Z0-9_-]+)=["\'][^"\']*["\']', "", text, flags=re.IGNORECASE)
    # Strip all remaining tags
    text = re.sub(r"<[^>]+>", " ", text)
    # Decode HTML entities
    text = html.unescape(text)
    # Collapse whitespace (including newlines) to single space, then trim
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _normalize_body(msg) -> str:
    """Extract plain text body. Prefer text/plain; use HTML only when necessary with aggressive cleanup."""
    body_parts = []
    if msg.is_multipart():
        for part in msg.walk():
            ct = part.get_content_type()
            if ct == "text/plain":
                try:
                    payload = part.get_payload(decode=True)
                    if payload:
                        body_parts.append(payload.decode(errors="replace"))
                except Exception:
                    pass
            elif ct == "text/html" and not body_parts:
                try:
                    payload = part.get_payload(decode=True)
                    if payload:
                        raw = payload.decode(errors="replace")
                        text = _clean_html_to_text(raw)
                        if text:
                            body_parts.append(text)
                except Exception:
                    pass
    else:
        try:
            payload = msg.get_payload(decode=True)
            if payload:
                body_parts.append(payload.decode(errors="replace"))
        except Exception:
            pass
    return "\n".join(body_parts).strip() if body_parts else ""


def _external_id(message_id: str | None, uid: int | str, date_str: str) -> str:
    """Stable id for dedup: Message-ID if present, else hash(uid|date)."""
    if message_id and message_id.strip():
        return message_id.strip()
    return hashlib.sha256(f"{uid}|{date_str}".encode()).hexdigest()


def _poll_one_mailbox(
    config: MailboxConfig,
    max_messages: int = 50,
) -> tuple[int, int, list[str]]:
    """Poll a single mailbox. Returns (added, skipped_duplicates, errors)."""
    conn = None
    try:
        if config.use_ssl:
            conn = imaplib.IMAP4_SSL(config.host)
        else:
            conn = imaplib.IMAP4(config.host)
        if getattr(config, "use_oauth_gmail", False):
            from . import gmail_oauth
            tok = gmail_oauth.get_gmail_oauth_access_token()
            if not tok:
                return 0, 0, [f"{config.label}: Gmail OAuth token missing or expired"]
            _email, access_token = tok
            # Return raw SASL string; imaplib base64-encodes it before sending (do not pre-encode).
            xoauth2_raw = gmail_oauth.build_xoauth2_string(config.user, access_token, already_base64=False)
            conn.authenticate("XOAUTH2", lambda _: xoauth2_raw)
        else:
            conn.login(config.user, config.password)
        # Read-only: do not allow server to record our session as modifying the mailbox
        conn.select(config.mailbox, readonly=True)
    except Exception as e:
        return 0, 0, [f"{config.label}: connection failed: {e}"]

    added = 0
    skipped_duplicates = 0
    errors: list[str] = []
    label_prefix = f"[{config.label}] " if config.label else ""

    try:
        _, data = conn.search(None, "UNSEEN")
        if not data or not data[0]:
            return 0, 0, []
        uids = data[0].split()
        uids = uids[-max_messages:] if len(uids) > max_messages else uids
        uids = list(reversed(uids))

        for uid in uids:
            try:
                # BODY.PEEK[]: fetch without setting \Seen — unread stays unread
                _, msg_data = conn.fetch(uid, "(BODY.PEEK[])")
                if not msg_data or not msg_data[0]:
                    continue
                raw = msg_data[0]
                if isinstance(raw, tuple):
                    raw = raw[1]
                msg = BytesParser(policy=policy.default).parsebytes(raw)
            except Exception as e:
                errors.append(f"{label_prefix}uid {uid}: fetch/parse failed: {e}")
                continue

            message_id = msg.get("Message-ID")
            date_header = msg.get("Date") or ""
            try:
                dt = parsedate_to_datetime(date_header)
                created_at = dt.isoformat()
            except Exception:
                created_at = None
            subject = (msg.get("Subject") or "").strip()
            body = _normalize_body(msg)

            ext_id = _external_id(message_id, uid.decode() if isinstance(uid, bytes) else uid, date_header)
            if get_by_external_id(ext_id) is not None:
                skipped_duplicates += 1
                continue
            try:
                item = run_pipeline(
                    body or "(No content)",
                    "email",
                    do_redact=True,
                    created_at=created_at,
                    subject=subject[:500] if subject else None,
                )
                item.external_id = ext_id
                item.subject = subject[:500] if subject else ""
                item.source_label = config.label
                item.sender = (msg.get("From") or "").strip()[:500] or ""
                add_item(item)
                added += 1
            except Exception as e:
                errors.append(f"{label_prefix}uid {uid}: pipeline failed: {e}")
    finally:
        try:
            conn.close()
            conn.logout()
        except Exception:
            pass

    return added, skipped_duplicates, errors


def poll_ingest_emails(
    *,
    configs: list[MailboxConfig] | None = None,
    max_messages: int = 50,
) -> tuple[dict[str, int | list[str]] | None, str | None]:
    """
    Poll one or more mailboxes, run pipeline, add to queue (skip duplicates).
    Returns (stats, config_error). stats is {"added": N, "skipped_duplicates": N, "errors": [...]};
    config_error is set if no configs (e.g. env not set).
    MVP: pass configs=None to use get_imap_config_from_env() (single mailbox). Later: pass a list of configs.
    """
    if configs is None:
        configs = get_imap_config()
    if not configs:
        return None, "Email ingestion not configured: set INTAKE_IMAP_HOST, INTAKE_IMAP_USER, INTAKE_IMAP_PASSWORD"

    total_added = 0
    total_skipped = 0
    all_errors: list[str] = []

    for cfg in configs:
        added, skipped, errs = _poll_one_mailbox(cfg, max_messages=max_messages)
        total_added += added
        total_skipped += skipped
        all_errors.extend(errs)

    return (
        {"added": total_added, "skipped_duplicates": total_skipped, "errors": all_errors},
        None,
    )
