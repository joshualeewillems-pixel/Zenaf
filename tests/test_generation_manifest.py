"""Generation-manifest tests (Training-Readiness Plan Q4.1).

The manifest is the per-turn fingerprint record of one generation:
provider, effective model, prompt sha256 + length, assembly stamp,
profile version, shaping flags, thread-summary hash, and — where a
selection-aware steward/pencil provider served the turn — the
source thread/reading ids. Founder ruling 2026-11-22: FINGERPRINT
ONLY. These tests prove the manifest is complete on the stored
assistant message, and that no prompt text is stored anywhere in
it. The LLM is faked everywhere; no real provider calls.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from types import SimpleNamespace

import local_ai.conversation.reply as reply_mod
from local_ai.conversation.service import ConversationService
from local_ai.conversation.store import ConversationStore
from local_ai.narrative.context import PreparedContext


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class _Capture:
    """A generate_fn that records the exact prompt it was handed."""

    def __init__(self, reply: str = "Fake reply."):
        self.reply = reply
        self.prompts: list[str] = []

    def __call__(self, prompt: str, **kwargs) -> str:
        self.prompts.append(prompt)
        return self.reply


def _svc(tmp_path, generate_fn, **svc_kwargs):
    store = ConversationStore(db_path=tmp_path / "conv.db")
    return ConversationService(store, generate_fn=generate_fn, **svc_kwargs), store


def _assistant(store, user="u1", conversation="skeleton"):
    hist = store.history(user, conversation)
    voices = [m for m in hist if m["role"] == "voice"]
    assert voices, "expected a persisted voice message"
    return voices[-1]


def _raw_context_json(db_path, role="voice"):
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(
            "SELECT context_json FROM messages WHERE role = ? ORDER BY created_at",
            (role,),
        ).fetchall()
    finally:
        conn.close()
    assert rows, f"expected a {role} row"
    return rows[-1][0]


# -- the manifest on the stored assistant message -----------------------------


def test_turn_persists_complete_manifest(tmp_path):
    cap = _Capture()
    svc, store = _svc(tmp_path, cap)
    result = svc.turn("u1", "mentor", "I need to plan my week")

    manifest = _assistant(store)["context"]["generation_manifest"]
    assert manifest["version"] == reply_mod.GENERATION_MANIFEST_VERSION
    assert manifest["assembly_version"] == reply_mod.PROMPT_ASSEMBLY_VERSION
    assert manifest["provider"] == "meta"
    from local_ai.providers.meta import _effective_model

    assert manifest["model"] == _effective_model(None)
    # The fingerprint is of the exact prompt the provider call carried.
    assert len(cap.prompts) == 1
    assert manifest["prompt_sha256"] == _sha(cap.prompts[0])
    assert manifest["prompt_chars"] == len(cap.prompts[0])
    # Assembly facts agree with the reply the turn produced.
    assert manifest["mode_used"] == result.reply.mode_used
    assert manifest["has_training"] == result.reply.has_training
    if not result.reply.has_training:
        assert manifest["profile_version"] is None
    assert manifest["thread_summary_sha256"] is None
    assert manifest["flags"] == {
        "canonical": True,
        "canonical_tier": False,
        "rhyme_carriage": False,
        "sketch_shaping": False,
    }
    assert "sources" not in manifest
    # The user message carries no manifest — it records generation,
    # and the user turn generated nothing.
    user_msg = store.history("u1", "skeleton")[0]
    assert user_msg["role"] == "user"
    assert "generation_manifest" not in user_msg["context"]
    store.close()


def test_manifest_stores_no_prompt_text(tmp_path):
    cap = _Capture()
    svc, store = _svc(tmp_path, cap)
    svc.turn("u1", "mentor", "A quiet word about kestrels")

    raw = _raw_context_json(tmp_path / "conv.db")
    prompt = cap.prompts[0]
    assert "A quiet word about kestrels" in prompt  # capture sanity
    # The assembled prompt itself is nowhere in the stored record.
    assert prompt not in raw
    # Prompt-only scaffolding (never client data, never reply text)
    # must not leak into the record either.
    assert "Keep replies conversational (2-5 sentences)." not in raw
    # Every string in the manifest is metadata or a hash — nothing
    # long enough to be prompt content, nothing equal to a prompt
    # fragment.
    manifest = json.loads(raw)["generation_manifest"]

    def _strings(value):
        if isinstance(value, str):
            yield value
        elif isinstance(value, dict):
            for v in value.values():
                yield from _strings(v)
        elif isinstance(value, list):
            for v in value:
                yield from _strings(v)

    for s in _strings(manifest):
        assert s not in prompt or len(s) < 24
    store.close()


def test_thread_summary_hash_recorded(tmp_path):
    cap = _Capture()
    svc, store = _svc(tmp_path, cap)
    summary = "A distinctive summary about kestrels and rest."
    store.update_thread_state(
        "u1", "skeleton", "mentor", summary=summary, reset_counter=True
    )
    svc.turn("u1", "mentor", "Following up on that")

    manifest = _assistant(store)["context"]["generation_manifest"]
    assert manifest["thread_summary_sha256"] == _sha(summary)
    # The hash identifies the summary; the summary text itself is
    # not duplicated into the message record.
    assert summary not in _raw_context_json(tmp_path / "conv.db")
    store.close()


def test_profile_version_recorded(tmp_path, monkeypatch):
    import local_ai.personality.blend as blend_mod
    import local_ai.personality.store as pstore_mod

    class FakeStore:
        def __init__(self, *a, **k):
            pass

        def get_current(self):
            return SimpleNamespace(version=7)

        def list_versions(self):
            return [{"version": i} for i in range(1, 8)]

        def close(self):
            pass

    monkeypatch.setattr(pstore_mod, "PersonalityStore", FakeStore)
    monkeypatch.setattr(
        blend_mod, "render_user_section", lambda p, k, w, vc: "rendered section"
    )
    cap = _Capture()
    svc, store = _svc(tmp_path, cap)
    result = svc.turn("u1", "mentor", "Plan my week with my patterns")

    assert result.reply.has_training is True
    assert result.reply.mode_used == "trained"
    manifest = _assistant(store)["context"]["generation_manifest"]
    assert manifest["profile_version"] == 7
    assert manifest["has_training"] is True
    assert manifest["mode_used"] == "trained"
    store.close()


# -- source ids from selection-aware providers --------------------------------


def test_steward_sources_recorded(tmp_path):
    prepared = PreparedContext(
        available=True,
        reason="available",
        block="Steward block about the kestrel thread.",
        threads=(
            {
                "thread_id": "thr-aaa",
                "title": "Kestrels",
                "status": "active",
                "scope": "",
                "evidence_count": 2,
            },
        ),
    )
    cap = _Capture()
    svc, store = _svc(
        tmp_path, cap, steward_context_provider=lambda u, m, h=None: prepared
    )
    svc.turn("u1", "conductor", "What threads are live?")

    assert "Steward block about the kestrel thread." in cap.prompts[0]
    manifest = _assistant(store)["context"]["generation_manifest"]
    assert manifest["sources"] == {"steward_thread_ids": ["thr-aaa"]}
    store.close()


def test_pencil_sources_recorded(tmp_path):
    prepared = PreparedContext(
        available=True,
        reason="available",
        block="Pencil block about the kestrel pattern.",
        threads=(
            {"thread_id": "thr-bbb", "reading_id": "rdg-bbb", "title": "Kestrels"},
        ),
    )
    cap = _Capture()
    svc, store = _svc(
        tmp_path, cap, pencil_context_provider=lambda u, m, h=None: prepared
    )
    svc.turn("u1", "maverick", "Paint me something sideways")

    assert "Pencil block about the kestrel pattern." in cap.prompts[0]
    manifest = _assistant(store)["context"]["generation_manifest"]
    assert manifest["sources"] == {
        "pencil_thread_ids": ["thr-bbb"],
        "pencil_reading_ids": ["rdg-bbb"],
    }
    store.close()


def test_string_provider_records_no_sources(tmp_path):
    cap = _Capture()
    svc, store = _svc(
        tmp_path,
        cap,
        steward_context_provider=lambda u, m, h=None: "Legacy string block.",
    )
    svc.turn("u1", "conductor", "What threads are live?")

    assert "Legacy string block." in cap.prompts[0]
    manifest = _assistant(store)["context"]["generation_manifest"]
    assert "sources" not in manifest
    store.close()


# -- shaping flags --------------------------------------------------------------


def test_sketch_shaping_flag_recorded(tmp_path, monkeypatch):
    cap = _Capture()
    svc, store = _svc(tmp_path, cap)
    svc.turn("u1", "skeptic", "Examine this claim")
    manifest = _assistant(store)["context"]["generation_manifest"]
    assert manifest["flags"]["sketch_shaping"] is False

    monkeypatch.setenv("ZENAF_SKETCH_SHAPING", "1")
    cap2 = _Capture()
    (tmp_path / "on").mkdir()
    svc2, store2 = _svc(tmp_path / "on", cap2)
    svc2.turn("u1", "skeptic", "Examine this claim")
    manifest2 = _assistant(store2)["context"]["generation_manifest"]
    assert manifest2["flags"]["sketch_shaping"] is True
    # The shaping instruction block really rode that turn's prompt.
    assert "[[sketch]]" in cap2.prompts[0]
    store.close()
    store2.close()


def test_rhyme_carriage_flag_recorded(tmp_path, monkeypatch):
    monkeypatch.setenv("ZENAF_FOX_RHYME_OFFER", "1")
    cap = _Capture()
    svc, store = _svc(tmp_path, cap)
    svc.turn("u1", "maverick", "Tell me something sideways")
    manifest = _assistant(store)["context"]["generation_manifest"]
    assert manifest["flags"]["rhyme_carriage"] is True
    store.close()


# -- seam discipline ------------------------------------------------------------


def test_client_supplied_manifest_key_is_overwritten(tmp_path):
    cap = _Capture()
    svc, store = _svc(tmp_path, cap)
    svc.turn(
        "u1",
        "mentor",
        "Hello",
        context={"generation_manifest": {"bogus": True}},
    )
    manifest = _assistant(store)["context"]["generation_manifest"]
    assert manifest["provider"] == "meta"
    assert "bogus" not in manifest
    store.close()


def test_manifest_failure_never_breaks_turn(tmp_path, monkeypatch):
    def _boom(**kwargs):
        raise RuntimeError("manifest boom")

    monkeypatch.setattr(reply_mod, "build_generation_manifest", _boom)
    cap = _Capture()
    svc, store = _svc(tmp_path, cap)
    result = svc.turn("u1", "mentor", "Hello anyway")
    assert result.reply.reply == "Fake reply."
    assert "generation_manifest" not in _assistant(store)["context"]
    store.close()


def test_generate_voice_reply_carries_manifest():
    cap = _Capture()
    reply = reply_mod.generate_voice_reply(
        "u1", "maverick", "hi", [], generate_fn=cap, canonical_tier=True
    )
    manifest = reply.generation_manifest
    assert manifest is not None
    assert manifest["prompt_sha256"] == _sha(cap.prompts[0])
    assert manifest["prompt_chars"] == len(cap.prompts[0])
    assert manifest["flags"]["canonical_tier"] is True
    assert manifest["flags"]["canonical"] is True
