"""Palace overhead layout records — store, validation, routes.

The store mirrors the chalk store's discipline (own SQLite db,
one lock, strictly owner-scoped rows); the routes are its only
HTTP surface. Handler-level tests, the chalk carriage pattern:
the store factory is monkeypatched and handlers are called with
plain current_user dicts.
"""

import pytest
from fastapi import HTTPException

from local_ai.conversation.palace_layout_store import (
    PalaceLayoutStore,
    validate_layout_record,
)

USER = "user-1"
OTHER_USER = "user-2"
PROJECT = "proj-1"


@pytest.fixture()
def layout_store(tmp_path):
    store = PalaceLayoutStore(db_path=tmp_path / "palace_layout.db")
    yield store
    store.close()


def _record(scale=10.13, moved=0):
    return {
        "version": 1,
        "scale": scale,
        "positions": {"t1": [10.5, -20.25], "t2": [-30.0, 5.0]},
        "weights": {"t1": 4, "t2": 2},
        "lastTransition": {"reflow": False, "steppedDown": 0, "movedRooms": moved},
        "unplaced": [],
    }


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------


def test_store_round_trip_and_upsert(layout_store):
    stored = layout_store.put_layout(user_id=USER, project_id=PROJECT, record=_record())
    assert stored["scale"] == 10.13
    got = layout_store.get_layout(USER, PROJECT)
    assert got == stored
    assert got["positions"]["t1"] == [10.5, -20.25]
    # A second write replaces the record whole (the plan keeps
    # only the standing composition).
    layout_store.put_layout(user_id=USER, project_id=PROJECT, record=_record(scale=7.5, moved=3))
    got = layout_store.get_layout(USER, PROJECT)
    assert got["scale"] == 7.5
    assert got["lastTransition"]["movedRooms"] == 3


def test_store_owner_isolation(layout_store):
    layout_store.put_layout(user_id=USER, project_id=PROJECT, record=_record())
    assert layout_store.get_layout(OTHER_USER, PROJECT) is None
    assert layout_store.get_layout(USER, "no-such-project") is None
    # Another user's write under the same project key lands on
    # their own row only.
    layout_store.put_layout(user_id=OTHER_USER, project_id=PROJECT, record=_record(scale=3.0))
    assert layout_store.get_layout(USER, PROJECT)["scale"] == 10.13
    assert layout_store.get_layout(OTHER_USER, PROJECT)["scale"] == 3.0


def test_store_unplaced_records_stand(layout_store):
    record = _record()
    record["unplaced"] = [{"id": "t9", "radius": 61.5, "cause": "SEARCH_EXHAUSTION"}]
    stored = layout_store.put_layout(user_id=USER, project_id=PROJECT, record=record)
    assert stored["unplaced"] == [{"id": "t9", "radius": 61.5, "cause": "SEARCH_EXHAUSTION"}]


# ---------------------------------------------------------------------------
# Validation (fail-closed)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "mutate",
    [
        lambda r: r.update(version=0),
        lambda r: r.update(version="1"),
        lambda r: r.update(scale=-1),
        lambda r: r.update(scale=float("inf")),
        lambda r: r.update(positions={"t1": [1]}),
        lambda r: r.update(positions={"t1": [1, "x"]}),
        lambda r: r.update(weights={"t1": 0}),
        lambda r: r.update(lastTransition={"reflow": "no", "steppedDown": 0, "movedRooms": 0}),
        lambda r: r.update(lastTransition={"reflow": False, "steppedDown": -1, "movedRooms": 0}),
        lambda r: r.update(unplaced=[{"id": "t9", "radius": 5, "cause": "TOO_BIG"}]),
        lambda r: r.update(unplaced=[{"id": "t9", "radius": -5, "cause": "SEARCH_EXHAUSTION"}]),
        lambda r: r.pop("positions"),
    ],
)
def test_validation_refuses_malformed_records(mutate):
    record = _record()
    mutate(record)
    with pytest.raises(ValueError):
        validate_layout_record(record)


def test_store_refuses_malformed_record_without_writing(layout_store):
    with pytest.raises(ValueError):
        layout_store.put_layout(user_id=USER, project_id=PROJECT, record={"version": 1})
    assert layout_store.get_layout(USER, PROJECT) is None


# ---------------------------------------------------------------------------
# Routes (handler-level, the chalk pattern)
# ---------------------------------------------------------------------------


def test_routes_round_trip_and_isolation(monkeypatch, layout_store):
    from api.routes import conversation_routes

    monkeypatch.setattr(conversation_routes, "_palace_layout_store", lambda: layout_store)

    empty = conversation_routes.get_palace_layout(project_id=PROJECT, current_user={"id": USER})
    assert empty == {"project_id": PROJECT, "layout": None}

    body = conversation_routes.PalaceLayoutBody(record=_record())
    saved = conversation_routes.put_palace_layout(
        project_id=PROJECT, body=body, current_user={"id": USER}
    )
    assert saved["layout"]["scale"] == 10.13

    mine = conversation_routes.get_palace_layout(project_id=PROJECT, current_user={"id": USER})
    assert mine["layout"]["positions"]["t2"] == [-30.0, 5.0]

    theirs = conversation_routes.get_palace_layout(
        project_id=PROJECT, current_user={"id": OTHER_USER}
    )
    assert theirs == {"project_id": PROJECT, "layout": None}


def test_routes_require_auth_and_refuse_bad_records(monkeypatch, layout_store):
    from api.routes import conversation_routes

    monkeypatch.setattr(conversation_routes, "_palace_layout_store", lambda: layout_store)

    with pytest.raises(HTTPException) as exc:
        conversation_routes.get_palace_layout(project_id=PROJECT, current_user={})
    assert exc.value.status_code == 401

    bad = conversation_routes.PalaceLayoutBody(record={"version": 1, "scale": -2})
    with pytest.raises(HTTPException) as exc:
        conversation_routes.put_palace_layout(
            project_id=PROJECT, body=bad, current_user={"id": USER}
        )
    assert exc.value.status_code == 422
    assert layout_store.get_layout(USER, PROJECT) is None
