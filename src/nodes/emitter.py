"""
Emit stage — promotes AxiomDraft → Axiom and delivers to Sentinel-L7.

This is the only place in the pipeline where an Axiom is constructed.
source_id comes from RawTelemetry (authoritative identity of the event).
emitted_at is stamped here, at the moment of delivery — not at extraction
time, not at judge time. The timestamp reflects when the validated Axiom
actually left the pipeline.

Pattern: Idempotent Emission
  The Axiom carries source_id + emitted_at so Sentinel-L7 can deduplicate
  on re-delivery. If the emitter retries after a transient failure, Sentinel
  can detect the duplicate and discard it safely.
"""

from __future__ import annotations

from datetime import UTC, datetime

import logfire
import redis.asyncio as aioredis

from config import settings
from src.clients.sentinel import SentinelClient
from src.models.axiom import Axiom, AxiomDraft, EmitError, RawTelemetry


def _default_client() -> SentinelClient:
    return SentinelClient(aioredis.from_url(settings.sentinel_redis_url))


async def emit(
    draft: AxiomDraft,
    telemetry: RawTelemetry,
    *,
    client: SentinelClient | None = None,
) -> Axiom:
    """
    Promote a validated AxiomDraft to a full Axiom and deliver it.

    Args:
        draft:    the AxiomDraft that passed the Judge stage
        telemetry: the original RawTelemetry — provides source_id
        client:   injectable SentinelClient (defaults to real HTTP) — used in tests

    Returns:
        the emitted Axiom (frozen, with source_id and emitted_at set)

    Raises:
        EmitError: if delivery to Sentinel-L7 fails for any reason.
                   The Axiom is not considered emitted on failure.
    """
    axiom = Axiom(
        status=draft.status,
        metric_value=draft.metric_value,
        anomaly_score=draft.anomaly_score,
        source_id=telemetry.source_id,
        emitted_at=datetime.now(UTC),
    )

    _client = client or _default_client()
    with logfire.span("emit", source_id=axiom.source_id, status=axiom.status):
        await _client.post_axiom(axiom)  # raises EmitError on failure

    return axiom
