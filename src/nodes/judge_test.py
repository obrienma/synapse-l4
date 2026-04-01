import math

import pytest

from src.models.axiom import AxiomDraft, JudgeRejection
from src.nodes.judge import judge


# ── Helpers ───────────────────────────────────────────────────────────────────

def draft(**kwargs: object) -> AxiomDraft:
    defaults: dict[str, object] = {
        "status": "nominal",
        "metric_value": 42.0,
        "anomaly_score": 0.2,
    }
    return AxiomDraft(**(defaults | kwargs))


# ── Pass cases ────────────────────────────────────────────────────────────────

def test_judge_returns_draft_unchanged_when_all_rules_pass() -> None:
    d = draft()
    result = judge(d)
    assert result is d


def test_judge_passes_critical_with_high_anomaly_score() -> None:
    result = judge(draft(status="critical", metric_value=95.0, anomaly_score=0.92))
    assert result.status == "critical"


def test_judge_passes_degraded_with_mid_anomaly_score() -> None:
    result = judge(draft(status="degraded", metric_value=70.0, anomaly_score=0.65))
    assert result.status == "degraded"


def test_judge_passes_nominal_with_zero_anomaly_score() -> None:
    judge(draft(status="nominal", metric_value=10.0, anomaly_score=0.0))


# ── Reject: anomaly_score_status_consistency ──────────────────────────────────

def test_judge_rejects_nominal_status_with_critical_anomaly_score() -> None:
    with pytest.raises(JudgeRejection) as exc_info:
        judge(draft(status="nominal", anomaly_score=0.85))
    assert exc_info.value.rule == "anomaly_score_status_consistency"


def test_judge_rejects_nominal_status_with_mid_anomaly_score() -> None:
    with pytest.raises(JudgeRejection) as exc_info:
        judge(draft(status="nominal", anomaly_score=0.55))
    assert exc_info.value.rule == "anomaly_score_status_consistency"


def test_judge_rejects_degraded_status_with_critical_anomaly_score() -> None:
    with pytest.raises(JudgeRejection) as exc_info:
        judge(draft(status="degraded", anomaly_score=0.9))
    assert exc_info.value.rule == "anomaly_score_status_consistency"


# ── Reject: metric_value_finite ───────────────────────────────────────────────

def test_judge_rejects_nan_metric_value() -> None:
    with pytest.raises(JudgeRejection) as exc_info:
        judge(draft(metric_value=math.nan))
    assert exc_info.value.rule == "metric_value_finite"


def test_judge_rejects_infinite_metric_value() -> None:
    with pytest.raises(JudgeRejection) as exc_info:
        judge(draft(metric_value=math.inf))
    assert exc_info.value.rule == "metric_value_finite"


# ── Rejection carries draft ───────────────────────────────────────────────────

def test_judge_rejection_carries_the_offending_draft() -> None:
    d = draft(status="nominal", anomaly_score=0.9)
    with pytest.raises(JudgeRejection) as exc_info:
        judge(d)
    assert exc_info.value.draft is d


# ── Rule ordering: metric_value_finite runs before consistency check ──────────

def test_metric_value_rule_fires_before_status_rule() -> None:
    # Both rules would fire on this draft — verify metric_value_finite wins
    d = draft(status="nominal", anomaly_score=0.9, metric_value=math.nan)
    with pytest.raises(JudgeRejection) as exc_info:
        judge(d)
    assert exc_info.value.rule == "metric_value_finite"
