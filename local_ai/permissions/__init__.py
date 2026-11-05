"""Standing-permission framework, Slice 1 foundation.

Registry definitions (``registry``), the extended stance store
(``store``), and the five-step framework check (``framework``).
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
    "get_pause",
    "get_stance",
    "get_stances",
    "migrate_flags_to_stances",
    "set_pause",
    "set_stance",
    "stance_history",
]
