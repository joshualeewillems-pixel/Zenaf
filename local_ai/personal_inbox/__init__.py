"""
Personal inbox cleanup: classification and reputation for high-volume personal mailboxes.

This module is intentionally separate from clinic/operational intake. It is used as:
- A negative corpus for anti-noise patterns.
- A tool for reporting and safe cleanup suggestions.
"""

from .classifier import classify_personal_message  # noqa: F401
from .reputation import load_reputation, save_reputation, update_reputation  # noqa: F401

