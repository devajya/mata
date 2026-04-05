"""
SQLite connection management and schema initialisation.

AGENT-CTX: SQLite is the job state store for Milestone 3. It is sufficient for a
single-process deployment (web + worker in the same container — see render.yaml).
If horizontal scaling is ever needed, migrate to PostgreSQL + asyncpg; the
repository interface in jobs.py does not need to change.

AGENT-CTX: The db/ package is intentionally separate from backend/backend/models.py.
Future entities (notes, annotations per graph/conversation) belong here, not in the
domain models layer.

AGENT-CTX: _get_db_path() reads from the environment at call time, NOT at import
time. This is deliberate — pytest's monkeypatch.setenv() overrides os.environ for
the duration of a test, and the change must propagate to all callers including the
ARQ worker which opens its own connections. A module-level DB_PATH constant would
capture the value at import time and ignore the override.
"""

import os

import aiosqlite

# ── Schema ─────────────────────────────────────────────────────────────────────

_CREATE_JOBS_TABLE = """
CREATE TABLE IF NOT EXISTS jobs (
    job_id      TEXT    PRIMARY KEY,
    query       TEXT    NOT NULL,
    status      TEXT    NOT NULL DEFAULT 'pending',
    result_json TEXT,
    error       TEXT,
    created_at  REAL    NOT NULL,
    updated_at  REAL    NOT NULL,
    -- AGENT-CTX: user_id is NULL until auth is added (Option B, Repository pattern).
    -- When auth middleware is wired, it overrides get_job_filter() in jobs.py to
    -- inject JobFilter(user_id=jwt.sub). All list queries filter on this column.
    -- No endpoint changes are needed at that point.
    user_id     TEXT
);
"""

# AGENT-CTX: WAL journal mode allows one writer and multiple concurrent readers.
# Without WAL, a writer holds an exclusive lock blocking all readers. With WAL,
# the worker can write results while the web process reads job status simultaneously.
_PRAGMA_WAL = "PRAGMA journal_mode=WAL;"


def _get_db_path() -> str:
    """Return DB file path, read from environment at call time."""
    return os.environ.get("SQLITE_DB_PATH", "./mata.db")


async def _create_tables(db: aiosqlite.Connection) -> None:
    """Create all tables. Idempotent — safe to call on every startup."""
    await db.execute(_PRAGMA_WAL)
    await db.execute(_CREATE_JOBS_TABLE)
    await db.commit()


async def init_db() -> None:
    """
    Initialise the database. Called from the FastAPI lifespan and ARQ worker startup.

    AGENT-CTX: Both the web process and the worker call this on startup.
    CREATE TABLE IF NOT EXISTS is idempotent — racing two startups is safe.
    """
    async with aiosqlite.connect(_get_db_path()) as db:
        await _create_tables(db)


async def get_db():
    """
    FastAPI dependency: yields an aiosqlite.Connection per request.

    AGENT-CTX: row_factory = aiosqlite.Row enables column-name access (row["col"])
    in all repository functions. Do NOT remove — jobs.py _row_to_* helpers depend on it.
    AGENT-CTX: The connection closes automatically when the request completes.
    Do not cache this connection or share it across requests.
    """
    async with aiosqlite.connect(_get_db_path()) as db:
        db.row_factory = aiosqlite.Row
        yield db
