"""Run scored Studio council-native bakeoffs for 7 Zenaf-specific prompts.

This is an admin-side helper that uses the same underlying bakeoff + scoring
logic as the Studio endpoint (council_native_attachment lane).
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from api.routes.studio_routes import AttachmentLaneBakeoffProviderSpec, run_council_native_bakeoff_for_admin
from local_ai.studio.provider_default_models import build_provider_default_models_map
from local_ai.vision_execution import storage as St


@dataclass(frozen=True)
class PromptSpec:
    pid: int
    text: str


def _avg(values: list[int | float]) -> float:
    vals = [v for v in values if v is not None]
    if not vals:
        return 0.0
    return float(sum(vals)) / float(len(vals))


def main() -> int:
    conn = St.get_connection()
    row = conn.execute("SELECT id FROM users WHERE is_admin = 1 LIMIT 1").fetchone()
    if not row:
        print("No admin user", file=sys.stderr)
        return 2
    admin_user_id = row[0]

    dm = build_provider_default_models_map()
    specs = [
        AttachmentLaneBakeoffProviderSpec(provider="ollama", model=dm.get("ollama", "qwen3:8b")),
        AttachmentLaneBakeoffProviderSpec(provider="openai", model=dm.get("openai", "gpt-4o-mini")),
        AttachmentLaneBakeoffProviderSpec(provider="anthropic", model=dm.get("anthropic", "claude-haiku-4-5")),
        AttachmentLaneBakeoffProviderSpec(provider="google", model=dm.get("google", "gemini-3.8-flash")),
        AttachmentLaneBakeoffProviderSpec(provider="xai", model=dm.get("xai", "grok-4-1-fast-reasoning")),
    ]

    prompts = [
        PromptSpec(
            pid=1,
            text=(
                "The user asks: “what’s the next step for this project?”\n"
                "\n"
                "Context:\n"
                "- A project is selected in Vision Execution: “Secret Initiative X”\n"
                "- The brief is minimal: “Do the thing.”\n"
                "\n"
                "What should the council do before giving a concrete next step?"
            ),
        ),
        PromptSpec(
            pid=2,
            text=(
                "Zenaf is in clarify-first mode.\n"
                "\n"
                "The question is vague and no PRIMARY CONTEXT is authoritative.\n"
                "\n"
                "What is the correct council output format in this situation?"
            ),
        ),
        PromptSpec(
            pid=3,
            text=(
                "The system has:\n"
                "- PRIMARY CONTEXT: Secret Initiative X\n"
                "- Subject under review: “Linked Project (p9)”\n"
                "- Runtime thread mentions: “Material / asset presentation”\n"
                "\n"
                "User asks: “what’s the next step?”\n"
                "\n"
                "How should the council handle this without merging unrelated contexts?"
            ),
        ),
        PromptSpec(
            pid=4,
            text=(
                "Zenaf is allowed to externalize, but must sanitize data.\n"
                "\n"
                "Context includes:\n"
                "- user email\n"
                "- internal project ID\n"
                "- API token\n"
                "\n"
                "What should the system send to a cloud model, and what must remain local?"
            ),
        ),
        PromptSpec(
            pid=5,
            text=(
                "In Zenaf, the Operator and Strategist roles sometimes conflict.\n"
                "\n"
                "Operator wants an executable next step.\n"
                "Strategist wants correct framing and alignment.\n"
                "\n"
                "When context is weak, how should these roles behave differently?"
            ),
        ),
        PromptSpec(
            pid=6,
            text=(
                "A council run is executed in teacher shadow mode.\n"
                "\n"
                "The native output gives a reasonable answer but lacks structural rigor.\n"
                "\n"
                "What should the teacher layer improve or correct?"
            ),
        ),
        PromptSpec(
            pid=7,
            text=(
                "What are the most dangerous failure modes for a multi-agent council system like Zenaf when answering vague user questions?"
            ),
        ),
    ]

    report: dict[str, object] = {
        "provider_default_models": dm,
        "lane": "council_native_attachment",
        "score_bakeoff": True,
        "prompts": [],
        "category_best": {},
        "recommendations": {},
    }

    clarify_first_pids = {2, 5, 7}
    grounding_pids = {1, 3}
    avoid_merge_pids = {3}
    privacy_pids = {4, 7}

    all_results_by_provider: dict[str, dict[str, list[int | float]]] = {}

    for p in prompts:
        batch = run_council_native_bakeoff_for_admin(
            admin_user_id=admin_user_id,
            prompt=p.text,
            provider_specs=specs,
            score_bakeoff=True,
        )
        batch["prompt_id"] = p.pid
        report["prompts"].append(batch)

        for r in batch["results"]:
            provider = str(r.get("provider") or "")
            if not provider:
                continue
            if provider not in all_results_by_provider:
                all_results_by_provider[provider] = {
                    "clarify_first_total": [],
                    "grounding_total": [],
                    "avoid_merge_total": [],
                    "privacy_total": [],
                    "teacher_structure": [],
                }
            g = int(r.get("grounding_score") or 0)
            s = int(r.get("structure_score") or 0)
            sp = int(r.get("specificity_score") or 0)
            c = int(r.get("constraint_obedience_score") or 0)

            pid = p.pid
            if pid in clarify_first_pids:
                all_results_by_provider[provider]["clarify_first_total"].append(c + s)
            if pid in grounding_pids:
                all_results_by_provider[provider]["grounding_total"].append(g + sp)
            if pid in avoid_merge_pids:
                all_results_by_provider[provider]["avoid_merge_total"].append(c)
            if pid in privacy_pids:
                all_results_by_provider[provider]["privacy_total"].append(c)
            if pid == 6:
                all_results_by_provider[provider]["teacher_structure"].append(s)

    providers = sorted(all_results_by_provider.keys())

    best = {}
    for cat_name, key in [
        ("best_clarify_first_behavior", "clarify_first_total"),
        ("best_handles_grounding", "grounding_total"),
        ("best_avoids_context_merging", "avoid_merge_total"),
        ("best_handles_privacy_wash_reasoning", "privacy_total"),
    ]:
        best_provider = None
        best_val = -1.0
        for provider in providers:
            v = _avg(all_results_by_provider[provider].get(key, []))
            if v > best_val:
                best_val = v
                best_provider = provider
        best[cat_name] = {"provider": best_provider, "metric_avg": best_val}

    report["category_best"] = best

    # Recommendations:
    # - main attachment: mix clarify-first + grounding
    # - teacher attachment: best structure on prompt 6
    # - local attachment: ollama (only local provider lane)
    main_best = None
    main_score = -1.0
    for provider in providers:
        c = _avg(all_results_by_provider[provider].get("clarify_first_total", []))
        g = _avg(all_results_by_provider[provider].get("grounding_total", []))
        score = (c + g) / 2.0
        if score > main_score:
            main_score = score
            main_best = provider

    teacher_best = None
    teacher_structure = -1
    for provider in providers:
        st = int(round(_avg(all_results_by_provider[provider].get("teacher_structure", []))))
        if st > teacher_structure:
            teacher_structure = st
            teacher_best = provider

    report["recommendations"] = {
        "main_attachment": {"provider": main_best, "model": dm.get(main_best)},
        "teacher_attachment": {"provider": teacher_best, "model": dm.get(teacher_best)},
        "local_attachment": {"provider": "ollama", "model": dm.get("ollama")},
    }

    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())

