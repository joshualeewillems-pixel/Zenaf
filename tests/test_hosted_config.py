"""Hosted-mode configuration tests.

Covers: prod-mode gating, fail-fast secrets, cookie hardening, data-dir
precedence, frontend apiBase centralization (no hardcoded backend URLs), and
the Docker artifact shape. All hermetic (monkeypatched env, no network).
"""
from __future__ import annotations

import os
import re
from pathlib import Path

import pytest

from local_ai import hosted_config as hc

REPO_ROOT = Path(__file__).resolve().parent.parent
FRONTEND_SRC = REPO_ROOT / "frontend" / "src"


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for var in (
        "ZENAF_PROD",
        "ZENAF_SECRET_KEY",
        "ZENAF_BOOTSTRAP_PASSWORD",
        "ZENAF_DB_DIR",
        "ZENAF_DATA_DIR",
        "ZENAF_LLM_PROVIDER",
        "PORT",
    ):
        monkeypatch.delenv(var, raising=False)


# --- prod gating -----------------------------------------------------------


def test_dev_is_default():
    assert hc.is_prod() is False
    assert hc.session_cookie_secure() is False
    # No-op in dev: never raises.
    hc.validate_prod_config()


@pytest.mark.parametrize("val", ["1", "true", "TRUE", "yes", "on"])
def test_prod_truthy_values(monkeypatch, val):
    monkeypatch.setenv("ZENAF_PROD", val)
    assert hc.is_prod() is True
    assert hc.session_cookie_secure() is True


@pytest.mark.parametrize("val", ["0", "false", "no", ""])
def test_prod_falsy_values(monkeypatch, val):
    monkeypatch.setenv("ZENAF_PROD", val)
    assert hc.is_prod() is False


def test_prod_requires_secret_key(monkeypatch):
    monkeypatch.setenv("ZENAF_PROD", "1")
    monkeypatch.setenv("ZENAF_BOOTSTRAP_PASSWORD", "x")
    with pytest.raises(RuntimeError, match="ZENAF_SECRET_KEY"):
        hc.validate_prod_config()


def test_prod_requires_bootstrap_password(monkeypatch):
    monkeypatch.setenv("ZENAF_PROD", "1")
    monkeypatch.setenv("ZENAF_SECRET_KEY", "s" * 32)
    with pytest.raises(RuntimeError, match="ZENAF_BOOTSTRAP_PASSWORD"):
        hc.validate_prod_config()


def test_prod_valid_config_passes(monkeypatch):
    monkeypatch.setenv("ZENAF_PROD", "1")
    monkeypatch.setenv("ZENAF_SECRET_KEY", "s" * 32)
    monkeypatch.setenv("ZENAF_BOOTSTRAP_PASSWORD", "correct-horse")
    hc.validate_prod_config()  # must not raise


# --- port / provider / data dir --------------------------------------------


def test_port_default_and_override(monkeypatch):
    assert hc.port() == 8010
    monkeypatch.setenv("PORT", "8080")
    assert hc.port() == 8080
    monkeypatch.setenv("PORT", "not-a-port")
    assert hc.port() == 8010


def test_default_llm_provider(monkeypatch):
    assert hc.default_llm_provider() == "ollama"
    monkeypatch.setenv("ZENAF_LLM_PROVIDER", "anthropic")
    assert hc.default_llm_provider() == "anthropic"
    monkeypatch.setenv("ZENAF_LLM_PROVIDER", "  ")
    assert hc.default_llm_provider() == "ollama"


def test_data_dir_precedence(monkeypatch, tmp_path):
    # Dev default: repo data/.
    assert hc.data_dir() == REPO_ROOT / "data"
    # Hosted override.
    monkeypatch.setenv("ZENAF_DB_DIR", str(tmp_path / "vol"))
    assert hc.data_dir() == tmp_path / "vol"
    # Test hermetic override wins over hosted override.
    monkeypatch.setenv("ZENAF_DATA_DIR", str(tmp_path / "hermetic"))
    assert hc.data_dir() == tmp_path / "hermetic"


def test_db_dir_alias_sets_data_dir(monkeypatch, tmp_path):
    """Import-time alias: ZENAF_DB_DIR -> ZENAF_DATA_DIR (when unset)."""
    monkeypatch.setenv("ZENAF_DB_DIR", str(tmp_path / "vol"))
    monkeypatch.delenv("ZENAF_DATA_DIR", raising=False)
    # Re-run the alias logic (it runs at import; simulate a fresh import).
    import importlib

    importlib.reload(hc)
    try:
        assert os.environ.get("ZENAF_DATA_DIR") == str(tmp_path / "vol")
    finally:
        importlib.reload(hc)  # restore module state


def test_db_dir_alias_does_not_clobber(monkeypatch, tmp_path):
    monkeypatch.setenv("ZENAF_DB_DIR", str(tmp_path / "vol"))
    monkeypatch.setenv("ZENAF_DATA_DIR", str(tmp_path / "keep"))
    import importlib

    importlib.reload(hc)
    try:
        assert os.environ.get("ZENAF_DATA_DIR") == str(tmp_path / "keep")
    finally:
        importlib.reload(hc)


# --- session cookie hardening ----------------------------------------------


def test_cookie_settings_dev(monkeypatch):
    from api.routes.auth_routes import _session_cookie_settings

    s = _session_cookie_settings()
    assert s["secure"] is False
    assert s["httponly"] is True
    assert s["samesite"] == "lax"


def test_cookie_settings_prod(monkeypatch):
    monkeypatch.setenv("ZENAF_PROD", "1")
    from api.routes.auth_routes import _session_cookie_settings

    s = _session_cookie_settings()
    assert s["secure"] is True
    assert s["httponly"] is True


# --- frontend: no hardcoded backend origin ---------------------------------


def test_apibase_helper_exists():
    p = FRONTEND_SRC / "apiBase.ts"
    assert p.is_file(), "frontend/src/apiBase.ts must exist"
    text = p.read_text(encoding="utf-8")
    assert "VITE_API_BASE" in text
    assert "127.0.0.1:8010" in text  # dev default preserved


def test_no_hardcoded_api_base_constant():
    """The old `const API_BASE = 'http://127.0.0.1:8010'` must be gone."""
    for path in FRONTEND_SRC.rglob("*.tsx"):
        text = path.read_text(encoding="utf-8")
        assert "const API_BASE = 'http://127.0.0.1:8010'" not in text, path
    for path in FRONTEND_SRC.rglob("*.ts"):
        if path.name == "apiBase.ts":
            continue
        text = path.read_text(encoding="utf-8")
        assert "const API_BASE = 'http://127.0.0.1:8010'" not in text, path


def test_no_hardcoded_fetch_origins():
    """No fetch() call may embed a hardcoded http(s) backend origin."""
    bad: list[str] = []
    pat = re.compile(r"fetch\(\s*[`'\"]https?://(127\.0\.0\.1|localhost)")
    for path in list(FRONTEND_SRC.rglob("*.tsx")) + list(FRONTEND_SRC.rglob("*.ts")):
        for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if pat.search(line):
                bad.append(f"{path.relative_to(REPO_ROOT)}:{i}")
    assert not bad, "hardcoded fetch origins:\n" + "\n".join(bad)


# --- docker artifact --------------------------------------------------------


def test_dockerfile_shape():
    p = REPO_ROOT / "Dockerfile"
    assert p.is_file()
    text = p.read_text(encoding="utf-8")
    assert "FROM node:" in text and "AS frontend" in text
    assert "FROM python:" in text
    assert 'VITE_API_BASE=""' in text
    assert "uvicorn api.main:app" in text
    assert "ZENAF_PROD=1" in text or "ZENAF_PROD" in text


def test_compose_shape():
    p = REPO_ROOT / "docker-compose.yml"
    assert p.is_file()
    text = p.read_text(encoding="utf-8")
    assert "ZENAF_SECRET_KEY" in text
    assert "ZENAF_BOOTSTRAP_PASSWORD" in text
    assert "/app/data" in text
    assert "/healthz" in text
