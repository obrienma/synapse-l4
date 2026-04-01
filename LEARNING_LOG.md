# Synapse-L4 — Learning Log

Append-only. One entry per build phase. Format: Pattern → Anti-Pattern → Challenge → Decision, each with Q:/A: flashcard blocks for active recall.

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
