# Synapse-L4 — Learning Log

Append-only. One entry per build phase. Format: Pattern → Anti-Pattern → Challenge → Decision, each with Q:/A: flashcard blocks for active recall.

---

## ADR-0016 Migration — Redis Streams Delivery

**Completed:** 2026-03-31
**Files changed:** `pyproject.toml`, `config.py`, `.env.example`, `src/clients/sentinel.py`, `src/clients/sentinel_test.py`, `src/nodes/emitter.py`

---

### Patterns Used

**At-Least-Once Delivery via Redis Streams**
Replacing the HTTP POST to Sentinel-L7 with a Redis XADD to `synapse:axioms` decouples Synapse-L4 from Sentinel-L7's availability. XADD is non-blocking — it appends to the stream and returns as soon as the message is durably written. Sentinel-L7 reads via `XREADGROUP` with `XACK`/`XCLAIM` recovery, ensuring no Axiom is lost on worker failure.

> **Q:** What delivery guarantee does HTTP POST provide, and how does Redis Streams improve on it?
> **A:** HTTP POST is at-most-once by default — if Sentinel-L7 is down, the message is lost. Redis Streams with consumer groups provides at-least-once: the message lives in the stream until a consumer explicitly ACKs it. If a worker crashes before ACKing, `XCLAIM` recovery reassigns the message to another worker.

---

**Decoupled Producer**
Synapse-L4 does not block on Sentinel-L7 processing time. XADD returns in microseconds regardless of how long Sentinel-L7 takes to classify the Axiom. Under high telemetry volume, this prevents back-pressure from the downstream consumer from stalling the upstream pipeline.

> **Q:** Why is XADD non-blocking even under high Sentinel-L7 load?
> **A:** XADD writes to the stream (an in-memory Redis data structure) and returns immediately. Sentinel-L7's processing speed is irrelevant to the producer — the stream acts as an elastic buffer. The producer and consumer are temporally decoupled.

---

**Stream-Per-Domain Separation**
`synapse:axioms` is a dedicated stream, separate from Sentinel-L7's existing `transactions` stream. Axioms are dimensionally different from financial transactions — mixing them in a shared consumer pipeline would couple unrelated schemas and create fan-out ambiguity.

> **Q:** Why not reuse Sentinel-L7's existing `transactions` stream?
> **A:** `transactions` has its own consumer group, schema assumptions, and processing logic. Injecting Axioms there would require Sentinel-L7's transaction consumer to branch on message type — coupling two unrelated domains. A dedicated `synapse:axioms` stream gives each domain a clean consumer pipeline.

---

### Anti-Patterns Avoided

**Synchronous HTTP Coupling**
The original `sentinel.py` used `httpx.AsyncClient.post()` — still async, but still tightly coupled: Sentinel-L7 must be reachable, respond within timeout, and return 2xx for the emit to succeed. A Redis stream absorbs transient unavailability. The producer writes; the consumer reads when it's ready.

> **Q:** Name the failure mode that HTTP coupling introduces that Redis Streams eliminates.
> **A:** Sentinel-L7 deploys a new version and restarts mid-stream. With HTTP: the in-flight emit fails with `ConnectionRefused`; Synapse-L4 raises `EmitError`; the Axiom is lost (no retry budget in Phase 4). With Redis Streams: XADD succeeds before the restart; the Axiom sits in the stream; Sentinel-L7 reads it after restart. The producer is oblivious to the consumer's lifecycle.

---

### Challenges

**`rediss://` vs `redis://` for TLS**
`redis.asyncio.from_url()` requires `rediss://` (double-s) for TLS connections. Upstash's `.env.example` docs show separate `REDIS_HOST`/`REDIS_PORT`/`REDIS_PASSWORD` vars — these must be assembled into a single `rediss://:PASSWORD@HOST:PORT` URL for `aioredis`. The `redis://` scheme silently connects without TLS, which Upstash rejects.

---

**Config field rename blocks test collection**
Renaming `sentinel_l7_url` (required) to `sentinel_redis_url` (required) + `sentinel_l7_url` (optional) causes `ValidationError` at import time if `.env` still has the old var name. pytest collection fails before any test runs — not with a test failure, but with a module import error. The fix is updating `.env` before running the suite, not after.

---

### Decisions

**`EmitError` wraps all Redis exceptions**
`SentinelClient.post_axiom` catches the broad `Exception` base class and re-raises as `EmitError` with `raise ... from exc`. This preserves exception chaining (`__cause__`) while presenting a stable error type to the emitter. The caller never needs to know whether the failure was `ConnectionError`, `TimeoutError`, or a Redis-specific exception.

> **Q:** Why catch `Exception` broadly in `post_axiom` instead of specific Redis exception types?
> **A:** `redis.asyncio` can raise `ConnectionError`, `TimeoutError`, `ResponseError`, and others depending on the failure mode. Catching each type explicitly creates a brittle allowlist — a new Redis exception type would silently propagate uncaught. Broad catch + typed re-raise gives the caller a stable contract while retaining the original for debugging via `__cause__`.

**`sentinel_l7_url` retained as optional**
The config field is kept (now optional) for health check use cases and to avoid breaking any existing tooling that reads it. It is not used in the current emit path.

---

## Phase 7 — Logfire Observation Layer

**Completed:** 2026-03-31
**Files:** `src/observation/instrumentation.py`, `src/observation/instrumentation_test.py`
**Updated:** `src/nodes/extractor.py`, `src/nodes/judge.py`, `src/nodes/emitter.py`, `main.py`

---

### Patterns Used

**Additive Observability**
Instrumentation is layered on top of the pipeline — it never changes correctness. Logfire spans wrap each stage but do not alter return values, exception behaviour, or control flow. If Logfire is misconfigured or unavailable, the pipeline continues unaffected.

> **Q:** What does "additive observability" mean in practice for this pipeline?
> **A:** Each `logfire.span()` call wraps existing code without modifying it. If Logfire's SDK raises an unexpected error internally, it is caught by Logfire itself — it does not propagate to the pipeline. Observability is a side effect of the pipeline, not a dependency of it.

---

**No-Op Mode for Missing Config**
When `LOGFIRE_TOKEN` is absent, `configure_logfire()` calls `logfire.configure(send_to_logfire=False)`. Spans are created in-process but never exported. The full test suite runs without a Logfire token — tests verify that spans don't crash the pipeline, not that spans have specific attributes.

> **Q:** Why is verifying span attribute structure left to the Logfire UI rather than automated tests?
> **A:** Span structure assertions would couple tests to Logfire's internal representation. If Logfire changes how attributes are stored or named, tests would break for non-functional reasons. What matters is that the pipeline behaves correctly — span content is an operational concern verified manually.

---

### Anti-Patterns Avoided

**Observability as a Hard Dependency**
If `configure_logfire()` raised when `LOGFIRE_TOKEN` was absent, a missing env var would prevent the service from starting. Observability must never be a gating dependency — the pipeline should run in a degraded-observability mode before it fails to start.

---

### Decisions

**Spans at stage boundaries, not inside rules**
`logfire.span("judge", ...)` wraps the full Judge pass, not individual rules. Adding a span per rule would produce noisy traces for a synchronous operation that completes in microseconds. Stage-level spans give enough resolution to identify which phase of the pipeline is slow or failing.

**`instrument_fastapi` and `instrument_httpx` called in lifespan**
Both need the `app` instance and a configured Logfire client — neither is available at import time. Lifespan is the correct place for startup instrumentation that depends on runtime state.

---

## Phase 6 — EventHorizon WebSocket Consumer

**Completed:** 2026-03-31
**Files:** `src/clients/eventhorizon.py`, `src/clients/eventhorizon_test.py`, `main.py` (lifespan wired)

---

### Patterns Used

**Resilient Async Subscriber**
A long-lived WebSocket client with exponential backoff reconnection. The outer `run()` loop catches `ConnectionClosed` and any unexpected exception, sleeps for an increasing delay, and retries. Delay starts at 1s, doubles on each failure, caps at 60s, resets to 1s on clean reconnect. `asyncio.CancelledError` is re-raised immediately — it is the shutdown signal, not a failure.

> **Q:** Why is `asyncio.CancelledError` re-raised in the reconnection loop rather than caught and retried?
> **A:** `CancelledError` means the task was cancelled by the caller (lifespan shutdown). Catching and retrying it would make the consumer impossible to stop gracefully. Every other exception is a transient failure worth retrying; `CancelledError` is an intentional termination signal.

---

**Per-Message Resilience**
`_handle_message` catches all pipeline exceptions (`ExtractionError`, `JudgeRejection`, `EmitError`) and logs them without re-raising. A single bad telemetry packet must not stop the consumer — the stream continues. JSON parse errors are also caught and skipped.

> **Q:** Why does a pipeline failure on one message not stop the consumer?
> **A:** The consumer is a stream processor. EventHorizon sends hundreds of events — if one causes a `JudgeRejection`, the correct response is to log it, skip it, and process the next one. Crashing the consumer on a single bad event would require a full reconnect and potentially lose subsequent events during the gap.

---

**Direct Pipeline Invocation (Bypass HTTP)**
The consumer calls `extract → judge → emit` directly — not via `POST /ingest`. The HTTP route and the WS consumer are two entry points to the same pipeline functions. This avoids an unnecessary HTTP round-trip and keeps the consumer testable without starting the HTTP server.

> **Q:** What would go wrong if the WebSocket consumer called `POST /ingest` over HTTP instead of calling pipeline functions directly?
> **A:** It would depend on the HTTP server being up and reachable (localhost coupling), add latency for every event, and require a real server in consumer tests. The pipeline functions are importable independently — using them directly is simpler and correct.

---

### Anti-Patterns Avoided

**Crashing on Bad Input**
A consumer that raises on malformed JSON or a pipeline error would disconnect from EventHorizon on every bad message, triggering a reconnect cycle. The exponential backoff would cause increasing delays processing subsequent valid messages. Per-message resilience prevents this entirely.

**Ignoring Shutdown**
Re-raising `asyncio.CancelledError` immediately (rather than catching it in the reconnect loop) ensures the consumer stops cleanly when `lifespan` cancels the task. Without this, the task would swallow the cancellation and continue running after FastAPI tries to shut down.

---

### Decisions

**`_consume` and `run` as separate functions**
`_consume` handles a single connection. `run` handles the reconnection loop. This separation makes both independently testable: `_consume` tests verify message routing through a mock WS; `run` tests verify reconnection by patching `_consume` itself.

**TODO on `_event_to_telemetry` field mapping**
The exact EventHorizon `StoredEvent` shape isn't confirmed yet — the mapping uses `raw.id` as `source_id` with a fallback chain. This is a known approximation, documented with a TODO, to be aligned when end-to-end integration is tested.

---

## Phase 5 — FastAPI Ingest Route

**Completed:** 2026-03-31
**Files:** `src/api/ingest.py`, `src/api/ingest_test.py`, `main.py` (router wired)

---

### Patterns Used

**Thin Route Handler**
The `/ingest` route is a pure coordinator — it calls `extract → judge → emit` in sequence and maps typed pipeline exceptions to HTTP responses. No business logic lives in the route. This keeps each concern testable in isolation: route tests mock the pipeline functions entirely; pipeline tests never touch HTTP.

> **Q:** Why mock `extract`, `judge`, and `emit` at the route level in tests rather than testing the full pipeline end-to-end?
> **A:** Route tests verify the HTTP contract — correct status codes, correct error keys, correct response shape. If they tested the full pipeline, a failing LLM call would break a route test. Isolation means route tests are fast, deterministic, and don't require LLM credentials.

---

**Exception-to-HTTP Mapping**
Each pipeline exception type maps to a specific HTTP status code and error envelope. `ExtractionError` and `JudgeRejection` are both client-recoverable (422); `EmitError` is a downstream failure (502). The error `code` field in the response body is machine-readable — callers can branch on `"judge_rejected"` without parsing the `detail` string.

> **Q:** Why are `ExtractionError` and `JudgeRejection` both 422 rather than different codes?
> **A:** Both mean the pipeline could not produce a valid Axiom from the given input. From the caller's perspective, the remedy is the same: inspect the error, fix the input, retry. A 422 signals "unprocessable" — accurate for both. Giving them different codes would suggest different retry strategies where none exist.

---

### Anti-Patterns Avoided

**Fat Route Handler**
Putting extraction logic, business rules, or delivery logic inside the route handler. This makes the route untestable without mocking infrastructure (LLM, HTTP clients) and makes the pipeline stages unreusable outside the HTTP context (e.g. from the WebSocket consumer).

**Divide-by-Zero on Metrics**
`avg_pipeline_ms` is `total_pipeline_ms // total_processed`. When `total_processed` is 0, this would raise `ZeroDivisionError`. The route guards with `if total > 0 else 0`. The test `test_metrics_avg_pipeline_ms_is_zero_when_no_requests_processed` verifies this on a fresh process.

---

### Decisions

**`JSONResponse` over `raise HTTPException`**
`HTTPException` in FastAPI wraps the detail in `{"detail": ...}`. Our error envelope uses `{"error": ..., "detail": ..., "rule": ...}` — a richer shape. Returning `JSONResponse` directly gives full control over the response body without fighting FastAPI's default exception serialization.

> **Q:** Where is the structured error envelope actually consumed, and why does the shape matter?
> **A:** By any client hitting `POST /ingest` — primarily Sentinel-L7. A client can branch on `body["error"] == "judge_rejected"` vs `"extraction_failed"` without parsing a nested string. `HTTPException` would wrap the body under `{"detail": {...}}`, forcing callers to unwrap one extra layer. The WebSocket consumer (Phase 6) bypasses HTTP entirely and calls the pipeline functions directly — it never sees these responses.

**In-memory metrics counter with a TODO**
A module-level `_metrics` dict is sufficient for Phase 5. It resets on process restart, is not thread-safe across multiple workers, and is not persisted. The TODO points to Logfire (Phase 7) where proper metrics instrumentation will replace it.

---

## Phase 4 — Emitter + Sentinel-L7 Client

**Completed:** 2026-03-31
**Files:** `src/models/axiom.py` (added `EmitError`), `src/clients/sentinel.py`, `src/clients/sentinel_test.py`, `src/nodes/emitter.py`, `src/nodes/emitter_test.py`

---

### Patterns Used

**AxiomDraft → Axiom Promotion**
The Emitter is the only place in the pipeline where a full `Axiom` is constructed. It merges the LLM-extracted fields from `AxiomDraft` with pipeline-owned fields: `source_id` from `RawTelemetry` and `emitted_at` stamped at the moment of delivery. No other stage constructs an `Axiom` — this is enforced by design, not convention.

> **Q:** Why is `emitted_at` stamped in the Emitter rather than earlier in the pipeline?
> **A:** `emitted_at` is a timestamp of when the validated Axiom was *delivered* to Sentinel-L7 — not when it was extracted or judged. The time between extraction and emission is non-trivial (Judge pass, potential retries). Stamping it at extraction time would produce a timestamp Sentinel-L7 can't trust as a delivery marker.

---

**Idempotent Emission**
The Axiom carries `source_id` + `emitted_at` so Sentinel-L7 can deduplicate on re-delivery. If the emitter retries after a transient network failure, Sentinel-L7 can detect the duplicate by comparing `source_id` and `emitted_at` and discard it safely.

> **Q:** What is idempotent emission and why does it matter for a microservice pipeline?
> **A:** Idempotent emission means delivering the same Axiom multiple times has the same effect as delivering it once. In a distributed system, retries are inevitable — networks fail, timeouts occur. Without deduplication keys (`source_id` + `emitted_at`), a retry would insert a duplicate record in Sentinel-L7. The Axiom carries its own identity so the receiver can make delivery safe.

---

**Injectable HTTP Client for Testability**
`SentinelClient` accepts an `httpx.AsyncClient` at construction. Tests inject a real `httpx.AsyncClient` mocked at the network layer via `respx`. The emitter tests inject a mock `SentinelClient` entirely. Two levels of injection — one for network-level tests (sentinel_test.py), one for pipeline-level tests (emitter_test.py).

> **Q:** Why use `respx` in `sentinel_test.py` rather than mocking `SentinelClient` directly?
> **A:** `sentinel_test.py` tests the HTTP contract — that the correct URL is called, the correct payload is sent, and non-2xx responses raise `EmitError`. These are questions about the HTTP layer, not the pipeline. Mocking `SentinelClient` entirely would skip verifying that the client actually makes the right HTTP call.

---

### Anti-Patterns Avoided

**Emitting on Failure**
The Axiom is only returned to the caller if `post_axiom` succeeds. If `EmitError` is raised, the function exits without returning — the caller cannot mistakenly treat a failed emission as a success. This is enforced by the control flow: `await _client.post_axiom(axiom)` raises before `return axiom` is reached.

**Constructing Axiom Before Delivery Succeeds**
The `Axiom` is constructed inside `emit()`, not before the call. This ensures `emitted_at` reflects actual delivery time rather than when the function was entered.

---

### Decisions

**HTTP POST over Redis XADD (for now)**
ADR-0016 in Sentinel-L7 documents the open decision. HTTP is implemented first because `SENTINEL_L7_URL` is already the only required downstream config, and the synchronous request/response model is simpler to test with `respx`. If Redis Streams are chosen, `src/clients/sentinel.py` is the only file that changes — the emitter node is unaffected.

**`EmitError` carries the Axiom**
The failed Axiom is attached to `EmitError` so the API layer can include it in the 502 response body. Callers that want to retry have the full Axiom available without reconstructing it. This mirrors the pattern established by `JudgeRejection` (carries draft) and `ExtractionError` (carries raw payload).

---

## Phase 3 — Judge Pass + Business Rules

**Completed:** 2026-03-31
**Files:** `src/evaluation/rules.py`, `src/evaluation/rules_test.py`, `src/nodes/judge.py`, `src/nodes/judge_test.py`
**Also:** fixed `extra="forbid"` on `AxiomDraft`

---

### Patterns Used

**Validator-as-Judge**
A deterministic code-level verification pass that runs *after* probabilistic LLM extraction. The Judge is not another LLM call — it enforces business rules that the LLM cannot be trusted to self-enforce. Rules are pure Python functions with no I/O, making them trivially unit-testable and independently auditable.

> **Q:** Why is the Judge a separate stage rather than being embedded inside Instructor's retry loop via Pydantic validators?
> **A:** Instructor retries when the LLM can't conform to the schema. Business rule violations are often not recoverable by retrying with the same input — they indicate ambiguous telemetry. Retrying wastes tokens. A separate Judge stage also produces a distinct error type (`JudgeRejection` vs. `ExtractionError`), making the failure reason unambiguous in logs and API responses.

---

**Rule Registry Pattern**
Rules are registered in an ordered list (`_RULES`) in `judge.py`. Adding a new business rule requires only adding a function to `rules.py` and appending it to the list — the `judge()` function itself never changes. This is the *Open/Closed Principle*: the Judge is open to extension (new rules) but closed to modification.

> **Q:** What does the rule registry pattern enable that a long `if/elif` chain inside `judge()` does not?
> **A:** Each rule is independently testable in isolation. New rules can be added without touching `judge.py`. The registry is readable as a list — rule ordering is explicit and auditable. An `if/elif` chain grows without bound and mixes concerns (rule logic with orchestration logic).

---

**Fail-Fast Validation**
The Judge runs rules in order and raises `JudgeRejection` on the first violation. It does not accumulate errors. This is the correct default for a pipeline: a draft with a non-finite `metric_value` and a status inconsistency is broken — there is no value in reporting both violations when the first alone is sufficient to reject it.

> **Q:** When would you change fail-fast to collect-all violations?
> **A:** When the caller needs to fix all errors in one round-trip — e.g. a form validation UX. In a machine-to-machine pipeline like this one, the caller (Synapse-L4 API) returns a 422 and the LLM re-runs. Knowing there are two violations rather than one doesn't change that outcome.

---

### Anti-Patterns Avoided

**Silent Contradiction**
An Axiom where `anomaly_score` is 0.91 but `status` is `"nominal"` would be internally contradictory. Sentinel-L7 would file a low-priority record for a near-certain anomaly. The `anomaly_score_status_consistency` rule makes this physically impossible to emit.

**Accepting Sentinel Float Values**
LLMs hallucinate `Infinity` or `NaN` for `metric_value` when the payload lacks a clear numeric signal. Pydantic accepts these as valid Python `float`s — they pass field validation. The `metric_value_finite` rule catches them before emission. Without it, Sentinel-L7 would receive a JSON payload with `"metric_value": Infinity`, which is not valid JSON and would cause a parse error downstream.

---

### Decisions

**Rule ordering: `metric_value_finite` before `anomaly_score_status_consistency`**
Structural sanity checks run before cross-field business logic. A draft with `metric_value=NaN` is structurally broken regardless of its status — there's no point evaluating the status rule. This also makes test assertions deterministic: when both rules would fire, the test can assert which rule name appears in the rejection.

> **Q:** Why does `metric_value_finite` run before `anomaly_score_status_consistency`?
> **A:** Structural validity before semantic consistency. You can't meaningfully ask "does this number's magnitude match the status?" if the number is NaN — the draft is already broken before business logic applies. Verifying a value is finite confirms it's a real measurement before checking what that measurement implies.

**Thresholds as module-level constants, not env vars (for now)**
`ANOMALY_CRITICAL_THRESHOLD = 0.8` and `ANOMALY_DEGRADED_THRESHOLD = 0.5` live in `rules.py`. Moving them to `config.py` as env vars enables operational tuning without code changes but adds cognitive overhead before the thresholds have been empirically validated. Deferred intentionally — see TODO in `rules.py`.

---

## Phase 2 — AxiomDraft Model + Extractor Node

**Completed:** 2026-03-31
**Files:** `src/models/axiom.py` (added `AxiomDraft`), `src/nodes/extractor.py`, `src/nodes/extractor_test.py`

---

### Patterns Used

**Bounded LLM Responsibility**
The LLM only fills in what it can uniquely determine from the payload — `status`, `metric_value`, `anomaly_score`. Pipeline-owned fields (`source_id`, `emitted_at`) are supplied from authoritative sources: `RawTelemetry` and the system clock at emission time. `AxiomDraft` encodes this boundary in the type system — the LLM literally cannot set fields it doesn't own.

> **Q:** Why does `AxiomDraft` not include `source_id` or `emitted_at`?
> **A:** `source_id` is already known with certainty from `RawTelemetry` — asking the LLM to echo it back introduces a trust gap. `emitted_at` doesn't exist yet at extraction time; it's stamped at delivery. Letting the LLM set either would mean trusting a probabilistic model with data the pipeline already holds deterministically.

---

**Injectable Client for Testability**
The extractor's `client` parameter defaults to `None` and builds the real Instructor client lazily on first call. Tests pass a mock directly — no `unittest.mock.patch` at the module level, no import-time side effects. This is the *Dependency Injection* pattern applied to async clients.

> **Q:** Why is the Instructor client constructed lazily (`_default_client()`) rather than at module import time?
> **A:** Module-level client construction runs `OPENAI_API_KEY` validation at import. Any test that imports the extractor would require a valid API key in the environment, even tests that never make a real LLM call. Lazy construction keeps tests self-contained and fast.

---

**Exception Chaining (`raise ... from exc`)**
`ExtractionError` is raised with `from exc`, preserving the original exception as `__cause__`. This means the full traceback — including the underlying `APIConnectionError` or `InstructorRetryException` — is visible in logs even though callers only handle `ExtractionError`. The stage boundary is clean outward; the debug trail is complete inward.

> **Q:** What does `raise ExtractionError(...) from exc` do that `raise ExtractionError(...)` alone does not?
> **A:** It sets `__cause__` on the new exception, explicitly linking it to the original. Python's traceback renderer prints both. Without it, the original exception is lost — you see `ExtractionError` in logs but not the underlying `APIConnectionError` that caused it.

---

### Anti-Patterns Avoided

**Prompt Engineering for Output Format**
Instructing the LLM to "return JSON matching this schema" with no enforcement mechanism — no retry, no type guarantee, no recovery path. Instructor replaces this entirely by using function-calling at the protocol level. If the model returns a non-conforming response, Instructor retries with the validation error as feedback. The schema is the source of truth, not the prompt.

---

**Leaking Third-Party Exceptions Across Stage Boundaries**
Without the `try/except` wrapper, a network timeout from `httpx` or an exhausted retry from `instructor` would propagate raw through the pipeline. The API layer would need to know about `openai.APIConnectionError` to return a sensible 503 — a direct coupling between the HTTP layer and the LLM client library. Wrapping in `ExtractionError` keeps each stage's error vocabulary self-contained.

---

### Challenges

**`AxiomDraft` extra fields rejection**
Pydantic v2 models reject extra fields by default only if `model_config = ConfigDict(extra="forbid")` is set. Without it, `AxiomDraft(source_id="x", ...)` silently ignores the extra field rather than raising `ValidationError`. The test `test_axiom_draft_has_no_source_id_or_emitted_at` catches this — but the fix (adding `extra="forbid"`) is a TODO for the implementation phase.

> **Q:** What happens if you pass `source_id` to `AxiomDraft` without `extra="forbid"`?
> **A:** Pydantic v2 silently ignores the unknown field by default. The model constructs successfully — the test would pass for the wrong reason. `extra="forbid"` makes the model actively reject unknown fields with a `ValidationError`.

---

### Decisions

**`AxiomDraft` rather than a partial `Axiom`**
An alternative would be making `source_id` and `emitted_at` optional on `Axiom` and treating a partially-populated instance as a draft. This was rejected because it allows a partially-constructed `Axiom` to be passed to the Emitter without ever being promoted — the type system can't distinguish "draft Axiom" from "complete Axiom". Separate types make invalid pipeline states unrepresentable.

> **Q:** Why not just make `source_id` and `emitted_at` optional on `Axiom` instead of creating `AxiomDraft`?
> **A:** Optional fields mean the Emitter could accidentally emit an `Axiom` with `source_id=None`. The type system cannot tell the difference between "draft Axiom awaiting promotion" and "complete Axiom ready for emission". Separate types make the pipeline stage contract explicit — `AxiomDraft` in, `Axiom` out.

---

## Phase 1 — Project Scaffold + Axiom Contract

**Completed:** 2026-03-31
**Files:** `pyproject.toml`, `config.py`, `.env.example`, `src/models/axiom.py`, `src/models/axiom_test.py`, `main.py`

---

### Patterns Used

**Specification-Driven Development**
Define the data contract (`Axiom`) before writing any pipeline logic. Every stage in Phases 2–4 will be written *to satisfy this model*, not the other way around. This is the same principle as writing a DB schema before writing queries — the schema is the spec.

> **Q:** Why define `Axiom` in Phase 1 before any pipeline code exists?
> **A:** Because every pipeline stage (Extract, Judge, Emit) depends on the same type. If each stage defined its own shape, schema drift between stages would be inevitable — and likely silent. `models/axiom.py` as the single source of truth prevents this class of bug structurally.

---

**Fail-Fast Configuration**
`config.py` uses Pydantic `BaseSettings`. The `settings` object is instantiated at module import time. If any required env var is missing or the wrong type, `ValidationError` is raised before FastAPI binds to a port. The service refuses to start in a broken state.

> **Q:** Why is fail-fast configuration better than catching missing config at request time?
> **A:** A service that starts but fails on the first request looks like a runtime bug. A service that refuses to start with a clear "field: sentinel_l7_url — field required" message is immediately debuggable. Fail-fast makes the deployment contract explicit.

---

**Frozen Value Objects**
`Axiom` uses `model_config = ConfigDict(frozen=True)`. This is the Value Object pattern from Domain-Driven Design — an object whose identity is its value, not its reference, and which cannot be mutated after creation. In a pipeline, the validated output of one stage should not be modifiable by the next.

> **Q:** What is the difference between `frozen=True` in Pydantic and just not mutating the object by convention?
> **A:** Convention is not enforced. Any function that receives an `Axiom` can mutate it, silently corrupting the verified state before emission. `frozen=True` raises `ValidationError` at the point of mutation — the error is immediate, located, and unambiguous. The type system enforces the invariant; documentation cannot.

---

**Type-Driven Error Modeling**
`JudgeRejection` and `ExtractionError` are typed exception classes with named fields (`rule`, `detail`, `axiom_candidate`, `raw_payload`). This is not just style — the API layer uses `exc.rule` to build a structured `422` response. An untyped `raise Exception("rejected")` would require string parsing to extract the same information.

> **Q:** Why model pipeline errors as typed exception classes instead of returning result tuples like `(Axiom | None, str | None)`?
> **A:** Result tuples require the caller to check a condition before using the value — and nothing enforces that check. A typed exception propagates through the call stack automatically and carries structured data. The distinction between `JudgeRejection` and `ExtractionError` at the API layer is only possible because they are different types.

---

### Anti-Patterns Avoided

**Mutable Validated Output**
Without `frozen=True`, an `Axiom` that passes the Judge could be mutated by the emitter before delivery. The validation would be meaningless — you'd be emitting a different object than the one that was verified.

> **Q:** Name the failure mode that `frozen=True` prevents.
> **A:** A pipeline stage downstream of the Judge mutates the Axiom (e.g., adds a computed field, normalises a value) and emits the modified object. The Judge never evaluated the mutated state. Sentinel-L7 receives data that was never validated. `frozen=True` makes this physically impossible.

---

**Config-at-Runtime**
The alternative to fail-fast config is lazy validation — reading env vars inside request handlers and raising errors if they're missing. This creates non-deterministic failure: the service starts, appears healthy, and fails only when a specific code path is exercised. A missing `SENTINEL_L7_URL` would only surface on the first `/ingest` request.

---

### Challenges

**`AnyWebsocketUrl` in Pydantic v2 / pydantic-settings**
`AnyWebsocketUrl` is a Pydantic v2 type that validates `ws://` and `wss://` URLs. It is less commonly documented than `AnyHttpUrl`. In pydantic-settings, it requires the env var value to be a valid URL string — `ws://localhost:3000/live` works; a bare hostname does not.

---

**`uv.lock` commit decision**
`uv.lock` is excluded from `.gitignore` in this project (solo dev, no CI yet). If CI or a second contributor is added later, `uv.lock` should be committed to ensure reproducible installs. This is a deliberate deferral, not an oversight.

---

### Decisions

**`JudgeRejection` carries the `axiom_candidate`**
The rejected Axiom is attached to the exception. This lets the API layer include `axiom_candidate` in the `422` response body, giving callers visibility into what was extracted before rejection. Without it, the caller only sees the rule name — not the values that triggered it.

**`RawTelemetry` as a separate input model**
The Consume stage accepts `RawTelemetry` (loosely typed `dict[str, Any]` payload), not `Axiom`. This keeps the entry point permissive — EventHorizon sends unstructured telemetry; it is the Extractor's job to produce a typed `Axiom`. If the ingestion route accepted `Axiom` directly, the Extractor stage would be bypassed entirely.

> **Q:** Why does `POST /ingest` accept `RawTelemetry` rather than `Axiom`?
> **A:** If the route accepted a fully-typed `Axiom`, the pipeline would be reduced to a pass-through — EventHorizon would have to pre-validate the data that Synapse-L4 exists to validate. The whole point of Synapse-L4 is the transformation from unstructured → structured. The entry point must accept unstructured input.
