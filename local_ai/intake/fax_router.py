"""
Fax intake: accept raw fax content (e.g. OCR text), run unified pipeline, return structured item.
Raw fax stays internal; only sanitized text is used for summary.
"""
from __future__ import annotations

from .pipeline import run_pipeline, IntakeItem


def process_fax(raw_content: str, *, do_redact: bool = True) -> IntakeItem:
    """
    Process raw fax/OCR content through the intake pipeline.
    Returns a structured IntakeItem (no raw content). Add to queue separately.
    """
    return run_pipeline(raw_content.strip(), "fax", do_redact=do_redact)
