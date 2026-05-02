# Synapse-L4 — API Reference

All endpoints are served by FastAPI on port `8000` by default. Interactive docs available at `/docs` (Swagger UI) and `/redoc`.

---

## Endpoints

### `POST /ingest`

Submit a raw telemetry packet for processing through the Validation Node pipeline (Consume → Extract → Evaluate → Emit).

**Request body**

```json
{
  "source_id": "sensor-42",
  "payload": {
    "raw_log": "CPU utilization spike detected: 98% for 45s on node prod-03",
    "timestamp": "2026-03-31T14:22:10Z",
    "tags": ["infra", "cpu", "prod"]
  }
}
```

| Field | Type | Required | Description |
|---|---|---|---|
| `source_id` | string | yes | Identifier for the originating EventHorizon source |
| `payload` | object | yes | Unstructured telemetry content — passed as-is to the extractor |

**Response `200 OK`**

```json
{
  "axiom": {
    "status": "critical",
    "metric_value": 98.0,
    "anomaly_score": 0.91,
    "source_id": "sensor-42",
    "emitted_at": "2026-03-31T14:22:11.043Z",
    "domain": "aml"
  },
  "pipeline_ms": 812
}
```

`domain` is omitted from the response (and from the Redis XADD payload) when the compliance domain cannot be determined.

| Field | Type | Description |
|---|---|---|
| `axiom.status` | `"nominal" \| "degraded" \| "critical"` | Classified system state |
| `axiom.metric_value` | float | Primary extracted metric |
| `axiom.anomaly_score` | float [0.0–1.0] | Anomaly confidence score (extracted or fast-path) |
| `axiom.source_id` | string | Echoed from request |
| `axiom.emitted_at` | ISO 8601 datetime | Timestamp of validated emission |
| `axiom.domain` | `"aml" \| "gdpr" \| "hipaa"` _(optional)_ | Compliance domain — absent when ambiguous |
| `pipeline_ms` | int | Total wall-clock time for the full pipeline |

**Response `422 Unprocessable Entity` — extraction failure**

Returned when Instructor exhausts retries without the LLM conforming to the Axiom schema.

```json
{
  "error": "extraction_failed",
  "detail": "LLM did not produce a valid Axiom after N attempts",
  "raw_payload": { ... }
}
```

**Response `422 Unprocessable Entity` — judge rejection**

Returned when extraction succeeds but the Axiom candidate fails the Judge pass.

```json
{
  "error": "judge_rejected",
  "rule": "anomaly_score_status_consistency",
  "detail": "anomaly_score 0.91 requires status 'critical', got 'nominal'",
  "axiom_candidate": { ... }
}
```

**Response `503 Service Unavailable`** — LLM unreachable

**Response `502 Bad Gateway`** — Sentinel-L7 delivery failed

---

### `GET /health`

Liveness check.

**Response `200 OK`**

```json
{
  "status": "ok",
  "version": "0.1.0"
}
```

---

### `GET /metrics`

Returns pipeline performance counters since process start.

**Response `200 OK`**

```json
{
  "total_processed": 1042,
  "extraction_failures": 3,
  "judge_rejections": 11,
  "emit_failures": 0,
  "avg_pipeline_ms": 743
}
```

---

## WebSocket — EventHorizon Consumer

Synapse-L4 can run as a **WebSocket client** connecting to EventHorizon's observation plane (`/live` endpoint). When active, it streams all incoming `{ type: "event" }` messages from EventHorizon and routes each through the Validation Node pipeline automatically.

This is not an inbound WS endpoint on Synapse-L4 itself — it is an outbound subscription managed by `src/clients/eventhorizon.py`.

---

## Error Shape

All error responses follow this envelope:

```json
{
  "error": "<error_code>",
  "detail": "<human-readable message>",
  "<context_key>": { ... }
}
```

| Error code | HTTP status | Meaning |
|---|---|---|
| `extraction_failed` | 422 | Instructor could not coerce LLM output to Axiom schema |
| `judge_rejected` | 422 | Axiom candidate failed a business rule |
| `llm_unavailable` | 503 | LLM API unreachable or returned 5xx |
| `emit_failed` | 502 | Sentinel-L7 delivery failed |
| `invalid_request` | 400 | Request body failed Pydantic validation |
