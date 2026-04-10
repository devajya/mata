"""
SQLite connection management and schema initialisation.

AGENT-CTX: SQLite is the job state store for Milestone 3. It is sufficient for a
single-process deployment (web + worker in the same container — see render.yaml).
If horizontal scaling is ever needed, migrate to PostgreSQL + asyncpg; the
repository interface in jobs.py does not need to change.

AGENT-CTX: Schema migrations are applied at startup via _run_migrations().
Migrations are append-only: never edit or delete an existing entry — always add
a new one with the next version number. The runner applies all unapplied
migrations in version order and is idempotent (safe to call multiple times).
Each migration is committed atomically with its version record, so a failed
migration does not advance the version and is retried on the next startup.

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

# ── Pragmas ─────────────────────────────────────────────────────────────────────

# AGENT-CTX: WAL journal mode allows one writer and multiple concurrent readers.
# Without WAL, a writer holds an exclusive lock blocking all readers. With WAL,
# the worker can write results while the web process reads job status simultaneously.
_PRAGMA_WAL = "PRAGMA journal_mode=WAL;"

# AGENT-CTX: busy_timeout tells SQLite to retry for up to N milliseconds when it
# encounters a locked database (SQLITE_BUSY) instead of immediately raising
# OperationalError. 5000ms covers the startup race where both the uvicorn process
# and the ARQ worker call init_db() concurrently — one will wait rather than fail.
# Without this, the second process to start always errors with "database is locked"
# even though the lock is held for only a few milliseconds.
_PRAGMA_BUSY_TIMEOUT = "PRAGMA busy_timeout=5000;"


# ── Schema version table ─────────────────────────────────────────────────────────

# AGENT-CTX: schema_version tracks the highest applied migration version.
# A fresh database has no rows (MAX(version) returns NULL → treated as 0).
# One row is inserted per applied migration. IF NOT EXISTS makes this safe
# to run against a pre-migration database that lacks the table.
_CREATE_SCHEMA_VERSION_TABLE = """
CREATE TABLE IF NOT EXISTS schema_version (
    version  INTEGER NOT NULL
);
"""


# ── Migrations ───────────────────────────────────────────────────────────────────
#
# AGENT-CTX: Each entry is (version: int, sql: str). Rules:
#   - Versions must be contiguous integers starting at 1.
#   - NEVER edit or delete an existing entry. The runner uses MAX(version) to
#     determine what has been applied; gaps or reordering will cause migrations
#     to be skipped or re-applied incorrectly.
#   - Each SQL string may contain multiple DDL statements separated by semicolons.
#     The runner splits on ";" and executes each non-empty statement individually.
#     Avoid semicolons inside string literals in migration SQL (DDL-only is safe).
#   - To add a schema change: append (next_version, "ALTER TABLE ...") and deploy.
#     The runner applies it exactly once to any DB behind that version.
#
_MIGRATIONS: list[tuple[int, str]] = [
    # v1 — initial schema: jobs table
    (1, """
        CREATE TABLE IF NOT EXISTS jobs (
            job_id      TEXT    PRIMARY KEY,
            query       TEXT    NOT NULL,
            status      TEXT    NOT NULL DEFAULT 'pending',
            result_json TEXT,
            error       TEXT,
            created_at  REAL    NOT NULL,
            updated_at  REAL    NOT NULL,
            user_id     TEXT
        )
    """),
    # Add future migrations here, for example:
    # (2, "ALTER TABLE jobs ADD COLUMN priority INTEGER NOT NULL DEFAULT 0"),
    # (3, "CREATE INDEX IF NOT EXISTS idx_jobs_user_id ON jobs (user_id)"),
]


# ── Migration runner ─────────────────────────────────────────────────────────────

async def _run_migrations(db: aiosqlite.Connection) -> None:
    """
    Apply any unapplied schema migrations in ascending version order.

    AGENT-CTX: Idempotent — safe to call on every startup from both the uvicorn
    process and the ARQ worker. Already-applied versions are skipped by comparing
    against MAX(version) in schema_version.

    AGENT-CTX: Each migration is committed in a single transaction together with
    its version record. If the migration SQL fails, neither the schema change nor
    the version insert is committed — the DB stays at the previous version and
    the same migration is retried on the next startup. This gives clear "retry
    on failure" semantics without leaving the DB in a half-migrated state.

    AGENT-CTX: Pragmas are applied before any writes so that busy_timeout and
    WAL mode are active during the migration itself, covering the concurrent
    startup race between uvicorn and the ARQ worker.
    """
    await db.execute(_PRAGMA_BUSY_TIMEOUT)
    await db.execute(_PRAGMA_WAL)

    # Bootstrap the version tracker. IF NOT EXISTS makes this safe against
    # pre-migration databases that don't yet have the schema_version table.
    await db.execute(_CREATE_SCHEMA_VERSION_TABLE)
    await db.commit()

    # Read the highest applied version. NULL (fresh DB) → 0.
    async with db.execute("SELECT MAX(version) FROM schema_version") as cursor:
        row = await cursor.fetchone()
    current_version: int = row[0] if (row and row[0] is not None) else 0

    for version, sql in _MIGRATIONS:
        if version <= current_version:
            continue  # already applied — skip

        # Execute each DDL statement in the migration block individually.
        # Splitting on ";" is safe for DDL-only migrations (no string literals).
        for statement in sql.split(";"):
            statement = statement.strip()
            if statement:
                await db.execute(statement)

        # Record the applied version in the same transaction as the migration
        # so they succeed or fail atomically.
        await db.execute(
            "INSERT INTO schema_version (version) VALUES (?)", (version,)
        )
        await db.commit()


# ── Public interface ─────────────────────────────────────────────────────────────

def _get_db_path() -> str:
    """Return DB file path, read from environment at call time."""
    return os.environ.get("SQLITE_DB_PATH", "./mata.db")


async def init_db() -> None:
    """
    Initialise the database. Called from the FastAPI lifespan and ARQ worker startup.

    AGENT-CTX: Both the web process and the worker call this on startup.
    _run_migrations() is idempotent — racing two startups is safe because
    busy_timeout causes the second caller to wait rather than fail, and the
    version check prevents any migration from being applied twice.
    """
    async with aiosqlite.connect(_get_db_path()) as db:
        await _run_migrations(db)


async def get_db():
    """
    FastAPI dependency: yields an aiosqlite.Connection per request.

    AGENT-CTX: row_factory = aiosqlite.Row enables column-name access (row["col"])
    in all repository functions. Do NOT remove — jobs.py _row_to_* helpers depend on it.
    AGENT-CTX: The connection closes automatically when the request completes.
    Do not cache this connection or share it across requests.
    AGENT-CTX: busy_timeout applied here too — not just at init — so that concurrent
    API requests (e.g. POST /jobs while worker is writing a result) retry on lock
    rather than returning a 500 to the frontend.
    """
    async with aiosqlite.connect(_get_db_path()) as db:
        db.row_factory = aiosqlite.Row
        await db.execute(_PRAGMA_BUSY_TIMEOUT)
        yield db
