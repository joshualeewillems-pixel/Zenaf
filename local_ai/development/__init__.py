"""Native character development (Increment N1, 2026-11-23).

The smallest genuinely useful native developmental loop: an author
can interact with a character, correct or develop that character
directly, and subsequently experience the resulting development —
without engineering intervention — while the developmental material
is preserved for eventual model adaptation.

Everything here is machinery + records, shipped DARK: the whole
package is inert unless ``ZENAF_NATIVE_DEVELOPMENT`` is explicitly
enabled, and every write path is additionally gated on authorship
(the caller's authorship relation over the character concerned —
see :mod:`local_ai.development.service`). No model calls, no
training, no dataset construction live in this package.

Layout:
- :mod:`~local_ai.development.store` — the append-only developmental
  store (character states, perspective material, authorial acts,
  verdict records, designations, preserved components, summary
  history, expression links), with its erasure enumeration.
- :mod:`~local_ai.development.service` — authorship resolution,
  correction-as-verdict recording, carriage, designation.
- :mod:`~local_ai.development.reconstruction` — the P-2 verification
  procedure (re-run the prompt builder over referenced components;
  the stored fingerprint is the verification mechanism).
"""

from __future__ import annotations

import os

__all__ = ["native_development_enabled"]


def native_development_enabled() -> bool:
    """Rollout flag for the N1 developmental loop.

    Follows the house flag pattern (cf. ``sketch_shaping_enabled``):
    an explicit ``ZENAF_NATIVE_DEVELOPMENT`` value wins
    ("1"/"true"/"yes"/"on" = on; anything else = off), read per
    call. Default OFF in every environment — local, staging, and
    production. N1 ships dark; production enablement on the author
    account is a separate founder decision.
    """
    raw = os.environ.get("ZENAF_NATIVE_DEVELOPMENT")
    if raw is None:
        return False
    return raw.strip().lower() in {"1", "true", "yes", "on"}
