"""
Evaluate stage — runs the Judge pass on an AxiomDraft.

Pattern: Validator-as-Judge
  A deterministic, code-level verification pass after probabilistic LLM
  extraction. The Judge is not another LLM call — it is pure Python logic
  that enforces business rules the LLM cannot be trusted to self-enforce.

  Rules live in src/evaluation/rules.py as plain functions. Adding a new
  rule means adding a function there and appending it to _RULES below.
  No changes to the Judge itself are required.

Fail-fast: the first violated rule raises JudgeRejection immediately.
The pipeline does not accumulate violations.
"""

from __future__ import annotations

from collections.abc import Callable

from src.evaluation.rules import (
    rule_anomaly_score_status_consistency,
    rule_metric_value_finite,
)
from src.models.axiom import AxiomDraft, JudgeRejection

# Rule registry — evaluated in order, fail-fast on first violation.
# TODO: if multiple violations should be reported at once, change to
# collect all JudgeRejections and raise a composite error.
_RULES: list[Callable[[AxiomDraft], None]] = [
    rule_metric_value_finite,               # structural sanity first
    rule_anomaly_score_status_consistency,  # cross-field business logic second
]


def judge(draft: AxiomDraft) -> AxiomDraft:
    """
    Validate an AxiomDraft against all registered business rules.

    Args:
        draft: the AxiomDraft returned by the Extractor

    Returns:
        the same draft, unchanged, if all rules pass

    Raises:
        JudgeRejection: on the first rule violation, with rule name and detail
    """
    for rule in _RULES:
        rule(draft)  # raises JudgeRejection on violation
    return draft
