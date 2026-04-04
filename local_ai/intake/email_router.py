"""
Email intake: accept raw email content, run unified pipeline, return structured item.
Raw email stays internal; only sanitized text is used for summary.
"""
from __future__ import annotations

from .pipeline import run_pipeline, IntakeItem


def process_email(raw_body: str, *, do_redact: bool = True) -> IntakeItem:
    """
    Process raw email body through the intake pipeline.
    Returns a structured IntakeItem (no raw content). Add to queue separately.
    """
    return run_pipeline(raw_body.strip(), "email", do_redact=do_redact)
