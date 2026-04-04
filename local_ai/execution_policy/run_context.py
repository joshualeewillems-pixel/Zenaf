"""
Per-request execution routing context.

- **Ollama model override:** when set, ``local_ai.llm.resolver`` (council and default adapter paths) uses that model.
- **Policy provider override:** when set (e.g. OpenAI from execution policy), resolver reads it via
  ``get_policy_provider_override()`` so ``ExecutionPrincipal`` → adapter matches the seam for the request.

Policy override takes precedence over the Ollama model token.
"""

from __future__ import annotations

import contextvars
import logging
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Generator, Optional

logger = logging.getLogger(__name__)

_ollama_model_override: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "atria_ollama_model_override",
    default=None,
)

_policy_provider_override: contextvars.ContextVar[Optional[Any]] = contextvars.ContextVar(
    "atria_policy_provider_override",
    default=None,
)


def get_ollama_model_override() -> Optional[str]:
    return _ollama_model_override.get()


def push_ollama_model_override(model: Optional[str]) -> contextvars.Token[Optional[str]]:
    return _ollama_model_override.set(model)


def reset_ollama_model_override(token: contextvars.Token[Optional[str]]) -> None:
    _ollama_model_override.reset(token)


def get_policy_provider_override() -> Optional[Any]:
    return _policy_provider_override.get()


def push_policy_provider_override(provider: Any) -> contextvars.Token[Optional[Any]]:
    return _policy_provider_override.set(provider)


def reset_policy_provider_override(token: contextvars.Token[Optional[Any]]) -> None:
    _policy_provider_override.reset(token)


@dataclass
class RoutingTeardown:
    """Tokens to reset after a routed ``/run`` / ``/run/stream`` request."""

    ollama_token: Optional[contextvars.Token[Optional[str]]] = None
    policy_provider_token: Optional[contextvars.Token[Optional[Any]]] = None


def end_execution_routing(teardown: Optional[RoutingTeardown]) -> None:
    if teardown is None:
        return
    if teardown.policy_provider_token is not None:
        try:
            reset_policy_provider_override(teardown.policy_provider_token)
        except ValueError as e:
            # Streaming teardown can run in a worker-thread context; avoid crashing request finalization.
            logger.warning("execution routing cleanup skipped for policy provider token due to context mismatch: %s", e)
    if teardown.ollama_token is not None:
        try:
            reset_ollama_model_override(teardown.ollama_token)
        except ValueError as e:
            # Token was created in a different ContextVar context; safe to skip on teardown.
            logger.warning("execution routing cleanup skipped for ollama token due to context mismatch: %s", e)


@contextmanager
def ollama_model_override(model: str) -> Generator[None, None, None]:
    token = push_ollama_model_override(model)
    try:
        yield
    finally:
        reset_ollama_model_override(token)
