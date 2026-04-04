"""Shared strict rebind helpers for compiled delegation."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from local_ai.delegation.externalized_inference import (
    INTEGRITY_FAILURE_MESSAGE,
    StrictRebindIntegrityFailure,
    StrictRebindOk,
    mapping_active_for_externalize,
    redact_when_mapping_ok,
    strict_rebind_cloud_output,
)
from local_ai.execution_policy.externalization import (
    ExternalizeResult,
    PlaceholderEntry,
    PlaceholderMap,
    make_placeholder_token,
)


def test_mapping_active_false_when_strategy_none():
    ex = ExternalizeResult("prompt", PlaceholderMap(), "none")
    assert mapping_active_for_externalize(ex) is False


def test_strict_rebind_ok_when_no_mapping():
    ex = ExternalizeResult("internal", PlaceholderMap(), "none")
    out = strict_rebind_cloud_output("plain json {}", ex, privacy_mode="normal")
    assert isinstance(out, StrictRebindOk)
    assert out.text == "plain json {}"
    assert out.mapping_active is False


def test_strict_rebind_fails_when_token_missing():
    sid = "subj-uuid-aa"
    tok = make_placeholder_token("subject_id", sid)
    pm = PlaceholderMap()
    pm.add(tok, PlaceholderEntry(kind="subject_id", internal_value=sid))
    pm.freeze_sent()
    ex = ExternalizeResult(f"x {tok} y", pm, "structured_placeholder_mapping")
    out = strict_rebind_cloud_output('{"a":1}', ex, privacy_mode="normal")
    assert isinstance(out, StrictRebindIntegrityFailure)
    assert out.redaction_extras.get("externalization_integrity_ok") is False


def test_integrity_message_constant_stable():
    assert "placeholder" in INTEGRITY_FAILURE_MESSAGE.lower()


def test_redact_when_mapping_ok_empty_without_mapping():
    assert redact_when_mapping_ok(privacy_mode="normal", mapping_active=False) == {}
