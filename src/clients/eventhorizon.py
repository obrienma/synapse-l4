"""
EventHorizon WebSocket consumer — subscribes to the /live endpoint and
routes incoming events through the Synapse-L4 Validation Node pipeline.

Pattern: Resilient Async Subscriber
  A long-lived connection with exponential backoff reconnection. Single
  message failures (pipeline errors, malformed JSON) are logged and
  skipped — one bad event must never crash the consumer loop.

  The consumer calls the pipeline functions (extract → judge → emit)
  directly, bypassing the HTTP layer. This is intentional: the route
  handler and the WS consumer are two entry points to the same pipeline.

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


async def _handle_message(
    raw: str,
    pipeline_fn: PipelineFn = _run_pipeline,
) -> None:
    """
    Parse one WS message and route it through the pipeline if it's an event.
    Logs and returns on any error — never raises.
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

    try:
        await pipeline_fn(telemetry)
    except ExtractionError as exc:
        logger.warning("eventhorizon: extraction failed for %s: %s", telemetry.source_id, exc.detail)
    except JudgeRejection as exc:
        logger.warning("eventhorizon: judge rejected %s [%s]: %s", telemetry.source_id, exc.rule, exc.detail)
    except EmitError as exc:
        logger.error("eventhorizon: emit failed for %s: %s", telemetry.source_id, exc.detail)


async def _consume(
    ws_url: str,
    pipeline_fn: PipelineFn = _run_pipeline,
) -> None:
    """Single connection attempt — raises websockets.exceptions.ConnectionClosed on disconnect."""
    async with websockets.connect(ws_url) as ws:
        logger.info("eventhorizon: connected to %s", ws_url)
        async for raw_message in ws:
            await _handle_message(str(raw_message), pipeline_fn)


async def run(
    ws_url: str,
    pipeline_fn: PipelineFn = _run_pipeline,
) -> None:
    """
    Run the consumer indefinitely with exponential backoff reconnection.

    Intended to be started as an asyncio.Task from main.py lifespan.
    Runs until the task is cancelled.
    """
    delay = _BACKOFF_INITIAL
    while True:
        try:
            await _consume(ws_url, pipeline_fn)
            delay = _BACKOFF_INITIAL  # reset on clean disconnect
        except asyncio.CancelledError:
            logger.info("eventhorizon: consumer cancelled, shutting down")
            raise
        except websockets.exceptions.ConnectionClosed as exc:
            logger.warning("eventhorizon: connection closed (%s), reconnecting in %.0fs", exc, delay)
        except Exception as exc:
            logger.error("eventhorizon: unexpected error (%s), reconnecting in %.0fs", exc, delay)

        await asyncio.sleep(delay)
        delay = min(delay * 2, _BACKOFF_MAX)
