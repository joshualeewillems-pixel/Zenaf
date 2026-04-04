from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from local_ai.vision_execution import storage as St


def test_studio_teacher_settings_roundtrip():
    out = St.upsert_studio_council_teacher_settings(
        teacher_mode="shadow",
        teacher_provider="openai",
        teacher_model="gpt-4.1",
        teacher_prompt_version="council_teacher_v1",
        teacher_prompt_overlay="prefer decisive options",
    )
    assert out["teacher_mode"] == "shadow"
    assert out["teacher_provider"] == "openai"
    got = St.get_studio_council_teacher_settings()
    assert got["teacher_model"] == "gpt-4.1"
    assert got["teacher_prompt_version"] == "council_teacher_v1"


def test_council_teacher_run_append_and_list():
    rid = St.append_council_teacher_run(
        {
            "user_id": None,
            "execution_scope": "account",
            "execution_principal_ref": "account:test",
            "capability_name": "council",
            "teacher_mode": "shadow",
            "final_selection_policy": "native",
            "prompt_version": "council_teacher_v1",
            "native_provider": "ollama",
            "native_model": "qwen3:8b",
            "teacher_provider_requested": "openai",
            "teacher_model_requested": "gpt-4.1",
            "teacher_provider_effective": "OpenAIProvider",
            "teacher_model_effective": "gpt-4.1",
            "teacher_succeeded": True,
            "native_text": "Strategist:\nNext step: A\n",
            "teacher_text": "Strategist:\nNext step: B\n",
            "native_artifact": {"question": "q"},
            "teacher_artifact": {"question": "q"},
            "comparison": {"teacher_present": True},
            "error": None,
        }
    )
    assert isinstance(rid, str) and rid
    rows = St.list_recent_council_teacher_runs(limit=5)
    assert any(r.get("id") == rid for r in rows)

