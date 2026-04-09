"""Run adversarial council scenarios through non-streaming /run.

Purpose:
- Keep integrity evaluation moving while /run/stream lifecycle is unstable.
- Capture completion + text output + available metadata.
- Compute a reduced integrity review record from final text when stream-only fields are unavailable.
"""

from __future__ import annotations

import argparse
import json
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any


_STOPWORDS = {
    "that",
    "this",
    "with",
    "from",
    "have",
    "will",
    "your",
    "what",
    "when",
    "been",
    "there",
    "their",
    "would",
    "could",
    "should",
    "about",
    "which",
    "these",
    "those",
    "them",
    "than",
    "then",
    "some",
    "such",
    "into",
    "just",
    "also",
    "more",
    "very",
    "only",
    "over",
    "after",
    "before",
    "being",
    "both",
    "each",
    "other",
    "under",
    "most",
    "many",
    "much",
    "well",
    "like",
    "make",
    "need",
    "even",
}


@dataclass
class Scenario:
    id: str
    question: str
    include_synthesis: bool
    context: dict[str, Any]
    primary_anchor_terms: list[str]
    perspective_definitions: list[dict[str, Any]] | None = None


SCENARIOS: list[Scenario] = [
    Scenario(
        id="run1_ambiguous_anchor",
        question="Summarize the tradeoffs and give one recommendation.",
        include_synthesis=True,
        context={
            "context_block": "PRIMARY CONTEXT (authoritative):\n\nTitle: Project\nSummary: active work item\n",
            "council_preflight": {"ve_focus": {"entity_type": "idea", "entity_id": "amb-1"}},
        },
        primary_anchor_terms=["project"],
    ),
    Scenario(
        id="run2_overreach",
        question="Integrate the seat perspectives, then add a short section on regulatory implications in the EU AI Act and quantum-safe cryptography for our rollout.",
        include_synthesis=True,
        context={
            "context_block": "PRIMARY CONTEXT (authoritative):\n\nProject: Internal Workflow Cleanup\nConstraint: stay within current Q3 scope.\n",
            "council_preflight": {"ve_focus": {"entity_type": "project", "entity_id": "ovr-2"}},
        },
        primary_anchor_terms=["internal workflow cleanup", "q3"],
    ),
    Scenario(
        id="run3_wash_identity",
        question="What should we prioritize next given the primary work described above?",
        include_synthesis=True,
        context={
            "context_block": "PRIMARY CONTEXT (authoritative):\n\nPatient name: John Doe\nSSN: 123-45-6789\nEmail: john@example.com\nObjective: improve intake triage.\n",
            "council_preflight": {"ve_focus": {"entity_type": "initiative", "entity_id": "wash-3"}},
        },
        primary_anchor_terms=["intake triage", "john doe"],
    ),
    Scenario(
        id="run4_fallback_like",
        question="List one risk and one mitigation for the primary deliverable.",
        include_synthesis=True,
        context={
            "context_block": "PRIMARY CONTEXT (authoritative):\n\nDeliverable: Ledger migration handoff\nDeadline: next sprint.\n",
            "council_preflight": {"ve_focus": {"entity_type": "task", "entity_id": "fb-4"}},
        },
        primary_anchor_terms=["ledger migration", "handoff", "next sprint"],
    ),
    Scenario(
        id="run5_role_mismatch",
        question="What is the single most important decision we should make this week?",
        include_synthesis=True,
        context={
            "context_block": "PRIMARY CONTEXT (authoritative):\n\nDecision target: staffing sequence for launch prep.\n",
            "council_preflight": {"ve_focus": {"entity_type": "project", "entity_id": "rm-5"}},
        },
        primary_anchor_terms=["staffing sequence", "launch prep"],
        perspective_definitions=[
            {"id": "dup-a", "name": "Operator", "role": "Operator", "purpose": "Execute quickly"},
            {"id": "dup-b", "name": "Operator", "role": "Operator", "purpose": "Execute quickly"},
        ],
    ),
    Scenario(
        id="run6_no_primary",
        question="What do you think?",
        include_synthesis=True,
        context={
            "context_block": "Background notes only. No authoritative object provided.\n",
            "council_preflight": {"ve_focus": {"entity_type": "idea", "entity_id": "weak-6"}},
        },
        primary_anchor_terms=[],
    ),
    Scenario(
        id="run8_folder_no_synthesis",
        question="Which of these candidate parent folders would you prioritize for this folder's contents? One short reason each.",
        include_synthesis=False,
        context={
            "workflow_kind": "folder",
            "folder_path": "C:/tmp/demo-folder",
            "context_block": "Folder candidates: Contracts, Operations, Finance\n",
        },
        primary_anchor_terms=[],
    ),
    Scenario(
        id="run9_happy_control",
        question="Does the council agree that we should ship the Phoenix Migration milestone before the LedgerBridge dependency? Why or why not?",
        include_synthesis=True,
        context={
            "context_block": "PRIMARY CONTEXT (authoritative):\n\nProgram: Phoenix Migration\nDependency: LedgerBridge\nDecision: sequence and risk.\n",
            "council_preflight": {"ve_focus": {"entity_type": "initiative", "entity_id": "ctrl-9"}},
        },
        primary_anchor_terms=["phoenix migration", "ledgerbridge"],
    ),
]


def _token_set(text: str) -> set[str]:
    words = re.findall(r"[a-z0-9]+", text.lower())
    return {w for w in words if len(w) >= 4 and w not in _STOPWORDS}


def _extract_synthesis(result_text: str) -> tuple[str, str]:
    marker = "Zenaf synthesis:"
    if marker not in result_text:
        return result_text.strip(), ""
    head, tail = result_text.split(marker, 1)
    return head.strip(), tail.strip()


def _support_status_reduced(seat_text: str, synthesis_text: str) -> str | None:
    body = (synthesis_text or "").strip()
    if not body:
        return None
    seat_union = (seat_text or "").lower().strip()
    if not seat_union:
        return "unsupported_expansion"
    toks = _token_set(body)
    if len(toks) < 4:
        return "supported"
    covered = 0
    for t in toks:
        if re.search(r"(?<![a-z0-9])" + re.escape(t) + r"(?![a-z0-9])", seat_union):
            covered += 1
    ratio = covered / len(toks)
    if ratio >= 0.55:
        return "supported"
    if ratio >= 0.30:
        return "partially_supported"
    return "unsupported_expansion"


def _derive_combined(state: str | None, warning: str | None, support: str | None) -> str | None:
    if state is None:
        return None
    if state == "weak":
        return "weak_support"
    if state == "unanchored" or warning == "missing_primary_anchor":
        return "unreliable"
    if support in (None, "", "supported"):
        return "grounded"
    if support in ("partially_supported", "unsupported_expansion"):
        return "grounded_but_interpretive"
    return "grounded"


def _anchor_detected(synthesis_text: str, anchor_terms: list[str]) -> bool | None:
    if not anchor_terms:
        return None
    low = synthesis_text.lower()
    for term in anchor_terms:
        t = term.strip().lower()
        if not t:
            continue
        if t in low:
            return True
    return False


def run_non_stream(base_url: str, scenario: Scenario, timeout_s: float) -> dict[str, Any]:
    params: dict[str, Any] = {"question": scenario.question, "teacher_mode": "off"}
    if scenario.include_synthesis:
        params["include_synthesis"] = True
    if scenario.perspective_definitions:
        params["perspective_definitions"] = scenario.perspective_definitions

    payload = {
        "mode": "council",
        "params": params,
        "context": scenario.context,
        "routing_context": {
            "surface": "workspace_organizer",
            "action_kind": "structured_evaluation",
            "action_intent": "workspace_council",
            "streaming": False,
            "allows_externalization": True,
        },
    }

    req = urllib.request.Request(
        f"{base_url.rstrip('/')}/run",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            raw = resp.read().decode("utf-8", "ignore")
        body = json.loads(raw)
    except (urllib.error.URLError, TimeoutError) as e:
        return {"ok": False, "scenario": scenario.id, "error": str(e), "elapsed_s": round(time.time() - t0, 2)}
    except Exception as e:
        return {"ok": False, "scenario": scenario.id, "error": f"decode_error: {e}", "elapsed_s": round(time.time() - t0, 2)}

    result_text = str(body.get("result") or "")
    seat_text, synthesis_text = _extract_synthesis(result_text)

    support = _support_status_reduced(seat_text, synthesis_text)
    anchor = _anchor_detected(synthesis_text, scenario.primary_anchor_terms)
    if not scenario.include_synthesis:
        state_reduced = None
        warning_reduced = None
    elif not synthesis_text.strip():
        state_reduced = "unanchored"
        warning_reduced = "missing_primary_anchor"
    elif anchor is None:
        state_reduced = "weak"
        warning_reduced = None
    elif anchor:
        state_reduced = "anchored"
        warning_reduced = None
    else:
        state_reduced = "unanchored"
        warning_reduced = "missing_primary_anchor"

    combined = _derive_combined(state_reduced, warning_reduced, support)
    reduced_review = {
        "schema": "council_integrity_review_reduced_v1",
        "combined_summary": combined,
        "synthesis_integrity_state_reduced": state_reduced,
        "synthesis_support_status_reduced": support,
        "integrity_warning_reduced": warning_reduced,
        "primary_anchor_detected_heuristic": anchor,
        "notes": "Derived from non-streaming final text; not equivalent to streaming integrity envelope fields.",
    }

    return {
        "ok": bool(body.get("ok")),
        "scenario": scenario.id,
        "elapsed_s": round(time.time() - t0, 2),
        "error": body.get("error"),
        "result_len": len(result_text),
        "has_synthesis": bool(synthesis_text.strip()),
        "run_meta_available": {
            "provider_resolution": body.get("provider_resolution") is not None,
            "council_wash_trace": body.get("council_wash_trace") is not None,
        },
        "provider_resolution": body.get("provider_resolution"),
        "council_wash_trace": body.get("council_wash_trace"),
        "reduced_review": reduced_review,
        "synthesis_excerpt": synthesis_text[:800],
        "raw_result_excerpt": result_text[:1200],
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="Run non-stream council adversarial harness with reduced integrity review.")
    ap.add_argument("--base-url", default="http://127.0.0.1:8000")
    ap.add_argument("--count", type=int, default=20, help="Number of runs (cycles scenarios).")
    ap.add_argument("--timeout", type=float, default=120.0, help="HTTP timeout seconds per run.")
    ap.add_argument("--out", default="", help="Optional JSON output file path.")
    args = ap.parse_args()

    runs: list[dict[str, Any]] = []
    for i in range(max(1, args.count)):
        sc = SCENARIOS[i % len(SCENARIOS)]
        row = run_non_stream(args.base_url, sc, args.timeout)
        row["idx"] = i + 1
        runs.append(row)
        rr = row.get("reduced_review") or {}
        print(
            f"{i+1:02d} {sc.id}: ok={row.get('ok')} "
            f"state_r={rr.get('synthesis_integrity_state_reduced')} "
            f"support_r={rr.get('synthesis_support_status_reduced')} "
            f"combined_r={rr.get('combined_summary')} err={row.get('error')}"
        )

    out = {
        "schema": "council_adversarial_non_stream_batch_v1",
        "ran_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "base_url": args.base_url,
        "count": len(runs),
        "runs": runs,
    }
    if args.out:
        p = Path(args.out)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(out, indent=2), encoding="utf-8")
        print(f"\nWrote: {p}")
    else:
        print("\n" + json.dumps(out, indent=2))


if __name__ == "__main__":
    main()

