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

from dataclasses import dataclass
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

    def generate_with_usage(self, prompt: str, *,
                            timeout: int = 120) -> tuple[str, dict | None]:
        """Parallel to generate(): (text, provider usage dict or None).

        generate() is untouched and still returns text only.
        """
        return _openai.generate_with_usage(
            self._api_key, prompt, model=self.model, timeout=timeout)


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


# ---------------------------------------------------------------------------
# R2: one participant per provider (approved design §6).
#
# Model-family names are identifiers, not roles (approval record): they
# carry explicit provider/model metadata and assert nothing about what
# any participant should do in the room. No casting labels appear here,
# in prompts, or in tests — not even labeled provisional.
# ---------------------------------------------------------------------------

from local_ai.providers import (  # noqa: E402
    anthropic as _anthropic,
)
from local_ai.providers import google_genai as _google  # noqa: E402
from local_ai.providers import meta as _meta  # noqa: E402
from local_ai.providers import xai as _xai  # noqa: E402

# Stable convene order for R2 meetings. This order is also the
# deterministic registration order (design §4): phase results are
# registered in this order, never in completion order.
SEAT_SPECS: tuple[tuple[str, str, str], ...] = (
    ("GPT", "openai", "gpt-4o-mini"),
    ("Claude", "anthropic", "claude-haiku-4-5"),
    ("Gemini", "google", "gemini-3.8-flash"),
    ("Grok", "xai", "grok-4-1-fast-reasoning"),
    ("Muse", "meta", "muse-spark-1.3"),
)

# GPT performs the synthesis function FOR THE ACCEPTANCE TEST ONLY
# (design §5). This is a test parameter, not a role ruling, not an
# identity, and not a permanent assignment.
SYNTHESIZER_NAME = "GPT"

_PROVIDER_GENERATE = {
    "openai": _openai.generate,
    "anthropic": _anthropic.generate,
    "google": _google.generate,
    "xai": _xai.generate,
    "meta": _meta.generate,
}


class SeatParticipant:
    """One R2 seat: a model-family name over one provider module.

    Same key discipline as OpenAIParticipant: the key value lives
    only on the instance (``repr`` excluded) and is passed solely to
    the provider call.
    """

    def __init__(self, name: str, provider_id: str, api_key: str,
                 model: str | None = None, key_source: str = "unknown"):
        self.name = name
        self.provider_id = provider_id
        self._api_key = api_key
        self.model = (model or "").strip() or name
        self.key_source = key_source

    def __repr__(self) -> str:  # never include the key value
        return (
            f"SeatParticipant(name={self.name!r}, provider_id={self.provider_id!r}, "
            f"model={self.model!r}, key_source={self.key_source!r})"
        )

    def generate(self, prompt: str, *, timeout: int = 120) -> str:
        fn = _PROVIDER_GENERATE[self.provider_id]
        return fn(self._api_key, prompt, model=self.model, timeout=timeout)

    def __getattr__(self, name: str):
        # Usage capture exists ONLY for the openai seat in v1: other
        # providers have no usage path, so the attribute genuinely
        # does not exist for them — measurement's hasattr check then
        # falls back to a single generate() call (estimated cost),
        # never a second generation. (A class-level method raising
        # AttributeError would instead be misread as a generation
        # failure by the measurement wrapper.)
        if name == "generate_with_usage" and self.provider_id == "openai":
            def _with_usage(prompt: str, *, timeout: int = 120):
                return _openai.generate_with_usage(
                    self._api_key, prompt, model=self.model, timeout=timeout)
            return _with_usage
        raise AttributeError(name)


@dataclass(frozen=True)
class Seat:
    """One resolved seat for a meeting: participant or visible absence.

    ``participant`` is None exactly when the key could not be
    resolved; ``absence_note`` then says why. The runner records the
    absence in the transcript — never a silent drop.
    """

    name: str
    provider_id: str
    model: str
    participant: Any | None
    absence_note: str = ""


def resolve_seat_participant(
    principal: ExecutionPrincipal | None,
    name: str,
    provider_id: str,
    model: str,
) -> Seat:
    """Resolve one seat, mirroring resolve_openai_participant exactly."""
    principal = principal or system_principal()
    key, src = resolve_cloud_api_key(principal, provider_id)
    if not key or not key.strip():
        if str(src) == "undecryptable":
            return Seat(
                name=name, provider_id=provider_id, model=model,
                participant=None,
                absence_note=(
                    f"present but undecryptable: a saved {provider_id} key exists "
                    "for this principal but cannot be decrypted with the current "
                    "settings key (re-save the key in Settings)"
                ),
            )
        return Seat(
            name=name, provider_id=provider_id, model=model,
            participant=None,
            absence_note=f"absent: no {provider_id} api key present for this principal",
        )
    return Seat(
        name=name, provider_id=provider_id, model=model,
        participant=SeatParticipant(
            name, provider_id, key.strip(), model=model, key_source=str(src)
        ),
    )


def resolve_seat_participants(
    principal: ExecutionPrincipal | None = None,
) -> list[Seat]:
    """Resolve all five seats in stable SEAT_SPECS order."""
    principal = principal or system_principal()
    return [
        resolve_seat_participant(principal, name, provider_id, model)
        for name, provider_id, model in SEAT_SPECS
    ]
