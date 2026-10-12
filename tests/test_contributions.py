"""Contribution claims: "I played guitar in this song."

Hermetic: every test runs against a tmp ZENAF_DATA_DIR and an explicit
tmp SQLite path — no touching the real data/, no network. Synthetic
fixtures only.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from local_ai.identity import LicenseRequired
from local_ai.identity import service as ident
from local_ai.identity.store import IdentityStore
from local_ai.presence_ingest.distill import distill_events
from local_ai.presence_ingest.schema import ContributionClaim, ImportSession, PresenceEvent
from local_ai.presence_ingest.service import (
    PresenceIngestError,
    define_contribution,
    remove_contribution,
)
from local_ai.presence_ingest.store import PresenceStore


@pytest.fixture()
def env(tmp_path, monkeypatch):
    """Isolated identity + presence stores under a tmp dir."""
    monkeypatch.setenv("ZENAF_DATA_DIR", str(tmp_path / "zenaf-data"))
    store = PresenceStore(db_path=tmp_path / "sig.db")
    yield store
    store.close()


@pytest.fixture()
def licensed(env):
    ident.issue_license(store=IdentityStore())
    return env


def _session(store: PresenceStore, sid: str = "imp-test") -> ImportSession:
    session = ImportSession(
        session_id=sid,
        source="chatgpt",
        file_name="conversations.json",
        status="parsed",
        counts={},
        created_at=datetime.now(timezone.utc),
        provenance={"license_id": "lic-test", "reanchored": True},
    )
    return store.create_session(session)


def _event(eid: str, text: str, conv: str = "conv-1") -> PresenceEvent:
    return PresenceEvent(
        event_id=eid,
        source="chatgpt",
        ts=datetime.now(timezone.utc),
        actor="user",
        kind="message",
        text=text,
        context={"conversation_id": conv, "conversation_title": "Midnight Run"},
        provenance={"license_id": "lic-test"},
    )


def _stub_capturing(captured: list):
    def stub(prompt: str) -> str:
        captured.append(prompt)
        return json.dumps(
            [
                {
                    "layer": "behavior",
                    "zone": "music",
                    "valence": "observed",
                    "summary": "User plays expressive lead guitar.",
                    "detail": "Bends and vibrato in the verses.",
                }
            ]
        )

    return stub


# ---------------------------------------------------------------- define


def test_define_and_list_claim(licensed):
    store = licensed
    _session(store)
    claim = define_contribution(
        "imp-test",
        role="guitar",
        work_title="Midnight Run (song)",
        parts="lead guitar, verses; not the solo",
        collaborators=["Maya"],
        note="my first studio session",
        store=store,
    )
    assert claim.claim_id.startswith("claim-")
    assert claim.role == "guitar"
    assert claim.license_id  # stamped from the active license
    assert claim.attestations == []  # reserved, always empty for now

    claims = store.list_claims("imp-test")
    assert len(claims) == 1
    assert claims[0].work_title == "Midnight Run (song)"
    assert claims[0].collaborators == ["Maya"]


def test_define_claim_empty_role_rejected(licensed):
    _session(licensed)
    with pytest.raises(PresenceIngestError):
        define_contribution("imp-test", role="   ", store=licensed)


def test_define_claim_unknown_session(licensed):
    with pytest.raises(PresenceIngestError):
        define_contribution("imp-nope", role="guitar", store=licensed)


def test_define_claim_unknown_event_ids_rejected(licensed):
    store = licensed
    _session(store)
    store.save_events("imp-test", [_event("e1", "hello")])
    with pytest.raises(PresenceIngestError):
        define_contribution("imp-test", role="guitar", event_ids=["e-nope"], store=store)
    # valid event ids are accepted
    claim = define_contribution("imp-test", role="guitar", event_ids=["e1"], store=store)
    assert claim.event_ids == ["e1"]


def test_define_claim_requires_license(env):
    _session(env)
    with pytest.raises(LicenseRequired):
        define_contribution("imp-test", role="guitar", store=env)


def test_api_body_rejects_blank_role():
    from pydantic import ValidationError

    from api.routes.ingest_routes import ContributionClaimBody

    with pytest.raises(ValidationError):
        ContributionClaimBody(role="  ")
    body = ContributionClaimBody(role="guitar", work_title="Midnight Run")
    assert body.role == "guitar"


# ---------------------------------------------------------------- delete


def test_remove_claim(licensed):
    store = licensed
    _session(store)
    claim = define_contribution("imp-test", role="guitar", store=store)
    assert remove_contribution(claim.claim_id, store=store) is True
    assert store.list_claims("imp-test") == []
    assert store.get_claim(claim.claim_id) is None


def test_remove_unknown_claim(licensed):
    with pytest.raises(PresenceIngestError):
        remove_contribution("claim-nope", store=licensed)


# ---------------------------------------------------------------- distill


def test_distill_injects_contribution_prompt():
    events = [_event("e1", "tracking guitars today"), _event("e2", "mix notes")]
    claim = ContributionClaim(
        claim_id="claim-1",
        session_id="imp-test",
        event_ids=[],
        work_title="Midnight Run (song)",
        role="guitar",
        parts="lead guitar, verses; not the solo",
        license_id="lic-test",
        created_at=datetime.now(timezone.utc),
    )
    captured: list = []
    signals = distill_events(
        events,
        complete_fn=_stub_capturing(captured),
        session_id="imp-test",
        claims=[claim],
    )
    assert len(captured) == 1
    prompt = captured[0]
    assert "guitar" in prompt
    assert "lead guitar, verses; not the solo" in prompt
    assert "Midnight Run (song)" in prompt
    assert "USER'S CONTRIBUTION ONLY" in prompt
    # signals are tagged with the claim
    assert len(signals) == 1
    assert signals[0].context_ref["contribution_claim_id"] == "claim-1"
    assert signals[0].provenance["contribution_role"] == "guitar"


def test_distill_without_claims_unchanged():
    events = [_event("e1", "hello")]
    captured: list = []
    signals = distill_events(
        events, complete_fn=_stub_capturing(captured), session_id="imp-test"
    )
    assert "CONTRIBUTION ONLY" not in captured[0]
    assert "contribution_claim_id" not in signals[0].context_ref
    assert "contribution_role" not in signals[0].provenance


def test_event_scoped_claim_only_matches_covered_batch():
    # Two batches (different conversations); claim covers only the first.
    events = [
        _event("e1", "guitar take", conv="conv-song"),
        _event("e2", "drum take", conv="conv-other"),
    ]
    claim = ContributionClaim(
        claim_id="claim-1",
        session_id="imp-test",
        event_ids=["e1"],
        work_title="Midnight Run (song)",
        role="guitar",
        license_id="lic-test",
        created_at=datetime.now(timezone.utc),
    )
    captured: list = []
    signals = distill_events(
        events,
        complete_fn=_stub_capturing(captured),
        session_id="imp-test",
        claims=[claim],
    )
    assert len(captured) == 2
    with_claim = [p for p in captured if "CONTRIBUTION ONLY" in p]
    without_claim = [p for p in captured if "CONTRIBUTION ONLY" not in p]
    assert len(with_claim) == 1 and len(without_claim) == 1
    tagged = [s for s in signals if "contribution_claim_id" in s.context_ref]
    untagged = [s for s in signals if "contribution_claim_id" not in s.context_ref]
    assert len(tagged) == 1 and len(untagged) == 1
    assert tagged[0].provenance["contribution_role"] == "guitar"


def test_session_level_claim_covers_all_batches():
    events = [
        _event("e1", "verse guitar", conv="conv-a"),
        _event("e2", "chorus guitar", conv="conv-b"),
    ]
    claim = ContributionClaim(
        claim_id="claim-1",
        session_id="imp-test",
        event_ids=[],  # session-level: covers everything
        role="guitar",
        license_id="lic-test",
        created_at=datetime.now(timezone.utc),
    )
    captured: list = []
    signals = distill_events(
        events,
        complete_fn=_stub_capturing(captured),
        session_id="imp-test",
        claims=[claim],
    )
    assert len(captured) == 2
    assert all("CONTRIBUTION ONLY" in p for p in captured)
    assert all(
        s.context_ref.get("contribution_claim_id") == "claim-1" for s in signals
    )


def test_claims_from_other_sessions_ignored():
    events = [_event("e1", "hello")]
    claim = ContributionClaim(
        claim_id="claim-1",
        session_id="imp-other",  # different session
        event_ids=[],
        role="guitar",
        license_id="lic-test",
        created_at=datetime.now(timezone.utc),
    )
    captured: list = []
    distill_events(
        events,
        complete_fn=_stub_capturing(captured),
        session_id="imp-test",
        claims=[claim],
    )
    assert "CONTRIBUTION ONLY" not in captured[0]
