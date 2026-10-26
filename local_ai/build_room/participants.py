"""Build-room participants, R1: GPT via the openai provider module.

Follows the council_seat_provider shim pattern (a small wrapper holding
an api key + model and exposing ``generate(prompt, timeout=...)``) —
NOT the intake path (``agent_intake/llm_keys.py::generate``), which does
not wire every provider and is the wrong pattern here.

Key handling: the key value lives only on the participant instance
(``repr`` excluded) and is passed solely to the provider call. Nothing
in this module formats, logs, or returns the key value.
"""

from __future__ import annotations

from typing import Any

from local_ai.llm.credentials import resolve_cloud_api_key
from local_ai.llm.execution_principal import ExecutionPrincipal, system_principal
from local_ai.providers import openai as _openai


class OpenAIParticipant:
    """GPT via the openai provider module."""

    name = "GPT"
    provider_id = "openai"

    def __init__(self, api_key: str, model: str | None = None, key_source: str = "unknown"):
        self._api_key = api_key
        self.model = (model or "").strip() or "gpt-4o-mini"
        self.key_source = key_source

    def __repr__(self) -> str:  # never include the key value
        return f"OpenAIParticipant(name={self.name!r}, model={self.model!r}, key_source={self.key_source!r})"

    def generate(self, prompt: str, *, timeout: int = 120) -> str:
        return _openai.generate(self._api_key, prompt, model=self.model, timeout=timeout)


def check_openai_key_present(principal: ExecutionPrincipal | None = None) -> tuple[bool, str]:
    """Presence check only. Returns (present, source-label); the value is discarded."""
    principal = principal or system_principal()
    key, src = resolve_cloud_api_key(principal, "openai")
    return (bool(key and key.strip()), str(src) if key else "none")


def resolve_openai_participant(
    principal: ExecutionPrincipal | None = None,
    model: str | None = None,
) -> tuple[OpenAIParticipant | None, str]:
    """Resolve the R1 participant, or (None, absence-note) when no key is present.

    Absence is a visible outcome, not a silent drop: the caller records it
    in the transcript.
    """
    principal = principal or system_principal()
    key, src = resolve_cloud_api_key(principal, "openai")
    if not key or not key.strip():
        if str(src) == "undecryptable":
            return (
                None,
                "present but undecryptable: a saved openai key exists for this principal "
                "but cannot be decrypted with the current settings key (re-save the key in Settings)",
            )
        return None, "absent: no openai api key present for this principal"
    return OpenAIParticipant(key.strip(), model=model, key_source=str(src)), ""
