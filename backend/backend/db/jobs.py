"""
Job repository — all database operations for the jobs table.

AGENT-CTX: All functions accept an aiosqlite.Connection as their first argument.
This makes them testable without FastAPI (pass a test DB connection directly) and
avoids the overhead of opening a new connection per operation.

AGENT-CTX: The auth extension point is get_job_filter() — see JobFilter docstring
in db/models.py for the swap instructions when auth is added.
"""

from __future__ import annotations

import time
import uuid
from datetime import datetime, timezone

import aiosqlite

from backend.db.models import (
    JobFilter,
    JobListItem,
    JobStatus,
    JobStatusResponse,
    JobSubmitResponse,
)
from backend.models import SearchResponse


# ── Write operations ────────────────────────────────────────────────────────────

async def create_job(
    db: aiosqlite.Connection,
    query: str,
    user_id: str | None = None,
) -> JobSubmitResponse:
    """
    Insert a new job in pending state and return the submission record.

    AGENT-CTX: job_id is a random UUID — no ordering implied by the id itself.
    The frontend sorts by created_at for display. user_id is always None today;
    passed through for auth extensibility.
    """
    job_id = str(uuid.uuid4())
    now = time.time()
    await db.execute(
        """
        INSERT INTO jobs (job_id, query, status, created_at, updated_at, user_id)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (job_id, query, JobStatus.pending.value, now, now, user_id),
    )
    await db.commit()
    return JobSubmitResponse(
        job_id=job_id,
        query=query,
        status=JobStatus.pending,
        created_at=_ts(now),
    )


async def set_job_running(db: aiosqlite.Connection, job_id: str) -> None:
    """Mark job as running. Called by the worker immediately on pickup."""
    await db.execute(
        "UPDATE jobs SET status = ?, updated_at = ? WHERE job_id = ?",
        (JobStatus.running.value, time.time(), job_id),
    )
    await db.commit()


async def set_job_complete(
    db: aiosqlite.Connection,
    job_id: str,
    result: SearchResponse,
) -> None:
    """Mark job as complete and persist the serialised SearchResponse."""
    # AGENT-CTX: model_dump_json() (Pydantic v2) produces compact JSON.
    # Deserialised on read via SearchResponse.model_validate_json().
    await db.execute(
        """
        UPDATE jobs SET status = ?, result_json = ?, updated_at = ?
        WHERE job_id = ?
        """,
        (JobStatus.complete.value, result.model_dump_json(), time.time(), job_id),
    )
    await db.commit()


async def set_job_failed(
    db: aiosqlite.Connection,
    job_id: str,
    error: str,
) -> None:
    """Mark job as failed with a human-readable error message."""
    await db.execute(
        """
        UPDATE jobs SET status = ?, error = ?, updated_at = ?
        WHERE job_id = ?
        """,
        (JobStatus.failed.value, error, time.time(), job_id),
    )
    await db.commit()


# ── Read operations ─────────────────────────────────────────────────────────────

async def get_job(
    db: aiosqlite.Connection,
    job_id: str,
) -> JobStatusResponse | None:
    """Return the full job record, or None if not found."""
    async with db.execute(
        "SELECT * FROM jobs WHERE job_id = ?", (job_id,)
    ) as cursor:
        row = await cursor.fetchone()
    return _row_to_status(row) if row is not None else None


async def list_jobs(
    db: aiosqlite.Connection,
    job_filter: JobFilter = JobFilter(),
) -> list[JobListItem]:
    """
    Return all jobs matching the filter, newest first.

    AGENT-CTX: user_id=None → no filter (all jobs returned — anonymous / no auth).
    When auth is wired, user_id is the JWT subject and only that user's jobs return.
    ORDER BY created_at DESC keeps the sidebar sorted newest-on-top.
    """
    if job_filter.user_id is not None:
        sql = "SELECT * FROM jobs WHERE user_id = ? ORDER BY created_at DESC"
        params: tuple = (job_filter.user_id,)
    else:
        sql = "SELECT * FROM jobs ORDER BY created_at DESC"
        params = ()
    async with db.execute(sql, params) as cursor:
        rows = await cursor.fetchall()
    return [_row_to_list_item(r) for r in rows]


# ── FastAPI dependency ──────────────────────────────────────────────────────────

async def get_job_filter() -> JobFilter:
    """
    FastAPI dependency: returns the job filter for list and create operations.

    AGENT-CTX: Today always returns JobFilter(user_id=None) — no filtering.
    When auth is added, override this dependency in main.py:
        app.dependency_overrides[get_job_filter] = authed_filter_dep
    where authed_filter_dep reads user_id from request.state (set by auth middleware).
    No endpoint code changes are needed — only this dep override.
    """
    return JobFilter()


# ── Private helpers ─────────────────────────────────────────────────────────────

def _ts(unix: float) -> datetime:
    return datetime.fromtimestamp(unix, tz=timezone.utc)


def _row_to_status(row: aiosqlite.Row) -> JobStatusResponse:
    result: SearchResponse | None = None
    if row["result_json"]:
        result = SearchResponse.model_validate_json(row["result_json"])
    return JobStatusResponse(
        job_id=row["job_id"],
        query=row["query"],
        status=JobStatus(row["status"]),
        result=result,
        error=row["error"],
        created_at=_ts(row["created_at"]),
        updated_at=_ts(row["updated_at"]),
    )


def _row_to_list_item(row: aiosqlite.Row) -> JobListItem:
    return JobListItem(
        job_id=row["job_id"],
        query=row["query"],
        status=JobStatus(row["status"]),
        error=row["error"],
        created_at=_ts(row["created_at"]),
        updated_at=_ts(row["updated_at"]),
    )
