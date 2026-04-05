SHELL := /bin/bash
BACKEND  := backend
FRONTEND := frontend

# AGENT-CTX: .DEFAULT_GOAL ensures `make` with no args prints help, not runs tests.
# This prevents accidental API calls when a developer just types `make`.
.DEFAULT_GOAL := help

.PHONY: help \
        install \
        test test-local test-live test-e2e \
        dev dev-local \
        frontend-install frontend-test frontend-dev

# ── Help ───────────────────────────────────────────────────────────────────────

help:
	@echo ""
	@echo "MATA — available commands"
	@echo "─────────────────────────────────────────────────────────────────────"
	@echo "TESTING"
	@echo "  make test           Safe default: mocked backend tests only, no real APIs"
	@echo "                      84 tests — unit + endpoint + job-pipeline (all mocked)"
	@echo ""
	@echo "  make test-local     Full backend suite using LOCAL Ollama instead of Groq"
	@echo "                      ~87 tests (adds 3 @live worker tests via Ollama + PubMed)"
	@echo "                      Excludes @e2e (those need a deployed server + make test-e2e)"
	@echo "                      Requires: ollama serve + llama-3.1-8b-instant alias"
	@echo ""
	@echo "  make test-live      @live tests only, against real Groq + PubMed APIs"
	@echo "                      ~9 tests — burns Groq quota, run sparingly"
	@echo "                      Requires: GROQ_API_KEY in backend/.env"
	@echo ""
	@echo "  make test-e2e       Smoke test the DEPLOYED stack (Render + Vercel + Groq)"
	@echo "                      Requires: backend/.env.e2e with deployed URLs"
	@echo ""
	@echo "  make frontend-test  Jest tests for the Next.js frontend (15 tests, all mocked)"
	@echo ""
	@echo "DEV SERVERS"
	@echo "  make dev            All 3 processes: uvicorn + ARQ worker + Next.js (Groq)"
	@echo "                      Requires: GROQ_API_KEY + REDIS_URL in backend/.env"
	@echo ""
	@echo "  make dev-local      All 3 processes: uvicorn + ARQ worker + Next.js (Ollama)"
	@echo "                      Requires: ollama serve + REDIS_URL in backend/.env"
	@echo ""
	@echo "  make frontend-dev   Next.js dev server only (:3000)"
	@echo "─────────────────────────────────────────────────────────────────────"
	@echo ""

# ── Install ────────────────────────────────────────────────────────────────────

install: backend-install frontend-install

backend-install:
	cd $(BACKEND) && uv pip install -e ".[dev]"

frontend-install:
	cd $(FRONTEND) && npm install

# ── Backend tests ──────────────────────────────────────────────────────────────

# AGENT-CTX: `make test` is the STANDARD test command for this project.
# Excludes `live` (real Groq/PubMed) and `e2e` (deployed URLs).
# 84 tests — always fast, deterministic, no network access required.
# Covers: unit logic, endpoint wiring, job repository, worker pipeline (mocked).
test:
	@cd $(BACKEND) && set -a && . .env && set +a && \
		.venv/bin/python -m pytest -m "not live and not e2e" -v

# AGENT-CTX: `make test-local` runs the full test suite including @live tests,
# but redirects Groq SDK to local Ollama (via .env.local). No Groq tokens consumed.
# The 3 @live worker tests exercise the full job pipeline:
#   run_search_job() → real PubMed fetch → real Ollama LLM → SQLite persistence
# No Redis or running server is needed — the worker function is called directly.
# Requires: ollama serve + llama-3.1-8b-instant alias created.
test-local:
	@cd $(BACKEND) && set -a && . .env && . .env.local && set +a && \
		{ curl -sf "$$OLLAMA_BASE_URL/api/tags" > /dev/null || { echo "ERROR: Ollama not reachable at $$OLLAMA_BASE_URL. Is OLLAMA_HOST=0.0.0.0 set on Windows?"; exit 1; }; } && \
		.venv/bin/python -m pytest -m "not e2e" -v

# AGENT-CTX: `make test-live` runs only @live-marked tests against real Groq + PubMed.
# Free tier limits apply — run sparingly to avoid exhausting daily quota (~9 tests).
test-live:
	@cd $(BACKEND) && set -a && . .env && set +a && \
		.venv/bin/python -m pytest -m live -v

# AGENT-CTX: `make test-e2e` smoke-tests the DEPLOYED stack (Render backend + Groq).
# Reads target URLs from backend/.env.e2e (no secrets — public URLs only).
# Does NOT require local GROQ_API_KEY — calls the deployed Render service instead.
# Render free tier cold-starts in 30-60s — the 120s timeout in test_e2e.py covers this.
test-e2e:
	@cd $(BACKEND) && set -a && . .env.e2e && set +a && \
		.venv/bin/python -m pytest -m e2e tests/test_e2e.py -v -s

# ── Dev servers ────────────────────────────────────────────────────────────────

# AGENT-CTX: `make dev` starts all three processes needed for the full local stack:
#   1. uvicorn — FastAPI web server on :8000
#   2. arq worker — picks up jobs from Redis and runs the search pipeline
#   3. Next.js — frontend on :3000
# Requires GROQ_API_KEY + REDIS_URL in backend/.env (Upstash URL works).
# All three processes share a kill signal via `trap 'kill 0' INT TERM`.
# If the ARQ worker fails to connect to Redis it logs an error but does not crash
# uvicorn — POST /jobs will return 503 until Redis is reachable.
dev:
	@trap 'kill 0' INT TERM; \
	(cd $(BACKEND) && set -a && . .env && set +a && \
		.venv/bin/uvicorn backend.main:app --reload --port 8000) & \
	(cd $(BACKEND) && set -a && . .env && set +a && \
		.venv/bin/arq backend.worker.WorkerSettings) & \
	(cd $(FRONTEND) && npm run dev) & \
	wait

# AGENT-CTX: `make dev-local` is identical to `make dev` but layers .env.local on top,
# redirecting Groq SDK calls to local Ollama. No Groq tokens consumed.
# The ARQ worker also uses Ollama (GROQ_BASE_URL from .env.local is inherited).
# Requires: ollama serve + REDIS_URL in backend/.env.
dev-local:
	@cd $(BACKEND) && set -a && . .env && . .env.local && set +a && \
		{ curl -sf "$$OLLAMA_BASE_URL/api/tags" > /dev/null || { echo "ERROR: Ollama not reachable at $$OLLAMA_BASE_URL. Is OLLAMA_HOST=0.0.0.0 set on Windows?"; exit 1; }; }
	@trap 'kill 0' INT TERM; \
	(cd $(BACKEND) && set -a && . .env && . .env.local && set +a && \
		.venv/bin/uvicorn backend.main:app --reload --port 8000) & \
	(cd $(BACKEND) && set -a && . .env && . .env.local && set +a && \
		.venv/bin/arq backend.worker.WorkerSettings) & \
	(cd $(FRONTEND) && npm run dev) & \
	wait

# ── Frontend ───────────────────────────────────────────────────────────────────

# AGENT-CTX: --forceExit prevents Jest from hanging after tests complete.
# The useJobHistory hook's async fetch (GET /jobs) can keep the event loop alive
# after tests finish — --forceExit terminates cleanly without masking failures.
frontend-test:
	cd $(FRONTEND) && npm test -- --forceExit

frontend-dev:
	cd $(FRONTEND) && npm run dev
