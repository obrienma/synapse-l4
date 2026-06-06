# Synapse-L4 — AI Logic & Evaluation Sidecar

> **Dual-LLM project**: Primary AI assistant is **Claude Code** (this file). GitHub Copilot context lives in `.github/copilot-instructions.md`. Keep both in sync when updating project context.

Synapse-L4 is the **"Brain"** in a three-system architecture — a Python/FastAPI sidecar that transforms raw, high-throughput telemetry from EventHorizon into deterministic, schema-validated **Axioms** for Sentinel-L7.

| System | Role | Tech |
|---|---|---|
| **EventHorizon** | "Nervous System" — real-time telemetry pipeline | TypeScript, Fastify, RabbitMQ |
| **Synapse-L4** | "Brain" — Specification-Driven orchestration, LLM contract enforcement | Python, FastAPI, Pydantic + Instructor |
| **Sentinel-L7** | "Gatekeeper" — semantic caching, API gateway, financial/transactional state | Laravel, Redis Streams, Upstash Vector |

---

## Architecture: Four-Stage Validation Node

```
Consume  →  Extract  →  Evaluate  →  Emit
```

Data flows **one direction only** through the node. No stage may call a downstream stage directly; each stage returns a typed output to the pipeline runner.

| Stage | Responsibility | Key files |
|---|---|---|
| **Consume** | Accept raw telemetry via FastAPI POST endpoint or WebSocket client | `src/api/ingest.py`, `src/clients/eventhorizon.py` |
| **Extract** | Pydantic + Instructor maps raw payload → typed `Axiom` | `src/nodes/extractor.py`, `src/models/axiom.py` |
| **Evaluate** | Judge pass — validates Axiom against hard business rules | `src/nodes/judge.py`, `src/evaluation/rules.py` |
| **Emit** | Return immutable, validated JSON Axiom to Sentinel-L7 | `src/nodes/emitter.py`, `src/clients/sentinel.py` |

---

## Directory Structure

```
src/
  api/           # FastAPI routes (ingestion endpoints)
  models/        # Pydantic Axiom schemas — shared contract across all stages
  nodes/         # Core pipeline: extractor.py, judge.py, emitter.py
  evaluation/    # Business rule validators (pure functions, no I/O)
  clients/       # eventhorizon.py (WS consumer), sentinel.py (HTTP/Redis emitter)
  observation/   # Logfire instrumentation
config.py        # Pydantic BaseSettings — process exits on startup if any var invalid
main.py          # FastAPI app entrypoint
```

---

## Hard Invariants — Never Violate These

- **Axioms are immutable**: Once the Judge pass succeeds, the `Axiom` object is never mutated before or after emission.
- **All LLM outputs through Instructor**: Raw LLM strings are never returned directly to any caller — extraction always goes through a Pydantic model via `instructor.patch()`.
- **`src/models/axiom.py` is the shared contract**: All stages import `Axiom` and related types from this module. No ad-hoc `dict` schemas anywhere in the pipeline.
- **Judge pass is mandatory**: Extraction without evaluation is not a valid pipeline path. The `extractor` output must flow through `judge` before reaching `emitter`.
- **Config validated at startup**: `config.py` uses Pydantic `BaseSettings`. The process exits with a clear error if any required env var is missing or invalid.
- **Keep `.env.example` in sync**: Any time `.env` is modified, update `.env.example` to reflect the change — keys and comments only, never real values (use placeholders like `your-token-here` or `rediss://:PASSWORD@HOST:PORT`).

---

## Stack

| Layer | Tech | Notes |
|---|---|---|
| Language | Python 3.12+, asyncio | |
| Framework | FastAPI | async routes throughout |
| Validation / LLM contracts | Pydantic v2 + Instructor | structured generation only |
| Observability | Logfire | accuracy benchmarking + tracing |
| Package management | uv (pyproject.toml) | |
| Testing | pytest + pytest-asyncio | |

---

## Axiom Shape

```python
ComplianceDomain = Literal["aml", "gdpr", "hipaa"]

class Axiom(BaseModel):
    model_config = ConfigDict(frozen=True)  # immutable

    status: Literal["nominal", "degraded", "critical"]
    metric_value: float
    anomaly_score: Annotated[float, Field(ge=0.0, le=1.0)]
    source_id: str
    emitted_at: datetime
    domain: ComplianceDomain | None = None  # omitted from XADD when None
```

`frozen=True` enforces immutability at the Pydantic level. Any attempt to mutate an emitted Axiom raises a `ValidationError`.

`domain` is optional — when `None`, the key is absent from the Redis XADD payload entirely (not set to `null`). Sentinel-L7 treats a missing `domain` key as "retrieve globally" across all policy namespaces.

---

## Environment Variables

All vars in `.env.example`. Validated in `config.py` — process exits on startup if any are missing/invalid.

Key vars: `OPENAI_API_KEY` (or `ANTHROPIC_API_KEY`), `SENTINEL_L7_URL`, `EVENTHORIZON_WS_URL`, `LOGFIRE_TOKEN`, `LOG_LEVEL`.

---

## Commands

```bash
uv run fastapi dev main.py       # Start FastAPI dev server (hot reload)
uv run pytest                    # Run test suite
uv run mypy src/                 # Type check
uv run pytest-watch              # Watch mode
```

---

## Testing Conventions

- `pytest-asyncio` for all async route and node tests
- FastAPI `TestClient` (or `httpx.AsyncClient`) for route tests
- Instructor LLM calls mocked via `unittest.mock.patch` or `respx`
- Judge/evaluation logic: pure unit tests — no LLM calls, no I/O
- Axiom schema tests: valid construction + `ValidationError` cases for out-of-range fields
- Tests colocated with source: `foo_test.py` next to `foo.py`

---

## Known Challenges & Gotchas

Lessons burned in during build — check these before touching the relevant areas.

### Extraction / LLM Cost
- **Obligatory LLM Invocation**: Every payload going through the LLM regardless of structure exhausts token quota fast. `_try_direct_extraction()` in `extractor.py` provides a deterministic fast path — structured payloads never reach the LLM. Don't remove it.
- **`instructor_max_retries` multiplier**: Each `extract()` call on an unstructured payload costs up to `1 + max_retries` LLM calls. At the default of 3, one struggling message burns 4 calls. Keep `INSTRUCTOR_MAX_RETRIES=1` in `.env` for development.
- **`_try_direct_extraction` must catch both `KeyError` and `ValidationError`**: `KeyError` = missing field; `ValidationError` = present but invalid (e.g. `status="unknown"`, `anomaly_score=2.5`). Catching only `KeyError` lets an invalid-but-present payload bypass the LLM and produce a corrupt `AxiomDraft`.
- **`_valid_domain()` helper prevents ValidationError cascade on bad domain values**: Passing an unrecognised domain string directly to `AxiomDraft()` raises `ValidationError`, which causes Shape 1 to fall through to Shape 2, then to the LLM — wasting a call for an otherwise-valid structured payload. `_valid_domain()` sanitises the value to `None` before construction.
- **Shape 2 requires a structural key guard**: Without `if "raw" not in payload and "processed" not in payload: return None`, Shape 2 matches *any* payload using fallback values (`status="degraded"`, `metric_value=0.0`), silently swallowing unstructured payloads that should reach the LLM.

### Async / WebSocket
- **`asyncio.CancelledError` is `BaseException`, not `Exception`** (Python 3.8+): It falls through `except Exception` naturally. The explicit `except asyncio.CancelledError: raise` in `eventhorizon.py` is intentional documentation — do not collapse it into the generic `except Exception` block.
- **Testing the reconnect loop**: `run()` loops forever. Tests must cancel the task or use `asyncio.timeout()` to stop it — they cannot just call `run()` and assert.

### Pydantic / Models
- **`frozen=True` blocks `model_copy(update={})`**: Frozen models raise `ValidationError` on `model_copy`. Construct `Axiom` from scratch in the Emitter; don't try to copy-and-update a draft.
- **`extra="forbid"` is required on `AxiomDraft`**: Without it, passing `source_id` to `AxiomDraft()` silently succeeds. The test `test_axiom_draft_has_no_source_id_or_emitted_at` relies on `extra="forbid"` being set.

### Testing
- **Module-level `_metrics` dict in `ingest.py` persists across tests**: `TestClient` runs in-process. Tests that assert exact counter values will be order-dependent. Current tests avoid this by only asserting shape, not values.
- **`respx` mock must be entered before `httpx.AsyncClient` construction**: `respx` patches at the transport level. A client constructed outside the `respx.mock` context makes real HTTP calls.
- **`LogfireNotConfiguredWarning` in tests**: Any test that calls pipeline code without first calling `logfire.configure()` emits this warning. It is suppressed via `filterwarnings` in `pyproject.toml` — don't remove that config.

### OTel / Observability
- **Always pass `service_name="synapse-l4"` to `logfire.configure()`**: Without it, Tempo shows `unknown_service`. Logfire does not default to the project name. The `OTEL_SERVICE_NAME` env var also works but is less reliable than the explicit parameter.

### Dependencies
- **`rediss://` (double-s) required for Upstash TLS**: `redis://` connects without TLS and Upstash rejects it silently. All Redis URLs must use `rediss://`.
- **`instructor` deprecation warning via Logfire**: Logfire's instrumentation imports from `instructor.client` (deprecated in v2). The warning is transitive — it is not caused by application code and cannot be fixed here.

---

## Current Build Status

**Completed:** CLAUDE.md, .github/copilot-instructions.md, README.md, docs/ARCHITECTURE.md, docs/API.md, docs/DEV_GETTING_STARTED.md, docs/TESTING.md, docs/adr/ (0001–0005), OTel/Phase 1 — OTLP export to Tempo + traceparent injection on Redis Stream + wide spans

**Build order: top-down** (scaffold → models → nodes → API → clients → observation)

**Not yet implemented** (in order):
1. ~~Project scaffold: `pyproject.toml`, `config.py`, `.env.example`~~ ✓
2. ~~`src/models/axiom.py` — shared Axiom schema~~ ✓ (with `axiom_test.py`; added `AxiomDraft`)
3. ~~`src/nodes/extractor.py` — Instructor extraction node~~ ✓ (with `extractor_test.py`)
4. ~~`src/nodes/judge.py` + `src/evaluation/rules.py` — Judge pass~~ ✓ (with `judge_test.py`, `rules_test.py`)
5. ~~`src/nodes/emitter.py` + `src/clients/sentinel.py` — emission to Sentinel-L7~~ ✓ (with `emitter_test.py`, `sentinel_test.py`)
6. ~~`src/api/ingest.py` + `src/main.py` — FastAPI ingestion endpoint~~ ✓ (with `ingest_test.py`)
7. ~~`src/clients/eventhorizon.py` — WebSocket consumer~~ ✓ (with `eventhorizon_test.py`)
8. ~~`src/observation/` — Logfire instrumentation~~ ✓ (with `instrumentation_test.py`)
9. Tests per layer

---

## Claude Code Workflow Notes

- **Work one step at a time** and pause for confirmation before moving to the next build step.
- **Commit after each logical step** — the user commits manually; don't push.
- **Don't add features beyond what's asked.** No extra error handling, no extra abstractions, no unrequested refactors.
- **No doc files** unless explicitly requested. Update `CLAUDE.md` Build Status section after each completed step.
- **Tests are written alongside each phase — not after.** A phase is not complete until its colocated tests pass. See [docs/TESTING.md](docs/TESTING.md) for per-phase test strategy.
- **`LEARNING_LOG.md` is referred to as `ll`** in conversation — treat "ll" as shorthand for `LEARNING_LOG.md`.
- **Maintain `LEARNING_LOG.md`**: Writing to `LEARNING_LOG.md` is a required step at the end of every phase — not optional. A phase is not complete until the log entry is written. Append entries for every pattern used, anti-pattern avoided, challenge encountered, or design decision made. Use the established entry format (Pattern / Anti-Pattern / Challenge / Decision sections with **Q:**/**A:** flashcard blocks).
- **Challenges are mandatory in every log entry**: Every phase entry must include a `### Challenges` section. If no challenge was encountered, state that explicitly — do not omit the section. Challenges include: unexpected library behaviour, error messages that required diagnosis, gotchas discovered during testing, version-specific quirks, and any moment where the first approach didn't work. Retroactively add challenges to existing entries if a new phase reveals a prior gotcha.
- All Pydantic models use explicit `model_config` — never rely on global config defaults.
- Update the Build Status section in this file after each completed step.

## ADR Files
Create decision logs in `docs/adr/` following the format in existing ADRs and the guidance at https://martinfowler.com/bliki/ArchitectureDecisionRecord.html. Number sequentially (`0006-...`). Existing ADRs: FastAPI (0001), Instructor (0002), Frozen Axioms (0003), Judge stage (0004), uv (0005), websockets client (0006).

---

## Learning & Mentorship Protocol

This project is a learning vehicle for **Structured Generation**, **LLM Reliability patterns**, and **Python async microservice design**.
Follow these rules for every interaction:

1. **Context First:** Before providing code, name the specific pattern being used (e.g., *Validator-as-Judge*, *Structured Generation*, *Idempotent Emission*, *Constrained Decoding*).
2. **The "Why" over "How":** For every major implementation choice (Instructor over raw JSON parsing, frozen Pydantic models, Judge as a separate stage), include a "Design Decision" comment explaining why this is superior to the alternative.
3. **Intentional Friction:** Provide core architecture and logic, but leave `TODO` blocks for retry budget configuration, backoff logic, and edge-case validators for manual implementation.
4. **Code Reviews:** If I provide code, critique it like a Senior Architect. Focus on:
    - Pydantic v2 discriminated unions and `model_config` correctness
    - Async context manager leaks (unclosed httpx clients, WebSocket connections)
    - Instructor retry loop exhaustion — what happens when `max_retries` is exceeded?
    - Scalability bottlenecks in the pipeline
5. **No Hallucinations:** If Instructor or Logfire have async quirks or version-specific behavior, flag it explicitly before writing code.
6. **Failure Mode First:** Before implementing any component, describe how it fails. What happens when the LLM returns unparseable output? When Sentinel-L7 is unreachable? When EventHorizon's WebSocket drops mid-stream? Write to `LEARNING_LOG.md`.
7. **Vocabulary Enforcement:** Use correct terminology consistently — *structured generation*, *constrained decoding*, *validator-as-judge*, *idempotent emission*, *at-most-once delivery*. Name the concept formally before casual language.
8. **Checkpoint Questions:** After each completed phase, ask me to explain back what was built and *why* — e.g. "Why does the Judge run after Instructor extraction, not inside the Instructor validator?"
9. **Name the Anti-Pattern Avoided:** When a design decision sidesteps a trap (Instructor vs. prompt engineering for JSON, frozen model vs. mutable dict, Judge stage vs. inline assertion), explicitly name the anti-pattern and the failure mode it prevents.
10. **Ask before completing TODOs.**
