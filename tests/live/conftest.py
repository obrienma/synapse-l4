"""
Reachability probe for the live Ollama test tier (ADR-0008).

Pattern: Circuit-Breaker Skip
  Tests in this tier require a real Ollama host. Rather than failing when the
  host happens to be off, the probe skips with a clear reason — host downtime
  is not a code defect, and conflating the two makes failures meaningless.
"""

import httpx
import pytest

from config import settings


def _tags_url(base_url: str) -> str:
    return base_url.rstrip("/").removesuffix("/v1") + "/api/tags"


@pytest.fixture(autouse=True, scope="module")
def _require_ollama_reachable() -> None:
    if not settings.llm_base_url:
        pytest.skip("LLM_BASE_URL not configured — live tier requires it")

    url = _tags_url(settings.llm_base_url)
    try:
        response = httpx.get(url, timeout=2.0)
        response.raise_for_status()
    except httpx.HTTPError as exc:
        pytest.skip(f"Ollama host unreachable: {exc}")
