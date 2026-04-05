from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from ..models import CheckerRun

CheckerFn = Callable[[Path], CheckerRun]

CHECKERS: dict[str, CheckerFn] = {}


def register(cid: str):
    def deco(fn: CheckerFn) -> CheckerFn:
        CHECKERS[cid] = fn
        return fn

    return deco


def load_all_checkers() -> None:
    """Import side effects register checkers."""
    from . import check_canonical_identity  # noqa: F401
    from . import check_data_access_surface  # noqa: F401
    from . import check_developmental_guidance  # noqa: F401
    from . import check_http_client_frontier  # noqa: F401
    from . import check_intake_observability  # noqa: F401
    from . import check_deterministic_commit  # noqa: F401
    from . import check_execution_seam_surface  # noqa: F401
    from . import check_mirror_interpretation  # noqa: F401
    from . import check_operator_boundaries  # noqa: F401
    from . import check_operator_mutation_depth  # noqa: F401
    from . import check_operator_trace_alignment  # noqa: F401
    from . import check_product_honesty  # noqa: F401
    from . import check_trace_coverage  # noqa: F401
    from . import check_vitality_value_boundary  # noqa: F401
    from . import canonical_identity_leaks  # noqa: F401
    from . import execution_seam_bypasses  # noqa: F401
    from . import product_honesty_phantom  # noqa: F401
    from . import schema_ui_drift  # noqa: F401
    from . import trace_or_exempt  # noqa: F401
