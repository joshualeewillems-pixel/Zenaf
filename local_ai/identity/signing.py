"""HMAC-SHA256 signing for licenses and deletion receipts.

This is tamper-evidence for a local-first system, NOT a public-key
infrastructure: the key lives on the owner's machine (0600), and signatures
prove that a license/receipt has not been altered since issuance — by anyone,
including Zenaf itself. If the key file is lost, previously issued signatures
can no longer be verified; document that to the user rather than hiding it.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
from pathlib import Path
from typing import Any

from . import identity_data_dir

KEY_FILENAME = ".license_key"
_KEY_BYTES = 32


def _key_path() -> Path:
    return identity_data_dir() / KEY_FILENAME


def get_key() -> bytes:
    """Load the license signing key, creating it (0600) on first use."""
    path = _key_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_file():
        return path.read_bytes()
    # O_EXCL: if two processes race, the loser reads the winner's key.
    try:
        fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        return path.read_bytes()
    try:
        key = os.urandom(_KEY_BYTES)
        os.write(fd, key)
    finally:
        os.close(fd)
    # Belt and suspenders: ensure restrictive perms even on odd filesystems.
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return key


def _canonical(mapping: dict[str, Any]) -> bytes:
    return json.dumps(mapping, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sign_mapping(mapping: dict[str, Any]) -> str:
    """Hex HMAC-SHA256 over the canonical JSON of `mapping`."""
    return hmac.new(get_key(), _canonical(mapping), hashlib.sha256).hexdigest()


def verify_mapping(mapping: dict[str, Any], signature: str) -> bool:
    """True iff `signature` is the valid HMAC of `mapping` under the key."""
    if not signature or not isinstance(signature, str):
        return False
    expected = sign_mapping(mapping)
    return hmac.compare_digest(expected, signature)
