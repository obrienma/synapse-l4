"""
HTTP client for delivering Axioms to Sentinel-L7.

Design Decision: HTTP POST over Redis XADD (for now)
  ADR-0016 documents the open decision between a dedicated Redis stream
  key and an HTTP endpoint. HTTP is implemented first because:
  - SENTINEL_L7_URL is already the only required config for the downstream
  - No Redis client dependency needed in Synapse-L4
  - Simpler to test with respx than with a mock Redis connection

  The trade-off: HTTP is synchronous and loses at-least-once delivery
  guarantees. If Redis Streams are chosen in ADR-0016, this module is
  the only file that changes.

Endpoint: POST {SENTINEL_L7_URL}/api/axioms
  This endpoint does not yet exist in Sentinel-L7 — it is the target
  shape agreed upon via ADR-0016 (stub). See sentinel-l7/docs/adr/0016.
"""

from __future__ import annotations

import httpx

from src.models.axiom import Axiom, EmitError


class SentinelClient:
    def __init__(
        self,
        base_url: str,
        *,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._http_client = http_client or httpx.AsyncClient()

    async def post_axiom(self, axiom: Axiom) -> None:
        """
        POST a validated Axiom to Sentinel-L7's ingestion endpoint.

        Raises:
            EmitError: on non-2xx response or network failure,
                       with status_code set if the server responded
        """
        try:
            response = await self._http_client.post(
                f"{self._base_url}/api/axioms",
                json=axiom.model_dump(mode="json"),
                timeout=10.0,
            )
        except Exception as exc:
            raise EmitError(
                detail=f"Sentinel-L7 unreachable: {exc}",
                axiom=axiom,
            ) from exc

        if response.status_code >= 400:
            raise EmitError(
                detail=f"Sentinel-L7 rejected Axiom: HTTP {response.status_code}",
                axiom=axiom,
                status_code=response.status_code,
            )
