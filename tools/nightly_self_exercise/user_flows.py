"""
Scripted API user flows for the nightly harness: exercise major surfaces end-to-end.

- Public routes: health, intake, transcript sort (no auth).
- Authenticated: settings LLM, VE CRUD chain (idea→initiative→project→task), execution steps,
  Layer-1 signals, decisions list, radar, prompt-signals (defer/check/dismiss cleanup).
- Optional admin: Studio read endpoints (403 → known_gap for non-admin nightly users).

Does not open folder-picker, POST /run (non-stream), or mailbox poll unless caller runs intake elsewhere.
"""
from __future__ import annotations

import http.cookiejar
import json
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any


@dataclass
class FlowOutcome:
    ok: bool
    checks: list[tuple[str, bool, str]] = field(default_factory=list)


def _json_req(
    opener: urllib.request.OpenerDirector,
    method: str,
    url: str,
    body: dict | list | None = None,
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
        try:
            parsed = json.loads(err_body)
        except json.JSONDecodeError:
            parsed = err_body
        return e.code, parsed


def _add(out: FlowOutcome, name: str, ok: bool, detail: str, *, hard: bool = True) -> None:
    out.checks.append((name, ok, detail))
    if hard and not ok:
        out.ok = False


def _add_soft(out: FlowOutcome, name: str, ok: bool, detail: str) -> None:
    """Non-admin / optional paths: failure does not fail the whole suite."""
    out.checks.append((name, ok, detail))


def run_public_user_flows(api_base: str) -> FlowOutcome:
    """Unauthenticated flows (always run)."""
    base = api_base.rstrip("/")
    out = FlowOutcome(ok=True)
    cj = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
    opener.add_handler(urllib.request.HTTPSHandler(context=ssl.create_default_context()))

    code, data = _json_req(opener, "GET", f"{base}/health", None, timeout=15.0)
    _add(out, "uf_public_health", code == 200, f"code={code}")

    code, data = _json_req(opener, "GET", f"{base}/intake/queue?limit=3", None, timeout=25.0)
    _add(out, "uf_public_intake_queue", code == 200, f"code={code}")

    code, data = _json_req(
        opener,
        "POST",
        f"{base}/intake/email",
        {"raw_body": "Subject: Nightly user-flow\n\nBody: harness synthetic ingest."},
        timeout=45.0,
    )
    _add(out, "uf_public_intake_email", code == 200, f"code={code}")

    code, data = _json_req(
        opener,
        "POST",
        f"{base}/transcripts/sort",
        {
            "raw_transcript_text": "Alice: We should ship the patch by Friday.\nBob: Agreed — I'll own QA.\n",
            "call_context": {},
        },
        timeout=90.0,
    )
    ok_ts = code == 200 and isinstance(data, dict)
    _add(out, "uf_public_transcript_sort", ok_ts, f"code={code} keys={list(data.keys())[:8] if isinstance(data, dict) else 'n/a'}")

    return out


def run_authenticated_user_flows(
    api_base: str,
    email: str,
    password: str,
) -> FlowOutcome:
    """Full VE + settings + prompt-signal flows; cleans up created rows."""
    base = api_base.rstrip("/")
    out = FlowOutcome(ok=True)
    cj = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
    opener.add_handler(urllib.request.HTTPSHandler(context=ssl.create_default_context()))

    tag = f"NightlyUF-{uuid.uuid4().hex[:8]}"

    code, _ = _json_req(opener, "POST", f"{base}/auth/login", {"email": email, "password": password}, timeout=30.0)
    _add(out, "uf_auth_login", code == 200, f"code={code}")

    code, st = _json_req(opener, "GET", f"{base}/settings/llm", None, timeout=30.0)
    _add(out, "uf_settings_llm", code == 200, f"code={code} body_type={type(st).__name__}")

    code, me = _json_req(opener, "GET", f"{base}/studio/me", None, timeout=20.0)
    is_admin = code == 200 and isinstance(me, dict)
    if is_admin:
        code2, runs = _json_req(opener, "GET", f"{base}/studio/council/recent-runs?limit=3", None, timeout=20.0)
        _add_soft(out, "uf_studio_recent_runs", code2 == 200, f"code={code2}")
        code3, _idx = _json_req(opener, "GET", f"{base}/studio/system-index", None, timeout=45.0)
        _add_soft(out, "uf_studio_system_index", code3 == 200, f"code={code3}")
    else:
        _add_soft(out, "uf_studio_admin_routes", code in (403, 401), f"skipped non-admin code={code}")

    idea_id: str | None = None
    ini_id: str | None = None
    proj_id: str | None = None
    task_id: str | None = None
    step_ids: list[str] = []

    try:
        code, created = _json_req(
            opener,
            "POST",
            f"{base}/vision-execution/ideas",
            {
                "title": f"{tag} idea",
                "summary": "user flow",
                "description": "nightly user_flows.py",
                "status": "Captured",
            },
            timeout=60.0,
        )
        if code == 200 and isinstance(created, dict):
            idea_id = str(created.get("id") or "")
        _add(out, "uf_ve_create_idea", code == 200 and bool(idea_id), f"code={code} id={idea_id}")

        code, ini = _json_req(
            opener,
            "POST",
            f"{base}/vision-execution/initiatives",
            {
                "title": f"{tag} initiative",
                "brief": "flow",
                "source_idea_id": idea_id,
                "status": "Draft",
            },
            timeout=60.0,
        )
        if code == 200 and isinstance(ini, dict):
            ini_id = str(ini.get("id") or "")
        _add(out, "uf_ve_create_initiative", code == 200 and bool(ini_id), f"code={code} id={ini_id}")

        if ini_id:
            code, st_row = _json_req(
                opener,
                "POST",
                f"{base}/vision-execution/initiatives/{ini_id}/execution-steps",
                {"title": f"{tag} step I"},
                timeout=30.0,
            )
            sid = ""
            if code == 200 and isinstance(st_row, dict):
                sid = str(st_row.get("id") or "")
                if sid:
                    step_ids.append(sid)
            _add(out, "uf_ve_exec_step_initiative", code == 200 and bool(sid), f"code={code} step={sid}")

        code, proj = _json_req(
            opener,
            "POST",
            f"{base}/vision-execution/projects",
            {
                "title": f"{tag} project",
                "brief": "flow",
                "initiative_id": ini_id,
                "status": "Draft",
            },
            timeout=60.0,
        )
        if code == 200 and isinstance(proj, dict):
            proj_id = str(proj.get("id") or "")
        _add(out, "uf_ve_create_project", code == 200 and bool(proj_id), f"code={code} id={proj_id}")

        if proj_id:
            code, stp = _json_req(
                opener,
                "POST",
                f"{base}/vision-execution/projects/{proj_id}/execution-steps",
                {"title": f"{tag} step P"},
                timeout=30.0,
            )
            sidp = ""
            if code == 200 and isinstance(stp, dict):
                sidp = str(stp.get("id") or "")
                if sidp:
                    step_ids.append(sidp)
            _add(out, "uf_ve_exec_step_project", code == 200 and bool(sidp), f"code={code} step={sidp}")

        code, task = _json_req(
            opener,
            "POST",
            f"{base}/vision-execution/tasks",
            {
                "project_id": proj_id,
                "title": f"{tag} task",
                "description": "nightly",
                "status": "Todo",
            },
            timeout=60.0,
        )
        if code == 200 and isinstance(task, dict):
            task_id = str(task.get("id") or "")
        _add(out, "uf_ve_create_task", code == 200 and bool(task_id), f"code={code} id={task_id}")

        code, idea_get = _json_req(opener, "GET", f"{base}/vision-execution/ideas/{idea_id}", None, timeout=30.0)
        _add(out, "uf_ve_get_idea", code == 200, f"code={code}")

        code, sig_body = _json_req(
            opener,
            "POST",
            f"{base}/vision-execution/signals",
            [
                {
                    "kind": "info",
                    "title": f"{tag} signal",
                    "detail": "nightly harness",
                    "source": "nightly_user_flow",
                    "linkedInitiativeId": ini_id,
                }
            ],
            timeout=30.0,
        )
        ok_sig = code == 200 and isinstance(sig_body, list) and len(sig_body) > 0
        _add(out, "uf_ve_post_signals", ok_sig, f"code={code} n={len(sig_body) if isinstance(sig_body, list) else 0}")

        code, sig_list = _json_req(
            opener, "GET", f"{base}/vision-execution/signals?source=nightly_user_flow&limit=5", None, timeout=20.0
        )
        _add(out, "uf_ve_list_signals", code == 200 and isinstance(sig_list, list), f"code={code}")

        code, _ = _json_req(
            opener,
            "POST",
            f"{base}/vision-execution/decisions",
            {
                "entity_type": "initiative",
                "entity_id": ini_id,
                "decision_type": "manual_score_override",
                "final_values_snapshot": {"source": "nightly_user_flow", "tag": tag},
            },
            timeout=20.0,
        )
        _add(out, "uf_ve_post_decision", code == 200, f"code={code}")

        code, decs = _json_req(
            opener,
            "GET",
            f"{base}/vision-execution/decisions?entity_type=initiative&entity_id={ini_id}&limit=10",
            None,
            timeout=20.0,
        )
        _add(out, "uf_ve_list_decisions", code == 200 and isinstance(decs, list), f"code={code} n={len(decs) if isinstance(decs, list) else 0}")

        code, radar = _json_req(opener, "GET", f"{base}/vision-execution/radar", None, timeout=45.0)
        _add(out, "uf_ve_radar", code == 200 and isinstance(radar, dict), f"code={code}")

        pid = f"dm:vm:g:nightly_uf_{uuid.uuid4().hex[:12]}"
        defer_until = (datetime.now(timezone.utc) + timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%S") + "Z"
        code, _ = _json_req(
            opener,
            "POST",
            f"{base}/vision-execution/prompt-signals",
            {
                "prompt_id": pid,
                "action": "deferred",
                "entity_type": "workspace",
                "entity_id": "vision_map",
                "prompt_summary": f"{tag} defer probe",
                "deferred_until": defer_until,
            },
            timeout=20.0,
        )
        _add(out, "uf_prompt_signal_defer", code == 200, f"code={code}")

        code, def_rows = _json_req(
            opener,
            "GET",
            f"{base}/vision-execution/prompt-signals/deferred?entity_type=workspace&entity_id=vision_map",
            None,
            timeout=20.0,
        )
        ok_def = code == 200 and isinstance(def_rows, dict) and isinstance(def_rows.get("items"), list)
        _add(out, "uf_prompt_signal_list_deferred", ok_def, f"code={code}")

        code, chk0 = _json_req(
            opener, "GET", f"{base}/vision-execution/prompt-signals/check?prompt_id={urllib.parse.quote(pid, safe='')}", None, timeout=15.0
        )
        show0 = isinstance(chk0, dict) and chk0.get("show") is True
        _add(out, "uf_prompt_signal_check_before_dismiss", code == 200 and show0, f"code={code} show={chk0!s}"[:300])

        code, _ = _json_req(
            opener,
            "POST",
            f"{base}/vision-execution/prompt-signals",
            {
                "prompt_id": pid,
                "action": "dismissed",
                "prompt_summary": f"{tag} dismiss cleanup",
            },
            timeout=20.0,
        )
        _add(out, "uf_prompt_signal_dismiss_global", code == 200, f"code={code}")

        code, chk1 = _json_req(
            opener, "GET", f"{base}/vision-execution/prompt-signals/check?prompt_id={qpid}", None, timeout=15.0
        )
        show1 = isinstance(chk1, dict) and chk1.get("show") is False
        _add(out, "uf_prompt_signal_check_after_dismiss", code == 200 and show1, f"code={code} show={chk1!s}"[:300])

        for sid in step_ids:
            code, _ = _json_req(opener, "DELETE", f"{base}/vision-execution/execution-steps/{sid}", None, timeout=20.0)
            _add(out, f"uf_ve_delete_step_{sid[:6]}", code == 200, f"code={code}")

        if task_id:
            code, _ = _json_req(opener, "DELETE", f"{base}/vision-execution/tasks/{task_id}", None, timeout=30.0)
            _add(out, "uf_ve_delete_task", code == 200, f"code={code}")
        if proj_id:
            code, _ = _json_req(opener, "DELETE", f"{base}/vision-execution/projects/{proj_id}", None, timeout=30.0)
            _add(out, "uf_ve_delete_project", code == 200, f"code={code}")
        if ini_id:
            code, _ = _json_req(opener, "DELETE", f"{base}/vision-execution/initiatives/{ini_id}", None, timeout=30.0)
            _add(out, "uf_ve_delete_initiative", code == 200, f"code={code}")
        if idea_id:
            code, _ = _json_req(opener, "DELETE", f"{base}/vision-execution/ideas/{idea_id}", None, timeout=30.0)
            _add(out, "uf_ve_delete_idea", code == 200, f"code={code}")

    except Exception as e:
        _add(out, "uf_authenticated_flow_exception", False, str(e)[:500])
        # best-effort cleanup
        for sid in step_ids:
            try:
                _json_req(opener, "DELETE", f"{base}/vision-execution/execution-steps/{sid}", None, timeout=15.0)
            except OSError:
                pass
        for eid, path in (
            (task_id, "tasks"),
            (proj_id, "projects"),
            (ini_id, "initiatives"),
            (idea_id, "ideas"),
        ):
            if eid:
                try:
                    _json_req(opener, "DELETE", f"{base}/vision-execution/{path}/{eid}", None, timeout=15.0)
                except OSError:
                    pass

    return out


def merge_flow_outcomes(public: FlowOutcome, auth: FlowOutcome | None) -> FlowOutcome:
    checks = list(public.checks)
    ok = public.ok
    if auth is not None:
        checks.extend(auth.checks)
        ok = ok and auth.ok
    return FlowOutcome(ok=ok, checks=checks)


def run_user_flow_suite(
    api_base: str,
    *,
    email: str | None,
    password: str | None,
) -> FlowOutcome:
    pub = run_public_user_flows(api_base)
    if not email or not password:
        auth_out = FlowOutcome(ok=True)
        auth_out.checks.append(
            (
                "uf_authenticated_skipped",
                True,
                "known_gap: set ATRIA_NIGHTLY_EMAIL and ATRIA_NIGHTLY_PASSWORD for full VE / settings / prompt-signal flows",
            )
        )
        return merge_flow_outcomes(pub, auth_out)
    auth = run_authenticated_user_flows(api_base, email, password)
    return merge_flow_outcomes(pub, auth)


def stress_user_flow_reads(api_base: str, email: str, password: str, iterations: int) -> tuple[bool, str, list[float]]:
    """
    Repeat lightweight authenticated + public reads to probe latency variance (no extra CRUD).
    """
    import statistics

    base = api_base.rstrip("/")
    times: list[float] = []
    errors: list[str] = []
    cj = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
    opener.add_handler(urllib.request.HTTPSHandler(context=ssl.create_default_context()))
    code, _ = _json_req(opener, "POST", f"{base}/auth/login", {"email": email, "password": password}, timeout=30.0)
    if code != 200:
        return False, f"login failed code={code}", []

    n = max(1, iterations)
    for i in range(n):
        t0 = time.perf_counter()
        try:
            c1, _ = _json_req(opener, "GET", f"{base}/health", None, timeout=12.0)
            c2, _ = _json_req(opener, "GET", f"{base}/vision-execution/ideas", None, timeout=25.0)
            c3, _ = _json_req(opener, "GET", f"{base}/vision-execution/projects", None, timeout=25.0)
            c4, _ = _json_req(opener, "GET", f"{base}/settings/llm", None, timeout=20.0)
            if c1 != 200 or c2 != 200 or c3 != 200 or c4 != 200:
                errors.append(f"iter{i}: codes h={c1} ideas={c2} proj={c3} llm={c4}")
        except Exception as e:
            errors.append(f"iter{i}:{e}")
        times.append(time.perf_counter() - t0)

    ok = not errors
    summary = f"n={n} p50={statistics.median(times):.3f}s max={max(times):.3f}s"
    if errors:
        summary += " | " + "; ".join(errors[:6])
    return ok, summary, times
