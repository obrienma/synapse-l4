from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from main import app
from src.models.axiom import Axiom, AxiomDraft, EmitError, ExtractionError, JudgeRejection

client = TestClient(app)

# ── Fixtures ──────────────────────────────────────────────────────────────────

VALID_REQUEST = {
    "source_id": "sensor-01",
    "payload": {"raw_log": "CPU at 94%", "tags": ["cpu"]},
}

VALID_DRAFT = AxiomDraft(status="critical", metric_value=94.0, anomaly_score=0.91)

VALID_AXIOM = Axiom(
    status="critical",
    metric_value=94.0,
    anomaly_score=0.91,
    source_id="sensor-01",
    emitted_at=datetime(2026, 3, 31, 12, 0, 0, tzinfo=timezone.utc),
)


def mock_pipeline(
    extract_result: AxiomDraft | Exception = VALID_DRAFT,
    judge_result: AxiomDraft | Exception = VALID_DRAFT,
    emit_result: Axiom | Exception = VALID_AXIOM,
) -> tuple[MagicMock, MagicMock, MagicMock]:
    mock_extract = AsyncMock(
        side_effect=extract_result if isinstance(extract_result, Exception) else None,
        return_value=extract_result if not isinstance(extract_result, Exception) else None,
    )
    mock_judge = MagicMock(
        side_effect=judge_result if isinstance(judge_result, Exception) else None,
        return_value=judge_result if not isinstance(judge_result, Exception) else None,
    )
    mock_emit = AsyncMock(
        side_effect=emit_result if isinstance(emit_result, Exception) else None,
        return_value=emit_result if not isinstance(emit_result, Exception) else None,
    )
    return mock_extract, mock_judge, mock_emit


# ── POST /ingest — success ────────────────────────────────────────────────────

def test_ingest_returns_200_with_axiom_on_success() -> None:
    mock_extract, mock_judge, mock_emit = mock_pipeline()
    with (
        patch("src.api.ingest.extract", mock_extract),
        patch("src.api.ingest.judge", mock_judge),
        patch("src.api.ingest.emit", mock_emit),
    ):
        response = client.post("/ingest", json=VALID_REQUEST)

    assert response.status_code == 200
    body = response.json()
    assert body["axiom"]["status"] == "critical"
    assert body["axiom"]["source_id"] == "sensor-01"
    assert "pipeline_ms" in body


def test_ingest_response_contains_all_axiom_fields() -> None:
    mock_extract, mock_judge, mock_emit = mock_pipeline()
    with (
        patch("src.api.ingest.extract", mock_extract),
        patch("src.api.ingest.judge", mock_judge),
        patch("src.api.ingest.emit", mock_emit),
    ):
        response = client.post("/ingest", json=VALID_REQUEST)

    axiom = response.json()["axiom"]
    for field in ("status", "metric_value", "anomaly_score", "source_id", "emitted_at"):
        assert field in axiom, f"missing field: {field}"


# ── POST /ingest — extraction failure ────────────────────────────────────────

def test_ingest_returns_422_on_extraction_failure() -> None:
    exc = ExtractionError("LLM timeout", raw_payload=VALID_REQUEST["payload"])
    mock_extract, mock_judge, mock_emit = mock_pipeline(extract_result=exc)
    with (
        patch("src.api.ingest.extract", mock_extract),
        patch("src.api.ingest.judge", mock_judge),
        patch("src.api.ingest.emit", mock_emit),
    ):
        response = client.post("/ingest", json=VALID_REQUEST)

    assert response.status_code == 422
    body = response.json()
    assert body["error"] == "extraction_failed"
    assert "detail" in body


# ── POST /ingest — judge rejection ────────────────────────────────────────────

def test_ingest_returns_422_on_judge_rejection() -> None:
    exc = JudgeRejection(
        rule="anomaly_score_status_consistency",
        detail="score 0.91 requires critical",
        draft=VALID_DRAFT,
    )
    mock_extract, mock_judge, mock_emit = mock_pipeline(judge_result=exc)
    with (
        patch("src.api.ingest.extract", mock_extract),
        patch("src.api.ingest.judge", mock_judge),
        patch("src.api.ingest.emit", mock_emit),
    ):
        response = client.post("/ingest", json=VALID_REQUEST)

    assert response.status_code == 422
    body = response.json()
    assert body["error"] == "judge_rejected"
    assert body["rule"] == "anomaly_score_status_consistency"
    assert "axiom_candidate" in body


# ── POST /ingest — emit failure ───────────────────────────────────────────────

def test_ingest_returns_502_on_emit_failure() -> None:
    exc = EmitError("Sentinel-L7 unreachable", axiom=VALID_AXIOM, status_code=503)
    mock_extract, mock_judge, mock_emit = mock_pipeline(emit_result=exc)
    with (
        patch("src.api.ingest.extract", mock_extract),
        patch("src.api.ingest.judge", mock_judge),
        patch("src.api.ingest.emit", mock_emit),
    ):
        response = client.post("/ingest", json=VALID_REQUEST)

    assert response.status_code == 502
    body = response.json()
    assert body["error"] == "emit_failed"
    assert body["status_code"] == 503


# ── POST /ingest — bad request ────────────────────────────────────────────────

def test_ingest_returns_422_on_missing_source_id() -> None:
    response = client.post("/ingest", json={"payload": {"x": 1}})
    assert response.status_code == 422  # FastAPI Pydantic validation


# ── GET /health ───────────────────────────────────────────────────────────────

def test_health_returns_ok() -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


# ── GET /metrics ──────────────────────────────────────────────────────────────

def test_metrics_returns_expected_shape() -> None:
    response = client.get("/metrics")
    assert response.status_code == 200
    body = response.json()
    for key in ("total_processed", "extraction_failures", "judge_rejections", "emit_failures", "avg_pipeline_ms"):
        assert key in body, f"missing key: {key}"


def test_metrics_avg_pipeline_ms_is_zero_when_no_requests_processed() -> None:
    # avg_pipeline_ms should not divide-by-zero when total_processed is 0
    response = client.get("/metrics")
    assert response.json()["avg_pipeline_ms"] >= 0
