"""Identity license + consent scopes + takeout + deletion tests.

Hermetic: every test runs against a tmp ZENAF_DATA_DIR — no touching the
real data/, no network. Synthetic fixtures only.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from local_ai.identity import LicenseRequired, ScopeDenied, identity_data_dir
from local_ai.identity import service as ident
from local_ai.identity.scopes import check_scope, require_scope
from local_ai.identity.signing import get_key, sign_mapping, verify_mapping
from local_ai.identity.store import IdentityStore


@pytest.fixture()
def data_dir(tmp_path, monkeypatch):
    """Isolate ALL identity + presence data under a tmp dir."""
    d = tmp_path / "zenaf-data"
    monkeypatch.setenv("ZENAF_DATA_DIR", str(d))
    return d


@pytest.fixture()
def store(data_dir):
    s = IdentityStore()
    yield s
    s.close()


# ---------------------------------------------------------------- license


def test_issue_and_verify(store):
    lic = ident.issue_license("tester", store=store)
    assert lic.license_id
    assert lic.status == "active"
    assert lic.signature
    assert ident.verify_license(store=store) is True
    # Idempotent: second issue returns the existing license.
    again = ident.issue_license("someone-else", store=store)
    assert again.license_id == lic.license_id


def test_tampered_rights_fail_verification(store):
    lic = ident.issue_license(store=store)
    assert ident.verify_license(store=store) is True
    lic.rights = lic.rights + " (forged amendment)"
    store.save_license(lic)
    assert ident.verify_license(store=store) is False


def test_signing_roundtrip_and_key_perms(data_dir):
    key = get_key()
    assert len(key) == 32
    sig = sign_mapping({"a": 1})
    assert verify_mapping({"a": 1}, sig) is True
    assert verify_mapping({"a": 2}, sig) is False
    assert verify_mapping({"a": 1}, "bogus") is False
    key_path = identity_data_dir() / ".license_key"
    assert key_path.is_file()
    import os
    import stat

    assert stat.S_IMODE(os.stat(key_path).st_mode) == 0o600


# ---------------------------------------------------------------- scopes


def test_grant_revoke_and_default_deny(store):
    assert check_scope("train:self", store=store) is False  # default-deny
    ident.grant_scope("train:self", store=store)
    assert check_scope("train:self", store=store) is True
    ident.revoke_scope("train:self", store=store)
    assert check_scope("train:self", store=store) is False
    # Ledger keeps both events (audit trail).
    actions = [e.action for e in store.list_scope_events()]
    assert actions == ["grant", "revoke"]


def test_require_scope_raises_with_helpful_message(store):
    with pytest.raises(ScopeDenied) as ei:
        require_scope("train:self", store=store)
    assert ei.value.scope == "train:self"
    assert "grant" in str(ei.value)


def test_unknown_scope_rejected(store):
    with pytest.raises(ValueError):
        ident.grant_scope("fly:to-the-moon", store=store)
    with pytest.raises(ValueError):
        ident.grant_scope("", store=store)
    with pytest.raises(ValueError):
        ident.grant_scope("rent:zone:", store=store)


def test_zone_wildcard_matching(store):
    assert check_scope("rent:zone:strategy", store=store) is False
    ident.grant_scope("rent:zone:*", store=store)
    assert check_scope("rent:zone:strategy", store=store) is True
    assert check_scope("rent:zone:creative", store=store) is True
    ident.revoke_scope("rent:zone:*", store=store)
    assert check_scope("rent:zone:strategy", store=store) is False
    # Single-zone grant covers only that zone.
    ident.grant_scope("rent:zone:strategy", store=store)
    assert check_scope("rent:zone:strategy", store=store) is True
    assert check_scope("rent:zone:creative", store=store) is False


# ---------------------------------------------------------------- takeout


def test_takeout_includes_license_and_ledger(store):
    lic = ident.issue_license(store=store)
    ident.grant_scope("train:self", note="test", store=store)
    bundle = ident.build_takeout(store=store)
    assert bundle["takeout_version"] == 1
    assert bundle["license"]["license_id"] == lic.license_id
    assert bundle["signature_valid"] is True
    assert len(bundle["scope_ledger"]) == 1
    assert bundle["scope_ledger"][0]["scope"] == "train:self"
    assert bundle["counts"]["scope_events"] == 1


def test_takeout_without_license_raises(store):
    with pytest.raises(LicenseRequired):
        ident.build_takeout(store=store)


# ---------------------------------------------------------------- deletion


def test_delete_wrong_confirmation(store):
    ident.issue_license(store=store)
    ident.grant_scope("delete:execute", store=store)
    with pytest.raises(ValueError, match="DELETE"):
        ident.delete_all("delete", store=store)


def test_delete_without_scope_denied(store):
    ident.issue_license(store=store)
    with pytest.raises(ScopeDenied) as ei:
        ident.delete_all("DELETE", store=store)
    assert ei.value.scope == "delete:execute"


def test_delete_full_flow(store, tmp_path):
    ident.issue_license(store=store)
    ident.grant_scope("delete:execute", store=store)
    ident.grant_scope("train:self", store=store)

    # Seed some presence data to prove it gets wiped.
    from local_ai.presence_ingest.store import PresenceStore

    pdb = tmp_path / "signals.db"
    pstore = PresenceStore(db_path=pdb)
    from local_ai.presence_ingest.schema import ImportSession

    pstore.create_session(
        ImportSession(
            session_id="imp-x", source="chatgpt", file_name="f.json",
            status="parsed", counts={}, provenance={"license_id": "lic-x"},
        )
    )
    upload_root = tmp_path / "uploads"
    (upload_root / "imp-x").mkdir(parents=True)
    (upload_root / "imp-x" / "conversations.json").write_text("{}")
    pstore.close()

    receipt = ident.delete_all(
        "DELETE",
        store=store,
        presence_upload_root=upload_root,
        presence_db_path=pdb,
    )
    # Receipt is signed and verifies.
    from local_ai.identity.service import _receipt_payload

    assert verify_mapping(_receipt_payload(receipt), receipt.signature) is True
    assert receipt.summary["import_sessions"] == 1
    assert receipt.summary["scope_events"] == 2
    # Data is gone...
    assert not pdb.exists()
    assert not upload_root.exists()
    assert store.list_scope_events() == []
    # ...but the tombstoned license and receipt persist.
    lic = store.get_license()
    assert lic is not None and lic.status == "terminated"
    assert len(store.list_receipts()) == 1


# ---------------------------------------------------------------- ingest integration


def _write_chatgpt_export(path: Path) -> Path:
    data = [
        {
            "id": "conv-1",
            "title": "Test chat",
            "mapping": {
                "n1": {
                    "message": {
                        "author": {"role": "user"},
                        "content": {"parts": ["Should I take the offer?"]},
                        "create_time": 1720000000.0,
                    }
                },
                "n2": {
                    "message": {
                        "author": {"role": "assistant"},
                        "content": {"parts": ["Consider the tradeoffs."]},
                        "create_time": 1720000060.0,
                    }
                },
            },
        }
    ]
    p = path / "conversations.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    return p


def _stub_complete(prompt: str) -> str:
    return json.dumps(
        [
            {
                "layer": "decision",
                "zone": "career",
                "valence": "endorsed",
                "summary": "User seeks decisive career input.",
                "detail": "Asked whether to take an offer.",
            }
        ]
    )


def _presence_parts(tmp_path):
    from local_ai.presence_ingest.store import PresenceStore

    pstore = PresenceStore(db_path=tmp_path / "signals.db")
    upload_root = tmp_path / "uploads"
    upload_root.mkdir(parents=True, exist_ok=True)
    return pstore, upload_root


def test_import_requires_license(data_dir, tmp_path):
    from local_ai.presence_ingest import service as ing

    pstore, upload_root = _presence_parts(tmp_path)
    try:
        export = _write_chatgpt_export(tmp_path)
        with pytest.raises(LicenseRequired):
            ing.start_import(export, "conversations.json",
                             store=pstore, upload_root=upload_root)
        assert pstore.list_sessions() == []
    finally:
        pstore.close()


def test_import_distill_gated_by_scope(data_dir, tmp_path, store):
    from local_ai.presence_ingest import service as ing

    ident.issue_license(store=store)
    pstore, upload_root = _presence_parts(tmp_path)
    try:
        export = _write_chatgpt_export(tmp_path)
        session = ing.start_import(export, "conversations.json",
                                   store=pstore, upload_root=upload_root)
        # License re-anchored into provenance.
        assert session.provenance["license_id"].startswith("lic-")
        events = pstore.list_events(session.session_id)
        assert events and all(
            e.provenance.get("license_id") == session.provenance["license_id"]
            for e in events
        )
        # Distill without train:self -> denied.
        with pytest.raises(ScopeDenied):
            ing.run_distill(session.session_id, complete_fn=_stub_complete,
                            store=pstore)
        # Grant -> proceeds.
        ident.grant_scope("train:self", store=store)
        n = ing.run_distill(session.session_id, complete_fn=_stub_complete,
                            store=pstore)
        assert n == 1
        cands = pstore.list_candidates(session.session_id)
        assert len(cands) == 1 and cands[0].status == "pending"
        # Revoke -> denied again.
        ident.revoke_scope("train:self", store=store)
        with pytest.raises(ScopeDenied):
            ing.run_distill(session.session_id, complete_fn=_stub_complete,
                            store=pstore)
    finally:
        pstore.close()
