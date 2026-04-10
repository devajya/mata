/**
 * API client — single module that owns all backend communication.
 *
 * Responsibilities:
 *   - Centralises API_URL so env-var changes propagate from one place.
 *   - Wraps every endpoint in a typed function so callers never construct
 *     URLs or parse error shapes themselves.
 *   - Owns the error-to-message conversion so duplicate try/catch blocks
 *     in page.tsx and hooks are eliminated.
 *
 * SRP boundaries:
 *   - This file: network + serialisation only. No React state, no side effects.
 *   - Hooks: React lifecycle + state management. Call these functions, own state.
 *   - Components: rendering only. Receive data from hooks.
 *
 * Do NOT import from app/, components/, or hooks/ — this file must stay
 * dependency-free to avoid circular imports.
 */

import {
  JobListItem,
  JobStatusResponse,
  JobSubmitResponse,
} from "../types";

export const API_URL =
  process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

// ── Typed error ───────────────────────────────────────────────────────────────

/**
 * Thrown by API functions when the server returns a non-2xx response.
 * `.message` is always a user-displayable string (from body.detail or a
 * generic status fallback). Callers can surface it directly in UI error state.
 */
export class ApiError extends Error {
  constructor(message: string, public readonly status?: number) {
    super(message);
    this.name = "ApiError";
  }
}

// ── Private helpers ───────────────────────────────────────────────────────────

/**
 * Extract a user-facing message from a non-OK response.
 * Prefers body.detail (FastAPI's default HTTPException shape); falls back to
 * a generic status string. Never throws — called only inside error paths.
 */
async function extractErrorMessage(response: Response): Promise<string> {
  try {
    const body = await response.json();
    if (body?.detail) return String(body.detail);
  } catch { /* JSON parse failed — fall through */ }
  return `Request failed with status ${response.status}`;
}

// ── Endpoint functions ────────────────────────────────────────────────────────

/**
 * POST /jobs — submit a search query and return the pending job record.
 *
 * Throws ApiError on server error (non-2xx) or network failure.
 * Callers catch ApiError and set their error state from `e.message`.
 */
export async function submitJob(query: string): Promise<JobSubmitResponse> {
  let response: Response;
  try {
    response = await fetch(`${API_URL}/jobs`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query }),
    });
  } catch {
    throw new ApiError("Network error — could not reach the server.");
  }
  if (!response.ok) {
    throw new ApiError(await extractErrorMessage(response), response.status);
  }
  return response.json() as Promise<JobSubmitResponse>;
}

/**
 * GET /job/{jobId} — poll a single job's status.
 *
 * Returns null when the job is not found (404) — callers should stop polling.
 * Throws on network failure so the polling loop can catch and retry.
 * Throws ApiError on unexpected server errors (5xx) so they are retried too,
 * not silently swallowed.
 */
export async function fetchJob(
  jobId: string,
): Promise<JobStatusResponse | null> {
  const response = await fetch(`${API_URL}/job/${jobId}`);
  if (response.status === 404) return null;
  if (!response.ok) {
    throw new ApiError(await extractErrorMessage(response), response.status);
  }
  return response.json() as Promise<JobStatusResponse>;
}

/**
 * GET /jobs — fetch the full job history list.
 *
 * Returns the list on success. Throws on network or server failure
 * (callers are expected to catch silently for non-fatal sidebar errors).
 */
export async function fetchJobs(): Promise<JobListItem[]> {
  const response = await fetch(`${API_URL}/jobs`);
  if (!response.ok) {
    throw new ApiError(await extractErrorMessage(response), response.status);
  }
  return response.json() as Promise<JobListItem[]>;
}

/**
 * DELETE /job/{jobId} — remove a job record from history.
 *
 * Best-effort: the caller proceeds regardless of whether this succeeds.
 * Swallows all errors internally — no throw — so callers need no try/catch.
 */
export async function deleteJob(jobId: string): Promise<void> {
  try {
    await fetch(`${API_URL}/job/${jobId}`, { method: "DELETE" });
  } catch { /* best-effort; caller proceeds unconditionally */ }
}
