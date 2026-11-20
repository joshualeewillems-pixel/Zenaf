"""The Atelier binding layer — derivations from records to expression.

Increment 1 (Aria's Grounded Expression, Gate B brief 2026-11-19):
one pure derivation, :func:`derive_aria_expression`, which reads the
records the system already keeps and produces Aria's expression
specification for one Work — the ACTIVITY-dimension substrate plus
the recorded-relations set, and nothing else (the Founder
Clarification's re-scoping governs: identity and purpose are not
derivable from project metadata and are never manufactured here).

The package is deliberately thin: derivations only. No rendering,
no stores of its own, no generation machinery.
"""

from __future__ import annotations

from local_ai.atelier.aria_expression import (
    AriaExpressionSpec,
    derive_aria_expression,
)

__all__ = ["AriaExpressionSpec", "derive_aria_expression"]
