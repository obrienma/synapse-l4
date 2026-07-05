"""
Live test tier (ADR-0008) — exercises extract()'s LLM path against a real
Ollama endpoint. Skipped entirely if LLM_BASE_URL is unset or the host is
unreachable (see conftest.py).

Pattern: Validator-as-Judge, applied to the model itself
  These tests don't check the *content* of the model's output — a real
  model's answer to an ambiguous fixture isn't reproducible run to run.
  They check that the output still conforms to the AxiomDraft contract:
  valid enum values, valid score range. That's the one thing worth proving
  live that a mock can't prove.
"""

import pytest

from src.models.axiom import AxiomDraft, RawTelemetry
from src.nodes.extractor import extract

# Deliberately unstructured — misses both _try_direct_extraction shapes,
# so the LLM path is actually exercised. Reused from extractor_test.py.
_UNSTRUCTURED_PAYLOAD = {"raw_log": "disk_full on /var", "node": "staging-02"}


@pytest.mark.asyncio
async def test_extract_produces_schema_conformant_draft_from_real_model() -> None:
    telemetry = RawTelemetry(source_id="live-sensor-01", payload=_UNSTRUCTURED_PAYLOAD)

    result = await extract(telemetry)

    assert isinstance(result, AxiomDraft)
    assert result.status in ("nominal", "degraded", "critical")
    assert 0.0 <= result.anomaly_score <= 1.0
    assert result.domain in ("aml", "gdpr", "hipaa", None)
