"""
Centralised logging configuration for the MATA backend.

All processes (FastAPI web server + ARQ worker) call setup_logging() once at
startup. Both write to the same destinations:

  1. stdout — always present; captured by Render's log aggregation in production
              and visible in the local terminal during `make dev`.

  2. logs/mata.log — rotating file; useful for local debugging and staging.
                     Rotates at 5 MB, retains 3 backups (mata.log.1 … .3).
                     Disabled when LOG_DIR env var is set to "" (e.g. in CI).

Log record format:
    2026-04-09T14:30:00 | WARNING  | backend.llm | JSON decode error: …

The module name field (e.g. backend.llm, backend.edges, backend.worker) makes
per-module filtering trivial:
    grep "backend.llm" logs/mata.log

LOG_DIR defaults to ./logs relative to the process working directory (backend/
when launched via Makefile or render.yaml). Set LOG_DIR to an absolute path if
the process runs from a different working directory.

AGENT-CTX: setup_logging() is idempotent — safe to call from both the FastAPI
lifespan and ARQ worker startup() without double-adding handlers. The _configured
guard ensures the second caller is a no-op.
"""

import logging
import logging.handlers
import os
from pathlib import Path

_LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
_DATE_FORMAT = "%Y-%m-%dT%H:%M:%S"

_formatter = logging.Formatter(fmt=_LOG_FORMAT, datefmt=_DATE_FORMAT)

_configured = False

# TODO: Add LLM call instrumentation (latency, token usage per call).
# Design: new llm_instrument.py with a frozen LLMCallResult dataclass and a
# single log_llm_call() function. The four provider call functions (_groq_call,
# _ollama_call, _groq_edge_call, _ollama_edge_call) return LLMCallResult instead
# of str; _raw_llm_call / classify_edges_via_llm log it and strip back to str.
# Groq: completion.usage has exact token counts at no extra cost.
# Ollama: resp.json()["usage"] on the OpenAI-compat /v1/chat/completions response.
# Latency: time.perf_counter() wrapping the asyncio.to_thread / httpx call.


def setup_logging(level: int = logging.INFO) -> None:
    """
    Configure the root logger with a console handler and an optional rotating
    file handler.

    Args:
        level: Root logger level (default INFO). Set to logging.DEBUG for
               verbose output during local development.

    AGENT-CTX: Idempotent — the _configured guard prevents double-handler
    registration when both FastAPI lifespan and ARQ worker startup() call this.
    In production both run in the same container but as separate processes,
    so each process configures its own logger independently (no shared state).
    """
    global _configured
    if _configured:
        return
    _configured = True

    root = logging.getLogger()
    root.setLevel(level)

    # ── Console handler ──────────────────────────────────────────────────────
    # Always present. Render captures stdout/stderr; local dev sees it in terminal.
    console = logging.StreamHandler()
    console.setFormatter(_formatter)
    root.addHandler(console)

    # ── File handler ─────────────────────────────────────────────────────────
    # Disabled when LOG_DIR="" (CI, unit tests that call setup_logging directly).
    # Defaults to ./logs/mata.log relative to CWD (backend/ in normal operation).
    log_dir_str = os.environ.get("LOG_DIR", "./logs")
    if not log_dir_str:
        return  # File logging explicitly disabled

    log_dir = Path(log_dir_str)
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        file_handler = logging.handlers.RotatingFileHandler(
            log_dir / "mata.log",
            maxBytes=5 * 1024 * 1024,  # 5 MB per file
            backupCount=3,             # mata.log, mata.log.1, mata.log.2, mata.log.3
            encoding="utf-8",
        )
        file_handler.setFormatter(_formatter)
        root.addHandler(file_handler)
    except OSError as exc:
        # Can't create the log directory (permission error, read-only FS, etc.).
        # Log the warning to console only and continue — file logging is best-effort.
        logging.getLogger(__name__).warning(
            "Could not initialise file logging at %s: %s", log_dir, exc
        )
