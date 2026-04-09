"""
Best-effort performance correlation for council /run/stream.

``perf_begin`` runs on the ASGI request thread; Starlette runs ``StreamingResponse``
body iteration in a worker thread, which does not inherit ContextVars. Call
``perf_restore`` at the start of the stream generator with values from
``perf_read_context()`` (captured on the request thread) so correlation and
``elapsed_ms`` stay aligned end-to-end.
"""

from __future__ import annotations

import logging
import time
from contextvars import ContextVar
from typing import Any

_log = logging.getLogger("zenaf.perf")

_perf_correlation: ContextVar[str | None] = ContextVar("zenaf_perf_correlation", default=None)
_perf_anchor: ContextVar[float | None] = ContextVar("zenaf_perf_anchor", default=None)


def perf_begin(correlation_id: str) -> None:
    _perf_correlation.set(correlation_id)
    _perf_anchor.set(time.perf_counter())


def perf_read_context() -> tuple[str | None, float | None]:
    """Snapshot correlation + perf_counter anchor from the current context (request thread)."""

    return _perf_correlation.get(), _perf_anchor.get()


def perf_restore(correlation_id: str, anchor_perf_counter: float | None) -> None:
    """Re-apply correlation/anchor in a new thread (e.g. streaming body worker).

    ``anchor_perf_counter`` must be the same value returned by ``perf_read_context``
    on the request thread so ``elapsed_ms`` stays monotonic across the handoff.
    If anchor is missing, starts a fresh anchor in this thread (degraded).
    """

    _perf_correlation.set(correlation_id)
    if anchor_perf_counter is not None:
        _perf_anchor.set(anchor_perf_counter)
    else:
        _perf_anchor.set(time.perf_counter())


def perf_mark(stage: str, **extra: Any) -> None:
    cid = _perf_correlation.get()
    anchor = _perf_anchor.get()
    elapsed_ms = (time.perf_counter() - anchor) * 1000 if anchor is not None else -1.0
    if extra:
        bits = " ".join(f"{k}={v!r}" for k, v in extra.items())
        _log.info("[zenaf-perf] correlation=%s elapsed_ms=%.2f stage=%s %s", cid or "-", elapsed_ms, stage, bits)
    else:
        _log.info("[zenaf-perf] correlation=%s elapsed_ms=%.2f stage=%s", cid or "-", elapsed_ms, stage)
