"""
Business rule validators for the Judge stage.

Each rule is a plain function: takes an AxiomDraft, returns None (pass)
or raises JudgeRejection (fail). No I/O, no LLM calls, no side effects.

Thresholds are module-level constants for now.
TODO: promote to config.py env vars when operational tuning is needed.
"""

from __future__ import annotations

import math

from src.models.axiom import AxiomDraft, JudgeRejection

# Anomaly score thresholds — cross-field consistency boundaries
ANOMALY_CRITICAL_THRESHOLD: float = 0.8  # score >= this requires status "critical"
ANOMALY_DEGRADED_THRESHOLD: float = 0.5  # score >= this requires status "degraded" or "critical"


def rule_anomaly_score_status_consistency(draft: AxiomDraft) -> None:
    """
    High anomaly scores must be reflected in the status field.

    The LLM could contradict itself — extracting a near-certain anomaly
    but classifying the system as "nominal". This rule catches that.

    Anti-pattern avoided: Silent Contradiction — an Axiom where the
    anomaly_score screams "critical" but status says "nominal" would cause
    Sentinel-L7 to file a non-urgent record for a critical event.
    """
    if draft.anomaly_score >= ANOMALY_CRITICAL_THRESHOLD and draft.status != "critical":
        raise JudgeRejection(
            rule="anomaly_score_status_consistency",
            detail=(
                f"anomaly_score {draft.anomaly_score:.2f} >= {ANOMALY_CRITICAL_THRESHOLD} "
                f"requires status 'critical', got '{draft.status}'"
            ),
            draft=draft,
        )

    if draft.anomaly_score >= ANOMALY_DEGRADED_THRESHOLD and draft.status == "nominal":
        raise JudgeRejection(
            rule="anomaly_score_status_consistency",
            detail=(
                f"anomaly_score {draft.anomaly_score:.2f} >= {ANOMALY_DEGRADED_THRESHOLD} "
                f"requires status 'degraded' or 'critical', got 'nominal'"
            ),
            draft=draft,
        )


def rule_metric_value_finite(draft: AxiomDraft) -> None:
    """
    metric_value must be a finite number — not NaN, not ±Infinity.

    LLMs occasionally hallucinate sentinel float values (Infinity, -1.0
    for "unknown") when the payload doesn't contain a clear numeric metric.
    Pydantic accepts these as valid floats; this rule rejects them.
    """
    if not math.isfinite(draft.metric_value):
        raise JudgeRejection(
            rule="metric_value_finite",
            detail=f"metric_value must be finite, got {draft.metric_value}",
            draft=draft,
        )
