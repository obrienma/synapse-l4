"""
Logfire instrumentation for Synapse-L4.

Pattern: Additive Observability
  Instrumentation is layered on top of the pipeline — it never changes
  correctness. When LOGFIRE_TOKEN is absent, Logfire runs in no-op mode
  (send_to_logfire=False). Spans are still created locally but not sent.

  Anti-pattern avoided: Observability as a Hard Dependency
  If the pipeline required a live Logfire connection to function, a missing
  token would break production. Observability must degrade gracefully.
"""

from __future__ import annotations

from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.trace.export import BatchSpanProcessor

import logfire

from config import settings


def configure_logfire() -> None:
    """
    Configure Logfire at startup.

    Called once from main.py lifespan before any requests are handled.
    When LOGFIRE_TOKEN is not set, runs in local no-op mode — spans are
    created but not exported. The pipeline behaves identically either way.

    When OTEL_EXPORTER_OTLP_ENDPOINT is set, an additional OTLP/HTTP exporter
    is wired alongside Logfire so spans are forwarded to the local collector
    (Tempo/Grafana stack) without removing Logfire as a secondary backend.
    """
    additional: list[BatchSpanProcessor] = []
    if settings.otel_exporter_otlp_endpoint:
        endpoint = f"{settings.otel_exporter_otlp_endpoint.rstrip('/')}/v1/traces"
        additional.append(BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint)))

    if settings.logfire_token:
        logfire.configure(
            token=settings.logfire_token,
            service_name="synapse-l4",
            additional_span_processors=additional,
        )
    else:
        logfire.configure(
            send_to_logfire=False,
            service_name="synapse-l4",
            additional_span_processors=additional,
        )


def instrument_fastapi(app: object) -> None:
    """Attach Logfire automatic instrumentation to the FastAPI app."""
    logfire.instrument_fastapi(app)  # type: ignore[arg-type]


def instrument_httpx() -> None:
    """Instrument httpx for outbound HTTP tracing (Sentinel-L7 client spans)."""
    logfire.instrument_httpx()
