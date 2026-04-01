# Synapse-L4 — Learning Log

Append-only. One entry per build phase. Format: Pattern → Anti-Pattern → Challenge → Decision, each with Q:/A: flashcard blocks for active recall.

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
