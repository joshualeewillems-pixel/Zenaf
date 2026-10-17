"""C2PA alignment seam for the provenance registry.

Spec §6: don't invent a metadata format. At mint time, embed a C2PA manifest
(creator, timestamp, artifact ID, edit actions) where the tooling supports it;
on ingest, read any manifest as a re-identification hint. The registry remains
canonical — C2PA is the portable claim, the registry is the verified record.

Current state:
- `read_manifest()` is REAL: parses an embedded C2PA manifest (if any) from
  image bytes, best-effort, returns None when absent or unparsable.
- `embed_manifest()` is a STUB: signing a manifest requires a real PKI
  identity (X.509 cert + private key for the manifest signer). Until Zenaf
  has a signing certificate, minting embeds nothing and the registry stays
  the sole record. The store already has a `c2pa_manifest` blob column, so
  when signing lands, this is the only function that needs a body.
- `harvest_hints()` is REAL: C2PA (when present) + EXIF/XMP tags, harvested
  at ingest as free provenance. Costs nothing, catches what it catches.
"""

from __future__ import annotations

import json
from io import BytesIO
from typing import Any


def _mime_for(data: bytes) -> str | None:
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:2] == b"\xff\xd8":
        return "image/jpeg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def read_manifest(data: bytes) -> dict[str, Any] | None:
    """Read an embedded C2PA manifest from image bytes.

    Returns the manifest as a dict, or None when absent/unreadable.
    Best-effort: never raises on malformed input.
    """
    try:
        import c2pa  # type: ignore
    except ImportError:
        return None
    mime = _mime_for(data)
    if mime is None:
        return None
    try:
        with BytesIO(data) as stream:
            reader = c2pa.Reader(mime, stream)
            raw = reader.json()
        return json.loads(raw) if isinstance(raw, str) else raw
    except Exception:
        return None


def embed_manifest(
    data: bytes,
    *,
    artifact_id: str,
    creator: str | None = None,
    claim_url: str | None = None,
) -> bytes | None:
    """Embed a C2PA manifest claiming this artifact. STUB.

    TODO: requires a manifest-signing identity (X.509 cert + private key).
    Until then, returns None and the registry remains the sole record.
    When signing lands: build the manifest JSON (title, creator, artifact_id
    + URL assertion pointing at the artifact page), sign with Builder, and
    return the re-encoded bytes. Store the returned bytes' manifest in the
    artifact's `c2pa_manifest` column too.
    """
    return None


def _exif_hints(data: bytes) -> dict[str, Any]:
    """Best-effort EXIF/XMP harvest. Free provenance, weak guarantees."""
    hints: dict[str, Any] = {}
    try:
        from PIL import Image
        from PIL.ExifTags import TAGS

        img = Image.open(BytesIO(data))
        exif = img.getexif()
        if exif:
            for tag_id, value in exif.items():
                tag = TAGS.get(tag_id, tag_id)
                if tag in ("Artist", "Copyright", "DateTime", "DateTimeOriginal",
                           "ImageDescription", "Software"):
                    hints[f"exif_{tag}"] = str(value)[:500]
        # PNG tEXt / iTXt chunks survive more often than EXIF.
        if isinstance(img.info, dict):
            for key in ("Title", "Author", "Description", "Copyright", "Creation Time"):
                if key in img.info:
                    hints[f"png_{key.lower().replace(' ', '_')}"] = str(img.info[key])[:500]
    except Exception:
        pass
    return hints


def harvest_hints(data: bytes) -> dict[str, Any]:
    """Harvest every portable provenance hint from image bytes.

    Returns {"c2pa": <manifest dict> | None, "exif": {...}}. Used at ingest:
    a C2PA manifest may carry the artifact ID or creator outright, which can
    shortcut fingerprint matching and seed creator attribution.
    """
    return {"c2pa": read_manifest(data), "exif": _exif_hints(data)}
