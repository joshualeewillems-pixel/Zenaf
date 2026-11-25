"""Reconstruction verification (P-2) — the increment's closing step.

The procedure is deliberately small, because the machinery it
verifies already exists: the Talk prompt is assembled from named
components by ``build_voice_prompt``, deterministically, and every
generated turn's manifest stores the assembled prompt's sha256
(the FINGERPRINT ruling: hash, not text). Reconstruction therefore
re-runs the builder itself over the referenced component versions
— no second implementation of assembly is built — and compares
hashes. **The fingerprint is the verification mechanism**: a match
verifies the turn's context in aggregate; the manifest's component
references (P-1) localize any mismatch.

This module is the offline/read-side half: it takes a manifest and
either a rebuilt prompt text or a builder callable (the caller's
re-run of ``build_voice_prompt`` over the referenced versions), and
it reports. It also names the Tier-2 legs: component classes whose
recoverability a manifest's references do NOT establish, so any
additional preservation they need is a named list, never a silent
gap (C2: a named deficit gates enablement; it never substitutes
for it).

Nothing here generates, trains, or touches production traffic.
"""

from __future__ import annotations

import hashlib
from typing import Any, Callable

#: Component-reference classes P-1 completes on the manifest. A
#: manifest silent on a class leaves that leg unverified; the
#: assessment names it as a Tier-2 leg rather than assuming it.
REFERENCE_CLASSES: tuple[str, ...] = (
    "character_state_id",
    "code_ref",
    "capability_slice_id",
    "visitor_state_refs",
    "service_blocks",
    "history_message_ids",
)


def sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()


def verify_reconstruction(
    manifest: dict[str, Any], rebuilt_prompt_text: str
) -> dict[str, Any]:
    """Compare a rebuilt prompt against the manifest's fingerprint."""
    expected = manifest.get("prompt_sha256")
    rebuilt = sha256_hex(rebuilt_prompt_text)
    return {
        "verified": bool(expected) and rebuilt == expected,
        "expected_prompt_sha256": expected,
        "rebuilt_prompt_sha256": rebuilt,
        "prompt_chars": len(rebuilt_prompt_text),
        "expected_prompt_chars": manifest.get("prompt_chars"),
    }


def verify_from_builder(
    manifest: dict[str, Any], build: Callable[[], str]
) -> dict[str, Any]:
    """Run the P-2 procedure: ``build`` re-runs ``build_voice_prompt``
    over the component versions the manifest references; the result
    is verified against the stored fingerprint."""
    return verify_reconstruction(manifest, build())


def assess_tier2(
    manifest: dict[str, Any],
    *,
    preserved_components: dict[str, Any] | None = None,
) -> list[dict[str, str]]:
    """Name the Tier-2 legs a manifest leaves open.

    A leg is open when the manifest's references do not establish
    that component's recoverability AND no preserved-component
    record covers it. N1-era author turns carry full references and
    Tier-1 preservation, so their expected assessment is empty;
    pre-P-1 turns honestly report every leg.
    """
    legs: list[dict[str, str]] = []
    refs = manifest.get("refs") or {}
    preserved = (preserved_components or {}).get("components") or {}

    for cls in REFERENCE_CLASSES:
        if cls not in refs:
            legs.append(
                {
                    "leg": cls,
                    "need": (
                        "manifest carries no reference for this "
                        "component class; stamp it at the write point "
                        "(P-1) or preserve the rendered component"
                    ),
                }
            )
    # The summary leg: a turn that SAW a thread summary is
    # reconstructible only if that summary state survives — the
    # summary-history record (Q4.3) or a preserved component.
    if manifest.get("thread_summary_sha256") and not (
        "thread_summary" in preserved or refs.get("summary_history")
    ):
        legs.append(
            {
                "leg": "thread_summary",
                "need": (
                    "the turn saw a thread summary whose state is "
                    "not preserved; summary history (Q4.3) or Tier-1 "
                    "preservation must cover it"
                ),
            }
        )
    # Mutable-source service blocks: references make the gap
    # measurable; preserved rendered text closes it outright.
    service_refs = refs.get("service_blocks") or {}
    for name in service_refs.get("present") or []:
        if name not in preserved and not service_refs.get("record_ids"):
            legs.append(
                {
                    "leg": f"service_block:{name}",
                    "need": (
                        "block rendered from mutable records with no "
                        "record ids stamped and no preserved text; "
                        "as-of reconstruction is unverified for it"
                    ),
                }
            )
    return legs
