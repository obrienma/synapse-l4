from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.models.axiom import Axiom, AxiomDraft, EmitError, RawTelemetry
from src.nodes.emitter import emit


# ── Fixtures ──────────────────────────────────────────────────────────────────

def valid_draft() -> AxiomDraft:
    return AxiomDraft(status="critical", metric_value=94.0, anomaly_score=0.91)


def valid_telemetry(**overrides: object) -> RawTelemetry:
    defaults: dict[str, object] = {
        "source_id": "sensor-01",
        "payload": {"raw_log": "cpu spike"},
    }
    return RawTelemetry(**(defaults | overrides))


def make_mock_client(side_effect: Exception | None = None) -> MagicMock:
    client = MagicMock()
    client.post_axiom = AsyncMock(side_effect=side_effect)
    return client


# ── Promotion: AxiomDraft → Axiom ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_emit_returns_axiom() -> None:
    client = make_mock_client()
    result = await emit(valid_draft(), valid_telemetry(), client=client)
    assert isinstance(result, Axiom)


@pytest.mark.asyncio
async def test_emit_copies_draft_fields_to_axiom() -> None:
    client = make_mock_client()
    draft = valid_draft()
    result = await emit(draft, valid_telemetry(), client=client)
    assert result.status == draft.status
    assert result.metric_value == draft.metric_value
    assert result.anomaly_score == draft.anomaly_score


@pytest.mark.asyncio
async def test_emit_sets_source_id_from_telemetry() -> None:
    client = make_mock_client()
    result = await emit(valid_draft(), valid_telemetry(source_id="node-99"), client=client)
    assert result.source_id == "node-99"


@pytest.mark.asyncio
async def test_emit_copies_domain_from_draft() -> None:
    client = make_mock_client()
    draft = AxiomDraft(status="critical", metric_value=94.0, anomaly_score=0.91, domain="aml")
    result = await emit(draft, valid_telemetry(), client=client)
    assert result.domain == "aml"


@pytest.mark.asyncio
async def test_emit_domain_is_none_when_draft_has_no_domain() -> None:
    client = make_mock_client()
    result = await emit(valid_draft(), valid_telemetry(), client=client)
    assert result.domain is None


@pytest.mark.asyncio
async def test_emit_sets_emitted_at_to_current_utc_time() -> None:
    client = make_mock_client()
    before = datetime.now(timezone.utc)
    result = await emit(valid_draft(), valid_telemetry(), client=client)
    after = datetime.now(timezone.utc)
    assert before <= result.emitted_at <= after


@pytest.mark.asyncio
async def test_emitted_axiom_is_frozen() -> None:
    from pydantic import ValidationError
    client = make_mock_client()
    result = await emit(valid_draft(), valid_telemetry(), client=client)
    with pytest.raises(ValidationError):
        result.status = "nominal"  # type: ignore[misc]


# ── Delivery ──────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_emit_calls_client_post_axiom() -> None:
    client = make_mock_client()
    await emit(valid_draft(), valid_telemetry(), client=client)
    client.post_axiom.assert_called_once()


@pytest.mark.asyncio
async def test_emit_passes_constructed_axiom_to_client() -> None:
    client = make_mock_client()
    result = await emit(valid_draft(), valid_telemetry(source_id="s1"), client=client)
    posted_axiom = client.post_axiom.call_args.args[0]
    assert posted_axiom is result


# ── Failure ───────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_emit_propagates_emit_error_from_client() -> None:
    axiom_placeholder = Axiom(
        status="critical", metric_value=94.0, anomaly_score=0.91,
        source_id="s1", emitted_at=datetime.now(timezone.utc),
    )
    client = make_mock_client(
        side_effect=EmitError("HTTP 503", axiom=axiom_placeholder, status_code=503)
    )
    with pytest.raises(EmitError) as exc_info:
        await emit(valid_draft(), valid_telemetry(), client=client)
    assert exc_info.value.status_code == 503


@pytest.mark.asyncio
async def test_axiom_not_returned_on_emit_failure() -> None:
    axiom_placeholder = Axiom(
        status="critical", metric_value=94.0, anomaly_score=0.91,
        source_id="s1", emitted_at=datetime.now(timezone.utc),
    )
    client = make_mock_client(
        side_effect=EmitError("unreachable", axiom=axiom_placeholder)
    )
    with pytest.raises(EmitError):
        await emit(valid_draft(), valid_telemetry(), client=client)
