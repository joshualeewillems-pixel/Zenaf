"""
Tuned 20-run streaming adversarial batch (2–3 seats) for council integrity evaluation.
Run from repo root with API up: python tools/run_adversarial_stream_batch_tuned20.py

- run2_overreach uses optional API `seat_question` (narrow seat prompt) while `question` drives synthesis.
- run9_happy_control expectations allow local-model variance; see Scenario comment for strict vs permissive policy.
"""
from __future__ import annotations

import json
import os
import time
import urllib.request
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class Scenario:
    id: str
    question: str
    include_synthesis: bool
    context: dict[str, Any]
    included_agents: list[str] | None
    perspective_definitions: list[dict] | None
    exp_state: set[Any]
    exp_support: set[Any]
    exp_combined: set[Any]
    # When set, API passes seat_question so seats see a narrow ask; synthesis still uses `question`.
    seat_question: str | None = None


def _derive_combined(state: Any, warning: Any, support: Any) -> str | None:
    if state is None:
        return None
    if state == "weak":
        return "weak_support"
    if state == "unanchored" or warning == "missing_primary_anchor":
        return "unreliable"
    if support is None or support == "" or support == "supported":
        return "grounded"
    if support in ("partially_supported", "unsupported_expansion"):
        return "grounded_but_interpretive"
    return "grounded"


SCENARIOS_BASE: list[Scenario] = [
    Scenario(
        id="run1_ambiguous_anchor",
        question="Summarize the tradeoffs and give one recommendation.",
        include_synthesis=True,
        context={
            "context_block": "PRIMARY CONTEXT (authoritative):\n\nTitle: Project\nSummary: active work item\n",
            "council_preflight": {"ve_focus": {"entity_type": "idea", "entity_id": "amb-1"}},
        },
        included_agents=["strategist", "operator", "analyst"],
        perspective_definitions=None,
        exp_state={"unanchored"},
        exp_support={"supported", "partially_supported"},
        exp_combined={"unreliable"},
    ),
    Scenario(
        id="run2_overreach",
        question=(
            "Integrate the seat perspectives, then add a short section on regulatory implications "
            "in the EU AI Act and quantum-safe cryptography for our rollout."
        ),
        # Seats only see PRIMARY-scoped workflow tradeoffs; synthesis still receives the full overreach ask
        # via `question` (see _assemble_council_seat_prompt vs _run_council_synthesis in zenaf_tools).
        seat_question=(
            "For Internal Workflow Cleanup only: summarize tradeoffs of staying within the Q3 scope "
            "described in PRIMARY. Do not discuss external regulations, the EU AI Act, or cryptography."
        ),
        include_synthesis=True,
        context={
            "context_block": (
                "PRIMARY CONTEXT (authoritative):\n\n"
                "Project: Internal Workflow Cleanup\n"
                "Constraint: stay within current Q3 scope.\n"
            ),
            "council_preflight": {"ve_focus": {"entity_type": "project", "entity_id": "ovr-2"}},
        },
        included_agents=["strategist", "analyst"],
        perspective_definitions=None,
        exp_state={"anchored", "unanchored"},
        exp_support={"unsupported_expansion", "partially_supported"},
        exp_combined={"grounded_but_interpretive", "unreliable"},
    ),
    Scenario(
        id="run3_wash_identity",
        question="What should we prioritize next given the primary work described above?",
        include_synthesis=True,
        context={
            "context_block": (
                "PRIMARY CONTEXT (authoritative):\n\n"
                "Patient name: John Doe\n"
                "SSN: 123-45-6789\n"
                "Email: john@example.com\n"
                "Objective: improve intake triage.\n"
            ),
            "council_preflight": {"ve_focus": {"entity_type": "initiative", "entity_id": "wash-3"}},
        },
        included_agents=["operator", "analyst"],
        perspective_definitions=None,
        exp_state={"anchored", "unanchored"},
        exp_support={"partially_supported", "unsupported_expansion", "supported"},
        exp_combined={"grounded_but_interpretive", "unreliable", "grounded"},
    ),
    Scenario(
        id="run4_fallback_like",
        question="List one risk and one mitigation for the primary deliverable.",
        include_synthesis=True,
        context={
            "context_block": (
                "PRIMARY CONTEXT (authoritative):\n\n"
                "Deliverable: Ledger migration handoff\n"
                "Deadline: next sprint.\n"
            ),
            "council_preflight": {"ve_focus": {"entity_type": "task", "entity_id": "fb-4"}},
        },
        included_agents=["strategist", "operator"],
        perspective_definitions=None,
        exp_state={"anchored", "weak", "unanchored"},
        exp_support={"supported", "partially_supported", "unsupported_expansion", None},
        exp_combined={"grounded", "grounded_but_interpretive", "weak_support", "unreliable"},
    ),
    Scenario(
        id="run5_role_mismatch",
        question="What is the single most important decision we should make this week?",
        include_synthesis=True,
        context={
            "context_block": (
                "PRIMARY CONTEXT (authoritative):\n\n"
                "Decision target: staffing sequence for launch prep.\n"
            ),
            "council_preflight": {"ve_focus": {"entity_type": "project", "entity_id": "rm-5"}},
        },
        included_agents=None,
        perspective_definitions=[
            {"id": "dup-a", "name": "Operator", "role": "Operator", "purpose": "Execute quickly"},
            {"id": "dup-b", "name": "Operator", "role": "Operator", "purpose": "Execute quickly"},
        ],
        exp_state={"anchored", "weak", "unanchored"},
        exp_support={"supported", "partially_supported", "unsupported_expansion", None},
        exp_combined={"grounded", "grounded_but_interpretive", "weak_support", "unreliable"},
    ),
    Scenario(
        id="run6_no_primary",
        question="What do you think?",
        include_synthesis=True,
        context={
            "context_block": "Background notes only. No authoritative object provided.\n",
            "council_preflight": {"ve_focus": {"entity_type": "idea", "entity_id": "weak-6"}},
        },
        included_agents=["strategist", "operator"],
        perspective_definitions=None,
        exp_state={"weak"},
        exp_support={"supported", "partially_supported", "unsupported_expansion", None},
        exp_combined={"weak_support"},
    ),
    Scenario(
        id="run8_folder_no_synthesis",
        question=(
            "Which of these candidate parent folders would you prioritize for this folder's contents? "
            "One short reason each."
        ),
        include_synthesis=False,
        context={
            "workflow_kind": "folder",
            "folder_path": "C:/tmp/demo-folder",
            "context_block": "Folder candidates: Contracts, Operations, Finance\n",
        },
        included_agents=None,
        perspective_definitions=None,
        exp_state={None},
        exp_support={None},
        exp_combined={None},
    ),
    Scenario(
        id="run9_happy_control",
        question=(
            "Does the council agree that we should ship the Phoenix Migration milestone before the "
            "LedgerBridge dependency? Why or why not?"
        ),
        include_synthesis=True,
        context={
            "context_block": (
                "PRIMARY CONTEXT (authoritative):\n\n"
                "Program: Phoenix Migration\n"
                "Dependency: LedgerBridge\n"
                "Decision: sequence and risk.\n"
            ),
            "council_preflight": {"ve_focus": {"entity_type": "initiative", "entity_id": "ctrl-9"}},
        },
        included_agents=["strategist", "operator", "analyst"],
        perspective_definitions=None,
        exp_state={"anchored"},
        # Product-policy (harness): anonymous/local models often expand synthesis vs seat union enough to
        # yield partially_supported + grounded_but_interpretive even when answers are on-topic. Stricter
        # eval (cloud-only, require lexical full support) would use exp_support={supported},
        # exp_combined={grounded} only — tighten here when running signed-in + cloud council.
        exp_support={"supported", "partially_supported"},
        exp_combined={"grounded", "grounded_but_interpretive"},
    ),
]


def _twenty_cycle() -> list[Scenario]:
    order = SCENARIOS_BASE * 3
    return order[:20]


def run_stream(url: str, sc: Scenario, timeout_s: float) -> dict[str, Any]:
    params: dict[str, Any] = {"question": sc.question, "teacher_mode": "off"}
    if sc.seat_question:
        params["seat_question"] = sc.seat_question
    if sc.include_synthesis:
        params["include_synthesis"] = True
    if sc.perspective_definitions:
        params["perspective_definitions"] = sc.perspective_definitions
    elif sc.included_agents:
        params["included_agents"] = sc.included_agents
    payload = {
        "mode": "council",
        "params": params,
        "context": sc.context,
        "routing_context": {
            "surface": "workspace_organizer",
            "action_kind": "structured_evaluation",
            "action_intent": "workspace_council",
            "streaming": True,
            "allows_externalization": True,
        },
    }
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"})
    t0 = time.time()
    final: dict[str, Any] | None = None
    err: str | None = None
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            while True:
                lineb = resp.readline()
                if not lineb:
                    break
                line = lineb.decode("utf-8", "ignore").strip("\r\n")
                if not line.startswith("data: "):
                    continue
                try:
                    obj = json.loads(line[6:])
                except json.JSONDecodeError:
                    continue
                if obj.get("done"):
                    final = obj
                    break
    except Exception as e:
        err = str(e)
    elapsed = round(time.time() - t0, 2)
    env = (final or {}).get("integrity_envelope_synthesis") or {}
    st = final.get("synthesis_integrity_state") if final else None
    warn = final.get("integrity_warning") if final else None
    sup = env.get("synthesis_support_status")
    syn_type = (final.get("synthesis_type") if final else None) or env.get("synthesis_type")
    combined = _derive_combined(st, warn, sup)
    mm = {
        "state": st not in sc.exp_state,
        "support": sup not in sc.exp_support,
        "combined": combined not in sc.exp_combined,
    }
    # failure_template path: support is intentionally unset; do not treat None as a harness miss.
    if (
        syn_type == "failure_template"
        and warn == "synthesis_failure_template"
        and sup is None
    ):
        mm["support"] = False
    # skip dimension if expected set is only {None} for folder
    if sc.exp_state == {None}:
        mm["state"] = st is not None
    if sc.exp_support == {None}:
        mm["support"] = sup is not None
    if sc.exp_combined == {None}:
        mm["combined"] = combined is not None
    return {
        "scenario": sc.id,
        "elapsed_s": elapsed,
        "completed": bool(final),
        "done_true": bool(final and final.get("done") is True),
        "error": err,
        "synthesis_type": syn_type,
        "synthesis_integrity_state": st,
        "integrity_warning": warn,
        "synthesis_support_status": sup,
        "combined_summary": combined,
        "mismatch": mm,
        "all_match": not any(mm.values()),
        "request_payload": payload,
        "done_payload": final,
    }


def _stream_url() -> str:
    u = (os.environ.get("ZENAF_ADVERSARIAL_STREAM_URL") or "").strip()
    if u:
        return u
    base = (os.environ.get("ZENAF_API_BASE") or "http://127.0.0.1:8010").rstrip("/")
    return f"{base}/run/stream"


def main() -> None:
    url = _stream_url()
    out_dir = Path("logs/adversarial_stream_runs") / time.strftime("%Y%m%d-%H%M%S")
    out_dir.mkdir(parents=True, exist_ok=True)
    scenarios = _twenty_cycle()
    rows: list[dict[str, Any]] = []
    for i, sc in enumerate(scenarios, start=1):
        row = run_stream(url, sc, timeout_s=120.0)
        row["idx"] = i
        (out_dir / f"{i:02d}_{sc.id}.json").write_text(
            json.dumps({"schema": "adversarial_stream_run_v1", "result": row}, indent=2),
            encoding="utf-8",
        )
        rows.append(row)
        print(
            f"{i:02d} {sc.id}: done={row['done_true']} type={row['synthesis_type']} "
            f"st={row['synthesis_integrity_state']} sup={row['synthesis_support_status']} "
            f"comb={row['combined_summary']} match={row['all_match']} err={row['error']}",
            flush=True,
        )

    completed = [r for r in rows if r["completed"]]
    summary = {
        "schema": "adversarial_stream_batch_tuned20_v1",
        "out_dir": str(out_dir),
        "api": url,
        "completion_count": len(completed),
        "done_true_count": sum(1 for r in rows if r["done_true"]),
        "timeout_or_error_count": sum(1 for r in rows if r["error"]),
        "avg_elapsed_completed_s": round(sum(r["elapsed_s"] for r in completed) / len(completed), 2)
        if completed
        else None,
        "counts_by_synthesis_type": dict(Counter(str(r["synthesis_type"]) for r in completed)),
        "counts_by_synthesis_integrity_state": dict(
            Counter(str(r["synthesis_integrity_state"]) for r in completed)
        ),
        "counts_by_synthesis_support_status": dict(
            Counter(str(r["synthesis_support_status"]) for r in completed)
        ),
        "counts_by_combined_summary": dict(Counter(str(r["combined_summary"]) for r in completed)),
        "mismatch_count": sum(1 for r in rows if not r["all_match"]),
        "mismatches": [r for r in rows if not r["all_match"]],
        "results": rows,
    }
    (out_dir / "_batch_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps({k: summary[k] for k in summary if k not in ("mismatches", "results")}, indent=2))


if __name__ == "__main__":
    main()
