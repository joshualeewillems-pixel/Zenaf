"""Shared extraction-model concurrency (upload S1, brief amendment A5).

One semaphore, one home, for every path that calls a model for
extraction: the upload extraction worker
(``local_ai/conversation/upload_extraction.py``) and the presence
distillation path (``local_ai/presence_ingest/distill.py``). A neutral
home — not in ``upload_extraction`` (which would make
``presence_ingest`` depend on ``conversation``, a layering inversion)
and not in ``distill`` (the same problem in reverse).

Size comes from ``ZENAF_EXTRACTION_CONCURRENCY`` (default 1), read
here at import time. Both paths take the slot around the model
generate call only — never around the Ollama reachability probe
(upload side) and per batch inside ``distill_events`` (distill side),
so the hold duration stays per call / per batch.
"""

from __future__ import annotations

import os
import threading
from contextlib import contextmanager
from typing import Iterator


def _concurrency() -> int:
    try:
        return max(1, int(os.environ.get("ZENAF_EXTRACTION_CONCURRENCY", "1") or 1))
    except ValueError:
        return 1


EXTRACTION_SEMAPHORE = threading.Semaphore(_concurrency())

# Back-compat alias: the upload worker re-exports this name.
EXTRACTION_MODEL_SEMAPHORE = EXTRACTION_SEMAPHORE


@contextmanager
def extraction_slot() -> Iterator[None]:
    """Hold one extraction-model slot for the enclosed generate call."""
    with EXTRACTION_SEMAPHORE:
        yield
