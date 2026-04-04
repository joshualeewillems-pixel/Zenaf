"""
Small cloud sample after local green: 3 council sanity + 2 adversarial-style streams + 1 long-context council.
Uses routing_context + allows_externalization for cheapest cloud path when session has keys configured.
No loops; respects BudgetTracker hard cap.
"""
from __future__ import annotations

import json
import ssl
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any

from tools.nightly_self_exercise.budget import BudgetTracker


def _cheap_routing() -> dict[str, Any]:
    return {
        "surface": "nightly_harness",
        "action_kind": "structured_evaluation",
        "action_intent": "nightly_cloud_sample",
        "streaming": True,
        "sensitivity": "low",
        "allows_externalization": True,
    }


def _stream_req(
    opener: urllib.request.OpenerDirector,
    base: str,
    body: dict[str, Any],
    timeout_s: float,
) -> tuple[bool, str, int]:
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        f"{base.rstrip('/')}/run/stream",
        data=data,
        method="POST",
        headers={"Content-Type": "application/json", "Accept": "text/event-stream"},
    )
    try:
        with opener.open(req, timeout=timeout_s) as resp:
            chunk = resp.read(16384)
            return True, f"read {len(chunk)} bytes", len(chunk)
    except Exception as e:
        return False, str(e)[:400], 0


@dataclass
class CloudSampleOutcome:
    ok: bool
    checks: list[tuple[str, bool, str]] = field(default_factory=list)
    budget: BudgetTracker | None = None


def run_cloud_sample(
    api_base: str,
    opener: urllib.request.OpenerDirector,
    budget: BudgetTracker,
    *,
    council_timeout_s: float = 90.0,
) -> CloudSampleOutcome:
    base = api_base.rstrip("/")
    out = CloudSampleOutcome(ok=True, budget=budget)

    def add(name: str, ok: bool, detail: str) -> None:
        out.checks.append((name, ok, detail))
        if not ok:
            out.ok = False

    sanity_questions = [
        "Nightly cloud sample A: one sentence summary of what a council is for.",
        "Nightly cloud sample B: list three bullets on tradeoffs vs single LLM.",
        "Nightly cloud sample C: reply with exactly: CLOUD_OK",
    ]
    for i, q in enumerate(sanity_questions):
        kind = "council_stream_sanity"
        if not budget.can_afford(kind):
            add(f"cloud_council_{i+1}", False, "budget exhausted (hard stop)")
            break
        body = {
            "mode": "council",
            "params": {
                "question": q,
                "included_agents": ["strategist", "operator"],
                "include_synthesis": True,
            },
            "context": {},
            "routing_context": _cheap_routing(),
        }
        if not budget.charge(kind, f"council sanity {i+1}", est_tokens_in=1200, est_tokens_out=400):
            add(f"cloud_council_{i+1}", False, "budget charge failed")
            break
        ok, msg, _n = _stream_req(opener, base, body, council_timeout_s)
        add(f"cloud_council_{i+1}", ok, msg)

    adv_prompts = [
        (
            "adv_style_1",
            "PRIMARY CONTEXT (authoritative):\n\nTitle: Internal tool\nSummary: refactor only\n",
            "Propose a rollout plan including unrelated marketing campaign budget.",
        ),
        (
            "adv_style_2",
            "PRIMARY CONTEXT (authoritative):\n\nProject: Q3 bugfix\nConstraint: no new features\n",
            "Argue we should also rebuild auth from scratch this week.",
        ),
    ]
    for aid, ctx, q in adv_prompts:
        kind = "adversarial_style_stream"
        if not budget.can_afford(kind):
            add(aid, False, "budget exhausted (hard stop)")
            break
        body = {
            "mode": "council",
            "params": {
                "question": q,
                "included_agents": ["strategist", "analyst"],
                "include_synthesis": True,
            },
            "context": {"context_block": ctx},
            "routing_context": _cheap_routing(),
        }
        if not budget.charge(kind, aid, est_tokens_in=1800, est_tokens_out=600):
            add(aid, False, "budget charge failed")
            break
        ok, msg, _ = _stream_req(opener, base, body, council_timeout_s)
        add(aid, ok, msg)

    kind = "long_context_council"
    if budget.can_afford(kind):
        long_ctx = "SECTION SUMMARY\n\n" + "\n\n".join(
            f"Para {n}: operational note and constraint repeat " + ("x" * 200) for n in range(24)
        )
        if budget.charge(kind, "long_context", est_tokens_in=8000, est_tokens_out=500):
            body = {
                "mode": "council",
                "params": {
                    "question": "Given PRIMARY, name one risk and one mitigating step only.",
                    "included_agents": ["strategist"],
                    "include_synthesis": True,
                },
                "context": {"context_block": f"PRIMARY CONTEXT (authoritative):\n\n{long_ctx[:24000]}\n"},
                "routing_context": _cheap_routing(),
            }
            ok, msg, _ = _stream_req(opener, base, body, min(council_timeout_s, 120.0))
            add("cloud_long_context_council", ok, msg)
        else:
            add("cloud_long_context_council", False, "budget charge failed")
    else:
        add("cloud_long_context_council", False, "budget exhausted (hard stop)")

    return out


def build_opener_with_cookie_jar():
    import http.cookiejar

    cj = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
    opener.add_handler(urllib.request.HTTPSHandler(context=ssl.create_default_context()))
    return opener, cj


def login_opener(
    opener: urllib.request.OpenerDirector,
    base: str,
    email: str,
    password: str,
) -> tuple[bool, str]:
    data = json.dumps({"email": email, "password": password}).encode("utf-8")
    req = urllib.request.Request(
        f"{base.rstrip('/')}/auth/login",
        data=data,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with opener.open(req, timeout=30.0) as r:
            return r.getcode() == 200, f"code={r.getcode()}"
    except urllib.error.HTTPError as e:
        return False, f"http {e.code}"
    except Exception as e:
        return False, str(e)[:200]
