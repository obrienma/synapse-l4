from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.clients.sentinel import AXIOMS_STREAM, SentinelClient
from src.models.axiom import Axiom, EmitError


# ── Fixtures ──────────────────────────────────────────────────────────────────

def valid_axiom() -> Axiom:
    return Axiom(
        status="critical",
        metric_value=94.0,
        anomaly_score=0.91,
        source_id="sensor-01",
        emitted_at=datetime(2026, 3, 31, 12, 0, 0, tzinfo=timezone.utc),
    )


def make_client(xadd_side_effect: Exception | None = None) -> tuple[SentinelClient, MagicMock]:
    mock_redis = MagicMock()
    mock_redis.xadd = AsyncMock(side_effect=xadd_side_effect)
    return SentinelClient(mock_redis), mock_redis


# ── Success ───────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_post_axiom_calls_xadd_on_correct_stream() -> None:
    client, mock_redis = make_client()
    await client.post_axiom(valid_axiom())
    mock_redis.xadd.assert_called_once()
    stream_key = mock_redis.xadd.call_args.args[0]
    assert stream_key == AXIOMS_STREAM


@pytest.mark.asyncio
async def test_post_axiom_sends_all_axiom_fields() -> None:
    client, mock_redis = make_client()
    await client.post_axiom(valid_axiom())
    fields = mock_redis.xadd.call_args.args[1]
    assert fields["status"] == "critical"
    assert fields["metric_value"] == "94.0"
    assert fields["anomaly_score"] == "0.91"
    assert fields["source_id"] == "sensor-01"
    assert "emitted_at" in fields


@pytest.mark.asyncio
async def test_post_axiom_serialises_emitted_at_as_iso_string() -> None:
    client, mock_redis = make_client()
    await client.post_axiom(valid_axiom())
    fields = mock_redis.xadd.call_args.args[1]
    assert fields["emitted_at"] == "2026-03-31T12:00:00+00:00"


# ── Failure ───────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_post_axiom_raises_emit_error_on_redis_failure() -> None:
    client, _ = make_client(xadd_side_effect=ConnectionError("Redis unreachable"))
    with pytest.raises(EmitError) as exc_info:
        await client.post_axiom(valid_axiom())
    assert AXIOMS_STREAM in exc_info.value.detail


@pytest.mark.asyncio
async def test_emit_error_carries_axiom_on_failure() -> None:
    client, _ = make_client(xadd_side_effect=ConnectionError("refused"))
    axiom = valid_axiom()
    with pytest.raises(EmitError) as exc_info:
        await client.post_axiom(axiom)
    assert exc_info.value.axiom is axiom


@pytest.mark.asyncio
async def test_emit_error_wraps_original_exception() -> None:
    original = ConnectionError("timeout")
    client, _ = make_client(xadd_side_effect=original)
    with pytest.raises(EmitError) as exc_info:
        await client.post_axiom(valid_axiom())
    assert exc_info.value.__cause__ is original
