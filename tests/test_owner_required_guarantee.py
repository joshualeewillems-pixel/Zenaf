"""Owner-required guarantee — no record is written without an owner.

Founder ruling 2026-11-22: no record in Zenaf should ever exist
without an owner, in any frame. The storage boundary is where that
is enforced (Track B pattern): a required ``user_id`` parameter is
not a valid identity — ``None`` and blank strings are refused with
``ValueError`` at every creation path patched under the guarantee,
never written through as NULL / ``""`` owners.

These tests pin the refusal at the storage layer itself (not the
routes, which already pass the authenticated user): each patched
creation function is called directly with an empty/None owner and
must raise before writing anything.
"""

from __future__ import annotations

import sqlite3

import pytest

from local_ai.vision_execution import models as M
from local_ai.vision_execution import storage as ve


# ---------------------------------------------------------------------------
# Vision Execution storage
# ---------------------------------------------------------------------------


@pytest.fixture()
def ve_ctx(tmp_path, monkeypatch):
    db_path = tmp_path / "ve.db"
    conn = ve.open_sqlite_with_ve_pragmas(db_path)
    monkeypatch.setattr(ve, "get_connection", lambda: conn)
    ve.init_db(conn)
    yield conn
    conn.close()


@pytest.mark.parametrize("bad_owner", ["", "   ", None])
def test_ve_root_creates_refuse_ownerless(ve_ctx, bad_owner):
    with pytest.raises(ValueError):
        ve.create_task(M.TaskCreate(title="x"), bad_owner)
    with pytest.raises(ValueError):
        ve.create_project(M.ProjectCreate(title="x"), bad_owner)
    with pytest.raises(ValueError):
        ve.create_initiative(M.InitiativeCreate(title="x"), bad_owner)
    with pytest.raises(ValueError):
        ve.create_idea(M.IdeaCreate(title="x"), bad_owner)
    with pytest.raises(ValueError):
        ve.create_core_profile(M.CoreProfileCreate(name="x"), bad_owner)
    with pytest.raises(ValueError):
        ve.create_content_brief({"title": "x"}, bad_owner)


@pytest.mark.parametrize("bad_owner", ["", None])
def test_ve_marketplace_and_signal_writers_refuse_ownerless(ve_ctx, bad_owner):
    with pytest.raises(ValueError):
        ve.create_seat_request(M.SeatRequestCreate(title="x"), bad_owner)
    with pytest.raises(ValueError):
        ve.create_capability_offer(M.CapabilityOfferCreate(title="x"), bad_owner)
    with pytest.raises(ValueError):
        ve.create_material_request(M.MaterialRequestCreate(title="x"), bad_owner)
    with pytest.raises(ValueError):
        ve.create_material_offer(M.MaterialOfferCreate(title="x"), bad_owner)
    with pytest.raises(ValueError):
        ve.insert_prompt_signal(
            bad_owner,
            prompt_id="p1",
            action="engaged",
            entity_type=None,
            entity_id=None,
        )
    with pytest.raises(ValueError):
        ve.record_seat_unlocks(bad_owner, ["mentor"])


@pytest.mark.parametrize("bad_owner", ["", None])
def test_ve_settings_writers_refuse_ownerless(ve_ctx, bad_owner):
    # The lazy insert-on-read getters must refuse too: a read for a
    # blank owner must not mint a phantom settings row.
    with pytest.raises(ValueError):
        ve.get_user_permissions_settings(bad_owner)
    with pytest.raises(ValueError):
        ve.get_user_llm_profile(bad_owner)
    with pytest.raises(ValueError):
        ve.get_user_notification_settings(bad_owner)
    with pytest.raises(ValueError):
        ve.upsert_user_council_workspace(bad_owner, [])
    with pytest.raises(ValueError):
        ve.upsert_llm_provider_credential(bad_owner, "openai", "sk-test")
    with pytest.raises(ValueError):
        ve.create_session(bad_owner)


def test_ve_workspace_message_refuses_ownerless_sender(ve_ctx):
    recipient = ve.create_user_account("rcpt@example.com", "pw", "Rcpt")
    with pytest.raises(ValueError):
        ve.create_workspace_message("", recipient["id"], "hi", {})
    with pytest.raises(ValueError):
        ve.create_workspace_message("ghost-user", recipient["id"], "hi", {})


def test_ve_proposal_recorder_refuses_ownerless(ve_ctx):
    with pytest.raises(ValueError):
        ve.record_task_proposal("", {"source_message_id": "m1"})


def test_ve_positive_controls_still_write_owned_rows(ve_ctx):
    task = ve.create_task(M.TaskCreate(title="real"), "user-a")
    row = ve_ctx.execute(
        "SELECT user_id FROM tasks WHERE id = ?", (task["id"],)
    ).fetchone()
    assert row[0] == "user-a"
    idea = ve.create_idea(M.IdeaCreate(title="real"), "user-a")
    row = ve_ctx.execute(
        "SELECT user_id FROM ideas WHERE id = ?", (idea["id"],)
    ).fetchone()
    assert row[0] == "user-a"
    token = ve.create_session("user-a")
    assert token


# ---------------------------------------------------------------------------
# Narrative store + sweep enumeration
# ---------------------------------------------------------------------------


@pytest.fixture()
def narrative_store(tmp_path):
    from local_ai.narrative.store import NarrativeStore

    return NarrativeStore(db_path=tmp_path / "narrative.db")


@pytest.mark.parametrize("bad_owner", ["", "   ", None])
def test_narrative_sweep_writers_refuse_ownerless(narrative_store, bad_owner):
    with pytest.raises(ValueError):
        narrative_store.set_processing_position(bad_owner, 0, "file-1")
    with pytest.raises(ValueError):
        narrative_store.sync_meeting_observables(bad_owner, [])
    with pytest.raises(ValueError):
        narrative_store.sync_thread_observables(bad_owner, "t1", [])
    with pytest.raises(ValueError):
        narrative_store.link_threads(bad_owner, "t1", "t2")
    with pytest.raises(ValueError):
        narrative_store.set_signal_delivery(
            bad_owner,
            signal_kind="reading",
            signal_id="s1",
            delivery_status="sent",
        )


def test_narrative_positive_control(narrative_store):
    narrative_store.set_processing_position("user-a", 0, "file-1")
    assert "user-a" in narrative_store.processing_position_users()


def test_sweep_enumeration_filters_blank_ids(narrative_store, ve_ctx):
    # A legacy blank id sitting in the permissions table (written
    # before the guarantee) must never be enumerated as a sweep user.
    ve_ctx.execute(
        "INSERT INTO user_permissions_settings (user_id, updated_at)"
        " VALUES ('', '2026-01-01T00:00:00Z')"
    )
    ve_ctx.execute(
        "INSERT INTO user_permissions_settings (user_id, updated_at)"
        " VALUES ('user-a', '2026-01-01T00:00:00Z')"
    )
    ve_ctx.commit()
    from local_ai.narrative.sweep import enumerate_sweep_users

    users = enumerate_sweep_users(narrative_store)
    assert "user-a" in users
    assert "" not in users
    assert all(u.strip() for u in users)


# ---------------------------------------------------------------------------
# Meeting store — dict-carried owners
# ---------------------------------------------------------------------------


@pytest.fixture()
def meeting_store(tmp_path):
    from local_ai.conversation.meeting import MeetingStore

    return MeetingStore(tmp_path / "meetings.db")


def _encounter_fields(**overrides):
    fields = {
        "run_id": "run-1",
        "archetype_id": "mentor",
        "keystone_index": 0,
        "run_number": 1,
        "conversation_id": "conv-1",
    }
    fields.update(overrides)
    return fields


def test_meeting_encounter_refuses_missing_or_blank_owner(meeting_store):
    with pytest.raises(ValueError):
        meeting_store.create_encounter(**_encounter_fields())
    with pytest.raises(ValueError):
        meeting_store.create_encounter(**_encounter_fields(user_id=""))
    with pytest.raises(ValueError):
        meeting_store.create_encounter(**_encounter_fields(user_id=None))


def test_meeting_encounter_with_request_refuses_ownerless(meeting_store):
    request = {
        "request_id": "req-1",
        "predecessor_run_id": "run-0",
        "successor_run_id": "run-1",
    }
    with pytest.raises(ValueError):
        meeting_store.create_encounter_with_request(
            _encounter_fields(user_id="user-a"), request
        )
    with pytest.raises(ValueError):
        meeting_store.create_encounter_with_request(
            _encounter_fields(), dict(request, user_id="user-a")
        )


def test_meeting_archive_refuses_ownerless(meeting_store):
    with pytest.raises(ValueError):
        meeting_store.archive_run("", "mentor", 0, {}, [])


def test_meeting_positive_control(meeting_store):
    enc = meeting_store.create_encounter(**_encounter_fields(user_id="user-a"))
    assert enc["user_id"] == "user-a"


# ---------------------------------------------------------------------------
# Conversation store — upload job calls need a real parent job
# ---------------------------------------------------------------------------


def test_upload_job_call_refuses_orphan_job(tmp_path):
    from local_ai.conversation.store import ConversationStore

    store = ConversationStore(tmp_path / "conv.db")
    with pytest.raises(ValueError):
        store.start_upload_job_call("no-such-job", 0, "extract")
    job = store.create_upload_job("user-a", "doc-1", 1)
    call = store.start_upload_job_call(job["job_id"], 0, "extract")
    assert call["job_id"] == job["job_id"]


# ---------------------------------------------------------------------------
# Long-tail stores
# ---------------------------------------------------------------------------


def test_followthrough_refuses_ownerless(tmp_path):
    from local_ai.followthrough.store import FollowthroughStore

    store = FollowthroughStore(db_path=tmp_path / "ft.db")
    with pytest.raises(ValueError):
        store.create_commitment("", "do the thing")
    with pytest.raises(ValueError):
        store.create_nudge(
            "",
            kind="stalled",
            entity_type="task",
            entity_id="t1",
            severity="low",
            why_text="because",
        )
    with pytest.raises(ValueError):
        store.log_event("", "engine_tick")
    with pytest.raises(ValueError):
        store.set_growth("task", "t1", "", "growing")


def test_followthrough_growth_never_mutates_another_owner(tmp_path):
    from local_ai.followthrough.store import FollowthroughStore

    store = FollowthroughStore(db_path=tmp_path / "ft.db")
    store.set_growth("task", "t1", "user-a", "growing")
    store.set_growth("task", "t1", "user-b", "stalled")
    assert store.get_growth("task", "t1", "user-a")["state"] == "growing"
    assert store.get_growth("task", "t1", "user-b") is None


def test_pipeline_refuses_ownerless(tmp_path):
    from local_ai.pipeline.store import PipelineStore

    store = PipelineStore(db_path=tmp_path / "pipeline.db")
    with pytest.raises(ValueError):
        store.create_entry("", "some text", "hash-1")
    with pytest.raises(ValueError):
        store.save_taste_profile("")


def test_feedback_refuses_ownerless(tmp_path):
    from local_ai.feedback.store import FeedbackStore

    store = FeedbackStore(db_path=tmp_path / "feedback.db")
    with pytest.raises(ValueError):
        store.add_feedback("", "ref-1", "conv-1", "mentor", 5, [], "")


def test_twigs_refuse_ownerless(tmp_path):
    from local_ai.council.twigs import TwigStore, sprout_twig

    store = TwigStore(tmp_path / "twigs.db")
    cluster = {"Heart": 0.5, "Hands": 0.3, "Compass": 0.2}
    with pytest.raises(ValueError):
        sprout_twig("", "guardian", "Cooking", cluster, signal_count=3, store=store)


def test_you_profile_refuses_ownerless(tmp_path):
    from local_ai.you_profile.store import YouProfileStore

    store = YouProfileStore(db_path=tmp_path / "you.db")
    with pytest.raises(ValueError):
        store.upsert("", "mentor")


def test_permissions_row_refuses_ownerless():
    from local_ai.permissions.store import _ensure_user_row

    conn = sqlite3.connect(":memory:")
    with pytest.raises(ValueError):
        _ensure_user_row(conn, "")
    _ensure_user_row(conn, "user-a")


def test_entity_strands_refuse_ownerless(ve_ctx):
    from local_ai.entity_strands import set_entity_strands

    weights = {
        "Voice": 0.3,
        "Logic": 0.25,
        "Eye": 0.15,
        "Ear": 0.05,
        "Hands": 0.1,
        "Heart": 0.1,
        "Compass": 0.05,
    }
    with pytest.raises(ValueError):
        set_entity_strands("", "project", "p1", weights, "user_stated")
