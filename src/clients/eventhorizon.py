"""
EventHorizon WebSocket consumer — subscribes to the /live endpoint and
routes incoming events through the Synapse-L4 Validation Node pipeline.

Pattern: Resilient Async Subscriber
  A long-lived connection with exponential backoff reconnection. Single
  message failures (pipeline errors, malformed JSON) are logged and
  skipped — one bad event must never crash the consumer loop.

Pattern: Producer/Consumer Decoupling via Bounded Queue
  The WebSocket receive loop (producer) puts RawTelemetry onto a bounded
  asyncio.Queue. A pool of worker coroutines (consumers) drain the queue
  and run the full pipeline concurrently. This decouples WS receive
  throughput from LLM latency: a slow LLM call no longer blocks the
  consumer from reading the next message.

  Backpressure: queue.put() blocks when the queue is full. That stalls the
  WS read loop, which fills EH's TCP send buffer — a natural signal that
  Synapse cannot keep up.

Anti-pattern avoided: Tight Coupling on Entry Point
  If the consumer called POST /ingest over HTTP, it would depend on the
  HTTP server being up, add unnecessary latency, and make testing harder.
  Direct function calls keep the pipeline reusable across entry points.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from typing import Any

import websockets
import websockets.exceptions

from config import settings
from src.models.axiom import EmitError, ExtractionError, JudgeRejection, RawTelemetry
from src.nodes.emitter import emit
from src.nodes.extractor import extract
from src.nodes.judge import judge

logger = logging.getLogger(__name__)

_BACKOFF_INITIAL: float = 1.0
_BACKOFF_MAX: float = 60.0

# Type alias for an injectable pipeline function (used in tests)
PipelineFn = Callable[[RawTelemetry], Awaitable[None]]


def _event_to_telemetry(data: dict[str, Any]) -> RawTelemetry:
    """
    Map an EventHorizon StoredEvent to RawTelemetry.

    TODO: align with the exact EventHorizon StoredEvent shape once the
    integration is tested end-to-end. Current mapping uses raw.id as
    source_id and passes the full data dict as the payload.
    """
    source_id: str = (
        data.get("raw", {}).get("id")
        or data.get("id")
        or "unknown"
    )
    return RawTelemetry(source_id=source_id, payload=data)


async def _run_pipeline(telemetry: RawTelemetry) -> None:
    """Run the full Validation Node pipeline for one telemetry packet."""
    draft = await extract(telemetry)
    judge(draft)
    await emit(draft, telemetry)


async def _enqueue(raw: str, queue: asyncio.Queue[RawTelemetry]) -> None:
    """
    Parse one WS message and enqueue it if it's an event. Logs and returns
    on any error — never raises.

    Blocks on queue.put() when the queue is full, propagating backpressure
    to the WS read loop and ultimately to EventHorizon's TCP send buffer.
    """
    try:
        message = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("eventhorizon: malformed message (not JSON), skipping")
        return

    if message.get("type") != "event":
        return  # ignore stats, ping, unknown types

    data = message.get("data")
    if not isinstance(data, dict):
        logger.warning("eventhorizon: 'event' message missing data dict, skipping")
        return

    telemetry = _event_to_telemetry(data)
    await queue.put(telemetry)  # blocks when queue is full — intentional backpressure


async def _worker(
    queue: asyncio.Queue[RawTelemetry],
    pipeline_fn: PipelineFn,
) -> None:
    """
    Drain the telemetry queue and run the pipeline for each item.

    Per-event errors are logged and skipped; the worker never stops on a
    single pipeline failure. task_done() is always called after a successful
    get() so queue.join() can be used in tests.

    Runs until cancelled by run() on shutdown.
    """
    while True:
        telemetry = await queue.get()
        try:
            await pipeline_fn(telemetry)
        except ExtractionError as exc:
            logger.warning("eventhorizon: extraction failed for %s: %s", telemetry.source_id, exc.detail)
        except JudgeRejection as exc:
            logger.warning("eventhorizon: judge rejected %s [%s]: %s", telemetry.source_id, exc.rule, exc.detail)
        except EmitError as exc:
            logger.error("eventhorizon: emit failed for %s: %s", telemetry.source_id, exc.detail)
        finally:
            queue.task_done()


async def _consume(
    ws_url: str,
    queue: asyncio.Queue[RawTelemetry],
) -> None:
    """Single connection attempt — raises websockets.exceptions.ConnectionClosed on disconnect."""
    async with websockets.connect(ws_url) as ws:
        logger.info("eventhorizon: connected to %s", ws_url)
        async for raw_message in ws:
            raw_str = str(raw_message)
            # Respond to EventHorizon's application-level heartbeat.
            # EH sends {"type":"ping"} every 30s and expects "pong" back;
            # no response marks the client as a zombie and triggers terminate().
            try:
                if json.loads(raw_str).get("type") == "ping":
                    await ws.send("pong")
                    continue
            except (json.JSONDecodeError, AttributeError):
                pass
            await _enqueue(raw_str, queue)


async def run(
    ws_url: str,
    pipeline_fn: PipelineFn = _run_pipeline,
) -> None:
    """
    Run the consumer indefinitely with exponential backoff reconnection.

    Creates a bounded queue and a pool of worker coroutines before entering
    the reconnect loop. Workers run for the lifetime of the consumer and are
    cancelled cleanly on task cancellation.

    Intended to be started as an asyncio.Task from main.py lifespan.
    Runs until the task is cancelled.
    """
    queue: asyncio.Queue[RawTelemetry] = asyncio.Queue(maxsize=settings.pipeline_queue_size)
    workers = [
        asyncio.create_task(_worker(queue, pipeline_fn))
        for _ in range(settings.pipeline_workers)
    ]

    delay = _BACKOFF_INITIAL
    try:
        while True:
            try:
                await _consume(ws_url, queue)
                delay = _BACKOFF_INITIAL  # reset on clean disconnect
            except asyncio.CancelledError:
                raise
            except websockets.exceptions.ConnectionClosed as exc:
                logger.warning("eventhorizon: connection closed (%s), reconnecting in %.0fs", exc, delay)
            except Exception as exc:
                logger.error("eventhorizon: unexpected error (%s), reconnecting in %.0fs", exc, delay)

            await asyncio.sleep(delay)
            delay = min(delay * 2, _BACKOFF_MAX)
    except asyncio.CancelledError:
        logger.info("eventhorizon: consumer cancelled, shutting down")
        for w in workers:
            w.cancel()
        await asyncio.gather(*workers, return_exceptions=True)
        raise
