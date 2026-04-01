"""
Redis Streams client for delivering Axioms to Sentinel-L7.

Decision: Redis XADD to `synapse:axioms` stream (ADR-0016)
  Axioms are written to a dedicated Redis stream key `synapse:axioms`,
  separate from Sentinel-L7's `transactions` stream. This gives:

  - At-least-once delivery: Redis Streams consumer groups with XACK
    ensure Axioms are not lost on Sentinel-L7 worker failure
  - Decoupling: Synapse-L4 does not block on Sentinel-L7 processing —
    XADD returns as soon as the message is appended to the stream
  - Clean separation: Axioms are dimensionally different from financial
    transactions and must not share the transactions consumer pipeline

  Sentinel-L7 consumes via `sentinel:watch-axioms` artisan command
  with XCLAIM recovery (same pattern as `sentinel:reclaim`).

Stream key: synapse:axioms
"""

from __future__ import annotations

import redis.asyncio as aioredis

from src.models.axiom import Axiom, EmitError

AXIOMS_STREAM = "synapse:axioms"


class SentinelClient:
    def __init__(self, redis_client: aioredis.Redis) -> None:  # type: ignore[type-arg]
        self._redis = redis_client

    async def post_axiom(self, axiom: Axiom) -> None:
        """
        Append a validated Axiom to the `synapse:axioms` Redis stream.

        Raises:
            EmitError: if the Redis connection fails or XADD returns an error
        """
        fields = {
            "status": axiom.status,
            "metric_value": str(axiom.metric_value),
            "anomaly_score": str(axiom.anomaly_score),
            "source_id": axiom.source_id,
            "emitted_at": axiom.emitted_at.isoformat(),
        }
        try:
            await self._redis.xadd(AXIOMS_STREAM, fields)  # type: ignore[arg-type]
        except Exception as exc:
            raise EmitError(
                detail=f"Failed to write Axiom to Redis stream '{AXIOMS_STREAM}': {exc}",
                axiom=axiom,
            ) from exc
