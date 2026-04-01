"""
Consume stage — FastAPI routes for the Validation Node pipeline.

Pattern: Thin Route Handler
  The route is a coordinator only. It calls extract → judge → emit in
  sequence and maps typed pipeline exceptions to HTTP responses.
  No business logic lives here — that belongs to nodes and evaluation.
"""

from __future__ import annotations

import time
from typing import Any

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from src.models.axiom import EmitError, ExtractionError, JudgeRejection, RawTelemetry
from src.nodes.emitter import emit
from src.nodes.extractor import extract
from src.nodes.judge import judge

router = APIRouter()

# In-memory pipeline counters — reset on process restart.
# TODO: replace with Logfire metrics when observation layer is added (Phase 7).
_metrics: dict[str, int] = {
    "total_processed": 0,
    "extraction_failures": 0,
    "judge_rejections": 0,
    "emit_failures": 0,
    "total_pipeline_ms": 0,
}


@router.post("/ingest")
async def ingest(telemetry: RawTelemetry) -> JSONResponse:
    start = time.monotonic()

    # Stage 1: Extract
    try:
        draft = await extract(telemetry)
    except ExtractionError as exc:
        _metrics["extraction_failures"] += 1
        return JSONResponse(
            status_code=422,
            content={
                "error": "extraction_failed",
                "detail": exc.detail,
                "raw_payload": exc.raw_payload,
            },
        )

    # Stage 2: Evaluate (Judge pass)
    try:
        judge(draft)
    except JudgeRejection as exc:
        _metrics["judge_rejections"] += 1
        return JSONResponse(
            status_code=422,
            content={
                "error": "judge_rejected",
                "rule": exc.rule,
                "detail": exc.detail,
                "axiom_candidate": exc.draft.model_dump(),
            },
        )

    # Stage 3: Emit
    try:
        axiom = await emit(draft, telemetry)
    except EmitError as exc:
        _metrics["emit_failures"] += 1
        return JSONResponse(
            status_code=502,
            content={
                "error": "emit_failed",
                "detail": exc.detail,
                "status_code": exc.status_code,
            },
        )

    elapsed_ms = int((time.monotonic() - start) * 1000)
    _metrics["total_processed"] += 1
    _metrics["total_pipeline_ms"] += elapsed_ms

    return JSONResponse(
        status_code=200,
        content={
            "axiom": axiom.model_dump(mode="json"),
            "pipeline_ms": elapsed_ms,
        },
    )


@router.get("/metrics")
async def metrics() -> dict[str, Any]:
    total = _metrics["total_processed"]
    return {
        "total_processed": total,
        "extraction_failures": _metrics["extraction_failures"],
        "judge_rejections": _metrics["judge_rejections"],
        "emit_failures": _metrics["emit_failures"],
        "avg_pipeline_ms": _metrics["total_pipeline_ms"] // total if total > 0 else 0,
    }
