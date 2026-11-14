"""D5 affirmation recovery (Gardener correction, 2026-11-07): an affirmed
impression in a meeting that never completes must not vanish.

The recovery sweep files affirmed-but-unfiled impressions from meetings
that are still active and whose conversation has been quiet for
AFFIRMATION_RECOVERY_QUIET_DAYS (7), through the same _file_impression
path the close uses, with filed_via="affirmation_recovery". Manual
invocation only — no schedule, no Review-queue trigger. A row whose
claim is stale (filed once, the row's read-back since revised) is
refreshed in place while still pending; a ruled claim is never touched.
"""

from __future__ import annotations

import json
import threading
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from local_ai.agent_intake import review_claims
from local_ai.agent_intake.store import AgentStore
from local_ai.conversation.meeting import (
    AFFIRMATION_RECOVERY_QUIET_DAYS,
    MeetingService,
    MeetingStore,
)
from local_ai.conversation.store import ConversationStore
from local_ai.vision_execution import keystone_seeding
from local_ai.vision_execution import service as ve


@pytest.fixture()
def ve_ctx(tmp_path, monkeypatch):
    """Isolate the vision-execution SQLite DB per test."""
    import local_ai.vision_execution.storage as ve_store

    monkeypatch.setattr(ve_store, "_DB_PATH", tmp_path / "ve.db")
    monkeypatch.setattr(ve_store, "_DB_DIR", tmp_path)
    monkeypatch.setattr(ve_store, "_init_done_paths", set())
    monkeypatch.setattr(ve_store, "_thread_local", threading.local())
    return {}


def _svc(tmp_path):
    agents_db = tmp_path / "agents.db"
    return MeetingService(
        ConversationStore(tmp_path / "conv.db"),
        MeetingStore(tmp_path / "meetings.db"),
        generate_fn=lambda prompt, **kwargs: "A plain reply.",
        agent_store_factory=lambda uid: AgentStore(agents_db, user_id=uid),
    )


def _agents(tmp_path, uid) -> AgentStore:
    return AgentStore(tmp_path / "agents.db", user_id=uid)


def _seeded_user(email="recovery@example.com"):
    user = ve.create_user_account(email, "pw", "Recovery")
    keystone_seeding.seed_meet_your_council(user["id"])
    return user["id"]


def _affirmed_row(svc, uid, arch="mentor", created_at="2026-10-20T10:00:00+00:00",
                  claim="You tend patiently.", response="Yes, that's right.",
                  visitor_response="affirmed"):
    """An active meeting row with a read-back and a visitor response."""
    # S3: MeetingStore.delete is retired with restart(); the helper
    # resets the row with a direct DELETE (it already writes
    # created_at through the connection below).
    svc.meetings._conn.execute(
        "DELETE FROM meetings WHERE user_id = ? AND archetype_id = ? "
        "AND keystone_index = 1",
        (uid, arch),
    )
    svc.meetings._conn.commit()
    svc.meetings.create(uid, arch, 1)
    svc.meetings._conn.execute(
        "UPDATE meetings SET created_at = ? WHERE user_id = ? "
        "AND archetype_id = ? AND keystone_index = 1",
        (created_at, uid, arch),
    )
    svc.meetings._conn.commit()
    svc.meetings.update(
        uid, arch, 1,
        readback_claim=claim,
        readback_response=response,
        readback_strands=json.dumps(["Compass", "Logic"]),
        readback_visitor_response=visitor_response,
    )


def _add_message(svc, uid, arch, created_at, body="A message."):
    svc.conversations._conn.execute(
        "INSERT INTO messages (id, user_id, conversation_id, archetype_id, "
        "role, body, mode, context_json, created_at) "
        "VALUES (?, ?, ?, ?, 'user', ?, 'trained', '{}', ?)",
        (f"msg-{arch}-{created_at}", uid, f"meeting-{arch}-1", arch, body, created_at),
    )
    svc.conversations._conn.commit()


def _iso(days_ago):
    return (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()


# ------------------------------------------------------------------- the sweep


def test_recovery_files_affirmed_quiet_meeting(ve_ctx, tmp_path):
    uid = _seeded_user()
    svc = _svc(tmp_path)
    _affirmed_row(svc, uid)
    filed = svc.recover_affirmed_impressions(uid)
    assert len(filed) == 1
    store = _agents(tmp_path, uid)
    claims = store.get_claims("meeting-mentor-1")
    assert len(claims) == 1
    assert claims[0].id == filed[0]
    assert claims[0].status == "pending"
    assert claims[0].inference == "You tend patiently."
    assert claims[0].evidence == "Yes, that's right."
    assert "Filed by recovery of an affirmed impression" in claims[0].detail
    assert "not review approval and not training authorization" in claims[0].detail


def test_recovery_skips_recent_meeting(ve_ctx, tmp_path):
    uid = _seeded_user()
    svc = _svc(tmp_path)
    _affirmed_row(svc, uid)
    _add_message(svc, uid, "mentor", _iso(0))
    assert svc.recover_affirmed_impressions(uid) == []
    assert _agents(tmp_path, uid).get_claims("meeting-mentor-1") == []


def test_recovery_files_after_seven_quiet_days(ve_ctx, tmp_path):
    uid = _seeded_user()
    svc = _svc(tmp_path)
    _affirmed_row(svc, uid)
    _add_message(svc, uid, "mentor", _iso(8))
    assert len(svc.recover_affirmed_impressions(uid)) == 1


def test_recovery_skips_six_day_old_meeting(ve_ctx, tmp_path):
    uid = _seeded_user()
    svc = _svc(tmp_path)
    _affirmed_row(svc, uid)
    _add_message(svc, uid, "mentor", _iso(6))
    assert svc.recover_affirmed_impressions(uid) == []


@pytest.mark.parametrize("visitor_response", ["disputed", "unresolved", ""])
def test_recovery_skips_non_affirmed(ve_ctx, tmp_path, visitor_response):
    uid = _seeded_user()
    svc = _svc(tmp_path)
    _affirmed_row(svc, uid, visitor_response=visitor_response)
    assert svc.recover_affirmed_impressions(uid) == []
    assert _agents(tmp_path, uid).get_claims("meeting-mentor-1") == []


def test_recovery_skips_empty_claim(ve_ctx, tmp_path):
    uid = _seeded_user()
    svc = _svc(tmp_path)
    _affirmed_row(svc, uid, claim="   ")
    assert svc.recover_affirmed_impressions(uid) == []


def test_recovery_is_idempotent(ve_ctx, tmp_path):
    uid = _seeded_user()
    svc = _svc(tmp_path)
    _affirmed_row(svc, uid)
    assert len(svc.recover_affirmed_impressions(uid)) == 1
    # Second run: the claim already exists, so nothing is filed again.
    assert svc.recover_affirmed_impressions(uid) == []
    assert len(_agents(tmp_path, uid).get_claims("meeting-mentor-1")) == 1


def test_recovery_skips_completed_meeting(ve_ctx, tmp_path):
    uid = _seeded_user()
    svc = _svc(tmp_path)
    _affirmed_row(svc, uid)
    svc.meetings.update(uid, "mentor", 1, status="complete")
    assert svc.recover_affirmed_impressions(uid) == []
    assert _agents(tmp_path, uid).get_claims("meeting-mentor-1") == []


def test_list_active_returns_only_active_meetings(ve_ctx, tmp_path):
    uid = _seeded_user()
    svc = _svc(tmp_path)
    _affirmed_row(svc, uid, arch="mentor")
    _affirmed_row(svc, uid, arch="guardian")
    svc.meetings.update(uid, "guardian", 1, status="complete")
    active = svc.meetings.list_active(uid)
    assert [r["archetype_id"] for r in active] == ["mentor"]


# ------------------------------------------------------- filed_via + staleness


def test_filed_via_marks_only_recovery_claims():
    recovered = review_claims.build_meeting_impression_claim(
        agent_id="meeting-mentor-1", seat_name="Gardener",
        readback_claim="You tend patiently.", readback_response="Yes.",
        strand_keys=["self"], run_key="run",
        readback_visitor_response="affirmed",
        filed_via="affirmation_recovery",
    )
    assert "Filed by recovery of an affirmed impression" in recovered.detail
    closed = review_claims.build_meeting_impression_claim(
        agent_id="meeting-mentor-1", seat_name="Gardener",
        readback_claim="You tend patiently.", readback_response="Yes.",
        strand_keys=["self"], run_key="run",
        readback_visitor_response="affirmed",
    )
    assert "Filed by recovery" not in closed.detail


def test_stale_pending_claim_updated_in_place(ve_ctx, tmp_path):
    uid = _seeded_user()
    svc = _svc(tmp_path)
    store = _agents(tmp_path, uid)
    _affirmed_row(svc, uid, claim="First impression.")
    assert len(svc.recover_affirmed_impressions(uid)) == 1
    claim = store.get_claims("meeting-mentor-1")[0]
    store.update_claim(claim.id, status="pending", user_note="my note")
    # The row's read-back is revised after filing; re-filing refreshes
    # the pending claim in place, under the same id.
    svc.meetings.update(uid, "mentor", 1, readback_claim="Revised impression.")
    svc._file_impression(uid, "mentor", 1, SimpleNamespace(character="mentor"))
    claims = store.get_claims("meeting-mentor-1")
    assert len(claims) == 1
    assert claims[0].id == claim.id
    assert claims[0].inference == "Revised impression."
    assert claims[0].status == "pending"
    assert claims[0].user_note == "my note"


def test_stale_ruled_claim_never_updated(ve_ctx, tmp_path):
    uid = _seeded_user()
    svc = _svc(tmp_path)
    store = _agents(tmp_path, uid)
    _affirmed_row(svc, uid, claim="First impression.")
    assert len(svc.recover_affirmed_impressions(uid)) == 1
    claim = store.get_claims("meeting-mentor-1")[0]
    store.update_claim(claim.id, status="accepted")
    svc.meetings.update(uid, "mentor", 1, readback_claim="Revised impression.")
    svc._file_impression(uid, "mentor", 1, SimpleNamespace(character="mentor"))
    claims = store.get_claims("meeting-mentor-1")
    assert len(claims) == 1
    assert claims[0].inference == "First impression."
    assert claims[0].status == "accepted"


def test_quiet_days_constant_is_seven():
    assert AFFIRMATION_RECOVERY_QUIET_DAYS == 7
