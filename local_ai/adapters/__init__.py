"""
Zenaf adapter layer: thin connectors to external systems.

Adapters only authenticate, fetch/send, and normalize. Core owns all decision logic.
Use the registry to resolve adapters by kind + name so core and API stay decoupled from concrete implementations.
"""
from __future__ import annotations

from typing import Any, Protocol

# -----------------------------------------------------------------------------
# Registry: kind -> name -> adapter instance
# -----------------------------------------------------------------------------
_ADAPTER_REGISTRY: dict[str, dict[str, Any]] = {}


def register_adapter(kind: str, name: str, adapter: Any) -> None:
    """Register an adapter under kind and name (e.g. kind='llm', name='ollama')."""
    if kind not in _ADAPTER_REGISTRY:
        _ADAPTER_REGISTRY[kind] = {}
    _ADAPTER_REGISTRY[kind][name] = adapter


def get_adapter(kind: str, name: str) -> Any:
    """Return the adapter for kind+name. Raises KeyError if not registered."""
    if kind not in _ADAPTER_REGISTRY or name not in _ADAPTER_REGISTRY[kind]:
        raise KeyError(f"Adapter not registered: {kind}.{name}")
    return _ADAPTER_REGISTRY[kind][name]


def get_adapter_optional(kind: str, name: str) -> Any | None:
    """Return the adapter for kind+name, or None if not registered."""
    try:
        return get_adapter(kind, name)
    except KeyError:
        return None


def list_adapters(kind: str | None = None) -> dict[str, list[str]]:
    """Return registered adapters. If kind is None, return all; else {kind: [name, ...]}."""
    if kind is not None:
        return {kind: list(_ADAPTER_REGISTRY.get(kind, {}).keys())}
    return {k: list(v.keys()) for k, v in _ADAPTER_REGISTRY.items()}


# -----------------------------------------------------------------------------
# Protocols (contract for adapter implementations)
# -----------------------------------------------------------------------------


class LLMAdapter(Protocol):
    """LLM provider: generate text from a prompt. No orchestration logic."""

    def generate(self, prompt: str, *, timeout: int | None = None, **kwargs: Any) -> str:
        ...


class MailboxAdapter(Protocol):
    """Mailbox: fetch (and optionally send) messages. Returns normalized message-like dicts.
    Core intake pipeline consumes these and produces IntakeItem; adapter does not run pipeline."""

    def fetch_messages(self, *, limit: int = 50) -> list[dict[str, Any]]:
        """Fetch recent/unread messages. Each dict: subject, body_plain, external_id, source_label, etc."""
        ...


# -----------------------------------------------------------------------------
# Default registrations (current implementations; no refactor of callers yet)
# -----------------------------------------------------------------------------
def _register_defaults() -> None:
    """Register default adapters so get_adapter('llm','ollama') works."""
    from local_ai.providers.ollama import OllamaProvider
    register_adapter("llm", "ollama", OllamaProvider())


_register_defaults()

__all__ = [
    "register_adapter",
    "get_adapter",
    "get_adapter_optional",
    "list_adapters",
    "LLMAdapter",
    "MailboxAdapter",
]
