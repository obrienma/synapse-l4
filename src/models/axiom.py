"""
Shared contract for the Synapse-L4 pipeline.

ALL stages import from this module. No stage defines its own event shape.
Axiom is frozen — once the Judge pass succeeds, the object is immutable.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class Axiom(BaseModel):
    """
    Validated, immutable output of the Synapse-L4 Validation Node.

    frozen=True enforces immutability at the Pydantic level — any attempt to
    set a field after instantiation raises ValidationError. This is not a
    convention; it is a type constraint.
    """

    model_config = ConfigDict(frozen=True)

    status: Literal["nominal", "degraded", "critical"]
    metric_value: float
    anomaly_score: Annotated[float, Field(ge=0.0, le=1.0)]
    source_id: str
    emitted_at: datetime


class RawTelemetry(BaseModel):
    """Loosely-typed input received at the Consume stage."""

    source_id: str
    payload: dict[str, Any]


class JudgeRejection(Exception):
    """
    Raised by the Judge stage when a business rule is violated.

    Carries the rule name so the API layer can return a structured 422 with
    enough detail for the caller to understand what failed and why.
    """

    def __init__(self, rule: str, detail: str, axiom_candidate: Axiom) -> None:
        super().__init__(detail)
        self.rule = rule
        self.detail = detail
        self.axiom_candidate = axiom_candidate


class ExtractionError(Exception):
    """Raised by the Extractor when Instructor exhausts max_retries."""

    def __init__(self, detail: str, raw_payload: dict[str, Any]) -> None:
        super().__init__(detail)
        self.detail = detail
        self.raw_payload = raw_payload
