"""Settings encryption key persistence: server deployments must not orphan saved keys.

Regression coverage for the Fly redeploy orphan: the key file used to be created
under home first (ephemeral on Fly), so a redeploy generated a new key and every
previously saved credential became undecryptable while the "Configured" display
(row presence only) still showed Configured.

All key material here is fake/mocked; no real key values appear in tests.
"""
from __future__ import annotations

import sys
import types
import uuid

import pytest

from local_ai.vision_execution import storage as St


@pytest.fixture
def no_hosted_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in ("ZENAF_PROD", "ZENAF_DATA_DIR", "ZENAF_DB_DIR", "ZENAF_SETTINGS_ENCRYPTION_KEY"):
        monkeypatch.delenv(var, raising=False)


@pytest.fixture
def fake_crypto(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stand-in for cryptography.fernet (not installed in this env); accepts any key."""

    class _FakeFernet:
        def __init__(self, raw: bytes) -> None:
            self._raw = raw

        @classmethod
        def generate_key(cls) -> bytes:
            return b"fake-test-fernet-key"

    pkg = types.ModuleType("cryptography")
    pkg.__path__ = []  # type: ignore[attr-defined]
    sub = types.ModuleType("cryptography.fernet")
    sub.Fernet = _FakeFernet  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "cryptography", pkg)
    monkeypatch.setitem(sys.modules, "cryptography.fernet", sub)


@pytest.fixture
def reset_key_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(St, "_settings_key_cache", None)


def test_key_paths_local_dev_home_first(no_hosted_env: None) -> None:
    paths = St._settings_encryption_key_paths()
    assert paths[0].parent.name == ".zenaf"
    assert paths[1] == St._DB_DIR / St._SETTINGS_KEY_LOCAL_FILE


def test_key_paths_prod_data_first(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ZENAF_PROD", "1")
    paths = St._settings_encryption_key_paths()
    assert paths[0] == St._DB_DIR / St._SETTINGS_KEY_LOCAL_FILE
    assert paths[1].parent.name == ".zenaf"


def test_key_paths_db_dir_override_data_first(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ZENAF_DB_DIR", "/app/data")
    paths = St._settings_encryption_key_paths()
    assert paths[0] == St._DB_DIR / St._SETTINGS_KEY_LOCAL_FILE


def test_create_goes_to_data_dir_on_server(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
    fake_crypto: None,
    reset_key_cache: None,
) -> None:
    home = tmp_path / "home"
    data = tmp_path / "data" / "vision_execution"
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr(St, "_DB_DIR", data)
    monkeypatch.setenv("ZENAF_PROD", "1")
    monkeypatch.delenv("ZENAF_SETTINGS_ENCRYPTION_KEY", raising=False)
    raw = St._get_settings_encryption_key_raw()
    assert raw == "fake-test-fernet-key"
    assert (data / St._SETTINGS_KEY_LOCAL_FILE).is_file()
    assert not (home / ".zenaf" / St._SETTINGS_KEY_LOCAL_FILE).exists()


def test_home_key_still_read_as_fallback_on_server(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
    fake_crypto: None,
    reset_key_cache: None,
) -> None:
    home = tmp_path / "home"
    data = tmp_path / "data" / "vision_execution"
    (home / ".zenaf").mkdir(parents=True)
    (home / ".zenaf" / St._SETTINGS_KEY_LOCAL_FILE).write_text(
        "fake-test-fernet-key", encoding="utf-8"
    )
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr(St, "_DB_DIR", data)
    monkeypatch.setenv("ZENAF_PROD", "1")
    monkeypatch.delenv("ZENAF_SETTINGS_ENCRYPTION_KEY", raising=False)
    assert St._get_settings_encryption_key_raw() == "fake-test-fernet-key"


def test_openai_row_present_but_undecryptable(monkeypatch: pytest.MonkeyPatch) -> None:
    from local_ai.execution_policy.openai_credentials import resolve_openai_api_key

    uid = str(uuid.uuid4())
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(St, "get_decrypted_llm_api_key", lambda u, p: None)
    monkeypatch.setattr(St, "llm_credential_row_exists", lambda u, p: True)
    assert resolve_openai_api_key(uid) == (None, "undecryptable")
    monkeypatch.setattr(St, "llm_credential_row_exists", lambda u, p: False)
    assert resolve_openai_api_key(uid) == (None, "none")


def test_cloud_key_undecryptable_openai_and_generic(monkeypatch: pytest.MonkeyPatch) -> None:
    from local_ai.llm.credentials import resolve_cloud_api_key
    from local_ai.llm.execution_principal import authenticated_account_principal

    uid = str(uuid.uuid4())
    p = authenticated_account_principal(uid)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(St, "get_decrypted_llm_api_key", lambda u, pr: None)
    monkeypatch.setattr(St, "llm_credential_row_exists", lambda u, pr: True)
    assert resolve_cloud_api_key(p, "openai") == (None, "undecryptable")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert resolve_cloud_api_key(p, "anthropic") == (None, "undecryptable")


def test_participant_undecryptable_message(monkeypatch: pytest.MonkeyPatch) -> None:
    from local_ai.build_room import participants

    monkeypatch.setattr(
        participants, "resolve_cloud_api_key", lambda pr, pid: (None, "undecryptable")
    )
    part, note = participants.resolve_openai_participant()
    assert part is None
    assert note.startswith("present but undecryptable")
    monkeypatch.setattr(participants, "resolve_cloud_api_key", lambda pr, pid: (None, "none"))
    part, note = participants.resolve_openai_participant()
    assert part is None
    assert note == "absent: no openai api key present for this principal"
