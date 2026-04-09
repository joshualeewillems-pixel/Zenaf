#!/usr/bin/env python3
"""
Multi-user sanity: log in as owner and phil, call GET /auth/me for each (separate cookie jars).

Requires API up (default http://127.0.0.1:8010). Uses the same dev defaults as storage bootstrap:

  owner@local.zenaf  — ZENAF_BOOTSTRAP_PASSWORD or local-dev-owner
  phil@local.zenaf   — ZENAF_PHIL_BOOTSTRAP_PASSWORD or phil-local-dev

Run: python tools/stress_two_user_login.py
"""
from __future__ import annotations

import json
import os
import ssl
import sys
import urllib.error
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def _login(base: str, email: str, password: str) -> urllib.request.OpenerDirector:
    import http.cookiejar

    cj = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
    opener.add_handler(urllib.request.HTTPSHandler(context=ssl.create_default_context()))
    data = json.dumps({"email": email, "password": password}).encode("utf-8")
    req = urllib.request.Request(
        f"{base.rstrip('/')}/auth/login",
        data=data,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    with opener.open(req, timeout=30.0) as r:
        body = r.read().decode("utf-8", errors="replace")
        if r.getcode() != 200:
            raise RuntimeError(f"login {email} -> {r.getcode()} {body[:500]}")
    return opener


def _me(opener: urllib.request.OpenerDirector, base: str) -> dict:
    req = urllib.request.Request(f"{base.rstrip('/')}/auth/me", method="GET")
    with opener.open(req, timeout=15.0) as r:
        return json.loads(r.read().decode("utf-8"))


def main() -> int:
    base = os.environ.get("ZENAF_API_BASE", "http://127.0.0.1:8010").rstrip("/")
    owner_pwd = (os.environ.get("ZENAF_BOOTSTRAP_PASSWORD") or "").strip() or "local-dev-owner"
    phil_pwd = (os.environ.get("ZENAF_PHIL_BOOTSTRAP_PASSWORD") or "").strip() or "phil-local-dev"
    pairs = [
        ("owner@local.zenaf", owner_pwd),
        ("phil@local.zenaf", phil_pwd),
    ]
    print(f"API {base}", flush=True)
    for email, pwd in pairs:
        try:
            op = _login(base, email, pwd)
            me = _me(op, base)
            print(f"OK  {email} -> me id={me.get('id')} display={me.get('display_name')!r}", flush=True)
        except (urllib.error.HTTPError, urllib.error.URLError, RuntimeError, json.JSONDecodeError) as e:
            print(f"FAIL {email}: {e}", flush=True)
            return 1
    print("Both users authenticated.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
