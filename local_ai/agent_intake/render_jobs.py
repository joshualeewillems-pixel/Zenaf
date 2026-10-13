"""Render jobs: the right way to handle JS-rendered pages.

Instead of failing with `browser_required`, the intake pipeline creates a
render job. A registered browser — the desktop extension, or the iOS
Shortcut — claims the job, renders the URL in the user's own browser,
extracts the conversation, and completes the job. The pipeline then resumes
autonomously.

Job lifecycle: pending -> claimed -> completed | failed
                    \-> expired (no renderer claimed it in time)

No renderer registered? The job waits in `pending` and the UI says so
honestly, instead of erroring out.
"""
from __future__ import annotations

import sqlite3
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

# A job nobody claims within this long is marked expired (still retryable).
CLAIM_TIMEOUT_S = 15 * 60


@dataclass
class RenderJob:
    id: str
    url: str
    status: str  # pending | claimed | completed | failed | expired
    created_at: float
    claimed_at: float | None = None
    claimed_by: str | None = None
    transcript: str | None = None
    title: str | None = None
    error: str | None = None
    agent_id: str | None = None  # intake agent waiting on this job

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "url": self.url,
            "status": self.status,
            "created_at": self.created_at,
            "claimed_at": self.claimed_at,
            "claimed_by": self.claimed_by,
            "has_transcript": self.transcript is not None,
            "title": self.title,
            "error": self.error,
            "agent_id": self.agent_id,
        }


def _db_path() -> Path:
    p = Path.home() / ".zenaf" / "agent_intake_render_jobs.db"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


class RenderJobStore:
    def __init__(self, db_path: str | Path | None = None):
        self.db_path = Path(db_path) if db_path else _db_path()
        self._init()

    def _connect(self) -> sqlite3.Connection:
        c = sqlite3.connect(str(self.db_path))
        c.row_factory = sqlite3.Row
        return c

    def _init(self) -> None:
        with self._connect() as c:
            c.execute(
                """CREATE TABLE IF NOT EXISTS render_jobs (
                    id TEXT PRIMARY KEY,
                    url TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    created_at REAL NOT NULL,
                    claimed_at REAL,
                    claimed_by TEXT,
                    transcript TEXT,
                    title TEXT,
                    error TEXT,
                    agent_id TEXT
                )"""
            )

    def create(self, url: str, agent_id: str | None = None) -> RenderJob:
        job = RenderJob(
            id=uuid.uuid4().hex[:12],
            url=url.strip(),
            status="pending",
            created_at=time.time(),
            agent_id=agent_id,
        )
        with self._connect() as c:
            c.execute(
                "INSERT INTO render_jobs (id, url, status, created_at, agent_id)"
                " VALUES (?, ?, ?, ?, ?)",
                (job.id, job.url, job.status, job.created_at, job.agent_id),
            )
        return job

    def get(self, job_id: str) -> RenderJob | None:
        with self._connect() as c:
            row = c.execute("SELECT * FROM render_jobs WHERE id = ?", (job_id,)).fetchone()
        return self._row_to_job(row) if row else None

    def _row_to_job(self, row: sqlite3.Row) -> RenderJob:
        return RenderJob(
            id=row["id"],
            url=row["url"],
            status=row["status"],
            created_at=row["created_at"],
            claimed_at=row["claimed_at"],
            claimed_by=row["claimed_by"],
            transcript=row["transcript"],
            title=row["title"],
            error=row["error"],
            agent_id=row["agent_id"],
        )

    def _expire_stale(self, c: sqlite3.Connection) -> None:
        cutoff = time.time() - CLAIM_TIMEOUT_S
        c.execute(
            "UPDATE render_jobs SET status = 'expired'"
            " WHERE status = 'claimed' AND claimed_at < ?",
            (cutoff,),
        )
        c.execute(
            "UPDATE render_jobs SET status = 'expired'"
            " WHERE status = 'pending' AND created_at < ?",
            (cutoff,),
        )

    def next_pending(self, worker_id: str) -> RenderJob | None:
        """Claim the oldest pending (or expired-retryable) job for a worker."""
        with self._connect() as c:
            self._expire_stale(c)
            row = c.execute(
                "SELECT * FROM render_jobs WHERE status IN ('pending', 'expired')"
                " ORDER BY created_at ASC LIMIT 1"
            ).fetchone()
            if not row:
                return None
            now = time.time()
            c.execute(
                "UPDATE render_jobs SET status = 'claimed', claimed_at = ?, claimed_by = ?"
                " WHERE id = ?",
                (now, worker_id, row["id"]),
            )
            job = self._row_to_job(row)
            job.status = "claimed"
            job.claimed_at = now
            job.claimed_by = worker_id
            return job

    def complete(self, job_id: str, transcript: str, title: str | None = None) -> RenderJob | None:
        transcript = (transcript or "").strip()
        if not transcript:
            return self.fail(job_id, "empty transcript")
        with self._connect() as c:
            c.execute(
                "UPDATE render_jobs SET status = 'completed', transcript = ?, title = ?"
                " WHERE id = ?",
                (transcript, (title or "").strip() or None, job_id),
            )
            row = c.execute("SELECT * FROM render_jobs WHERE id = ?", (job_id,)).fetchone()
        return self._row_to_job(row) if row else None

    def fail(self, job_id: str, error: str) -> RenderJob | None:
        with self._connect() as c:
            c.execute(
                "UPDATE render_jobs SET status = 'failed', error = ? WHERE id = ?",
                (error[:500], job_id),
            )
            row = c.execute("SELECT * FROM render_jobs WHERE id = ?", (job_id,)).fetchone()
        return self._row_to_job(row) if row else None

    def pending_count(self) -> int:
        with self._connect() as c:
            self._expire_stale(c)
            row = c.execute(
                "SELECT COUNT(*) AS n FROM render_jobs WHERE status = 'pending'"
            ).fetchone()
        return row["n"] if row else 0
