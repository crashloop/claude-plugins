"""Test isolation: no real model, no real LLM endpoint, ever."""
import pytest


@pytest.fixture(autouse=True)
def isolate_externals(tmp_path_factory, monkeypatch):
    """Semantic and local_llm always take their documented skip path."""
    cache = tmp_path_factory.mktemp("hoolint-cache")
    monkeypatch.setenv("HOOLINT_CACHE_DIR", str(cache))   # marker absent
    monkeypatch.setenv("HOOLINT_LLM_BASE_URL", "http://127.0.0.1:1")  # closed
