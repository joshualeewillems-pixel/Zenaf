"""Share-link intake: accept a shared conversation URL, fetch it, parse it.

ChatGPT, Claude, and others let users create public share links for
conversations (e.g. https://chatgpt.com/share/abc123). Anyone with the link
can view it — no auth needed. This module detects supported share URLs,
fetches the conversation, and parses it into a standard transcript format
that feeds the agent-intake sorter (as examples) or presence ingestion
(as events).

Fetching strategy (per platform):
  1. Try the platform's JSON/data endpoint or server-rendered HTML first
     (fast, no browser).
  2. If the page is client-rendered only, return needs_browser=True so the
     caller can complete the fetch with a real browser (the frontend or a
     worker), then call parse_html() on the rendered DOM.

New platforms are added by registering a ShareLinkSource below.
"""
from __future__ import annotations

import json
import re
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Callable

from local_ai.presence_ingest.redact import redact_text


@dataclass
class SharedMessage:
    role: str  # "user" | "assistant" | "system"
    text: str  # redacted


@dataclass
class SharedConversation:
    source: str  # "chatgpt" | "claude" | ...
    url: str
    title: str
    messages: list[SharedMessage] = field(default_factory=list)
    needs_browser: bool = False  # True when fetch requires JS rendering

    def as_examples(self, max_messages: int = 200) -> list[str]:
        """Flatten to example strings for the agent-intake sorter.

        Keeps the full conversation (up to max_messages turns) so
        moment-level review cards can anchor to any moment. The sorter
        itself only reads the first ~20 for its prompt budget.
        """
        out: list[str] = []
        for m in self.messages[:max_messages]:
            out.append(f"{m.role}: {m.text[:2000]}")
        return out


# ---------------------------------------------------------------------------
# Source definitions
# ---------------------------------------------------------------------------

@dataclass
class ShareLinkSource:
    key: str
    url_pattern: re.Pattern
    # Returns raw HTML/text or raises. Signature: fetch(url) -> str
    fetch: Callable[[str], str] | None = None
    # Parses fetched content into SharedConversation. Signature: parse(url, raw) -> SharedConversation
    parse: Callable[[str, str], SharedConversation] | None = None


def _http_fetch(url: str, timeout: int = 25) -> str:
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0 (compatible; Zenaf/1.0)"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        charset = resp.headers.get_content_charset() or "utf-8"
        return resp.read().decode(charset, errors="replace")


def _parse_chatgpt(url: str, raw: str) -> SharedConversation:
    """Parse a ChatGPT share page.

    Tries, in order: embedded __NEXT_DATA__ JSON, then a best-effort text
    extraction. If neither yields messages, flags needs_browser.
    """
    title = ""
    messages: list[SharedMessage] = []

    # Next.js embedded data
    m = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', raw, re.S)
    if m:
        try:
            data = json.loads(m.group(1))
            # Walk the props for message-like structures
            stack: list[Any] = [data]
            seen: list[tuple[str, str]] = []
            while stack:
                node = stack.pop()
                if isinstance(node, dict):
                    # ChatGPT share payloads nest messages under various keys
                    for k in ("parts", "content", "message"):
                        v = node.get(k)
                        if isinstance(v, list):
                            stack.extend(v)
                        elif isinstance(v, dict):
                            stack.append(v)
                    role = node.get("role") or node.get("author", {}).get("role")
                    text = node.get("text") or node.get("content")
                    if role in ("user", "assistant", "system") and isinstance(text, str) and text.strip():
                        seen.append((role, text.strip()))
                    stack.extend(v for v in node.values() if isinstance(v, (dict, list)))
                elif isinstance(node, list):
                    stack.extend(node)
            # de-dupe preserving order
            dedup: list[tuple[str, str]] = []
            for item in seen:
                if item not in dedup:
                    dedup.append(item)
            for role, text in dedup[:50]:
                messages.append(SharedMessage(role=role, text=redact_text(text)))
            title = _extract_title(raw) or "Shared ChatGPT conversation"
        except (json.JSONDecodeError, AttributeError):
            pass

    if not messages:
        # Best-effort: strip tags and look for conversational structure.
        # If the page is a JS shell with no content, we need a browser.
        text_only = re.sub(r"<script.*?</script>", "", raw, flags=re.S | re.I)
        text_only = re.sub(r"<style.*?</style>", "", text_only, flags=re.S | re.I)
        text_only = re.sub(r"<[^>]+>", " ", text_only)
        text_only = re.sub(r"\s+", " ", text_only).strip()
        if len(text_only) < 200:
            return SharedConversation(
                source="chatgpt", url=url, title="Shared ChatGPT conversation",
                needs_browser=True,
            )
        title = _extract_title(raw) or "Shared ChatGPT conversation"
        messages.append(SharedMessage(role="user", text=redact_text(text_only[:8000])))

    return SharedConversation(source="chatgpt", url=url, title=title, messages=messages)


def _parse_claude(url: str, raw: str) -> SharedConversation:
    """Parse a Claude share page (similar strategy to ChatGPT)."""
    m = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', raw, re.S)
    messages: list[SharedMessage] = []
    title = "Shared Claude conversation"
    if m:
        try:
            data = json.loads(m.group(1))
            stack: list[Any] = [data]
            seen: list[tuple[str, str]] = []
            while stack:
                node = stack.pop()
                if isinstance(node, dict):
                    role = node.get("role") or node.get("sender")
                    text = node.get("text") or node.get("content")
                    if role in ("user", "assistant", "human", "ai") and isinstance(text, str) and text.strip():
                        norm = "user" if role in ("user", "human") else "assistant"
                        seen.append((norm, text.strip()))
                    stack.extend(v for v in node.values() if isinstance(v, (dict, list)))
                elif isinstance(node, list):
                    stack.extend(node)
            dedup: list[tuple[str, str]] = []
            for item in seen:
                if item not in dedup:
                    dedup.append(item)
            for role, text in dedup[:50]:
                messages.append(SharedMessage(role=role, text=redact_text(text)))
        except (json.JSONDecodeError, AttributeError):
            pass
    if not messages:
        text_only = re.sub(r"<script.*?</script>", "", raw, flags=re.S | re.I)
        text_only = re.sub(r"<[^>]+>", " ", text_only)
        text_only = re.sub(r"\s+", " ", text_only).strip()
        if len(text_only) < 200:
            return SharedConversation(source="claude", url=url, title=title, needs_browser=True)
        messages.append(SharedMessage(role="user", text=redact_text(text_only[:8000])))
    return SharedConversation(source="claude", url=url, title=title, messages=messages)


def _extract_title(html: str) -> str:
    m = re.search(r"<title>(.*?)</title>", html, re.S | re.I)
    return m.group(1).strip()[:120] if m else ""


SOURCES: tuple[ShareLinkSource, ...] = (
    ShareLinkSource(
        key="chatgpt",
        url_pattern=re.compile(r"^https?://(www\.)?chatgpt\.com/share/(?:e/)?[a-zA-Z0-9-]+/?(?:\?.*)?$"),
        fetch=_http_fetch,
        parse=_parse_chatgpt,
    ),
    ShareLinkSource(
        key="claude",
        url_pattern=re.compile(r"^https?://claude\.ai/share/[a-zA-Z0-9-]+/?(?:\?.*)?$"),
        fetch=_http_fetch,
        parse=_parse_claude,
    ),
)


def detect_source(url: str) -> ShareLinkSource | None:
    """Return the ShareLinkSource for a URL, or None if unsupported."""
    url = (url or "").strip()
    for src in SOURCES:
        if src.url_pattern.match(url):
            return src
    return None


def fetch_shared_conversation(url: str) -> SharedConversation:
    """Accept a share URL, fetch it, parse it.

    Raises ValueError for unsupported URLs. Returns SharedConversation with
    needs_browser=True when the page requires JS rendering — the caller
    should render it in a browser and call the source's parse() on the HTML.
    """
    src = detect_source(url)
    if src is None:
        raise ValueError(f"Unsupported share URL: {url[:80]}")
    if src.fetch is None or src.parse is None:
        raise ValueError(f"Source '{src.key}' has no fetch/parse implementation")
    raw = src.fetch(url)
    return src.parse(url, raw)
