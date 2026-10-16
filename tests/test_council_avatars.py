"""Seat avatar storage + unlock milestones for council archetypes.

Tests the PersonalityStore avatar methods, the naming.py avatar helpers,
and the build_cast comic-pipeline contract (avatar_url flows through,
None when locked).
"""

import os
import tempfile

import pytest


@pytest.fixture()
def store():
    from local_ai.personality.store import PersonalityStore

    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    s = PersonalityStore(user_id="test-user", db_path=path)
    try:
        yield s
    finally:
        s.close()
        os.unlink(path)


def test_avatar_roundtrip(store):
    assert store.get_archetype_avatar("mentor") is None  # ??? default
    url = store.set_archetype_avatar("mentor", "https://example.com/mentor.png")
    assert url == "https://example.com/mentor.png"
    assert store.get_archetype_avatar("mentor") == url


def test_avatar_clear_restores_placeholder(store):
    store.set_archetype_avatar("skeptic", "https://example.com/s.png")
    store.clear_archetype_avatar("skeptic")
    assert store.get_archetype_avatar("skeptic") is None


def test_avatar_unknown_archetype_raises(store):
    with pytest.raises(ValueError):
        store.get_archetype_avatar("not-a-seat")
    with pytest.raises(ValueError):
        store.set_archetype_avatar("not-a-seat", "https://example.com/x.png")


def test_avatar_rejects_bad_urls(store):
    with pytest.raises(ValueError):
        store.set_archetype_avatar("mentor", "")
    with pytest.raises(ValueError):
        store.set_archetype_avatar("mentor", "not a url")
    # data: and blob: URLs are allowed (pasted/generated images)
    assert store.set_archetype_avatar("mentor", "data:image/png;base64,AAA")


def test_avatar_unlock_threshold():
    from local_ai.council.naming import (
        AVATAR_DEPTH_THRESHOLD,
        RENAME_DEPTH_THRESHOLD,
        avatar_unlocked_for_depth,
    )

    assert AVATAR_DEPTH_THRESHOLD == 10.0
    assert RENAME_DEPTH_THRESHOLD == 25.0
    assert AVATAR_DEPTH_THRESHOLD < RENAME_DEPTH_THRESHOLD  # face before name
    assert avatar_unlocked_for_depth(10.0)
    assert avatar_unlocked_for_depth(50.0)
    assert not avatar_unlocked_for_depth(9.9)
    assert not avatar_unlocked_for_depth(0.0)


def test_rename_status_includes_avatar_fields():
    from local_ai.council.naming import rename_status

    status = rename_status(None)  # no user -> all zeros, nothing unlocked
    assert "avatar_threshold" in status
    assert status["avatar_threshold"] == 10.0
    for entry in status["archetypes"]:
        assert entry["avatar_url"] is None
        assert entry["avatar_unlocked"] is False
        assert entry["avatar_signals_to_unlock"] == 10


def test_build_cast_includes_avatar_url():
    from local_ai.journal.story import build_cast

    cast = build_cast([("mentor", 0.8), ("skeptic", 0.6)], user_id=None)
    assert len(cast) == 2
    for member in cast:
        assert "avatar_url" in member  # contract: always present, None when locked
        assert member["avatar_url"] is None  # no user -> locked -> None
        assert "id" in member and "name" in member and "similarity" in member


def test_get_avatar_url_never_raises():
    from local_ai.council.naming import get_avatar_url

    assert get_avatar_url(None, "mentor") is None
    assert get_avatar_url("nobody", "not-a-seat") is None
