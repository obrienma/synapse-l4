from datetime import datetime, timezone

import httpx
import pytest
import respx

from src.clients.sentinel import SentinelClient
from src.models.axiom import Axiom, EmitError

BASE_URL = "http://sentinel-l7.test"
AXIOMS_URL = f"{BASE_URL}/api/axioms"


def valid_axiom() -> Axiom:
    return Axiom(
        status="critical",
        metric_value=94.0,
        anomaly_score=0.91,
        source_id="sensor-01",
        emitted_at=datetime(2026, 3, 31, 12, 0, 0, tzinfo=timezone.utc),
    )


def make_client(http_client: httpx.AsyncClient) -> SentinelClient:
    return SentinelClient(BASE_URL, http_client=http_client)


# ── Success ───────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
@respx.mock
async def test_post_axiom_succeeds_on_201() -> None:
    respx.post(AXIOMS_URL).mock(return_value=httpx.Response(201))
    async with httpx.AsyncClient() as http:
        await make_client(http).post_axiom(valid_axiom())


@pytest.mark.asyncio
@respx.mock
async def test_post_axiom_succeeds_on_200() -> None:
    respx.post(AXIOMS_URL).mock(return_value=httpx.Response(200))
    async with httpx.AsyncClient() as http:
        await make_client(http).post_axiom(valid_axiom())


@pytest.mark.asyncio
@respx.mock
async def test_post_axiom_sends_all_axiom_fields() -> None:
    route = respx.post(AXIOMS_URL).mock(return_value=httpx.Response(201))
    async with httpx.AsyncClient() as http:
        await make_client(http).post_axiom(valid_axiom())

    request_body = route.calls.last.request
    import json
    payload = json.loads(request_body.content)
    assert payload["status"] == "critical"
    assert payload["metric_value"] == 94.0
    assert payload["anomaly_score"] == 0.91
    assert payload["source_id"] == "sensor-01"
    assert "emitted_at" in payload


# ── HTTP error responses ──────────────────────────────────────────────────────

@pytest.mark.asyncio
@respx.mock
async def test_post_axiom_raises_emit_error_on_422() -> None:
    respx.post(AXIOMS_URL).mock(return_value=httpx.Response(422))
    async with httpx.AsyncClient() as http:
        with pytest.raises(EmitError) as exc_info:
            await make_client(http).post_axiom(valid_axiom())
    assert exc_info.value.status_code == 422


@pytest.mark.asyncio
@respx.mock
async def test_post_axiom_raises_emit_error_on_500() -> None:
    respx.post(AXIOMS_URL).mock(return_value=httpx.Response(500))
    async with httpx.AsyncClient() as http:
        with pytest.raises(EmitError) as exc_info:
            await make_client(http).post_axiom(valid_axiom())
    assert exc_info.value.status_code == 500


@pytest.mark.asyncio
@respx.mock
async def test_emit_error_carries_axiom_on_http_failure() -> None:
    respx.post(AXIOMS_URL).mock(return_value=httpx.Response(503))
    axiom = valid_axiom()
    async with httpx.AsyncClient() as http:
        with pytest.raises(EmitError) as exc_info:
            await make_client(http).post_axiom(axiom)
    assert exc_info.value.axiom is axiom


# ── Network failure ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
@respx.mock
async def test_post_axiom_raises_emit_error_on_connection_failure() -> None:
    respx.post(AXIOMS_URL).mock(side_effect=httpx.ConnectError("refused"))
    async with httpx.AsyncClient() as http:
        with pytest.raises(EmitError) as exc_info:
            await make_client(http).post_axiom(valid_axiom())
    assert exc_info.value.status_code is None
    assert "unreachable" in exc_info.value.detail


@pytest.mark.asyncio
@respx.mock
async def test_network_error_wraps_original_exception() -> None:
    original = httpx.ConnectError("timeout")
    respx.post(AXIOMS_URL).mock(side_effect=original)
    async with httpx.AsyncClient() as http:
        with pytest.raises(EmitError) as exc_info:
            await make_client(http).post_axiom(valid_axiom())
    assert exc_info.value.__cause__ is original
