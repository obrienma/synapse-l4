import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import websockets.exceptions

from src.clients.eventhorizon import _consume, _enqueue, _event_to_telemetry, _worker, run
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


# ── _enqueue: routing ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_enqueue_puts_event_to_queue() -> None:
    queue: asyncio.Queue[RawTelemetry] = asyncio.Queue()
    await _enqueue(event_message(EVENT_DATA), queue)
    assert queue.qsize() == 1
    telemetry = queue.get_nowait()
    assert telemetry.source_id == "sensor-01"


@pytest.mark.asyncio
async def test_enqueue_ignores_stats_type() -> None:
    queue: asyncio.Queue[RawTelemetry] = asyncio.Queue()
    await _enqueue(stats_message(), queue)
    assert queue.empty()


@pytest.mark.asyncio
async def test_enqueue_ignores_unknown_type() -> None:
    queue: asyncio.Queue[RawTelemetry] = asyncio.Queue()
    await _enqueue(json.dumps({"type": "unknown"}), queue)
    assert queue.empty()


@pytest.mark.asyncio
async def test_enqueue_skips_malformed_json_without_raising() -> None:
    queue: asyncio.Queue[RawTelemetry] = asyncio.Queue()
    await _enqueue("not json {{", queue)
    assert queue.empty()


@pytest.mark.asyncio
async def test_enqueue_skips_event_without_data_dict() -> None:
    queue: asyncio.Queue[RawTelemetry] = asyncio.Queue()
    await _enqueue(json.dumps({"type": "event", "data": "not a dict"}), queue)
    assert queue.empty()


# ── _worker: pipeline execution and resilience ────────────────────────────────

@pytest.mark.asyncio
async def test_worker_calls_pipeline_with_telemetry() -> None:
    queue: asyncio.Queue[RawTelemetry] = asyncio.Queue()
    telemetry = RawTelemetry(source_id="s1", payload={})
    await queue.put(telemetry)

    pipeline = AsyncMock()
    worker_task = asyncio.create_task(_worker(queue, pipeline))
    await queue.join()  # blocks until task_done() called
    worker_task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await worker_task

    pipeline.assert_called_once_with(telemetry)


@pytest.mark.asyncio
async def test_worker_continues_after_extraction_error() -> None:
    queue: asyncio.Queue[RawTelemetry] = asyncio.Queue()
    await queue.put(RawTelemetry(source_id="s1", payload={}))

    pipeline = AsyncMock(side_effect=ExtractionError("timeout", raw_payload={}))
    worker_task = asyncio.create_task(_worker(queue, pipeline))
    await queue.join()
    worker_task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await worker_task
    # must not raise before cancel


@pytest.mark.asyncio
async def test_worker_continues_after_judge_rejection() -> None:
    queue: asyncio.Queue[RawTelemetry] = asyncio.Queue()
    await queue.put(RawTelemetry(source_id="s1", payload={}))

    draft = AxiomDraft(status="nominal", metric_value=1.0, anomaly_score=0.1)
    pipeline = AsyncMock(side_effect=JudgeRejection("rule", "detail", draft=draft))
    worker_task = asyncio.create_task(_worker(queue, pipeline))
    await queue.join()
    worker_task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await worker_task


@pytest.mark.asyncio
async def test_worker_continues_after_emit_error() -> None:
    queue: asyncio.Queue[RawTelemetry] = asyncio.Queue()
    await queue.put(RawTelemetry(source_id="s1", payload={}))

    axiom = Axiom(
        status="critical", metric_value=94.0, anomaly_score=0.9,
        source_id="s1", emitted_at=datetime.now(timezone.utc),
    )
    pipeline = AsyncMock(side_effect=EmitError("unreachable", axiom=axiom))
    worker_task = asyncio.create_task(_worker(queue, pipeline))
    await queue.join()
    worker_task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await worker_task


@pytest.mark.asyncio
async def test_worker_calls_task_done_on_error() -> None:
    """task_done() must be called even when the pipeline raises, so queue.join() never hangs."""
    queue: asyncio.Queue[RawTelemetry] = asyncio.Queue()
    await queue.put(RawTelemetry(source_id="s1", payload={}))

    pipeline = AsyncMock(side_effect=ExtractionError("fail", raw_payload={}))
    worker_task = asyncio.create_task(_worker(queue, pipeline))
    # queue.join() will only return if task_done() was called despite the error
    await asyncio.wait_for(queue.join(), timeout=2.0)
    worker_task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await worker_task


# ── _consume ──────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_consume_sends_pong_on_ping() -> None:
    """_consume must reply "pong" to EventHorizon's heartbeat ping.
    Without this, EH marks the client as a zombie and calls terminate()."""
    queue: asyncio.Queue[RawTelemetry] = asyncio.Queue()
    messages = [ping_message()]

    async def async_messages():
        for m in messages:
            yield m

    mock_ws = MagicMock()
    mock_ws.__aenter__ = AsyncMock(return_value=mock_ws)
    mock_ws.__aexit__ = AsyncMock(return_value=False)
    mock_ws.__aiter__ = MagicMock(return_value=async_messages())
    mock_ws.send = AsyncMock()

    with patch("src.clients.eventhorizon.websockets.connect", return_value=mock_ws):
        await _consume("ws://test", queue)

    mock_ws.send.assert_called_once_with("pong")
    assert queue.empty()


@pytest.mark.asyncio
async def test_consume_enqueues_event_messages() -> None:
    queue: asyncio.Queue[RawTelemetry] = asyncio.Queue()
    messages = [event_message(EVENT_DATA), stats_message(), event_message(EVENT_DATA)]

    async def async_messages():
        for m in messages:
            yield m

    mock_ws = MagicMock()
    mock_ws.__aenter__ = AsyncMock(return_value=mock_ws)
    mock_ws.__aexit__ = AsyncMock(return_value=False)
    mock_ws.__aiter__ = MagicMock(return_value=async_messages())
    mock_ws.send = AsyncMock()

    with patch("src.clients.eventhorizon.websockets.connect", return_value=mock_ws):
        await _consume("ws://test", queue)

    assert queue.qsize() == 2  # stats ignored, 2 events enqueued


# ── run: reconnection ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_run_reconnects_after_connection_closed() -> None:
    call_count = 0

    async def fake_consume(url: str, queue: object) -> None:
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
    async def fake_consume(url: str, queue: object) -> None:
        raise asyncio.CancelledError

    with patch("src.clients.eventhorizon._consume", fake_consume):
        with pytest.raises(asyncio.CancelledError):
            await run("ws://test")
