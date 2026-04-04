"""Run scored Studio council-native bakeoffs for multiple prompts (admin DB user)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from api.routes.studio_routes import AttachmentLaneBakeoffProviderSpec, run_council_native_bakeoff_for_admin
from local_ai.studio.provider_default_models import build_provider_default_models_map
from local_ai.vision_execution import storage as St


def main() -> int:
    conn = St.get_connection()
    row = conn.execute("SELECT id FROM users WHERE is_admin = 1 LIMIT 1").fetchone()
    if not row:
        print("No admin user", file=sys.stderr)
        return 2
    uid = row[0]

    dm = build_provider_default_models_map()
    specs = [
        AttachmentLaneBakeoffProviderSpec(provider="ollama", model=dm.get("ollama", "qwen3:8b")),
        AttachmentLaneBakeoffProviderSpec(provider="openai", model=dm.get("openai", "gpt-4o-mini")),
        AttachmentLaneBakeoffProviderSpec(provider="anthropic", model=dm.get("anthropic", "claude-haiku-4-5")),
        AttachmentLaneBakeoffProviderSpec(provider="google", model=dm["google"]),
        AttachmentLaneBakeoffProviderSpec(provider="xai", model=dm["xai"]),
    ]
    prompts = [
        "What is the next step for improving council grounding?",
        "A project question is vague, and the system has a selected object in context. "
        "What should the council do before producing a plan?",
        "The user asks 'what's the next step for this project?' but there is no confirmed project brief. "
        "What should the council output format be?",
    ]
    out_all: list[dict] = []
    for i, p in enumerate(prompts, 1):
        print(f"--- PROMPT {i} ---", file=sys.stderr)
        batch = run_council_native_bakeoff_for_admin(
            admin_user_id=uid,
            prompt=p,
            provider_specs=specs,
            score_bakeoff=True,
        )
        batch["prompt_id"] = i
        out_all.append(batch)
    print(json.dumps(out_all, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
