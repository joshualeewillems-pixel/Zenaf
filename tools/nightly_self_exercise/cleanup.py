"""Remove stray NightlyHarness scratch ideas (harness-only; idempotent)."""
from __future__ import annotations

import json
import ssl
import urllib.request

PREFIX = "NightlyHarness"


def _json(
    opener: urllib.request.OpenerDirector,
    method: str,
    url: str,
    body: dict | None = None,
    timeout: float = 45.0,
) -> tuple[int, object]:
    data = None
    h = {"Accept": "application/json"}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        h["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, method=method, headers=h)
    try:
        with opener.open(req, timeout=timeout) as resp:
            raw = resp.read()
            if not raw:
                return resp.getcode(), None
            try:
                return resp.getcode(), json.loads(raw.decode())
            except json.JSONDecodeError:
                return resp.getcode(), raw.decode(errors="replace")[:500]
    except Exception as e:
        return -1, str(e)


def cleanup_nightly_scratch_ideas(api_base: str, email: str, password: str) -> tuple[int, list[str]]:
    """
    Log in, list ideas, delete any whose title starts with PREFIX.
    Returns (deleted_count, log_lines).
    """
    import http.cookiejar

    base = api_base.rstrip("/")
    lines: list[str] = []
    cj = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
    opener.add_handler(urllib.request.HTTPSHandler(context=ssl.create_default_context()))

    code, _ = _json(opener, "POST", f"{base}/auth/login", {"email": email, "password": password})
    if code != 200:
        lines.append(f"cleanup: login failed code={code}")
        return 0, lines

    code, ideas = _json(opener, "GET", f"{base}/vision-execution/ideas", None)
    if code != 200 or not isinstance(ideas, list):
        lines.append(f"cleanup: list ideas failed code={code}")
        return 0, lines

    deleted = 0
    for row in ideas:
        if not isinstance(row, dict):
            continue
        title = (row.get("title") or "").strip()
        iid = row.get("id")
        if not iid or not title.startswith(PREFIX):
            continue
        dc, _ = _json(opener, "DELETE", f"{base}/vision-execution/ideas/{iid}", None)
        lines.append(f"cleanup: DELETE {iid} ({title[:40]!r}) -> {dc}")
        if dc == 200:
            deleted += 1
    return deleted, lines
