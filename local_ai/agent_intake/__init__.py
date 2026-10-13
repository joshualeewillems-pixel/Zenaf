"""Agent Intake & Sorting ("The Sorting") — v1.

Connect external AI agents (custom GPTs, Claude Projects, bots), sort them
into the seven strand agents as skills / talents / projects, and queue them
for user review. See docs/01_TRUTH/AGENT_INTAKE_AND_SORTING.md.
"""
from .pipeline import confirm_agent, connect_agent
from .schema import ConnectedAgent, SortResult, StrandClaim
from .sorter import sort
from .store import AgentStore

__all__ = [
    "AgentStore",
    "ConnectedAgent",
    "SortResult",
    "StrandClaim",
    "confirm_agent",
    "connect_agent",
    "sort",
]
