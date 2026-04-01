import math

import pytest

from src.evaluation.rules import (
    ANOMALY_CRITICAL_THRESHOLD,
    ANOMALY_DEGRADED_THRESHOLD,
    rule_anomaly_score_status_consistency,
    rule_metric_value_finite,
)
from src.models.axiom import AxiomDraft, JudgeRejection


# ── Helpers ───────────────────────────────────────────────────────────────────

def draft(**kwargs: object) -> AxiomDraft:
    defaults: dict[str, object] = {
        "status": "nominal",
        "metric_value": 50.0,
        "anomaly_score": 0.2,
    }
    return AxiomDraft(**(defaults | kwargs))


# ── rule_anomaly_score_status_consistency ─────────────────────────────────────

def test_passes_nominal_with_low_anomaly_score() -> None:
    rule_anomaly_score_status_consistency(draft(status="nominal", anomaly_score=0.1))


def test_passes_degraded_with_mid_anomaly_score() -> None:
    rule_anomaly_score_status_consistency(draft(status="degraded", anomaly_score=0.6))


def test_passes_critical_with_high_anomaly_score() -> None:
    rule_anomaly_score_status_consistency(draft(status="critical", anomaly_score=0.9))


def test_passes_degraded_with_high_anomaly_score() -> None:
    # degraded is acceptable when anomaly_score >= critical threshold? No —
    # only "critical" is valid at or above ANOMALY_CRITICAL_THRESHOLD
    with pytest.raises(JudgeRejection) as exc_info:
        rule_anomaly_score_status_consistency(
            draft(status="degraded", anomaly_score=ANOMALY_CRITICAL_THRESHOLD)
        )
    assert exc_info.value.rule == "anomaly_score_status_consistency"


def test_rejects_nominal_with_high_anomaly_score() -> None:
    with pytest.raises(JudgeRejection) as exc_info:
        rule_anomaly_score_status_consistency(
            draft(status="nominal", anomaly_score=ANOMALY_CRITICAL_THRESHOLD)
        )
    assert exc_info.value.rule == "anomaly_score_status_consistency"
    assert "critical" in exc_info.value.detail


def test_rejects_nominal_with_mid_anomaly_score() -> None:
    with pytest.raises(JudgeRejection) as exc_info:
        rule_anomaly_score_status_consistency(
            draft(status="nominal", anomaly_score=ANOMALY_DEGRADED_THRESHOLD)
        )
    assert exc_info.value.rule == "anomaly_score_status_consistency"
    assert "degraded" in exc_info.value.detail


def test_boundary_just_below_degraded_threshold_passes_nominal() -> None:
    score = ANOMALY_DEGRADED_THRESHOLD - 0.001
    rule_anomaly_score_status_consistency(draft(status="nominal", anomaly_score=score))


def test_boundary_just_below_critical_threshold_passes_degraded() -> None:
    score = ANOMALY_CRITICAL_THRESHOLD - 0.001
    rule_anomaly_score_status_consistency(draft(status="degraded", anomaly_score=score))


def test_rejection_carries_draft() -> None:
    d = draft(status="nominal", anomaly_score=0.9)
    with pytest.raises(JudgeRejection) as exc_info:
        rule_anomaly_score_status_consistency(d)
    assert exc_info.value.draft is d


# ── rule_metric_value_finite ──────────────────────────────────────────────────

def test_passes_normal_float() -> None:
    rule_metric_value_finite(draft(metric_value=42.0))


def test_passes_zero() -> None:
    rule_metric_value_finite(draft(metric_value=0.0))


def test_passes_negative_finite() -> None:
    rule_metric_value_finite(draft(metric_value=-10.5))


def test_rejects_positive_infinity() -> None:
    with pytest.raises(JudgeRejection) as exc_info:
        rule_metric_value_finite(draft(metric_value=math.inf))
    assert exc_info.value.rule == "metric_value_finite"


def test_rejects_negative_infinity() -> None:
    with pytest.raises(JudgeRejection):
        rule_metric_value_finite(draft(metric_value=-math.inf))


def test_rejects_nan() -> None:
    with pytest.raises(JudgeRejection) as exc_info:
        rule_metric_value_finite(draft(metric_value=math.nan))
    assert exc_info.value.rule == "metric_value_finite"
