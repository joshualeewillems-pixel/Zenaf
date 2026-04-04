"""
Deprecated intake-specific access policy.

Kept as a thin shim for backward compatibility. Use `local_ai.policy.data_access`
for all new code (intake, council/perspectives, file steward, connectors, etc.).
"""
from __future__ import annotations

from local_ai.policy.data_access import *  # noqa: F401,F403
