SHELL := /bin/bash
BACKEND  := backend
FRONTEND := frontend

# AGENT-CTX: .DEFAULT_GOAL ensures `make` with no args prints help, not runs tests.
# This prevents accidental API calls when a developer just types `make`.
.DEFAULT_GOAL := help

.PHONY: help \
        install \
        test test-live \
        dev \
        frontend-install frontend-test frontend-dev

# ── Help ───────────────────────────────────────────────────────────────────────

help:
	@echo ""
	@echo "MATA — available commands"
	@echo "─────────────────────────────────────────────"
	@echo "  make install        Install backend + frontend deps"
	@echo ""
	@echo "  make test           Run backend tests (NO live API calls) ← default"
	@echo "  make test-live      Run backend tests that hit real APIs"
	@echo "                      (requires GROQ_API_KEY + NCBI_API_KEY in backend/.env)"
	@echo ""
	@echo "  make dev            Start backend dev server on :8000 (hot-reload)"
	@echo "  make frontend-dev   Start frontend dev server on :3000"
	@echo ""
	@echo "  make frontend-test  Run frontend jest tests"
	@echo "─────────────────────────────────────────────"
	@echo ""

# ── Install ────────────────────────────────────────────────────────────────────

install: backend-install frontend-install

backend-install:
	cd $(BACKEND) && uv pip install -e ".[dev]"

frontend-install:
	cd $(FRONTEND) && npm install

# ── Backend tests ──────────────────────────────────────────────────────────────

# AGENT-CTX: `make test` is the STANDARD test command for this project.
# It ALWAYS runs with -m "not live" so it never touches real APIs.
# Use this in CI, pre-commit hooks, and local development by default.
# Only use `make test-live` when you explicitly want to verify live API behaviour.
test:
	@cd $(BACKEND) && set -a && . .env && set +a && \
		.venv/bin/python -m pytest -m "not live" -v

# AGENT-CTX: `make test-live` hits real PubMed + Groq APIs.
# Requires valid GROQ_API_KEY in backend/.env.
# Free tier limits apply — run sparingly to avoid exhausting daily quota.
test-live:
	@cd $(BACKEND) && set -a && . .env && set +a && \
		.venv/bin/python -m pytest -m live -v

# ── Backend dev server ─────────────────────────────────────────────────────────

dev:
	@cd $(BACKEND) && set -a && . .env && set +a && \
		.venv/bin/uvicorn backend.main:app --reload --port 8000

# ── Frontend ───────────────────────────────────────────────────────────────────

frontend-test:
	cd $(FRONTEND) && npm test

frontend-dev:
	cd $(FRONTEND) && npm run dev
