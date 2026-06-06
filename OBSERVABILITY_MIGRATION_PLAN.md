# OTel Observability Migration — Cross-Service Plan

**Audience:** implementation agent (Claude Code or similar)
**Drop location:** copy this file to the root of each of the four repos as `OBSERVABILITY_MIGRATION_PLAN.md`
**Source of truth:** this plan is ordered across four repos. The phase you can work on depends on which repo you are in AND which prior phases are complete. **Do not skip ahead. Pause checkpoints are mandatory.**

---

## Goal

Unified observability across four services using OpenTelemetry as the signal layer and a self-hosted Grafana stack (Tempo + Loki + Prometheus + Grafana) as the backend. The differentiating outcome is **distributed traces that cross async boundaries** — specifically Redis Streams (Synapse → Sentinel) and RabbitMQ (EventHorizon's internal stages).

## Services in scope

1. `sentinel-l7` (Laravel/PHP) — compliance engine, consumes axioms from Redis Streams
2. `EventHorizon` (TypeScript/Fastify) — four-stage telemetry pipeline over RabbitMQ + MongoDB
3. `synapse-l4` (Python/FastAPI) — LLM validation sidecar, emits to Sentinel via Redis Streams
4. `ruby-invoicer` (Ruby, name TBC) — invoicing against Sentinel customers

## Architecture target

```
[synapse-l4] ──┐
[sentinel-l7] ─┼─ OTLP → [otel-collector] ─┬→ Tempo  (traces)
[EventHorizon]─┤                            ├→ Loki   (logs)
[invoicer]   ──┘                            └→ Prometheus (metrics)
                                              ↓
                                          [Grafana]
```

## Architectural posture: wide spans on pillar backend

The backend is the canonical OSS pillar stack (Tempo + Loki + Prometheus) because it is what most interviewers and most production teams recognize. The *instrumentation* is deliberately wider than a 1.0-style setup: every business-critical span carries as many high-cardinality attributes as the operation knows about — `source_id`, `customer_id`, `domain`, `status`, `anomaly_score`, `driver_used`, etc. Attributes that *could* be span attributes go on spans; we do not pre-aggregate them into Prometheus counters unless there's a concrete operational need.

The reasoning, which is worth being able to articulate verbatim in interviews:

> The pillar backend was a deliberate tradeoff. The wide-events model (Honeycomb, SigNoz, Clickhouse-based stacks) is genuinely better for arbitrary-cardinality debugging — but the pillar stack is more recognizable, has a much larger OSS community, and maps directly to what most companies run including those on Datadog. I instrumented for the wide-events model regardless: rich attributes on every span, queryable via TraceQL. If this needed to scale into production with real cardinality requirements, the migration path is swap Tempo+Prometheus for Clickhouse — the application instrumentation does not change.

This shapes every per-service phase below: when the choice is "Prometheus counter with N labels" vs "rich span attribute," default to span attribute.

## Sequencing rationale

- Synapse first because Logfire is already OTel under the hood — lowest activation energy, validates the pipeline end-to-end.
- Sentinel second because it consumes Synapse — together they prove cross-service trace propagation, the headline result.
- EventHorizon third because it is an independent pipeline; instrumenting it adds the second async boundary (RabbitMQ) to the story.
- Invoicer last because it is the least built — instrumenting too early means rework.

---

## How to use this plan

For each phase below:

1. Check which repo you are in. Skip phases that target other repos.
2. Check whether prior phases are complete (look for the completion marker in their respective repos: `.observability/phase-N-complete`).
3. If a prior phase is incomplete, **STOP** and surface this to the human — they will direct you to the correct repo.
4. When a phase finishes, write `.observability/phase-N-complete` with a one-line summary and commit it. Then **PAUSE** and tell the human the phase is done and which repo to move to next.

---

## Phase 0 — Observability infrastructure

**Repo:** new repo `cyber-rhizome/observability`, OR a sibling `infra/observability/` dir in `sentinel-l7`. Recommend new repo since it's shared across four services. Human decides.

**Goal:** local-runnable Grafana stack with OTel Collector accepting OTLP on 4317 (gRPC) and 4318 (HTTP).

**Tasks:**

1. `docker-compose.yml` with services: `otel-collector`, `tempo`, `loki`, `prometheus`, `grafana`.
2. `otel-collector-config.yaml`:
   - Receivers: `otlp` (grpc + http)
   - Processors: `batch`, `memory_limiter`
   - Exporters: `otlp/tempo`, `loki`, `prometheus`
3. Tempo config (`tempo.yaml`) — local block storage, no S3.
4. Loki config — local filesystem.
5. Prometheus config — scrape collector's `/metrics`.
6. Grafana provisioning: three datasources (Tempo, Loki, Prometheus) auto-configured. One starter dashboard.
7. `README.md` — `docker compose up` should produce a working stack on `localhost:3000` (Grafana).

**Definition of done:**

- `docker compose up` succeeds.
- A curl test (`curl -X POST localhost:4318/v1/traces` with a sample trace payload) produces a visible trace in Tempo via Grafana UI.

**Confidence flags:**

- Exact collector image tags drift — verify `otel/opentelemetry-collector-contrib:latest` is current before pinning.
- Tempo's config schema has changed across minor versions; reference `grafana/tempo` docs for the current `local` storage block.

**PAUSE CHECKPOINT 0:** Stack must be running and a synthetic trace must be visible in Grafana before Phase 1 begins. Commit `.observability/phase-0-complete`.

**STATUS: ✓ Complete** — stack running at `~/dev/rhizome-observability`. Synthetic trace verified in Tempo. Marker: `.observability/phase-0-complete`.

---

## Phase 1 — Synapse-L4 (Python/FastAPI)

**Repo:** `synapse-l4`

**Goal:** Synapse emits OTLP traces to the collector. Trace context (`traceparent`) is propagated on Redis Stream XADD to Sentinel.

**Current state observed:**

- Logfire is already wired in `src/observation/instrumentation.py`.
- `src/nodes/emitter.py` has a `logfire.span("emit", ...)` around the Redis publish.
- `Axiom` payload carries `source_id` and `emitted_at` but no trace context.

**Tasks:**

1. Logfire's SDK already exports OTLP. Add config option to point the OTLP exporter at the local collector (`OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318`) instead of/alongside Logfire's hosted endpoint. Keep Logfire as an optional secondary exporter — do not rip it out.
2. In `src/clients/sentinel.py` (the Redis Streams client — verify path), inject the current trace context as a top-level XADD field named `traceparent`. Use the OTel propagator:
   ```python
   from opentelemetry.propagate import inject
   carrier = {}
   inject(carrier)  # populates {"traceparent": "00-...", "tracestate": "..."}
   ```
   Pass `carrier["traceparent"]` as a top-level field alongside `data`.
3. Make the `emit` span **wide**. Add as many high-cardinality attributes as the operation knows about: `source_id`, `status`, `anomaly_score`, `metric_value`, `domain`, `axiom.emitted_at`. Use OTel attribute API directly rather than going through Logfire's helpers, so the attribute names follow OTel semantic conventions where applicable. The earlier Judge/Extract spans should be similarly widened with `judge.confidence`, `extract.model`, `extract.tokens_in/out` — anything that might be useful to slice by later.
4. **Do not** modify the existing `Axiom` Pydantic model. The `traceparent` is a transport-layer concern, not a business identity concern. Carry it on the stream entry, not inside the JSON payload.

**Definition of done:**

- Triggering a Synapse pipeline run produces a trace visible in Tempo.
- The trace shows the `emit` span with `source_id` as an attribute.
- Inspecting the resulting Redis Stream entry (`XREAD STREAMS synapse:axioms 0`) shows `traceparent` as a top-level field.

**Confidence flags:**

- Logfire+OTel interop: high confidence Logfire SDK respects `OTEL_EXPORTER_OTLP_ENDPOINT`, but verify against current Pydantic Logfire docs before committing the config.
- The exact path of the Redis client in this repo: pattern-matched from memory, verify before editing.

**As-built notes (Phase 1 complete):**

- `OTEL_EXPORTER_OTLP_ENDPOINT` is read by Pydantic Settings into `config.otel_exporter_otlp_endpoint`; the `/v1/traces` path is appended in `instrumentation.py` when constructing `OTLPSpanExporter`.
- Logfire v3 `configure()` accepts `additional_span_processors: list[SpanProcessor]` — this is the dual-export mechanism. Logfire is retained as an optional secondary backend.
- **`service_name` must be passed explicitly** to `logfire.configure(service_name="synapse-l4")`. Without it Tempo shows `unknown_service`. The `OTEL_SERVICE_NAME` env var also works but is less reliable than the explicit parameter. This will bite every subsequent service — see note in Phase 2 confidence flags.
- `traceparent` is injected only when `inject(carrier)` produces a non-empty carrier (i.e. when there is an active span). No active span → no field written → Sentinel-L7 must handle the absent key gracefully.
- Actual `traceparent` format confirmed on stream: `00-<32-hex-trace-id>-<16-hex-span-id>-01`.

**PAUSE CHECKPOINT 1:** Synapse traces visible in Tempo; `traceparent` confirmed on stream entries. Commit `.observability/phase-1-complete`. **Pause before starting Phase 2.**

**STATUS: ✓ Complete** — traces visible in Tempo under service `synapse-l4`; `traceparent` field confirmed on `synapse:axioms` stream entries. Marker: `.observability/phase-1-complete`.

---

## Phase 2 — Sentinel-L7 (Laravel/PHP)

**Repo:** `sentinel-l7`

**Goal:** Sentinel extracts `traceparent` from incoming Redis Stream messages and continues the trace as a child span. End-to-end Synapse → Sentinel trace becomes visible.

**Current state observed:**

- `app/Services/AxiomStreamService.php` reads via `XREADGROUP` and parses flat field arrays.
- `app/Services/AxiomProcessorService.php` processes a single Axiom and routes to AI driver.
- All logging is Laravel `Log::` (Monolog). No trace context anywhere.

**Tasks:**

1. Install OTel:
   - `composer require open-telemetry/sdk open-telemetry/exporter-otlp`
   - For Laravel auto-instrumentation: `composer require open-telemetry/opentelemetry-auto-laravel` (verify current package name before installing).
2. Bootstrap the SDK in `config/otel.php` or via a service provider. Point OTLP at `http://localhost:4318`.
3. In `AxiomStreamService::parseFields()`, surface `traceparent` as a separate return value, not inside the parsed Axiom data. Suggested signature change: return `['fields' => [...], 'traceparent' => '...' | null]`. **Do not** add `traceparent` to the `ComplianceEvent` model or DB schema — it is transport-layer only.
4. In `AxiomProcessorService::process()`, extract the trace context using the OTel propagator and start the work as a child span:
   ```php
   $context = TraceContextPropagator::getInstance()
       ->extract(['traceparent' => $traceparent]);
   $span = $tracer->spanBuilder('axiom.process')
       ->setParent($context)
       ->startSpan();
   ```
   Make this span **wide**. Add every attribute the processing decision touches: `source_id`, `anomaly_score`, `metric_value`, `domain`, `status`, `routed_to_ai`, `risk_level`, `driver_used`, `threshold`, `is_duplicate`, `elapsed_ms`. The `routeToAi()` and `recordSubThreshold()` paths should each get their own child span with the AI driver result fully attributed: `ai.driver`, `ai.confidence`, `ai.policy_refs`, `ai.narrative_length`. Anything you might want to filter or group by in a query goes on a span.
5. New code goes under `app/Services/Compliance/` per repo convention — likely a thin `TraceContextExtractor` helper.
6. **Do not** modify `AxiomStreamService::publish()` to add traceparent on the outbound side yet. There are no current consumers of Sentinel-side publishes; this is YAGNI. Wait until it hurts.

**Definition of done:**

- A Synapse pipeline run produces a single trace in Tempo with at least two services in the waterfall (`synapse-l4.emit` parent → `sentinel-l7.axiom.process` child).
- The trace shows the AI driver call as a further child span (auto-instrumented HTTP).
- `source_id` is queryable as a span attribute in both services.

**Confidence flags:**

- **`service.name` must be set explicitly** — without it Tempo shows `unknown_service`. In PHP, set `OTEL_SERVICE_NAME=sentinel-l7` as an env var before the SDK bootstraps, or pass it in the SDK configuration. This burned time in Phase 1 (Python); don't repeat it here.
- PHP OTel auto-instrumentation packages are less mature than Python/Node equivalents. The `auto-laravel` package may require manual span wiring for Redis (predis is not always auto-instrumented). Budget extra time here.
- The PHP SDK requires the OTel PECL extension OR runs in pure PHP mode — verify Render's PHP image supports the chosen path.

**ADR consideration:** This introduces a new cross-cutting concern. Worth a short ADR documenting "trace context is transport-layer, not domain-layer" — i.e. why traceparent doesn't land in `ComplianceEvent`.

**PAUSE CHECKPOINT 2:** End-to-end Synapse → Sentinel trace must be visible. Commit `.observability/phase-2-complete`. **Pause before starting Phase 3.**

---

## Phase 3 — EventHorizon (TypeScript/Fastify)

**Repo:** `EventHorizon`

**Goal:** All four pipeline stages (ingest → process → store → observe) emit traces. Trace context propagates through RabbitMQ message headers. The known silent-drop issue becomes visible via span events.

**Current state observed:**

- Logging is `console.log/warn/error` with bracketed prefixes — structured by convention only.
- `src/observation/metrics.ts` does in-memory metric counting, not exported.
- No trace context anywhere.

**Tasks:**

1. Install OTel:
   - `npm i @opentelemetry/sdk-node @opentelemetry/auto-instrumentations-node @opentelemetry/exporter-trace-otlp-http @opentelemetry/exporter-logs-otlp-http`
2. Create `src/observation/tracing.ts` that initializes the Node SDK before any other imports. Wire into `src/index.ts` as the **first** import.
3. Auto-instrumentation will cover Fastify, http, amqplib, MongoDB out of the box. Verify each shows up.
4. For RabbitMQ propagation:
   - On publish (ingest → process boundary): inject the current context into message `properties.headers`:
     ```typescript
     const headers: Record<string, string> = {};
     propagation.inject(context.active(), headers);
     channel.publish(exchange, routingKey, content, { headers });
     ```
   - On consume (worker side): extract context from `msg.properties.headers` and run the handler within that context.
5. Replace `console.*` calls with the OTel logs API OR with a structured logger (pino) configured to export via OTLP. Recommend pino + `@opentelemetry/instrumentation-pino` for least churn.
6. The current silent-drop on malformed messages (known issue) should become a span event with `exception.type` and `exception.message` plus the raw message attributes attached. The drop is now a queryable span, not just a counter — you can ask "show me all dropped messages from the last hour grouped by exception.type" via TraceQL. Keep one Prometheus counter (`dropped_messages_total`) for alerting purposes only; everything else is on spans.
7. Each of the four pipeline stages emits a **wide** span: ingest span carries `http.route`, `payload.size_bytes`, `tenant_id`; process span carries `processor.name`, `payload.type`, `enrichment.applied`; store span carries `mongo.collection`, `doc.size_bytes`, `write.duration_ms`; observe span carries `subscribers.count`, `fanout.duration_ms`. Replace the in-memory counters in `metrics.ts` with span attributes wherever possible — only keep Prometheus counters for things that need to drive alerts (queue depth, drop rate).

**Definition of done:**

- A single ingested event produces a four-stage trace in Tempo: HTTP ingest → AMQP publish → AMQP consume → MongoDB write → WebSocket fanout.
- Forcing a malformed message produces a visible span with an exception event AND increments the drop counter in Prometheus.
- Existing tests still pass.

**Confidence flags:**

- Node SDK initialization order is finicky. The `tracing.ts` import MUST come before any instrumented module is imported — this often requires a `-r ./dist/observation/tracing.js` flag at process start rather than a top-of-file import.
- amqplib auto-instrumentation injects context via headers by default in recent versions but check the version pinned in this repo.

**PAUSE CHECKPOINT 3:** Four-stage EventHorizon trace visible; malformed-message drops now produce observable signals. Commit `.observability/phase-3-complete`. **Pause before starting Phase 4.**

---

## Phase 4 — Ruby invoicer

**Repo:** TBC (likely `cyber-rhizome/invoicer` or similar)

**Goal:** Invoicer is instrumented from day one. Any HTTP calls to Sentinel automatically propagate trace context, linking invoicing flows back to the underlying compliance events they bill against.

**Tasks:**

1. Install gems:
   - `opentelemetry-sdk`
   - `opentelemetry-exporter-otlp`
   - `opentelemetry-instrumentation-all` (or pick the specific instrumentations for the chosen framework — Rails, Sinatra, Roda)
2. Configure in an initializer:
   ```ruby
   OpenTelemetry::SDK.configure do |c|
     c.service_name = 'invoicer'
     c.use_all  # auto-instrument everything available
   end
   ```
3. Outbound HTTP calls to Sentinel will automatically inject `traceparent` headers. On the Sentinel side, the Laravel auto-instrumentation from Phase 2 should pick this up automatically — verify the trace links across.
4. Add manual spans around business operations: `invoice.generate`, `invoice.send`, `invoice.mark_paid`. Make these **wide**. Attributes: `customer_id`, `invoice_id`, `amount_cents`, `currency`, `line_items.count`, `period.start`, `period.end`, `billing.plan`, `payment.method`, `email.template_id`. The point is that "which customer hit the longest invoice generation time last month" becomes a TraceQL query, not a custom metric you have to think about in advance.

**Definition of done:**

- Generating a test invoice that queries Sentinel produces a trace spanning both services in Tempo.
- The trace shows Ruby spans (invoicer.invoice.generate) → HTTP call → Sentinel spans (the existing compliance query handler).

**Confidence flags:**

- Ruby OTel is mature but the `use_all` autoload can be slow on startup. If invoicer becomes a CLI tool rather than a long-running server, prefer explicit `c.use 'OpenTelemetry::Instrumentation::Faraday'` etc.

**PAUSE CHECKPOINT 4:** Ruby → Sentinel trace links visible. Commit `.observability/phase-4-complete`.

---

## Phase 5 — Logs and dashboards polish (defer until interview prep needs it)

**Repos:** all four

This phase is decorative compared to traces. The interview talking point is "distributed tracing across async boundaries in four languages" — that lives entirely in phases 0–4. Defer this phase until you have a concrete need (e.g. dashboard screenshots for portfolio site).

When ready:

- Ship logs via OTel Collector → Loki from each service (most SDKs support this in the same OTLP exporter).
- Build dashboards that answer business questions via TraceQL queries over wide span attributes — not via pre-aggregated Prometheus counters. Example queries to support:
  - "Axioms processed per minute, grouped by domain" → TraceQL over `axiom.process` spans grouped by `domain` attribute.
  - "Anomaly score distribution by driver" → TraceQL over `axiom.process` spans, histogram of `anomaly_score` faceted by `driver_used`.
  - "Invoice amount totals by customer" → TraceQL over `invoice.generate` spans grouped by `customer_id`.
- Reserve Prometheus counters exclusively for alerting signals where you need pre-aggregated rates (queue depth, drop rate, error rate). These are operational signals, not analytics. Everything analytics-shaped stays on spans.
- Build one Grafana dashboard per service plus one "executive" dashboard showing the full system. Each panel should ideally be a TraceQL query, not a PromQL query.

---

## Interview narrative artifacts (parallel, not blocking)

Whenever a phase completes, update the corresponding repo's README with an "Observability" section. Recommended structure:

- One sentence on the signal stack (OTel → Collector → Tempo/Loki/Prometheus → Grafana).
- A bullet on cross-service propagation specifically (this is the differentiator).
- A link or embedded screenshot of an example trace.

A portfolio-level architecture diagram showing the full system with trace flow arrows belongs in the `observability` repo's README, not duplicated in each service.

---

## Anti-goals (do not do these without a concrete trigger)

- Do not add Temporal. Async durability is already handled by Redis Streams consumer groups and RabbitMQ — adding Temporal duplicates infrastructure for no current gain. (Separate conversation: Temporal makes sense if the invoicer grows into a multi-step durable workflow. Wait until it hurts.)
- Do not add `traceparent` to the `Axiom` Pydantic model or `ComplianceEvent` DB schema. Transport-layer concern.
- Do not expand OTel instrumentation to cover every function — auto-instrumentation plus manual spans on business-critical operations is the right granularity. Adding spans for trivial helpers creates noise.
- Do not silently replace Logfire with raw OTel in Synapse. Logfire IS OTel; keep it as an exporter option.
- **Do not pre-aggregate business attributes into Prometheus counters.** `axioms_by_domain_total{domain="..."}`, `invoice_amount_by_customer_total{customer_id="..."}` — these belong as wide span attributes queryable via TraceQL, not as pre-committed metric dimensions. Prometheus counters are reserved for things that drive alerts (rates, error counts, queue depth). The discipline matters because once a Prometheus counter exists, people start querying it instead of the spans, and the wide-attribute story degrades over time.

---

## When this plan is fully executed

You will have:

- One unified observability backend (pillar-aligned OSS stack: Tempo + Loki + Prometheus).
- Distributed traces across four languages.
- Trace context propagating across two distinct async boundaries (Redis Streams, RabbitMQ).
- **Wide, high-cardinality spans** on every business-critical operation — instrumented for the wide-events model even though the backend is pillar-aligned.
- A concrete answer to "tell me about a time you improved system reliability through observability" — you built the layer.
- A direct mapping to Owner's stated stack (Datadog ≈ Grafana stack; OTel is vendor-neutral and well-understood by both).
- A defensible answer to the architectural-tradeoff question (see "Architectural posture" above): you can speak to the wide-events vs three-pillars debate, name what you chose, name what you'd do at scale, and name the migration path.
