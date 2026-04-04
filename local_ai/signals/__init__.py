"""
Canonical Signal entity (Layer 1). Cross-source: meeting-extraction, inbox-triage, doc-parse, etc.
Radar is a view over Signal; storage uses vision_execution SQLite.
"""
from .models import Signal, SignalCreate, SignalUpdate
from .service import create_signals, list_signals, update_signal

__all__ = [
    "Signal",
    "SignalCreate",
    "SignalUpdate",
    "create_signals",
    "list_signals",
    "update_signal",
]
