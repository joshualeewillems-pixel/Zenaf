"""The backend is the single source of truth for persona content.

`frontend/src/perspectives/builtinPersonas.generated.ts` is produced by
`scripts/codegen_builtin_personas.py` from
`local_ai/zenaf_tools.py::BUILT_IN_PERSONA_DEFINITIONS`. This test fails if
the checked-in generated file is stale — i.e. someone edited the backend
definitions without regenerating — so the frontend/backend drift that
happened before (conversation claimed a sync the code never got) cannot
recur silently.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "codegen_builtin_personas.py"


def test_generated_personas_in_sync():
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "--check"],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode == 0, (
        "builtinPersonas.generated.ts is stale.\n"
        f"stdout: {proc.stdout}\nstderr: {proc.stderr}\n"
        "Run: python3 scripts/codegen_builtin_personas.py"
    )


def test_backend_definitions_cover_frontend_builtins():
    """Every id the frontend composes must exist in the backend definitions
    (except the documented frontend-only skeptic)."""
    from local_ai.zenaf_tools import BUILT_IN_PERSONA_DEFINITIONS

    # Mirror of BUILTIN_DISPLAY_ORDER in frontend/src/perspectives/types.ts.
    frontend_ids = {
        "zenaf",
        "storyteller",
        "patternist",
        "seer",
        "songwriter",
        "maker",
        "mediator",
        "guide",
        "skeptic",  # frontend-only by design
    }
    backend_ids = set(BUILT_IN_PERSONA_DEFINITIONS.keys())
    missing = frontend_ids - backend_ids - {"skeptic"}
    assert not missing, f"frontend builtins missing from backend: {missing}"
