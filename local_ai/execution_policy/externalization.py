"""
Minimal v1 externalization: structured placeholder mapping for cloud calls only.

Scope:

- ``workspace_next_step`` + OpenAI: ``subject_id`` when present in the internal prompt.
- Compiled ``initiative_evaluate`` + OpenAI: ``initiative_id`` and/or account ``user_id`` when
  present verbatim in the synthesized prompt (narrow v1; no broad washing).
- Compiled ``core_profile_reconcile`` + OpenAI: **v1 no substitutions** (hook only); prompt does
  not yet embed stable server ids verbatim.
"""

from __future__ import annotations

import base64
import hashlib
import re
from dataclasses import dataclass, field
from typing import Any, FrozenSet, Literal, Mapping, Optional

ExternalizationStrategy = Literal["none", "structured_placeholder_mapping"]

WORKSPACE_NEXT_STEP_INTENT = "workspace_next_step"

INITIATIVE_EVALUATE_INTENT = "initiative_evaluate"

CORE_PROFILE_RECONCILE_INTENT = "core_profile_reconcile"

# [[ATRIA_REF:kind:BASE64URL_ID:ck8hex]]
_TOKEN_PATTERN = re.compile(
    r"\[\[ATRIA_REF:([a-z_]+):([A-Za-z0-9_-]+):([a-f0-9]{8})\]\]"
)


def _checksum(kind: str, internal_id: str) -> str:
    h = hashlib.sha256(f"atria.v1|{kind}|{internal_id}".encode("utf-8")).hexdigest()
    return h[:8]


def _b64url_encode(s: str) -> str:
    raw = s.encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64url_decode(payload: str) -> str | None:
    try:
        pad = "=" * ((4 - len(payload) % 4) % 4)
        # Avoid ``validate=`` — not supported on all Python builds; length/padding is enough for v1.
        return base64.urlsafe_b64decode(payload + pad).decode("utf-8")
    except Exception:
        return None


def make_placeholder_token(kind: str, internal_id: str) -> str:
    """Build a single deterministic placeholder token (includes type + encoded id + checksum)."""
    k = (kind or "").strip().lower()
    if not k or not internal_id:
        raise ValueError("kind and internal_id required")
    body = _b64url_encode(internal_id)
    ck = _checksum(k, internal_id)
    return f"[[ATRIA_REF:{k}:{body}:{ck}]]"


@dataclass(frozen=True)
class PlaceholderEntry:
    kind: str
    internal_value: str


@dataclass
class PlaceholderMap:
    """token string -> entry (what to substitute back)."""

    by_token: dict[str, PlaceholderEntry] = field(default_factory=dict)
    tokens_sent: FrozenSet[str] = field(default_factory=frozenset)

    def add(self, token: str, entry: PlaceholderEntry) -> None:
        self.by_token[token] = entry

    def freeze_sent(self) -> None:
        self.tokens_sent = frozenset(self.by_token.keys())


@dataclass(frozen=True)
class ExternalizeResult:
    external_prompt: str
    placeholder_map: PlaceholderMap
    strategy: ExternalizationStrategy


@dataclass(frozen=True)
class RebindResult:
    text: str
    integrity_ok: bool
    unresolved_tokens: tuple[str, ...]  # sent in prompt but absent from model output
    invalid_tokens_in_output: tuple[str, ...]  # malformed checksum / unknown token


def _validate_token_match(kind: str, payload_b64: str, ck: str) -> str | None:
    internal = _b64url_decode(payload_b64)
    if internal is None:
        return None
    if _checksum(kind, internal) != ck.lower():
        return None
    return internal


def apply_subject_id_mapping(internal_prompt: str, subject_id: str) -> tuple[str, PlaceholderMap]:
    """Replace every exact occurrence of ``subject_id`` with one placeholder token."""
    sid = (subject_id or "").strip()
    if not sid or sid not in internal_prompt:
        return internal_prompt, PlaceholderMap()
    token = make_placeholder_token("subject_id", sid)
    pm = PlaceholderMap()
    pm.add(token, PlaceholderEntry(kind="subject_id", internal_value=sid))
    external = internal_prompt.replace(sid, token)
    pm.freeze_sent()
    return external, pm


def apply_ordered_identifier_mappings(
    internal_prompt: str,
    specs: list[tuple[str, str]],
) -> tuple[str, PlaceholderMap]:
    """
    Replace exact substring occurrences with placeholder tokens.

    ``specs`` is ``(kind, internal_value)`` pairs. Longer values are applied first so a
    shorter id cannot split a longer one. Each kind/value pair maps to one token;
    rebind uses the same strict rules as ``rebind_after_cloud_response``.
    """
    # Longest internal strings first
    ordered = sorted(
        ((k, (v or "").strip()) for k, v in specs if (v or "").strip()),
        key=lambda t: len(t[1]),
        reverse=True,
    )
    if not ordered:
        return internal_prompt, PlaceholderMap()
    combined = PlaceholderMap()
    text = internal_prompt
    for kind, val in ordered:
        if val not in text:
            continue
        k = (kind or "").strip().lower()
        if not k:
            continue
        token = make_placeholder_token(k, val)
        combined.add(token, PlaceholderEntry(kind=k, internal_value=val))
        text = text.replace(val, token)
    if not combined.by_token:
        return internal_prompt, PlaceholderMap()
    combined.freeze_sent()
    return text, combined


def maybe_externalize_structured_initiative_evaluate_for_cloud(
    *,
    routing_context: Optional[Mapping[str, Any]],
    exec_meta: Mapping[str, Any],
    internal_prompt: str,
    initiative_id: Optional[str],
    user_id: Optional[str],
) -> ExternalizeResult:
    """
    Narrow v1: substitute **initiative_id** and/or **user_id** when they appear verbatim
    in the internal prompt, only for compiled initiative evaluate + OpenAI + routing.

    No-op when conditions fail or neither id appears in the prompt.
    """
    if not routing_context:
        return ExternalizeResult(internal_prompt, PlaceholderMap(), "none")
    intent = (routing_context.get("action_intent") or "").strip()
    if intent != INITIATIVE_EVALUATE_INTENT:
        return ExternalizeResult(internal_prompt, PlaceholderMap(), "none")
    prov = (exec_meta.get("provider_used") or "").strip().lower()
    if prov != "openai":
        return ExternalizeResult(internal_prompt, PlaceholderMap(), "none")
    iid = (initiative_id or "").strip()
    uid = (user_id or "").strip()
    specs: list[tuple[str, str]] = []
    if iid:
        specs.append(("initiative_id", iid))
    if uid:
        specs.append(("user_id", uid))
    ext, pm = apply_ordered_identifier_mappings(internal_prompt, specs)
    if not pm.by_token:
        return ExternalizeResult(internal_prompt, PlaceholderMap(), "none")
    return ExternalizeResult(ext, pm, "structured_placeholder_mapping")


def maybe_externalize_structured_core_profile_reconcile_for_cloud(
    *,
    routing_context: Optional[Mapping[str, Any]],
    exec_meta: Mapping[str, Any],
    internal_prompt: str,
    profile_id: Optional[str],
    user_id: Optional[str],
) -> ExternalizeResult:
    """
    Compiled ``core_profile_reconcile`` + OpenAI. **v1:** identity (no tokens).

    Reserved for future verbatim ``profile_id`` / ``user_id`` in the synthesis template,
    using the same ordered mapping + rebind pattern as initiative evaluate.
    """
    _ = (routing_context, exec_meta, profile_id, user_id)
    return ExternalizeResult(internal_prompt, PlaceholderMap(), "none")


def maybe_externalize_for_cloud(
    *,
    mode: str,
    routing_context: Optional[Mapping[str, Any]],
    exec_meta: Mapping[str, Any],
    internal_prompt: str,
    subject_id: Optional[str],
) -> ExternalizeResult:
    """
    No-op unless: ``mode`` is next_step, routing present, policy primary is OpenAI (cloud),
    intent is ``workspace_next_step``, and ``subject_id`` is non-empty and appears in prompt.

    ``provider_used`` may be ``ollama`` when ``anonymous_openai_fallback_ollama`` is set (same externalization rules).
    """
    if not routing_context:
        return ExternalizeResult(internal_prompt, PlaceholderMap(), "none")
    mode_l = (mode or "").strip().lower()
    if mode_l != "next_step":
        return ExternalizeResult(internal_prompt, PlaceholderMap(), "none")
    intent = (routing_context.get("action_intent") or "").strip()
    if intent != WORKSPACE_NEXT_STEP_INTENT:
        return ExternalizeResult(internal_prompt, PlaceholderMap(), "none")
    prov = (exec_meta.get("provider_used") or "").strip().lower()
    policy_p = (exec_meta.get("policy_primary_provider") or "").strip().lower()
    anon_ollama_fb = bool(exec_meta.get("anonymous_openai_fallback_ollama"))
    substrate_ok = prov == "openai" or (prov == "ollama" and anon_ollama_fb and policy_p == "openai")
    if not substrate_ok:
        return ExternalizeResult(internal_prompt, PlaceholderMap(), "none")
    sid = (subject_id or "").strip()
    if not sid:
        return ExternalizeResult(internal_prompt, PlaceholderMap(), "none")
    ext, pm = apply_subject_id_mapping(internal_prompt, sid)
    if not pm.by_token:
        return ExternalizeResult(internal_prompt, PlaceholderMap(), "none")
    return ExternalizeResult(ext, pm, "structured_placeholder_mapping")


def rebind_after_cloud_response(model_text: str, placeholder_map: PlaceholderMap) -> RebindResult:
    """
    Exact token match only. Unknown or checksum-invalid tokens → ``integrity_ok`` False.
    """
    text = model_text
    invalid: list[str] = []
    found_in_output: set[str] = set()

    def _repl(m: re.Match[str]) -> str:
        kind, payload_b64, ck = m.group(1), m.group(2), m.group(3)
        full = m.group(0)
        internal = _validate_token_match(kind, payload_b64, ck)
        if internal is None:
            invalid.append(full)
            return full
        entry = placeholder_map.by_token.get(full)
        if entry is None or entry.kind != kind or entry.internal_value != internal:
            invalid.append(full)
            return full
        found_in_output.add(full)
        return entry.internal_value

    rebound = _TOKEN_PATTERN.sub(_repl, text)
    missing = tuple(sorted(placeholder_map.tokens_sent - found_in_output))
    ok = len(invalid) == 0
    return RebindResult(
        text=rebound,
        integrity_ok=ok,
        unresolved_tokens=missing,
        invalid_tokens_in_output=tuple(invalid),
    )


def redact_externalization_for_privacy(
    *,
    privacy_mode: Optional[str],
    integrity_ok: bool,
    unresolved_tokens: tuple[str, ...],
    invalid_tokens: tuple[str, ...],
) -> dict[str, Any]:
    """
    Do not expose token strings in API / traces for restricted-like modes.
    """
    m = (privacy_mode or "").strip().lower()
    base: dict[str, Any] = {
        "externalization_integrity_ok": integrity_ok,
    }
    if m in ("restricted", "local_only"):
        base["externalization_unresolved_count"] = len(unresolved_tokens)
        base["externalization_invalid_count"] = len(invalid_tokens)
        return base
    base["externalization_unresolved_tokens"] = list(unresolved_tokens)
    base["externalization_invalid_tokens"] = list(invalid_tokens)
    return base
