from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from src.models.axiom import Axiom, ExtractionError, JudgeRejection, RawTelemetry


# ── Fixtures ──────────────────────────────────────────────────────────────────

def valid_axiom(**overrides: object) -> Axiom:
    defaults: dict[str, object] = {
        "status": "nominal",
        "metric_value": 42.0,
        "anomaly_score": 0.3,
        "source_id": "sensor-01",
        "emitted_at": datetime(2026, 3, 31, 12, 0, 0, tzinfo=timezone.utc),
    }
    return Axiom(**(defaults | overrides))


# ── Axiom: valid construction ─────────────────────────────────────────────────

def test_axiom_constructs_with_valid_fields() -> None:
    axiom = valid_axiom()
    assert axiom.status == "nominal"
    assert axiom.metric_value == 42.0
    assert axiom.anomaly_score == 0.3
    assert axiom.source_id == "sensor-01"


def test_axiom_accepts_all_status_values() -> None:
    for status in ("nominal", "degraded", "critical"):
        axiom = valid_axiom(status=status)
        assert axiom.status == status


def test_axiom_accepts_anomaly_score_boundary_values() -> None:
    low = valid_axiom(anomaly_score=0.0)
    high = valid_axiom(anomaly_score=1.0)
    assert low.anomaly_score == 0.0
    assert high.anomaly_score == 1.0


def test_axiom_accepts_iso_string_for_emitted_at() -> None:
    axiom = valid_axiom(emitted_at="2026-03-31T12:00:00Z")
    assert isinstance(axiom.emitted_at, datetime)


# ── Axiom: validation errors ──────────────────────────────────────────────────

def test_axiom_rejects_invalid_status() -> None:
    with pytest.raises(ValidationError):
        valid_axiom(status="unknown")


def test_axiom_rejects_anomaly_score_above_1() -> None:
    with pytest.raises(ValidationError):
        valid_axiom(anomaly_score=1.001)


def test_axiom_rejects_anomaly_score_below_0() -> None:
    with pytest.raises(ValidationError):
        valid_axiom(anomaly_score=-0.001)


def test_axiom_rejects_missing_source_id() -> None:
    with pytest.raises(ValidationError):
        Axiom(
            status="nominal",
            metric_value=1.0,
            anomaly_score=0.1,
            emitted_at=datetime.now(tz=timezone.utc),
        )  # type: ignore[call-arg]


# ── Axiom: immutability ───────────────────────────────────────────────────────

def test_axiom_is_immutable() -> None:
    axiom = valid_axiom()
    with pytest.raises(ValidationError):
        axiom.status = "degraded"  # type: ignore[misc]


def test_axiom_is_hashable() -> None:
    axiom = valid_axiom()
    # frozen=True makes the model hashable — usable in sets and as dict keys
    assert hash(axiom) is not None
    seen = {axiom}
    assert axiom in seen


# ── RawTelemetry ──────────────────────────────────────────────────────────────

def test_raw_telemetry_constructs() -> None:
    rt = RawTelemetry(source_id="s1", payload={"raw_log": "cpu spike", "value": 98})
    assert rt.source_id == "s1"
    assert rt.payload["value"] == 98


def test_raw_telemetry_rejects_missing_source_id() -> None:
    with pytest.raises(ValidationError):
        RawTelemetry(payload={"x": 1})  # type: ignore[call-arg]


# ── JudgeRejection ────────────────────────────────────────────────────────────

def test_judge_rejection_carries_rule_and_detail() -> None:
    candidate = valid_axiom()
    exc = JudgeRejection(
        rule="anomaly_score_status_consistency",
        detail="anomaly_score 0.91 requires status 'critical'",
        axiom_candidate=candidate,
    )
    assert exc.rule == "anomaly_score_status_consistency"
    assert exc.axiom_candidate is candidate
    assert "anomaly_score" in str(exc)


# ── ExtractionError ───────────────────────────────────────────────────────────

def test_extraction_error_carries_raw_payload() -> None:
    payload: dict[str, object] = {"raw_log": "...", "tags": []}
    exc = ExtractionError(detail="LLM did not conform after 3 attempts", raw_payload=payload)
    assert exc.raw_payload is payload
    assert "3 attempts" in str(exc)
