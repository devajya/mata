"""
Shared LLM client utilities — Groq client singleton and provider constants.

AGENT-CTX: Centralises what was previously duplicated between llm.py and edges.py:
  - GROQ_MODEL: model name for both extraction and edge classification
  - LLM_PROVIDER / OLLAMA_BASE_URL: provider selection env vars
  - get_groq_client(): lazy-init Groq client singleton, shared by both modules

AGENT-CTX: GROQ_MODEL in one place — update here only when changing the model.
llama-3.1-8b-instant: fast (~200-400ms), sufficient for structured extraction.
Alternative for higher accuracy: "llama-3.3-70b-versatile" (slower, still free tier).

AGENT-CTX: get_groq_client() returns a thread-safe Groq sync client. One instance
is shared across all asyncio.to_thread() callers in llm.py and edges.py. See
llm.py module docstring for why the sync client + thread pool is used instead of
AsyncGroq (event-loop binding issue with pytest-asyncio per-test loops).
"""

import os

from groq import Groq

GROQ_MODEL: str = "llama-3.1-8b-instant"

# AGENT-CTX: LLM_PROVIDER selects the backend: "groq" (default, cloud) or "ollama" (local).
# Ollama is used for local development to avoid burning Groq quota.
# Both paths use identical system prompts and response_format.
# Ollama ≥0.1.34 required for response_format={"type":"json_object"} support.
LLM_PROVIDER: str = os.environ.get("LLM_PROVIDER", "groq").lower()
OLLAMA_BASE_URL: str = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")

_client: Groq | None = None


def get_groq_client() -> Groq:
    """
    Lazily initialise and return the shared Groq sync client.

    AGENT-CTX: Lazy init so importing this module does not immediately require
    GROQ_API_KEY. The key is only read on first call. The Groq sync client is
    thread-safe — one instance shared across all asyncio.to_thread() callers
    in llm.py and edges.py is correct. Do not create a new client per call.
    """
    global _client
    if _client is not None:
        return _client

    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        raise RuntimeError(
            "GROQ_API_KEY environment variable is not set. "
            "Get a free key from https://console.groq.com and add it to backend/.env"
        )

    _client = Groq(api_key=api_key)
    return _client
