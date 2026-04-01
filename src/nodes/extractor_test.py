from unittest.mock import AsyncMock, MagicMock

import pytest

from src.models.axiom import AxiomDraft, ExtractionError, RawTelemetry
from src.nodes.extractor import extract


# ── Fixtures ──────────────────────────────────────────────────────────────────

def make_telemetry(**overrides: object) -> RawTelemetry:
    defaults: dict[str, object] = {
        "source_id": "sensor-01",
        "payload": {"raw_log": "CPU at 94% for 60s on prod-01", "tags": ["cpu", "prod"]},
    }
    return RawTelemetry(**(defaults | overrides))


def make_mock_client(return_value: object | None = None, side_effect: Exception | None = None) -> MagicMock:
    """Build a mock Instructor AsyncInstructor client."""
    client = MagicMock()
    client.chat = MagicMock()
    client.chat.completions = MagicMock()
    mock_create = AsyncMock()
    if side_effect is not None:
        mock_create.side_effect = side_effect
    else:
        mock_create.return_value = return_value
    client.chat.completions.create = mock_create
    return client


# ── Success path ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_extract_returns_axiom_draft_on_success() -> None:
    expected = AxiomDraft(status="critical", metric_value=94.0, anomaly_score=0.89)
    client = make_mock_client(return_value=expected)

    result = await extract(make_telemetry(), client=client)

    assert isinstance(result, AxiomDraft)
    assert result.status == "critical"
    assert result.metric_value == 94.0
    assert result.anomaly_score == 0.89


@pytest.mark.asyncio
async def test_extract_calls_client_with_source_id_in_message() -> None:
    client = make_mock_client(
        return_value=AxiomDraft(status="nominal", metric_value=10.0, anomaly_score=0.1)
    )

    await extract(make_telemetry(source_id="node-99"), client=client)

    call_kwargs = client.chat.completions.create.call_args.kwargs
    user_message = next(m for m in call_kwargs["messages"] if m["role"] == "user")
    assert "node-99" in user_message["content"]


@pytest.mark.asyncio
async def test_extract_calls_client_with_axiom_draft_response_model() -> None:
    client = make_mock_client(
        return_value=AxiomDraft(status="nominal", metric_value=1.0, anomaly_score=0.05)
    )

    await extract(make_telemetry(), client=client)

    call_kwargs = client.chat.completions.create.call_args.kwargs
    assert call_kwargs["response_model"] is AxiomDraft


@pytest.mark.asyncio
async def test_extract_passes_payload_content_to_llm() -> None:
    client = make_mock_client(
        return_value=AxiomDraft(status="degraded", metric_value=78.0, anomaly_score=0.55)
    )
    telemetry = make_telemetry(payload={"raw_log": "disk_full on /var", "node": "staging-02"})

    await extract(telemetry, client=client)

    call_kwargs = client.chat.completions.create.call_args.kwargs
    user_message = next(m for m in call_kwargs["messages"] if m["role"] == "user")
    assert "disk_full" in user_message["content"]


# ── Failure path ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_extract_raises_extraction_error_on_llm_failure() -> None:
    client = make_mock_client(side_effect=RuntimeError("API unreachable"))

    with pytest.raises(ExtractionError) as exc_info:
        await extract(make_telemetry(), client=client)

    assert exc_info.value.raw_payload == make_telemetry().payload


@pytest.mark.asyncio
async def test_extraction_error_wraps_original_exception() -> None:
    original = RuntimeError("connection timeout")
    client = make_mock_client(side_effect=original)

    with pytest.raises(ExtractionError) as exc_info:
        await extract(make_telemetry(), client=client)

    assert exc_info.value.__cause__ is original


@pytest.mark.asyncio
async def test_extraction_error_detail_contains_failure_description() -> None:
    client = make_mock_client(side_effect=ValueError("schema mismatch after 3 retries"))

    with pytest.raises(ExtractionError) as exc_info:
        await extract(make_telemetry(), client=client)

    assert "AxiomDraft" in exc_info.value.detail
