import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import websockets.exceptions

from src.clients.eventhorizon import _consume, _handle_message, _event_to_telemetry, run
from src.models.axiom import EmitError, ExtractionError, JudgeRejection, AxiomDraft, Axiom, RawTelemetry
from datetime import datetime, timezone


# ── Fixtures ──────────────────────────────────────────────────────────────────

def event_message(data: dict) -> str:
    return json.dumps({"type": "event", "data": data})


def stats_message() -> str:
    return json.dumps({"type": "stats", "data": {"totalProcessed": 42}})


def ping_message() -> str:
    return json.dumps({"type": "ping"})


EVENT_DATA = {"raw": {"id": "sensor-01"}, "type": "sensor", "value": 94.0}

mock_pipeline = AsyncMock()


# ── _event_to_telemetry ───────────────────────────────────────────────────────

def test_event_to_telemetry_uses_raw_id_as_source_id() -> None:
    telemetry = _event_to_telemetry({"raw": {"id": "node-42"}, "value": 1})
    assert telemetry.source_id == "node-42"


def test_event_to_telemetry_falls_back_to_top_level_id() -> None:
    telemetry = _event_to_telemetry({"id": "fallback-id", "value": 1})
    assert telemetry.source_id == "fallback-id"


def test_event_to_telemetry_uses_unknown_when_no_id() -> None:
    telemetry = _event_to_telemetry({"value": 1})
    assert telemetry.source_id == "unknown"


def test_event_to_telemetry_passes_full_data_as_payload() -> None:
    data = {"raw": {"id": "s1"}, "value": 99}
    telemetry = _event_to_telemetry(data)
    assert telemetry.payload == data


# ── _handle_message: routing ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_handle_message_routes_event_to_pipeline() -> None:
    pipeline = AsyncMock()
    await _handle_message(event_message(EVENT_DATA), pipeline_fn=pipeline)
    pipeline.assert_called_once()
    telemetry: RawTelemetry = pipeline.call_args.args[0]
    assert telemetry.source_id == "sensor-01"


@pytest.mark.asyncio
async def test_handle_message_ignores_stats_type() -> None:
    pipeline = AsyncMock()
    await _handle_message(stats_message(), pipeline_fn=pipeline)
    pipeline.assert_not_called()


@pytest.mark.asyncio
async def test_handle_message_ignores_ping_type() -> None:
    pipeline = AsyncMock()
    await _handle_message(ping_message(), pipeline_fn=pipeline)
    pipeline.assert_not_called()


@pytest.mark.asyncio
async def test_handle_message_ignores_unknown_type() -> None:
    pipeline = AsyncMock()
    await _handle_message(json.dumps({"type": "unknown"}), pipeline_fn=pipeline)
    pipeline.assert_not_called()


# ── _handle_message: resilience ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_handle_message_skips_malformed_json_without_raising() -> None:
    pipeline = AsyncMock()
    await _handle_message("not json {{", pipeline_fn=pipeline)
    pipeline.assert_not_called()


@pytest.mark.asyncio
async def test_handle_message_continues_after_extraction_error() -> None:
    pipeline = AsyncMock(side_effect=ExtractionError("timeout", raw_payload={}))
    await _handle_message(event_message(EVENT_DATA), pipeline_fn=pipeline)
    # must not raise


@pytest.mark.asyncio
async def test_handle_message_continues_after_judge_rejection() -> None:
    draft = AxiomDraft(status="nominal", metric_value=1.0, anomaly_score=0.1)
    pipeline = AsyncMock(side_effect=JudgeRejection("rule", "detail", draft=draft))
    await _handle_message(event_message(EVENT_DATA), pipeline_fn=pipeline)
    # must not raise


@pytest.mark.asyncio
async def test_handle_message_continues_after_emit_error() -> None:
    axiom = Axiom(
        status="critical", metric_value=94.0, anomaly_score=0.9,
        source_id="s1", emitted_at=datetime.now(timezone.utc),
    )
    pipeline = AsyncMock(side_effect=EmitError("unreachable", axiom=axiom))
    await _handle_message(event_message(EVENT_DATA), pipeline_fn=pipeline)
    # must not raise


# ── _consume ──────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_consume_processes_multiple_messages() -> None:
    messages = [event_message(EVENT_DATA), stats_message(), event_message(EVENT_DATA)]
    pipeline = AsyncMock()

    async def async_messages():
        for m in messages:
            yield m

    mock_ws = MagicMock()
    mock_ws.__aenter__ = AsyncMock(return_value=mock_ws)
    mock_ws.__aexit__ = AsyncMock(return_value=False)
    mock_ws.__aiter__ = MagicMock(return_value=async_messages())

    with patch("src.clients.eventhorizon.websockets.connect", return_value=mock_ws):
        await _consume("ws://test", pipeline_fn=pipeline)

    assert pipeline.call_count == 2  # stats ignored, 2 events processed


# ── run: reconnection ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_run_reconnects_after_connection_closed() -> None:
    call_count = 0

    async def fake_consume(url: str, pipeline_fn: object) -> None:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise websockets.exceptions.ConnectionClosed(None, None)  # type: ignore[arg-type]
        raise asyncio.CancelledError  # stop after second attempt

    with (
        patch("src.clients.eventhorizon._consume", fake_consume),
        patch("src.clients.eventhorizon.asyncio.sleep", AsyncMock()),
    ):
        with pytest.raises(asyncio.CancelledError):
            await run("ws://test")

    assert call_count == 2


@pytest.mark.asyncio
async def test_run_cancels_cleanly() -> None:
    async def fake_consume(url: str, pipeline_fn: object) -> None:
        raise asyncio.CancelledError

    with patch("src.clients.eventhorizon._consume", fake_consume):
        with pytest.raises(asyncio.CancelledError):
            await run("ws://test")
