"""Fingerprint module: pHash + SHA-256, exact/near matching (no network)."""

from __future__ import annotations

import io

import pytest
from PIL import Image, ImageDraw

from local_ai.provenance.fingerprints import (
    NEAR_THRESHOLD,
    fingerprint_image,
    is_near_match,
    phash_distance,
)


def _to_bytes(img: Image.Image, fmt: str = "PNG", **kw) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format=fmt, **kw)
    return buf.getvalue()


def _vhalves() -> bytes:
    img = Image.new("RGB", (128, 128), "white")
    ImageDraw.Draw(img).rectangle([0, 0, 63, 127], fill="black")
    return _to_bytes(img)


def _circle() -> bytes:
    img = Image.new("RGB", (128, 128), "white")
    ImageDraw.Draw(img).ellipse([24, 24, 104, 104], fill="black")
    return _to_bytes(img)


def test_fingerprint_shape():
    fp = fingerprint_image(_vhalves())
    assert len(fp.phash) == 16  # 64-bit hex
    assert len(fp.sha256) == 64
    int(fp.phash, 16)  # valid hex


def test_identical_bytes_identical_fingerprints():
    data = _vhalves()
    assert fingerprint_image(data) == fingerprint_image(data)


def test_recompression_is_near_match():
    """JPEG recompression changes bytes but not the perceptual hash much."""
    a = fingerprint_image(_vhalves())
    recompressed = _to_bytes(
        Image.open(io.BytesIO(_vhalves())), fmt="JPEG", quality=70
    )
    b = fingerprint_image(recompressed)
    assert a.sha256 != b.sha256  # bytes differ -> not exact
    assert phash_distance(a.phash, b.phash) <= NEAR_THRESHOLD
    assert is_near_match(a.phash, b.phash)


def test_different_image_is_not_near_match():
    a = fingerprint_image(_vhalves())
    b = fingerprint_image(_circle())
    assert phash_distance(a.phash, b.phash) > NEAR_THRESHOLD
    assert not is_near_match(a.phash, b.phash)


def test_invalid_bytes_raise():
    with pytest.raises(ValueError):
        fingerprint_image(b"this is not an image at all")


def test_phash_distance_symmetric():
    a = fingerprint_image(_vhalves())
    b = fingerprint_image(_circle())
    assert phash_distance(a.phash, b.phash) == phash_distance(b.phash, a.phash)
    assert phash_distance(a.phash, a.phash) == 0
