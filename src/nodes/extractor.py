"""
Extract stage — maps RawTelemetry → AxiomDraft via Instructor.

Pattern: Structured Generation
  The LLM client is patched with Instructor, which uses the provider's
  function-calling protocol to constrain the response to the AxiomDraft
  schema. This is enforced at the API level — not by prompt instructions
  and not by post-hoc JSON parsing.

  Anti-pattern avoided: Prompt Engineering for Output Format
  Telling the LLM to "respond only with JSON matching this schema" has no
  recovery mechanism and no type guarantee. Instructor retries automatically
  with the validation error as feedback, up to max_retries.
"""

from __future__ import annotations

import json
from typing import Any

import instructor
import logfire
import logging
from openai import AsyncOpenAI

logger = logging.getLogger(__name__)
from pydantic import ValidationError

from config import settings
from src.models.axiom import AxiomDraft, ComplianceDomain, ExtractionError, RawTelemetry

_SYSTEM_PROMPT = """\
You are a telemetry analysis system. Given a raw telemetry payload, extract:

- status: overall system state — "nominal", "degraded", or "critical"
- metric_value: the primary numeric metric from the payload (e.g. CPU %, memory %, error rate)
- anomaly_score: your confidence that this reading represents an anomaly, from 0.0 (normal) to 1.0 (critical anomaly)
- domain: the compliance domain this event belongs to — one of "aml", "gdpr", "hipaa", or null if it cannot be determined

Be precise. Do not invent values not present or strongly implied by the payload.
"""

_VALID_DOMAINS: frozenset[str] = frozenset({"aml", "gdpr", "hipaa"})


def _valid_domain(value: object) -> ComplianceDomain | None:
    """Return value if it is a known ComplianceDomain, otherwise None."""
    if isinstance(value, str) and value in _VALID_DOMAINS:
        return value  # type: ignore[return-value]
    return None


def _try_direct_extraction(payload: dict[str, Any]) -> AxiomDraft | None:
    """
    Pattern: Deterministic Fast Path
      If the payload already contains the fields AxiomDraft requires, extract
      them without calling the LLM. This is the common case when EventHorizon
      sends structured events — the LLM is only needed for unstructured text.

    Handles two shapes:
      1. Already-shaped: payload has status/metric_value/anomaly_score directly.
      2. EventHorizon raw document: nested raw.payload + processed.classification.

    Returns None if the payload is missing or invalid for any required field,
    so the caller falls through to LLM-based extraction.
    """
    # Shape 1: already-shaped payload
    try:
        return AxiomDraft(
            status=payload["status"],
            metric_value=payload["metric_value"],
            anomaly_score=payload["anomaly_score"],
            domain=_valid_domain(payload.get("domain")),
        )
    except (KeyError, ValidationError):
        pass

    # Shape 2: EventHorizon raw document — requires at least one structural key
    if "raw" not in payload and "processed" not in payload:
        return None
    try:
        inner: dict[str, Any] = payload.get("raw", {}).get("payload", {})
        processed: dict[str, Any] = payload.get("processed", {})

        pipeline_status = inner.get("status", "")
        classification = processed.get("classification", "")
        if pipeline_status in ("passed", "success"):
            status = "nominal"
        elif pipeline_status in ("failed", "error"):
            status = "critical"
        elif classification == "normal":
            status = "nominal"
        elif classification == "warning":
            status = "degraded"
        elif classification == "critical":
            status = "critical"
        else:
            status = "degraded"

        metric_value = float(inner.get("durationMs") or inner.get("value") or 0.0)

        if classification == "normal":
            anomaly_score = 0.1
        elif classification == "warning":
            anomaly_score = 0.5
        elif classification == "critical":
            anomaly_score = 0.9
        else:
            anomaly_score = 0.3

        return AxiomDraft(
            status=status,
            metric_value=metric_value,
            anomaly_score=anomaly_score,
            domain=_valid_domain(processed.get("domain")),
        )
    except (KeyError, ValidationError):
        return None


def _default_client() -> instructor.AsyncInstructor:
    # Design Decision: client is constructed lazily (on first call) rather than
    # at module import time. This lets tests inject a mock without patching
    # module-level state, and avoids requiring OPENAI_API_KEY at import.
    return instructor.from_openai(AsyncOpenAI(api_key=settings.openai_api_key))


async def extract(
    telemetry: RawTelemetry,
    *,
    client: instructor.AsyncInstructor | None = None,
) -> AxiomDraft:
    """
    Extract structured fields from raw telemetry using the LLM.

    Args:
        telemetry: the raw input from the Consume stage
        client: injectable Instructor client (defaults to OpenAI) — used in tests

    Returns:
        AxiomDraft with status, metric_value, and anomaly_score

    Raises:
        ExtractionError: if the LLM cannot conform to the schema after max_retries,
                         or if the LLM API is unreachable
    """
    logger.debug("extract: payload keys=%s", list(telemetry.payload.keys()))
    fast = _try_direct_extraction(telemetry.payload)
    if fast is not None:
        logfire.info("extract: fast path succeeded, skipping LLM", source_id=telemetry.source_id)
        return fast
    logger.warning("extract: fast path missed, falling through to LLM. payload=%s", telemetry.payload)

    _client = client or _default_client()

    with logfire.span("extract", source_id=telemetry.source_id, llm_model=settings.llm_model):
        try:
            return await _client.chat.completions.create(  # type: ignore[return-value]
                model=settings.llm_model,
                response_model=AxiomDraft,
                max_retries=settings.instructor_max_retries,
                messages=[
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {
                        "role": "user",
                        "content": (
                            f"Source ID: {telemetry.source_id}\n\n"
                            f"Payload:\n{json.dumps(telemetry.payload, indent=2)}"
                        ),
                    },
                ],
            )
        except Exception as exc:
            # TODO: narrow to instructor.exceptions.InstructorRetryException and
            # openai.APIConnectionError for finer-grained error reporting
            raise ExtractionError(
                detail=f"LLM did not produce a valid AxiomDraft: {exc}",
                raw_payload=telemetry.payload,
            ) from exc
