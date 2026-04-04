"""Council mini-suite: POST /run with X-Atria-Session; load stored rows for comparison."""
from __future__ import annotations

import json
import os
import re
import sys
import urllib.request
from typing import Any

# repo root
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

BASE = os.environ.get("ATRIA_API_BASE", "http://127.0.0.1:8010").rstrip("/")

EMAIL = os.environ.get("ATRIA_SUITE_EMAIL", "owner@local.atria")
PASSWORD = os.environ.get("ATRIA_BOOTSTRAP_PASSWORD", "").strip() or "local-dev-owner"


def session_token() -> str:
    body = json.dumps({"email": EMAIL, "password": PASSWORD}).encode()
    req = urllib.request.Request(
        f"{BASE}/auth/login",
        data=body,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        r.read()
        cookies = r.headers.get_all("Set-Cookie") or []
    for c in cookies:
        m = re.search(r"atria_session=([^;]+)", c)
        if m:
            return m.group(1)
    raise RuntimeError("no atria_session in login response")


def post_run(token: str, question: str, perspective_definitions: list[dict] | None) -> dict[str, Any]:
    params: dict[str, Any] = {
        "question": question,
        "teacher_mode": "shadow",
        "native_provider": "openai",
        "native_model": "gpt-4.1-mini",
        "teacher_provider": "openai",
        "teacher_model": "gpt-4.1",
        "include_synthesis": True,
    }
    if perspective_definitions:
        params["perspective_definitions"] = perspective_definitions
    else:
        # Suite expects native multi-seat council; empty seats would otherwise use conversational partner.
        params["force_full_council"] = True
    payload = {"mode": "council", "params": params}
    req = urllib.request.Request(
        f"{BASE}/run",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", "X-Atria-Session": token},
    )
    with urllib.request.urlopen(req, timeout=600) as r:
        return json.loads(r.read().decode())


def main() -> None:
    from local_ai.vision_execution import storage as St

    token = session_token()
    cases: list[tuple[str, str, list[dict] | None]] = [
        (
            "1.1",
            "what's the next step for this project?",
            None,
        ),
        (
            "1.3",
            "Project: Improve council grounding by enforcing truth-source order in prompts.\n"
            "Outcome: All council runs include explicit truth-source subsection and inline ordering.\n"
            "What's the next step?",
            None,
        ),
        (
            "2.1",
            "Should we expand features or improve reliability first?",
            None,
        ),
        (
            "3.1",
            "What's the next step for this project?",
            [
                {
                    "name": "Investor",
                    "purpose": "Evaluate decisions through ROI, risk, and scalability.",
                    "values": ["ROI", "risk", "scalability"],
                }
            ],
        ),
    ]

    rows_out: list[dict[str, Any]] = []

    for tag, question, pdefs in cases:
        resp = post_run(token, question, pdefs)
        rid = resp.get("teacher_artifact_id")
        if not rid:
            print(f"ERROR {tag}: no teacher_artifact_id", json.dumps(resp)[:800])
            continue
        row = St.get_council_teacher_run(str(rid)) or {}
        nd = row.get("native_run_debug") or {}
        sel = (nd.get("selection") or {}) if isinstance(nd, dict) else {}
        comp = row.get("comparison") or row.get("comparison_json") or {}
        if isinstance(comp, str):
            try:
                comp = json.loads(comp)
            except Exception:
                comp = {}
        rows_out.append(
            {
                "case": tag,
                "run_id": rid,
                "http": {
                    "execution_principal_ref": resp.get("execution_principal_ref"),
                    "native_provider": resp.get("native_provider"),
                    "native_model": resp.get("native_model"),
                    "teacher_provider_effective": resp.get("teacher_provider_effective"),
                    "teacher_model_effective": resp.get("teacher_model_effective"),
                    "teacher_succeeded": resp.get("teacher_succeeded"),
                },
                "stored_final_selection_policy": row.get("final_selection_policy"),
                "selected_source": sel.get("selected_source"),
                "comparison": comp,
            }
        )

    print(json.dumps(rows_out, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
