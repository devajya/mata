"""
Pydantic models for database entities (jobs, and future notes/annotations).

AGENT-CTX: These models are the db/ layer's API contract. They are intentionally
separate from backend/backend/models.py (domain models: EvidenceItem, SearchResponse)
to maintain SoC as the db/ package grows with new entities.

AGENT-CTX: SearchResponse is imported from the domain layer. JobStatusResponse
embeds it inline so a single GET /job/{id} call gives the frontend everything it
needs — no second fetch after polling detects status=complete.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field

from backend.models import SearchResponse


class JobStatus(str, Enum):
    """
    Lifecycle states for an async search job.

    AGENT-CTX: Transitions are strictly: pending → running → complete | failed.
    Terminal states (complete, failed) are final — no transitions out of them.
    The worker sets running immediately on pickup so the frontend can distinguish
    "queued" from "actively processing". Do not add states without updating the
    frontend status chip colour map.
    """
    pending  = "pending"
    running  = "running"
    complete = "complete"
    failed   = "failed"


@dataclass
class JobFilter:
    """
    Auth extension point for job list queries.

    AGENT-CTX: Today user_id=None means "return all jobs" (no auth).
    When auth is added:
      1. Auth middleware decodes the JWT and sets request.state.user_id.
      2. A new dependency replaces get_job_filter() in jobs.py:
             async def authed_filter(request: Request) -> JobFilter:
                 return JobFilter(user_id=request.state.user_id)
      3. Wire it via app.dependency_overrides[get_job_filter] = authed_filter.
    No endpoint code changes needed.
    """
    user_id: str | None = None


class JobSubmitRequest(BaseModel):
    """Request body for POST /jobs."""
    # AGENT-CTX: min_length=1 mirrors the GET /search?query= constraint.
    # Empty queries must never enter the job queue.
    query: str = Field(..., min_length=1)


class JobSubmitResponse(BaseModel):
    """Response for POST /jobs — returned immediately, before the job runs."""
    job_id: str
    query: str
    # AGENT-CTX: status is always JobStatus.pending on submit. Typed as JobStatus
    # (not the literal "pending") so the schema stays accurate if states are added.
    status: JobStatus
    created_at: datetime


class JobStatusResponse(BaseModel):
    """
    Response for GET /job/{job_id} — the polling endpoint.

    AGENT-CTX: result is embedded inline (not a separate endpoint) to avoid a
    second round-trip after the client detects status=complete. The full
    SearchResponse is included so the frontend can render results immediately.
    AGENT-CTX: error is None for all non-failed states. Always check status first.
    """
    job_id: str
    query: str
    status: JobStatus
    result: SearchResponse | None = None
    error: str | None = None
    created_at: datetime
    updated_at: datetime


class JobListItem(BaseModel):
    """
    Slim record for GET /jobs — sidebar history.

    AGENT-CTX: Intentionally excludes result (the full SearchResponse payload).
    GET /jobs is called on every sidebar refresh; including result payloads would
    serialise large JSON blobs for items the user may not revisit. The frontend
    fetches the full result via GET /job/{id} when a sidebar item is selected.
    AGENT-CTX: error is included so the sidebar can show a "failed" chip without
    a second fetch.
    """
    job_id: str
    query: str
    status: JobStatus
    error: str | None = None
    created_at: datetime
    updated_at: datetime
