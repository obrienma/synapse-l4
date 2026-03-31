# Synapse-L4 — Testing Strategy

## Philosophy

**Every pipeline phase has tests written alongside it — not after.** Tests are not a final step; they are the acceptance criteria for each build phase. A phase is not complete until its tests pass.

Tests are also the primary tool for verifying LLM contract enforcement: the Judge and Extractor tests prove that Instructor and the business rules actually reject bad outputs — not just that they happen to accept good ones.

---

## Tools

| Tool | Purpose |
|---|---|
| `pytest` | Test runner |
| `pytest-asyncio` | Async test support for FastAPI and asyncio code |
| `httpx` | Async HTTP client used in route tests |
| `respx` | Mock httpx requests (for Sentinel-L7 client tests) |
| `unittest.mock` | Mock Instructor LLM calls in extractor tests |
| `pytest-watch` | Watch mode for TDD |

---

## Test File Layout

Tests are colocated with source files:

```
src/
  models/
    axiom.py
    axiom_test.py          ← schema validation tests
  nodes/
    extractor.py
    extractor_test.py      ← mocked Instructor calls
    judge.py
    judge_test.py          ← pure business rule tests
    emitter.py
    emitter_test.py        ← mocked Sentinel-L7 client
  evaluation/
    rules.py
    rules_test.py          ← pure function tests
  api/
    ingest.py
    ingest_test.py         ← FastAPI TestClient route tests
  clients/
    sentinel.py
    sentinel_test.py       ← mocked HTTP delivery
    eventhorizon.py
    eventhorizon_test.py   ← mocked WebSocket connection
```

---

## Per-Phase Test Strategy

### Phase 1 — `src/models/axiom.py`

**What to test:**
- Valid Axiom construction succeeds
- `anomaly_score` outside `[0.0, 1.0]` raises `ValidationError`
- Unknown `status` value raises `ValidationError`
- `frozen=True` — mutating a field after construction raises `ValidationError`
- `emitted_at` accepts both datetime objects and ISO 8601 strings

**Pattern:** Pure Pydantic instantiation — no I/O, no mocking.

```python
def test_axiom_rejects_anomaly_score_above_1():
    with pytest.raises(ValidationError):
        Axiom(status="nominal", metric_value=50.0, anomaly_score=1.1,
              source_id="s1", emitted_at=datetime.utcnow())

def test_axiom_is_immutable():
    axiom = Axiom(...)
    with pytest.raises(ValidationError):
        axiom.status = "degraded"
```

---

### Phase 2 — `src/nodes/extractor.py`

**What to test:**
- Extractor returns a valid `Axiom` when Instructor succeeds
- Extractor raises `ExtractionError` when `max_retries` is exhausted
- Extractor passes the correct prompt structure to the LLM client
- Async: extractor is awaitable and returns the correct type

**Pattern:** Mock the Instructor-patched client using `unittest.mock.AsyncMock`. Never make real LLM calls in tests.

```python
@pytest.mark.asyncio
async def test_extractor_returns_axiom_on_success(mock_instructor_client):
    mock_instructor_client.chat.completions.create.return_value = valid_axiom_fixture
    result = await extract(raw_telemetry_fixture, client=mock_instructor_client)
    assert isinstance(result, Axiom)
    assert result.anomaly_score >= 0.0
```

---

### Phase 3 — `src/nodes/judge.py` + `src/evaluation/rules.py`

**What to test:**
- All business rules pass for a valid Axiom — `judge()` returns the Axiom unchanged
- Each individual rule raises `JudgeRejection` with the correct `rule` name when violated
- Cross-field consistency: `anomaly_score > 0.8` with `status != "critical"` is rejected
- Edge values: `anomaly_score == 0.8` is the boundary — test both sides

**Pattern:** Pure unit tests. No I/O, no mocking. Judge is deterministic — inputs fully determine output.

```python
def test_judge_rejects_high_anomaly_with_nominal_status():
    candidate = Axiom(status="nominal", anomaly_score=0.91, ...)
    with pytest.raises(JudgeRejection) as exc:
        judge(candidate)
    assert exc.value.rule == "anomaly_score_status_consistency"
```

---

### Phase 4 — `src/nodes/emitter.py` + `src/clients/sentinel.py`

**What to test:**
- Emitter serializes the Axiom to JSON correctly (all fields present, datetime ISO formatted)
- Emitter calls the Sentinel-L7 client with the correct payload
- Client raises `EmitError` on non-2xx response from Sentinel-L7
- Client timeout raises `EmitError` with timeout detail
- The emitted JSON is the frozen Axiom — not a mutated copy

**Pattern:** Mock `httpx.AsyncClient` via `respx` to simulate Sentinel-L7 responses without a live service.

---

### Phase 5 — `src/api/ingest.py`

**What to test:**
- `POST /ingest` with valid payload returns `200` with an `axiom` object
- `POST /ingest` with a missing required field returns `400`
- `POST /ingest` where extraction fails returns `422` with `extraction_failed` error code
- `POST /ingest` where judge rejects returns `422` with `judge_rejected` error code and `rule` field
- `GET /health` returns `200` with `{ "status": "ok" }`
- `GET /metrics` returns correct counter shapes

**Pattern:** FastAPI `TestClient` (synchronous) or `httpx.AsyncClient` (async). Mock the pipeline nodes using `unittest.mock.patch` at the node boundary — route tests verify HTTP contract, not pipeline logic.

```python
def test_ingest_returns_422_on_judge_rejection(client, mock_pipeline):
    mock_pipeline.side_effect = JudgeRejection(rule="anomaly_score_status_consistency", ...)
    response = client.post("/ingest", json=valid_request_fixture)
    assert response.status_code == 422
    assert response.json()["error"] == "judge_rejected"
```

---

### Phase 6 — `src/clients/eventhorizon.py`

**What to test:**
- Consumer correctly parses `{ type: "event" }` messages and routes them to the pipeline
- Consumer ignores `{ type: "stats" }` and `{ type: "ping" }` message types
- Consumer reconnects after `websockets.ConnectionClosed` (verify backoff called)
- Malformed WS message does not crash the consumer — logs and continues

**Pattern:** Mock `websockets.connect` to yield a sequence of controlled messages. Test the message dispatch logic in isolation.

---

## What Is Not Automated

| Scenario | Why not automated |
|---|---|
| Real LLM calls (OpenAI / Anthropic) | Cost, latency, non-determinism — all tests mock Instructor |
| Live Sentinel-L7 delivery | Integration test — mocked in unit tests via `respx` |
| Live EventHorizon WS feed | Mocked in consumer tests |
| Logfire span structure | Observability assertions are manual / Logfire UI |

---

## Running Tests

```bash
uv run pytest                        # Full suite
uv run pytest -x                     # Stop on first failure
uv run pytest src/nodes/judge_test.py  # Single file
uv run pytest -k "test_judge"        # Filter by name pattern
uv run pytest --watch                # Watch mode
uv run pytest --cov=src              # Coverage report
```
