"""
Tests for backend.provider — ProviderConfig registry and Ollama probe.

AGENT-CTX: These tests cover the two public functions:
  - get_provider_config() — pure env-var lookup, no I/O
  - probe_ollama_concurrency() — async HTTP call, monkeypatched here

No real HTTP calls are made. httpx.AsyncClient.get is monkeypatched via
a lightweight fake response class rather than unittest.mock so tests remain
readable and free of mock boilerplate.

AGENT-CTX: The probe tests verify the three outcomes that map to real scenarios:
  GPU model loaded (size_vram > 0)  → 2
  CPU-only model (size_vram == 0)   → 1
  Ollama unreachable / bad response → 1 (safe default)
"""

import pytest

from backend.provider import ProviderConfig, get_provider_config, probe_ollama_concurrency


# ── get_provider_config ───────────────────────────────────────────────────────

class TestGetProviderConfig:
    def test_returns_groq_config_by_default(self, monkeypatch):
        monkeypatch.delenv("LLM_PROVIDER", raising=False)
        config = get_provider_config()
        # Groq allows high concurrency — confirm it is clearly > 1
        assert config.extraction_concurrency > 1

    def test_returns_groq_config_when_explicitly_set(self, monkeypatch):
        monkeypatch.setenv("LLM_PROVIDER", "groq")
        config = get_provider_config()
        assert isinstance(config, ProviderConfig)
        assert config.extraction_concurrency == 10

    def test_returns_ollama_config_with_conservative_concurrency(self, monkeypatch):
        monkeypatch.setenv("LLM_PROVIDER", "ollama")
        config = get_provider_config()
        # AGENT-CTX: Ollama CPU default must be 1 — the fix for the TimeoutError bug.
        # If this assertion fails, the concurrency guard has been weakened; check
        # provider.py and the module docstring in worker.py before changing.
        assert config.extraction_concurrency == 1

    def test_falls_back_to_groq_for_unknown_provider(self, monkeypatch):
        """Unknown LLM_PROVIDER value returns Groq config (permissive default)."""
        monkeypatch.setenv("LLM_PROVIDER", "nonexistent_provider")
        config = get_provider_config()
        # Should not raise; falls back to Groq concurrency
        assert config.extraction_concurrency > 1

    def test_provider_config_is_immutable(self, monkeypatch):
        """ProviderConfig is frozen — fields cannot be mutated after construction."""
        monkeypatch.setenv("LLM_PROVIDER", "groq")
        config = get_provider_config()
        with pytest.raises((AttributeError, TypeError)):
            config.extraction_concurrency = 999  # type: ignore[misc]

    def test_ollama_config_has_positive_timeout_hint(self, monkeypatch):
        monkeypatch.setenv("LLM_PROVIDER", "ollama")
        config = get_provider_config()
        assert config.timeout_hint_s > 0

    def test_groq_config_has_positive_max_tokens(self, monkeypatch):
        monkeypatch.setenv("LLM_PROVIDER", "groq")
        config = get_provider_config()
        assert config.max_tokens_extraction > 0
        assert config.max_tokens_edge > 0


# ── probe_ollama_concurrency ──────────────────────────────────────────────────

class _FakeResponse:
    """Minimal httpx.Response stand-in for probe tests."""
    def __init__(self, status_code: int, body: dict | None = None):
        self.status_code = status_code
        self._body = body or {}

    def json(self):
        return self._body


class TestProbeOllamaConcurrency:
    @pytest.mark.asyncio
    async def test_returns_2_when_gpu_model_loaded(self, monkeypatch):
        """size_vram > 0 on any loaded model → GPU inference → concurrency 2."""
        async def mock_get(self, url, **kwargs):
            return _FakeResponse(200, {"models": [{"name": "llama3.1:8b", "size_vram": 4294967296}]})

        import httpx
        monkeypatch.setattr(httpx.AsyncClient, "get", mock_get)
        result = await probe_ollama_concurrency("http://localhost:11434")
        assert result == 2

    @pytest.mark.asyncio
    async def test_returns_1_when_cpu_only_model_loaded(self, monkeypatch):
        """size_vram == 0 → CPU inference → sequential (concurrency 1)."""
        async def mock_get(self, url, **kwargs):
            return _FakeResponse(200, {"models": [{"name": "llama3.1:8b", "size_vram": 0}]})

        import httpx
        monkeypatch.setattr(httpx.AsyncClient, "get", mock_get)
        result = await probe_ollama_concurrency("http://localhost:11434")
        assert result == 1

    @pytest.mark.asyncio
    async def test_returns_1_when_no_models_loaded(self, monkeypatch):
        """Empty models list → no inference possible → default to 1."""
        async def mock_get(self, url, **kwargs):
            return _FakeResponse(200, {"models": []})

        import httpx
        monkeypatch.setattr(httpx.AsyncClient, "get", mock_get)
        result = await probe_ollama_concurrency("http://localhost:11434")
        assert result == 1

    @pytest.mark.asyncio
    async def test_returns_1_on_non_200_status(self, monkeypatch):
        """Ollama returns an error status → safe default 1."""
        async def mock_get(self, url, **kwargs):
            return _FakeResponse(503)

        import httpx
        monkeypatch.setattr(httpx.AsyncClient, "get", mock_get)
        result = await probe_ollama_concurrency("http://localhost:11434")
        assert result == 1

    @pytest.mark.asyncio
    async def test_returns_1_on_connection_error(self, monkeypatch):
        """Connection refused (Ollama not running) → safe default 1, no exception raised."""
        async def mock_get(self, url, **kwargs):
            raise ConnectionRefusedError("Connection refused")

        import httpx
        monkeypatch.setattr(httpx.AsyncClient, "get", mock_get)
        result = await probe_ollama_concurrency("http://localhost:11434")
        assert result == 1

    @pytest.mark.asyncio
    async def test_returns_1_on_malformed_json(self, monkeypatch):
        """Ollama returns unparseable JSON → safe default 1, no exception raised."""
        class _BadJsonResponse:
            status_code = 200
            def json(self):
                raise ValueError("Not JSON")

        async def mock_get(self, url, **kwargs):
            return _BadJsonResponse()

        import httpx
        monkeypatch.setattr(httpx.AsyncClient, "get", mock_get)
        result = await probe_ollama_concurrency("http://localhost:11434")
        assert result == 1

    @pytest.mark.asyncio
    async def test_gpu_detection_uses_first_model_with_vram(self, monkeypatch):
        """Multiple models: first GPU-loaded one triggers the return value 2."""
        async def mock_get(self, url, **kwargs):
            return _FakeResponse(200, {"models": [
                {"name": "model-a", "size_vram": 0},
                {"name": "model-b", "size_vram": 2147483648},  # second model has GPU
            ]})

        import httpx
        monkeypatch.setattr(httpx.AsyncClient, "get", mock_get)
        result = await probe_ollama_concurrency("http://localhost:11434")
        assert result == 2
