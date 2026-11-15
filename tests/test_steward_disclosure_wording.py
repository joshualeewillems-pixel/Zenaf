"""D2 interim disclosure correction — wording pins (2026-11-15).

Until steward erasure is wired and verified, two surfaces must not
overclaim (D2 erasure packet §5, founder-approved as a narrow wording
correction):

- POST /identity/delete removes only the imported presence footprint
  and the consent ledger; its served wording must disclose that the
  narrative record and the other stores survive.
- The steward-derivation consent wording must not promise review or
  deletion of notes that no surface can yet perform.

These tests pin the served wording (the OpenAPI document is what the
API presents) and every carrier of the consent sentence, so the
promise and the deployed behavior cannot drift apart silently.
"""
from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

NEW_TOGGLE_WORDING = (
    "Can Zenaf connect our talks into ongoing threads and note what "
    "they might mean? The notes are kept in your narrative record. "
    "You can turn this off at any time — that stops new notes; "
    "erasing existing notes is not yet available and will be offered "
    "here when it is verified."
)
OLD_TOGGLE_PROMISE = "review/delete them"


def _norm(text: str) -> str:
    """Collapse whitespace and drop markdown bold so wrapped or
    emphasised source text compares as the sentence a reader sees."""
    return re.sub(r"\s+", " ", text.replace("**", "")).strip()


def _delete_operation() -> dict:
    from fastapi import FastAPI

    from api.routes.identity_routes import router

    app = FastAPI()
    app.include_router(router)
    return app.openapi()["paths"]["/identity/delete"]["post"]


def test_delete_endpoint_summary_no_longer_claims_everything():
    op = _delete_operation()
    assert op["summary"] == (
        "Delete imported presence data and the consent ledger (signed receipt)"
    )
    assert "everything" not in op["summary"].lower()


def test_delete_endpoint_description_discloses_coverage():
    description = _norm(_delete_operation()["description"])
    # What it does delete (packet §5, verbatim substance).
    assert "What this deletes:" in description
    assert "your imported presence data" in description
    assert "consent scope ledger" in description
    assert "signed receipt listing counts of what was removed" in description
    # What it does not delete yet — the disclosure that was missing.
    assert "What this does not delete yet:" in description
    assert "narrative threads and steward notes" in description
    assert "conversations and meetings" in description
    assert "Vision Execution records" in description
    assert (
        "turning off steward consent stops new notes without erasing "
        "existing ones" in description
    )
    # The old overclaim is gone from the served description.
    assert "Delete everything derived from the owner" not in description


def test_delete_all_service_docstring_is_scoped():
    from local_ai.identity import service

    doc = _norm(service.delete_all.__doc__ or "")
    assert "Delete everything derived from the owner" not in doc
    assert "Does not remove:" in doc
    assert "narrative record" in doc


def test_steward_toggle_wording_carriers_all_corrected():
    from local_ai.narrative import consent
    from local_ai.permissions.registry import get_capability

    # The capability registry entry served to the permissions surface.
    r2 = get_capability("R2")
    assert r2 is not None
    assert _norm(r2.covers) == NEW_TOGGLE_WORDING

    # The recorded approved wording in the consent gate module. (The
    # module docstring's revision note quotes the old fragment while
    # explaining the change; the full old promise sentence must be gone.)
    consent_doc = _norm(consent.__doc__ or "")
    assert NEW_TOGGLE_WORDING in consent_doc
    assert "keep those notes where you can review/delete them" not in consent_doc

    # Both frontend carriers of the toggle hint (settings + onboarding).
    for rel in (
        "frontend/src/settings/sections/PermissionsSection.tsx",
        "frontend/src/auth/ConsentOnboardingGate.tsx",
    ):
        text = (REPO_ROOT / rel).read_text(encoding="utf-8")
        assert NEW_TOGGLE_WORDING in text, rel
        assert OLD_TOGGLE_PROMISE not in text, rel
