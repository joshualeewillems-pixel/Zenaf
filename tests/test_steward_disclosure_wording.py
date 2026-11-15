"""Steward disclosure wording pins (2026-11-15; Gate C F1 succession).

Originally the D2 interim disclosure correction (PR #381): until
steward erasure was wired and verified, two surfaces must not
overclaim (D2 erasure packet §5):

- POST /identity/delete must disclose what it does not delete.
- The steward-derivation consent wording must not promise review or
  deletion of notes that no surface can yet perform.

The D2 build wired the Scope S erasure, and the packet's §8.5
post-build statement (COVERAGE_STATEMENT) supersedes the interim
delete wording by the packet's own prescription. The three
delete-surface pins below were updated to pin the post-build
statement (Gate C review, finding F1), preserving the
anti-overclaim substance: no "everything" claim, the explicit
not-erased list, and a receipt composed from verified counts.

The consent-toggle pin was revised again by Steward D1 (packet
§§8.1/15.5, founder ruling Q3): retaining people's names as
candidate records required an explicit candidate-retention
disclosure in the toggle text, and the same revision retired the
interim erasure clause — false since D2's verified erasure
landed — for the clear-and-erase statement D1's coverage
expansion makes true. The pin below carries the D1 wording;
every carrier must hold it identically, and capture is gated on
consents recorded under it (consent version "permissions-v2",
no grandfathering).

These tests pin the served wording (the OpenAPI document is what
the API presents) and every carrier of the consent sentence, so
the promise and the deployed behavior cannot drift apart silently.
"""
from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

NEW_TOGGLE_WORDING = (
    "Can Zenaf connect our talks into ongoing threads and note what "
    "they might mean? The notes are kept in your narrative record. "
    "You can turn this off at any time — that stops new notes. "
    "If you mention someone who isn't in your records yet, Zenaf may "
    "keep a provisional note of their name and where they came up. "
    "The note isn't a person record, and it doesn't claim anything "
    "about who they are. Its only use is to ask — when coordination "
    "is also on — whether you'd like them tracked properly. These "
    "notes clear and erase with the rest of your narrative record."
)
OLD_TOGGLE_PROMISE = "review/delete them"
SUPERSEDED_INTERIM_CLAUSE = "erasing existing notes is not yet available"


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
        "Delete presence data, your narrative steward record, and "
        "fellowship observations (signed receipt)"
    )
    assert "everything" not in op["summary"].lower()


def test_delete_endpoint_description_discloses_coverage():
    from local_ai.identity.erasure import COVERAGE_STATEMENT

    description = _norm(_delete_operation()["description"])
    # The served description IS the §8.5 post-build statement — the
    # same words the receipt carries as its coverage.
    assert description == _norm(COVERAGE_STATEMENT)
    # What it erases (post-build statement, verbatim substance).
    assert "Erased: your narrative record" in description
    assert "your fellowship observations" in description
    assert (
        "verified by recount and by a provenance check of the "
        "records that remain" in description
    )
    assert "A content-free marker remains" in description
    # What it does not erase — the disclosure that must not go missing.
    assert "Not erased by this action:" in description
    assert "the activity log's contents (under separate review)" in description
    assert "your conversations, meetings, projects, and claims" in description
    assert (
        "anything held in backups or snapshots, which this action "
        "cannot reach" in description
    )
    # The old overclaim is gone from the served description.
    assert "Delete everything derived from the owner" not in description
    assert "everything" not in description.lower()


def test_delete_all_service_docstring_is_scoped():
    from local_ai.identity import service

    doc = _norm(service.delete_all.__doc__ or "")
    assert "Delete everything derived from the owner" not in doc
    assert "Delete the owner's deletable footprint" in doc
    assert (
        "presence data, the narrative steward record, and "
        "fellowship observations are erased" in doc
    )
    assert "the receipt is composed from those verifications" in doc
    assert "What persists after deletion" in doc


def test_steward_toggle_wording_carriers_all_corrected():
    from local_ai.narrative import consent
    from local_ai.permissions.registry import get_capability

    # The capability registry entry served to the permissions surface.
    r2 = get_capability("R2")
    assert r2 is not None
    assert _norm(r2.covers) == NEW_TOGGLE_WORDING

    # The recorded approved wording in the consent gate module. (The
    # module docstring's revision note quotes old fragments while
    # explaining the changes; the full superseded sentences must be
    # gone.)
    consent_doc = _norm(consent.__doc__ or "")
    assert NEW_TOGGLE_WORDING in consent_doc
    assert "keep those notes where you can review/delete them" not in consent_doc
    assert SUPERSEDED_INTERIM_CLAUSE not in consent_doc

    # Both frontend carriers of the toggle hint (settings + onboarding).
    for rel in (
        "frontend/src/settings/sections/PermissionsSection.tsx",
        "frontend/src/auth/ConsentOnboardingGate.tsx",
    ):
        text = (REPO_ROOT / rel).read_text(encoding="utf-8")
        assert NEW_TOGGLE_WORDING in text, rel
        assert OLD_TOGGLE_PROMISE not in text, rel
        assert SUPERSEDED_INTERIM_CLAUSE not in text, rel


def test_candidate_disclosure_consent_version_aligned():
    """The D1 no-grandfathering gate (packet §§8.1/15.5): the
    backend's disclosure consent version and both frontend
    CONSENT_VERSION constants are the same string, so a consent
    recorded by the shipped frontend is one the capture gate can
    recognize — and a pre-disclosure consent ("permissions-v1")
    is not."""
    from local_ai.narrative.consent import DISCLOSURE_CONSENT_VERSION

    assert DISCLOSURE_CONSENT_VERSION != "permissions-v1"
    for rel in (
        "frontend/src/settings/sections/PermissionsSection.tsx",
        "frontend/src/auth/ConsentOnboardingGate.tsx",
    ):
        text = (REPO_ROOT / rel).read_text(encoding="utf-8")
        assert f"const CONSENT_VERSION = '{DISCLOSURE_CONSENT_VERSION}'" in text, rel
