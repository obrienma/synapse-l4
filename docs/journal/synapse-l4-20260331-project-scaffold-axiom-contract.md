---
id: synapse-l4-20260331-project-scaffold-axiom-contract
repo: synapse-l4
title: "Project Scaffold + Axiom Contract"
date: 2026-03-31
phase: 1
tags: [config-at-runtime, fail-fast-configuration, frozen-value-objects, judgerejection-carries-axiom-candidate, mutable-validated-output, rawtelemetry-as-a-separate-input-model, specification-driven-development, type-driven-error-modeling, uvlock-commit-strategy]
files: [pyproject.toml, config.py, .env.example, src/models/axiom.py, src/models/axiom_test.py, main.py]
---

### Pattern: Specification-Driven Development
Define the data contract (`Axiom`) before writing any pipeline logic. Every
stage in Phases 2–4 was written *to satisfy this model*, not the other way
around. This is the same principle as writing a DB schema before writing
queries — the schema is the spec.

**Retrospective:** the hardest part of this phase was exactly this —
committing to the `Axiom` shape (frozen, typed errors, fail-fast config) with
no pipeline code yet in existence to validate the design against. Every field
on `Axiom` was a bet on what Phases 2–7 would need.

### Pattern: Fail-Fast Configuration
`config.py` uses Pydantic `BaseSettings`. The `settings` object is
instantiated at module import time. If any required env var is missing or
the wrong type, `ValidationError` is raised before FastAPI binds to a port.
The service refuses to start in a broken state.

### Pattern: Frozen Value Objects
`Axiom` uses `model_config = ConfigDict(frozen=True)`. This is the Value
Object pattern from Domain-Driven Design — an object whose identity is its
value, not its reference, and which cannot be mutated after creation. In a
pipeline, the validated output of one stage must not be modifiable by the
next.

### Pattern: Type-Driven Error Modeling
`JudgeRejection` and `ExtractionError` are typed exception classes with named
fields (`rule`, `detail`, `axiom_candidate`, `raw_payload`). This is not just
style — the API layer uses `exc.rule` to build a structured `422` response.
An untyped `raise Exception("rejected")` would require string parsing to
extract the same information.

### Anti-Pattern Avoided: Mutable Validated Output
Without `frozen=True`, an `Axiom` that passes the Judge could be mutated by
the emitter before delivery. The validation would be meaningless — you'd be
emitting a different object than the one that was verified.

### Anti-Pattern Avoided: Config-at-Runtime
The alternative to fail-fast config is lazy validation — reading env vars
inside request handlers and raising errors if they're missing. This creates
non-deterministic failure: the service starts, appears healthy, and fails
only when a specific code path is exercised. A missing `SENTINEL_L7_URL`
would only surface on the first `/ingest` request.

### Challenge: AnyWebsocketUrl in pydantic-settings
`AnyWebsocketUrl` is a Pydantic v2 type that validates `ws://` and `wss://`
URLs. It is less commonly documented than `AnyHttpUrl`. In
`pydantic-settings`, it requires the env var value to be a valid URL string —
`ws://localhost:3000/live` works; a bare hostname does not.

### Decision: JudgeRejection Carries axiom_candidate
The rejected Axiom is attached to the exception. This lets the API layer
include `axiom_candidate` in the `422` response body, giving callers
visibility into what was extracted before rejection. Without it, the caller
only sees the rule name — not the values that triggered it.

### Decision: RawTelemetry as a Separate Input Model
The Consume stage accepts `RawTelemetry` (a loosely typed `dict[str, Any]`
payload), not `Axiom`. This keeps the entry point permissive — EventHorizon
sends unstructured telemetry; it is the Extractor's job to produce a typed
`Axiom`. If the ingestion route accepted `Axiom` directly, the Extractor
stage would be bypassed entirely.

### Decision: uv.lock Commit Strategy
`uv.lock` is committed despite this being a solo project with no CI yet. If
CI or a second contributor is added later, a committed `uv.lock` ensures
reproducible installs from day one — a deliberate choice made early, not an
oversight discovered under pressure.

**Retrospective:** flagged as deserving more thought now that the project has
grown to 10 phases across two LLM providers (OpenAI/Anthropic) and a Redis
Streams dependency. Revisit whether `uv.lock` pinning strategy still matches
the dependency surface — this was a fast Phase 1 call made before that
surface existed.

---
