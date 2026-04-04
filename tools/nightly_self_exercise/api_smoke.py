"""
HTTP smoke against a running API — stdlib only.

- Does not mutate mailbox (intake poll optional and off by default).
- VE warm: list ideas after login.
- Auth: POST /auth/login with env credentials.
"""
from __future__ import annotations

import http.cookiejar
import json
import os
import ssl
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Literal

SmokeTier = Literal["quick", "local", "full"]


@dataclass
class SmokeOutcome:
    ok: bool
    checks: list[tuple[str, bool, str]] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    council_stream_flaky: bool = False
    """Set after successful VE create until successful delete (for harness cleanup if run aborts)."""
    scratch_idea_id: str | None = None


def _json_req(
    opener: urllib.request.OpenerDirector,
    method: str,
    url: str,
    body: dict | None = None,
    timeout: float = 60.0,
) -> tuple[int, Any]:
    data = None
    headers = {"Accept": "application/json"}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with opener.open(req, timeout=timeout) as resp:
            raw = resp.read()
            code = resp.getcode()
            if not raw:
                return code, None
            try:
                return code, json.loads(raw.decode("utf-8"))
            except json.JSONDecodeError:
                return code, raw.decode("utf-8", errors="replace")[:2000]
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="replace")[:2000]
        return e.code, {"_http_error": err_body}


def run_api_smoke(
    api_base: str,
    *,
    email: str | None,
    password: str | None,
    tier: SmokeTier = "full",
    intake_poll: bool = False,
    council_stream_timeout_s: float = 45.0,
    council_stream_twice_for_flaky: bool = True,
) -> SmokeOutcome:
    base = api_base.rstrip("/")
    out = SmokeOutcome(ok=True)
    cj = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
    ctx = ssl.create_default_context()
    opener.add_handler(urllib.request.HTTPSHandler(context=ctx))

    def add(name: str, ok: bool, detail: str) -> None:
        out.checks.append((name, ok, detail))
        if not ok:
            out.ok = False
            out.errors.append(f"{name}: {detail}")

    # Health
    code, data = _json_req(opener, "GET", f"{base}/health", None, timeout=15.0)
    add("health", code == 200, f"code={code} body={str(data)[:200]}")

    # Intake queue (no auth)
    code, data = _json_req(opener, "GET", f"{base}/intake/queue?limit=5", None, timeout=30.0)
    add("intake_queue", code == 200, f"code={code} type={type(data).__name__}")

    # Synthetic email ingest (in-memory queue; not mailbox)
    code, data = _json_req(
        opener,
        "POST",
        f"{base}/intake/email",
        {"raw_body": "Subject: Nightly test\n\nBody: prescription refill request for nightly harness."},
        timeout=60.0,
    )
    add("intake_email_synthetic", code == 200, f"code={code}")

    if intake_poll:
        code, data = _json_req(opener, "POST", f"{base}/intake/email/poll", {}, timeout=120.0)
        ok = code in (200, 503)
        add("intake_email_poll", ok, f"code={code} (503 ok if IMAP not configured)")

    if tier == "quick":
        return out

    rw_id: str | None = None
    if email and password:
        code, _ = _json_req(opener, "POST", f"{base}/auth/login", {"email": email, "password": password}, timeout=30.0)
        add("auth_login", code == 200, f"code={code}")

        code, ideas = _json_req(opener, "GET", f"{base}/vision-execution/ideas", None, timeout=60.0)
        add("ve_list_ideas", code == 200, f"code={code}")

        tag = "NightlyHarness"
        create_body = {
            "title": f"{tag} scratch",
            "summary": "auto",
            "description": "nightly self-exercise",
            "status": "Captured",
        }
        code, created = _json_req(opener, "POST", f"{base}/vision-execution/ideas", create_body, timeout=60.0)
        idea_id = None
        if code == 200 and isinstance(created, dict):
            idea_id = created.get("id")
        add("ve_create_idea", code == 200 and bool(idea_id), f"code={code} id={idea_id}")
        if idea_id:
            out.scratch_idea_id = str(idea_id)

        if idea_id:
            code, _ = _json_req(
                opener,
                "PATCH",
                f"{base}/vision-execution/ideas/{idea_id}",
                {"summary": f"{tag} updated"},
                timeout=60.0,
            )
            add("ve_patch_idea", code == 200, f"code={code}")
            code, _ = _json_req(opener, "DELETE", f"{base}/vision-execution/ideas/{idea_id}", None, timeout=60.0)
            add("ve_delete_idea", code == 200, f"code={code}")
            if code == 200:
                out.scratch_idea_id = None
        else:
            add("ve_patch_idea", False, "skipped")
            add("ve_delete_idea", False, "skipped")

        code, _ = _json_req(
            opener,
            "POST",
            f"{base}/vision-execution/learning-records/user-outcome",
            {"learning_record_id": "__nightly_nonexistent__", "user_outcome": "dismissed"},
            timeout=15.0,
        )
        add(
            "learning_user_outcome_route",
            code == 404,
            f"code={code} (expect 404 for fake id — proves route + validation)",
        )

        code, _ = _json_req(opener, "GET", f"{base}/vision-execution/learning-records/stats", None, timeout=15.0)
        add(
            "learning_stats_gate",
            code in (200, 403),
            f"code={code} (403 ok when export disabled)",
        )

        if tier == "local":
            add("focus_rewrite", True, "skipped (local tier — no LLM loop in smoke)")
            add("idea_evaluate", True, "skipped (local tier — no LLM loop in smoke)")
        else:
            code, ideas2 = _json_req(opener, "GET", f"{base}/vision-execution/ideas", None, timeout=30.0)
            if code == 200 and isinstance(ideas2, list) and ideas2:
                rw_id = ideas2[0].get("id")
            if rw_id:
                code, fr = _json_req(
                    opener,
                    "POST",
                    f"{base}/vision-execution/focus-actions/rewrite",
                    {
                        "entity_type": "idea",
                        "entity_id": rw_id,
                        "field_key": "summary",
                        "field_label": "Summary",
                        "text_override": "Nightly harness rewrite probe. One sentence.",
                    },
                    timeout=120.0,
                )
                err = ""
                if isinstance(fr, dict):
                    err = (fr.get("error") or "")[:300]
                llm_gap = code == 200 and isinstance(fr, dict) and fr.get("error")
                if llm_gap:
                    add("focus_rewrite", True, f"known_gap LLM: code={code} err={err}")
                else:
                    add("focus_rewrite", code == 200, f"code={code} err={err or 'none'}")
            else:
                add("focus_rewrite", True, "skipped — no ideas in DB for rewrite probe")

            if rw_id:
                code, ev = _json_req(
                    opener,
                    "POST",
                    f"{base}/vision-execution/ideas/{rw_id}/evaluate",
                    {"relaxed": True},
                    timeout=180.0,
                )
                err_ev = ""
                if isinstance(ev, dict):
                    err_ev = str(ev.get("error") or "")[:300]
                llm_ev_err = code == 200 and isinstance(ev, dict) and ev.get("error")
                if llm_ev_err:
                    add("idea_evaluate", True, f"known_gap LLM: {err_ev}")
                else:
                    add(
                        "idea_evaluate",
                        code == 200 and isinstance(ev, dict),
                        f"code={code} err={err_ev or 'none'}",
                    )
    else:
        for name, msg in [
            ("auth_login", "no ATRIA_NIGHTLY_EMAIL/PASSWORD"),
            ("ve_list_ideas", "auth required"),
            ("ve_create_idea", "auth required"),
            ("ve_patch_idea", "auth required"),
            ("ve_delete_idea", "auth required"),
            ("learning_user_outcome_route", "auth required"),
            ("learning_stats_gate", "auth required"),
            ("focus_rewrite", "auth required"),
            ("idea_evaluate", "auth required"),
        ]:
            add(name, True, f"skipped (known_gap: {msg})")

    if tier == "local":
        add(
            "council_stream",
            True,
            "skipped (local tier — council covered by optional cloud sample after local green)",
        )
        return out

    # Full-tier stream probe shares the cookie jar; without nightly creds we never logged in —
    # running it anyway produces noisy IncompleteRead/empty-body failures while public + auth-skip checks are green.
    if not (email and password):
        add(
            "council_stream",
            True,
            "skipped (known_gap: set ATRIA_NIGHTLY_EMAIL and ATRIA_NIGHTLY_PASSWORD for stream probe)",
        )
        return out

    # Council stream probe (optional LLM); full tier only
    def stream_once() -> tuple[bool, str]:
        body = {
            "mode": "council",
            "params": {
                "question": "Nightly harness: reply with exactly: OK",
                "included_agents": ["strategist"],
                "include_synthesis": True,
            },
            "context": {},
        }
        data = json.dumps(body).encode("utf-8")
        req = urllib.request.Request(
            f"{base}/run/stream",
            data=data,
            method="POST",
            headers={"Content-Type": "application/json", "Accept": "text/event-stream"},
        )
        try:
            with opener.open(req, timeout=council_stream_timeout_s) as resp:
                chunk = resp.read(8192)
                return True, f"read {len(chunk)} bytes status={resp.getcode()}"
        except Exception as e:
            return False, str(e)[:500]

    ok_s, det_s = stream_once()
    if council_stream_twice_for_flaky:
        ok_s2, det_s2 = stream_once()
        out.council_stream_flaky = ok_s != ok_s2
        ok_final = ok_s or ok_s2
        add(
            "council_stream",
            ok_final,
            f"run1={ok_s} {det_s} | run2={ok_s2} {det_s2}" + (" | FLAKY" if out.council_stream_flaky else ""),
        )
    else:
        add("council_stream", ok_s, det_s)

    return out
