"""Image fingerprints for the provenance registry.

Per artifact, stored at registration:
- 64-bit DCT perceptual hash (pHash) — near-duplicate matching. Survives
  resize, recompression, format swaps, light crops, approximately screenshots.
- SHA-256 of the raw bytes — exact matching.

Matching: SHA-256 first (exact), then pHash Hamming distance <= NEAR_THRESHOLD
(default 10, per spec) for near-duplicates. Small scale: brute force is fine;
later BK-tree/LSH.

Libraries: `ImageHash` for pHash, stdlib `hashlib` for SHA-256, Pillow for
decoding. No ML, milliseconds per artifact.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from io import BytesIO

import imagehash
from PIL import Image

#: Hamming-distance threshold for near-duplicate image matches (spec §2).
NEAR_THRESHOLD = 10


@dataclass(frozen=True)
class ImageFingerprint:
    """Fingerprints for one image artifact."""

    #: Hex string of the 64-bit DCT perceptual hash (16 hex chars).
    phash: str
    #: Hex string of the SHA-256 of the raw image bytes.
    sha256: str

    @property
    def phash_int(self) -> int:
        return int(self.phash, 16)


def fingerprint_image(data: bytes) -> ImageFingerprint:
    """Compute pHash + SHA-256 for raw image bytes.

    Raises ValueError if the bytes are not a decodable image.
    """
    try:
        img = Image.open(BytesIO(data))
        img.load()
    except Exception as exc:
        raise ValueError(f"not a decodable image: {exc}") from exc
    phash = str(imagehash.phash(img))
    return ImageFingerprint(phash=phash, sha256=sha256(data).hexdigest())


def phash_distance(a_hex: str, b_hex: str) -> int:
    """Hamming distance between two hex-encoded 64-bit perceptual hashes."""
    return bin(int(a_hex, 16) ^ int(b_hex, 16)).count("1")


def is_exact_match(a: ImageFingerprint, b_sha256: str) -> bool:
    """Exact match: SHA-256 equality."""
    return a.sha256 == b_sha256


def is_near_match(a_phash_hex: str, b_phash_hex: str, threshold: int = NEAR_THRESHOLD) -> bool:
    """Near-duplicate match: pHash Hamming distance within threshold."""
    return phash_distance(a_phash_hex, b_phash_hex) <= threshold
