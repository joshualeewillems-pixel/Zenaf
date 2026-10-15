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
    user_id: str = ""  # owner; jobs are per-user so renderers can't cross-claim
    # Idempotent /complete: the agent + mined payload produced by the first
    # successful completion, so a repeat POST can return them instead of
    # re-running the pipeline (which created duplicate agents).
    result_agent_id: str | None = None
    result_mined: str | None = None  # JSON of the mined dict from /complete

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
            "user_id": self.user_id,
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
                    agent_id TEXT,
                    user_id TEXT NOT NULL DEFAULT ''
                )"""
            )
            cols = [r["name"] for r in c.execute("PRAGMA table_info(render_jobs)").fetchall()]
            if cols and "user_id" not in cols:
                c.execute("ALTER TABLE render_jobs ADD COLUMN user_id TEXT NOT NULL DEFAULT ''")
            if cols and "result_agent_id" not in cols:
                c.execute("ALTER TABLE render_jobs ADD COLUMN result_agent_id TEXT")
            if cols and "result_mined" not in cols:
                c.execute("ALTER TABLE render_jobs ADD COLUMN result_mined TEXT")

    def create(self, url: str, agent_id: str | None = None, user_id: str | None = None) -> RenderJob:
        job = RenderJob(
            id=uuid.uuid4().hex[:12],
            url=url.strip(),
            status="pending",
            created_at=time.time(),
            agent_id=agent_id,
            user_id=user_id or "",
        )
        with self._connect() as c:
            c.execute(
                "INSERT INTO render_jobs (id, url, status, created_at, agent_id, user_id)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (job.id, job.url, job.status, job.created_at, job.agent_id, job.user_id),
            )
        return job

    def get(self, job_id: str, user_id: str | None = None) -> RenderJob | None:
        with self._connect() as c:
            q = "SELECT * FROM render_jobs WHERE id = ?" + (" AND user_id = ?" if user_id else "")
            row = c.execute(q, ((job_id, user_id) if user_id else (job_id,))).fetchone()
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
            user_id=row["user_id"] if "user_id" in row.keys() else "",
            result_agent_id=row["result_agent_id"] if "result_agent_id" in row.keys() else None,
            result_mined=row["result_mined"] if "result_mined" in row.keys() else None,
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

    def next_pending(self, worker_id: str, user_id: str | None = None) -> RenderJob | None:
        """Claim the oldest pending (or expired-retryable) job for a worker."""
        with self._connect() as c:
            self._expire_stale(c)
            row = c.execute(
                "SELECT * FROM render_jobs WHERE status IN ('pending', 'expired')"
                + (" AND user_id = ?" if user_id else "")
                + " ORDER BY created_at ASC LIMIT 1",
                ((user_id,) if user_id else ()),
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

    def complete(self, job_id: str, transcript: str, title: str | None = None, user_id: str | None = None) -> RenderJob | None:
        """Mark a job completed with its transcript.

        Idempotent: completing an already-completed job returns the job
        unchanged — the route layer replays the stored result instead of
        re-running the intake pipeline (which created duplicate agents).
        """
        transcript = (transcript or "").strip()
        if not transcript:
            return self.fail(job_id, "empty transcript", user_id=user_id)
        with self._connect() as c:
            cur = c.execute(
                "UPDATE render_jobs SET status = 'completed', transcript = ?, title = ?"
                " WHERE id = ? AND status != 'completed'"
                + (" AND user_id = ?" if user_id else ""),
                (transcript, (title or "").strip() or None, job_id, *([user_id] if user_id else [])),
            )
            if cur.rowcount == 0:
                # Either unknown, owned by someone else, or already completed.
                row = c.execute("SELECT * FROM render_jobs WHERE id = ?", (job_id,)).fetchone()
                if row is None:
                    return None
                job = self._row_to_job(row)
                if job.status == "completed" and (not user_id or job.user_id == user_id):
                    return job
                return None
            row = c.execute("SELECT * FROM render_jobs WHERE id = ?", (job_id,)).fetchone()
        return self._row_to_job(row) if row else None

    def set_result(self, job_id: str, agent_id: str, mined_json: str) -> None:
        """Record the agent + mined payload produced by a completed job.

        Lets a repeat /complete replay the stored result instead of
        re-running the pipeline.
        """
        with self._connect() as c:
            c.execute(
                "UPDATE render_jobs SET result_agent_id = ?, result_mined = ? WHERE id = ?",
                (agent_id, mined_json, job_id),
            )

    def fail(self, job_id: str, error: str, user_id: str | None = None) -> RenderJob | None:
        """Mark a job failed.

        Guarded transition: only non-terminal jobs can be failed. A completed
        job can never be failed; re-failing an already-failed job is a no-op
        returning the job unchanged (original error preserved).
        """
        with self._connect() as c:
            cur = c.execute(
                "UPDATE render_jobs SET status = 'failed', error = ?"
                " WHERE id = ? AND status NOT IN ('completed', 'failed')"
                + (" AND user_id = ?" if user_id else ""),
                (error[:500], job_id, *([user_id] if user_id else [])),
            )
            if cur.rowcount == 0:
                return None
            row = c.execute("SELECT * FROM render_jobs WHERE id = ?", (job_id,)).fetchone()
        return self._row_to_job(row) if row else None

    def pending_count(self, user_id: str | None = None) -> int:
        with self._connect() as c:
            self._expire_stale(c)
            row = c.execute(
                "SELECT COUNT(*) AS n FROM render_jobs WHERE status = 'pending'" + (" AND user_id = ?" if user_id else ""),
                ((user_id,) if user_id else ()),
            ).fetchone()
        return row["n"] if row else 0
