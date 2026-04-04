"""
SQLite pragma regression tests.

Never open or verify pragmas against the production vision_execution.db or intake_mirror.db
here — use tmp_path-only files so tests cannot corrupt or lock real data.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from local_ai.intake.mirror import open_mirror_sqlite
from local_ai.vision_execution.storage import open_sqlite_with_ve_pragmas


def _assert_wal_and_busy(conn) -> None:
    journal = conn.execute("PRAGMA journal_mode").fetchone()[0]
    assert str(journal).lower() == "wal"
    busy = conn.execute("PRAGMA busy_timeout").fetchone()[0]
    assert busy == 5000


@pytest.mark.parametrize(
    "open_fn,path_name",
    [
        (open_sqlite_with_ve_pragmas, "ve_pragma_test.db"),
        (open_mirror_sqlite, "mirror_pragma_test.db"),
    ],
)
def test_sqlite_pragmas_wal_and_busy_timeout(tmp_path: Path, open_fn, path_name: str) -> None:
    # Do not point this at repo vision_execution.db or intake_mirror.db — only tmp_path files.
    db = tmp_path / path_name
    conn = open_fn(db)
    try:
        _assert_wal_and_busy(conn)
    finally:
        conn.close()
