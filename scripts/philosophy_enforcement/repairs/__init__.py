"""
Bounded repair handlers for auto_repair.py.

Register callables in HANDLERS keyed by checker_id. Each handler receives:
  repo: Path
  findings: list[dict]  # flatten_confirmed_findings subset for that checker
  checker_config: dict  # entry from repair_registry.json

Must return RepairBatchResult. See AUTONOMOUS_REPAIR_POLICY.md.
"""
from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from .models import RepairBatchResult
from .trace_exempt_registry_sync import repair_trace_exempt_registry_gaps

HandlerFn = Callable[[Path, list[dict[str, Any]], dict[str, Any]], RepairBatchResult]

# Phase 1: single bounded handler (see repair_registry.json).
HANDLERS: dict[str, HandlerFn] = {
    "trace_or_exempt": repair_trace_exempt_registry_gaps,
}


def get_handler(checker_id: str) -> HandlerFn | None:
    return HANDLERS.get(checker_id)
