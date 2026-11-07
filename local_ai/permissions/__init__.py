"""Standing-permission framework, Slice 1 foundation + Slice 2 surface.

Registry definitions (``registry``), the extended stance store
(``store``), the five-step framework check (``framework``), and the
retained-information counts (``retained``, Slice 2).
See each module's docstring for the governing design and bounds.
"""

from .framework import AuthorizationContract, FrameworkDecision, framework_check
from .registry import (
    ASK_ME,
    CAPABILITIES,
    DONT_DO_IT,
    JUST_DO_IT,
    RETIRED_CAPABILITY_IDS,
    get_capability,
    is_registered,
)
from .retained import retained_counts
from .store import (
    get_pause,
    get_stance,
    get_stances,
    migrate_flags_to_stances,
    set_pause,
    set_stance,
    stance_history,
)

__all__ = [
    "AuthorizationContract",
    "FrameworkDecision",
    "framework_check",
    "ASK_ME",
    "CAPABILITIES",
    "DONT_DO_IT",
    "JUST_DO_IT",
    "RETIRED_CAPABILITY_IDS",
    "get_capability",
    "is_registered",
    "retained_counts",
    "get_pause",
    "get_stance",
    "get_stances",
    "migrate_flags_to_stances",
    "set_pause",
    "set_stance",
    "stance_history",
]
