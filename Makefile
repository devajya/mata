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
	@echo "─────────────────────────────────────────────"
	@echo "  make install        Install backend + frontend deps"
	@echo ""
	@echo "  make test           Run backend tests (NO live API calls) ← default"
	@echo "  make test-local     Run ALL backend tests using local Ollama (no Groq tokens)"
	@echo "                      Requires: ollama serve + llama-3.1-8b-instant alias"
	@echo "  make test-live      Run live backend tests against real Groq + PubMed APIs"
	@echo "                      (requires GROQ_API_KEY + NCBI_API_KEY in backend/.env)"
	@echo "  make test-e2e       [T9] Smoke test against deployed Vercel + Render + Groq"
	@echo ""
	@echo "  make dev            Start backend (:8000) + frontend (:3000) using Groq"
	@echo "  make dev-local      Start backend (:8000) + frontend (:3000) using local Ollama"
	@echo "  make frontend-dev   Start frontend dev server on :3000 only"
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
# Only use `make test-local` or `make test-live` when you need live API behaviour.
# AGENT-CTX: Excludes both `live` (hits real Groq/PubMed) and `e2e` (hits deployed URLs).
# This ensures `make test` is always fast, deterministic, and requires no network access.
test:
	@cd $(BACKEND) && set -a && . .env && set +a && \
		.venv/bin/python -m pytest -m "not live and not e2e" -v

# AGENT-CTX: `make test-local` runs the full test suite (including @live tests)
# with Groq redirected to local Ollama. No Groq tokens consumed.
# Requires Ollama running with llama-3.1-8b-instant alias:
#   ollama serve
#   echo "FROM llama3.1:8b" | ollama create llama-3.1-8b-instant -f -
# .env is loaded first for NCBI_API_KEY etc., then .env.local overrides GROQ_* vars.
test-local:
	@cd $(BACKEND) && set -a && . .env && . .env.local && set +a && \
		{ curl -sf "$$OLLAMA_BASE_URL/api/tags" > /dev/null || { echo "ERROR: Ollama not reachable at $$OLLAMA_BASE_URL. Is OLLAMA_HOST=0.0.0.0 set on Windows?"; exit 1; }; } && \
		.venv/bin/python -m pytest -v

# AGENT-CTX: `make test-live` hits real PubMed + Groq APIs.
# Requires valid GROQ_API_KEY in backend/.env.
# Free tier limits apply — run sparingly to avoid exhausting daily quota.
test-live:
	@cd $(BACKEND) && set -a && . .env && set +a && \
		.venv/bin/python -m pytest -m live -v

# AGENT-CTX: `make test-e2e` runs smoke tests against the DEPLOYED stack.
# Reads target URLs from backend/.env.e2e (no secrets — public URLs only).
# Does NOT require GROQ_API_KEY locally — it calls the deployed Render service,
# which uses its own GROQ_API_KEY set as a Render environment variable.
# AGENT-CTX: Render free tier cold-starts in 30-60s — the 120s search timeout
# in test_e2e.py accounts for this. The first run after idle may be slow.
test-e2e:
	@cd $(BACKEND) && set -a && . .env.e2e && set +a && \
		.venv/bin/python -m pytest -m e2e tests/test_e2e.py -v -s

# ── Dev servers ────────────────────────────────────────────────────────────────

dev:
	@trap 'kill 0' INT TERM; \
	(cd $(BACKEND) && set -a && . .env && set +a && \
		.venv/bin/uvicorn backend.main:app --reload --port 8000) & \
	(cd $(FRONTEND) && npm run dev) & \
	wait

# AGENT-CTX: `make dev-local` is identical to `make dev` but layers .env.local on top,
# redirecting Groq SDK calls to local Ollama. No Groq tokens consumed during development.
# Requires Ollama running: ollama serve
dev-local:
	@cd $(BACKEND) && set -a && . .env && . .env.local && set +a && \
		{ curl -sf "$$OLLAMA_BASE_URL/api/tags" > /dev/null || { echo "ERROR: Ollama not reachable at $$OLLAMA_BASE_URL. Is OLLAMA_HOST=0.0.0.0 set on Windows?"; exit 1; }; }
	@trap 'kill 0' INT TERM; \
	(cd $(BACKEND) && set -a && . .env && . .env.local && set +a && \
		.venv/bin/uvicorn backend.main:app --reload --port 8000) & \
	(cd $(FRONTEND) && npm run dev) & \
	wait

# ── Frontend ───────────────────────────────────────────────────────────────────

frontend-test:
	cd $(FRONTEND) && npm test

frontend-dev:
	cd $(FRONTEND) && npm run dev
