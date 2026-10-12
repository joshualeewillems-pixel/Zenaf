"""Presence ingestion pipeline tests: adapters, redaction, distill, store, service.

All fixtures are tiny synthetic exports written inline — no real user data.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from local_ai.presence_ingest import redact as redact_mod
from local_ai.presence_ingest.adapters.chatgpt import ChatGPTAdapter
from local_ai.presence_ingest.adapters.claude import ClaudeAdapter
from local_ai.presence_ingest.adapters.registry import detect_source, get_adapter
from local_ai.presence_ingest.adapters.x_archive import XArchiveAdapter
from local_ai.presence_ingest.distill import DistillError, distill_events
from local_ai.presence_ingest.schema import PresenceEvent
from local_ai.presence_ingest.service import (
    delete_session,
    review,
    run_distill,
    start_import,
)
from local_ai.presence_ingest.store import PresenceStore


# ---------------------------------------------------------------- fixtures


def _write_chatgpt_export(path: Path) -> Path:
    """Synthetic ChatGPT conversations.json with one malformed node."""
    data = [
        {
            "id": "conv-1",
            "title": "Career move",
            "mapping": {
                "n1": {
                    "message": {
                        "author": {"role": "user"},
                        "content": {
                            "parts": [
                                "Should I take the startup offer? "
                                "Email me at jane.doe@example.com or "
                                "call 415-555-0132 to discuss."
                            ]
                        },
                        "create_time": 1720000000.0,
                    }
                },
                "n2": {
                    "message": {
                        "author": {"role": "assistant"},
                        "content": {"parts": ["Let's weigh the tradeoffs..."]},
                        "create_time": 1720000060.0,
                    }
                },
                "n3": {"message": None},  # malformed node -> skipped
                "n4": {
                    "message": {
                        "author": {"role": "user"},
                        "content": {"parts": ["I decided to take it."]},
                        "create_time": 1720000120.0,
                    }
                },
            },
        }
    ]
    p = path / "conversations.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    return p


def _write_claude_export(path: Path) -> Path:
    data = [
        {
            "uuid": "c-conv-1",
            "name": "Writing help",
            "chat_messages": [
                {
                    "sender": "human",
                    "text": "Help me draft a resignation letter.",
                    "created_at": "2024-06-01T10:00:00Z",
                },
                {
                    "sender": "assistant",
                    "text": "Of course, here's a draft...",
                    "created_at": "2024-06-01T10:00:30Z",
                },
                {"sender": "human", "text": "", "created_at": "2024-06-01T10:01:00Z"},
            ],
        }
    ]
    p = path / "claude_conversations.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    return p


def _write_x_archive(path: Path) -> Path:
    payload = [
        {
            "tweet": {
                "id_str": "12345",
                "full_text": "Shipping my side project today! Contact: me@example.org",
                "created_at": "Wed Jun 12 20:19:24 +0000 2024",
            }
        },
        {"tweet": {"id_str": "12346", "full_text": "", "created_at": ""}},
    ]
    p = path / "tweets.js"
    p.write_text(
        "window.YTD.tweets.part0 = " + json.dumps(payload), encoding="utf-8"
    )
    return p


def _stub_complete_factory():
    def stub(prompt: str) -> str:
        assert "Excerpts" in prompt
        return json.dumps(
            [
                {
                    "layer": "decision",
                    "zone": "career",
                    "valence": "endorsed",
                    "summary": "User commits quickly once tradeoffs are clear.",
                    "detail": "Decided to take the startup offer after weighing options.",
                },
                {
                    "layer": "behavior",
                    "zone": "general",
                    "valence": "observed",
                    "summary": "User asks direct, action-oriented questions.",
                    "detail": "Messages are short and decision-seeking.",
                },
                {"layer": "bogus", "summary": "should be dropped"},
            ]
        )

    return stub


# ---------------------------------------------------------------- redaction


def test_redact_replaces_pii():
    out = redact_mod.redact_text(
        "mail jane.doe@example.com, call 415-555-0132, ssn 123-45-6789, "
        "acct 9876543, year 2026"
    )
    assert "jane.doe@example.com" not in out
    assert "415-555-0132" not in out
    assert "123-45-6789" not in out
    assert "9876543" not in out
    assert "[EMAIL]" in out and "[PHONE]" in out
    assert "[ID]" in out and "[NUMBER]" in out
    assert "2026" in out  # short runs untouched


def test_redact_empty():
    assert redact_mod.redact_text("") == ""
    assert redact_mod.redact_text(None) == ""


# ---------------------------------------------------------------- adapters


def test_chatgpt_adapter_parse(tmp_path):
    p = _write_chatgpt_export(tmp_path)
    adapter = ChatGPTAdapter()
    events = list(adapter.iter_events(p))
    assert len(events) == 3  # 2 user + 1 assistant; malformed node skipped
    assert adapter.last_skipped == 1
    user_msgs = [e for e in events if e.actor == "user"]
    assert len(user_msgs) == 2
    # redaction applied at capture
    assert "jane.doe@example.com" not in user_msgs[0].text
    assert "[EMAIL]" in user_msgs[0].text
    assert "[PHONE]" in user_msgs[0].text
    assert events[0].context["conversation_title"] == "Career move"
    assert events[0].provenance["adapter"] == "chatgpt"


def test_claude_adapter_parse(tmp_path):
    p = _write_claude_export(tmp_path)
    adapter = ClaudeAdapter()
    events = list(adapter.iter_events(p))
    assert len(events) == 2  # empty-text message skipped
    assert adapter.last_skipped == 1
    assert events[0].actor == "user"
    assert events[1].actor == "assistant"
    assert events[0].ts is not None and events[0].ts.year == 2024


def test_claude_adapter_tolerates_variant_key(tmp_path):
    data = [
        {
            "name": "v",
            "conversation_messages": [
                {"sender": "human", "text": "hi", "created_at": "2024-01-01T00:00:00Z"}
            ],
        }
    ]
    p = tmp_path / "c.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    events = list(ClaudeAdapter().iter_events(p))
    assert len(events) == 1


def test_x_archive_adapter_parse(tmp_path):
    p = _write_x_archive(tmp_path)
    adapter = XArchiveAdapter()
    events = list(adapter.iter_events(p))
    assert len(events) == 1  # empty tweet skipped
    assert events[0].actor == "user"
    assert events[0].kind == "post"
    assert "me@example.org" not in events[0].text
    assert "[EMAIL]" in events[0].text
    assert events[0].ts is not None and events[0].ts.year == 2024


def test_registry_detect(tmp_path):
    chatgpt_p = _write_chatgpt_export(tmp_path)
    claude_p = _write_claude_export(tmp_path)
    x_p = _write_x_archive(tmp_path)
    other = tmp_path / "notes.txt"
    other.write_text("hello", encoding="utf-8")

    assert detect_source(chatgpt_p).source_id == "chatgpt"
    assert detect_source(claude_p).source_id == "claude"
    assert detect_source(x_p).source_id == "x"
    assert detect_source(other) is None

    assert get_adapter("chatgpt").display_name == "ChatGPT"
    assert get_adapter("nope") is None


def test_adapter_never_crashes_on_garbage(tmp_path):
    p = tmp_path / "broken.json"
    p.write_text("{not json", encoding="utf-8")
    for adapter in (ChatGPTAdapter(), ClaudeAdapter(), XArchiveAdapter()):
        assert adapter.detect(p) is False
        assert list(adapter.iter_events(p)) == []


# ---------------------------------------------------------------- distill


def test_distill_with_stub_produces_pending_candidates():
    events = [
        PresenceEvent(
            event_id="e1",
            source="chatgpt",
            actor="user",
            kind="message",
            text="I decided to take the startup offer.",
            context={"conversation_title": "Career move"},
            provenance={"adapter": "chatgpt"},
        ),
        PresenceEvent(
            event_id="e2",
            source="chatgpt",
            actor="assistant",
            kind="message",
            text="Great, let's plan the transition.",
            context={"conversation_title": "Career move"},
            provenance={"adapter": "chatgpt"},
        ),
    ]
    signals = distill_events(
        events,
        complete_fn=_stub_complete_factory(),
        zone_hint="career",
        session_id="imp-test",
    )
    # third extraction has a bogus layer -> dropped
    assert len(signals) == 2
    for s in signals:
        assert s.status == "pending"
        assert s.session_id == "imp-test"
        assert s.layer in ("decision", "behavior", "guidance")
        assert s.valence in ("endorsed", "rejected", "corrected", "observed")
        assert s.summary
        assert s.provenance["sources"] == ["chatgpt"]
        assert "e1" in s.context_ref["source_events"]
    assert signals[0].zone == "career"


def test_distill_empty_events_no_llm_call():
    def boom(prompt: str) -> str:
        raise AssertionError("should not be called")

    assert distill_events([], complete_fn=boom) == []


def test_distill_propagates_llm_failure():
    def fail(prompt: str) -> str:
        raise DistillError("ollama down")

    events = [
        PresenceEvent(
            event_id="e1",
            source="x",
            actor="user",
            kind="post",
            text="hello",
        )
    ]
    with pytest.raises(DistillError):
        distill_events(events, complete_fn=fail)


def test_distill_garbage_llm_output_yields_nothing():
    events = [
        PresenceEvent(
            event_id="e1", source="x", actor="user", kind="post", text="hello"
        )
    ]
    assert distill_events(events, complete_fn=lambda p: "not json at all") == []


# ---------------------------------------------------------------- store


def test_store_round_trip(tmp_path):
    store = PresenceStore(db_path=tmp_path / "sig.db")
    try:
        from local_ai.presence_ingest.schema import ImportSession, TrainingSignal

        session = ImportSession(
            session_id="imp-1", source="chatgpt", file_name="c.json"
        )
        store.create_session(session)
        assert store.get_session("imp-1").source == "chatgpt"
        assert len(store.list_sessions()) == 1

        event = PresenceEvent(
            event_id="e1",
            source="chatgpt",
            actor="user",
            kind="message",
            text="redacted text",
        )
        assert store.save_events("imp-1", [event]) == 1
        assert store.count_events("imp-1") == 1

        sig = TrainingSignal(
            signal_id="sig-1",
            ts_ms=1,
            layer="decision",
            zone="career",
            actor="user",
            summary="s",
            valence="observed",
            session_id="imp-1",
        )
        store.save_candidate_signals([sig])
        assert len(store.list_candidates("imp-1")) == 1
        assert store.list_signals(status="approved") == []

        assert store.review_signals(["sig-1"], approve=True) == 1
        approved = store.list_signals(status="approved")
        assert len(approved) == 1 and approved[0].signal_id == "sig-1"
        assert store.list_candidates("imp-1") == []

        # re-review of an already-reviewed signal is a no-op
        assert store.review_signals(["sig-1"], approve=False) == 0

        sig2 = TrainingSignal(
            signal_id="sig-2",
            ts_ms=2,
            layer="behavior",
            zone="career",
            actor="user",
            summary="s2",
            valence="observed",
            session_id="imp-1",
        )
        store.save_candidate_signals([sig2])
        assert store.review_signals(["sig-2"], approve=False) == 1
        rejected = store.list_signals(status="rejected")
        assert len(rejected) == 1  # kept as audit trail, not deleted
        assert store.list_signals(zone="career", status="approved")[0].signal_id == "sig-1"
    finally:
        store.close()


# ---------------------------------------------------------------- service


def _service_env(tmp_path):
    db = tmp_path / "sig.db"
    uploads = tmp_path / "uploads"
    return PresenceStore(db_path=db), uploads


def test_service_full_flow(tmp_path, monkeypatch):
    monkeypatch.setenv("ZENAF_DATA_DIR", str(tmp_path / "zenaf-data"))
    from local_ai.identity import service as ident
    from local_ai.identity.store import IdentityStore

    ident.issue_license(store=IdentityStore())
    ident.grant_scope("train:self")
    store, uploads = _service_env(tmp_path)
    try:
        src = _write_chatgpt_export(tmp_path)
        session = start_import(src, "conversations.json", store=store, upload_root=uploads)
        assert session.source == "chatgpt"
        assert session.status == "parsed"
        assert session.counts["events"] == 3
        assert session.counts["skipped"] == 1
        upload_dir = uploads / session.session_id
        assert (upload_dir / "conversations.json").exists()

        n = run_distill(
            session.session_id,
            complete_fn=_stub_complete_factory(),
            store=store,
        )
        assert n == 2
        candidates = store.list_candidates(session.session_id)
        assert len(candidates) == 2

        result = review(
            session.session_id,
            {candidates[0].signal_id: True, candidates[1].signal_id: False},
            store=store,
        )
        assert result == {"approved": 1, "rejected": 1}
        assert len(store.list_signals(status="approved")) == 1

        delete_session(session.session_id, store=store, upload_root=uploads)
        # raw upload + events gone...
        assert not upload_dir.exists()
        assert store.count_events(session.session_id) == 0
        # ...but the approved signal persists as training data
        assert len(store.list_signals(status="approved")) == 1
        assert store.get_session(session.session_id).status == "deleted"
    finally:
        store.close()


def test_service_rejects_unknown_format(tmp_path, monkeypatch):
    monkeypatch.setenv("ZENAF_DATA_DIR", str(tmp_path / "zenaf-data"))
    from local_ai.identity import service as ident
    from local_ai.identity.store import IdentityStore
    from local_ai.presence_ingest.service import PresenceIngestError

    ident.issue_license(store=IdentityStore())

    store, uploads = _service_env(tmp_path)
    try:
        p = tmp_path / "notes.txt"
        p.write_text("hello", encoding="utf-8")
        with pytest.raises(PresenceIngestError):
            start_import(p, "notes.txt", store=store, upload_root=uploads)
    finally:
        store.close()
