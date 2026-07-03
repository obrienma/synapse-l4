---
id: synapse-l4-20260331-axiomdraft-model-extractor-node
repo: synapse-l4
title: "AxiomDraft Model + Extractor Node"
date: 2026-03-31
phase: 2
tags: [axiomdraft-rather-than-a-partial-axiom, bounded-llm-responsibility, exception-chaining-raise-from-exc, injectable-client-for-testability, leaking-third-party-exceptions-across-stage-boundaries, prompt-engineering-for-output-format]
files: [src/models/axiom.py (added AxiomDraft), src/nodes/extractor.py, src/nodes/extractor_test.py]
---

### Pattern: Bounded LLM Responsibility
The LLM only fills in what it can uniquely determine from the payload —
`status`, `metric_value`, `anomaly_score`. Pipeline-owned fields (`source_id`,
`emitted_at`) are supplied from authoritative sources: `RawTelemetry` and the
system clock at emission time. `AxiomDraft` encodes this boundary in the type
system — the LLM literally cannot set fields it doesn't own.

### Pattern: Injectable Client for Testability
The extractor's `client` parameter defaults to `None` and builds the real
Instructor client lazily on first call. Tests pass a mock directly — no
`unittest.mock.patch` at the module level, no import-time side effects. This
is the Dependency Injection pattern applied to async clients.

**Retrospective:** designing this lazy-construction pattern was the hardest
part of Phase 2 — getting the default-`None`-then-build-on-first-call shape
right so that import-time and call-time concerns stayed separated, without
introducing a second code path for "real" vs. "test" clients.

### Pattern: Exception Chaining (raise ... from exc)
`ExtractionError` is raised with `from exc`, preserving the original
exception as `__cause__`. The full traceback — including the underlying
`APIConnectionError` or `InstructorRetryException` — remains visible in logs
even though callers only handle `ExtractionError`. The stage boundary is
clean outward; the debug trail is complete inward.

### Anti-Pattern Avoided: Prompt Engineering for Output Format
Instructing the LLM to "return JSON matching this schema" with no enforcement
mechanism — no retry, no type guarantee, no recovery path. Instructor
replaces this entirely by using function-calling at the protocol level. If
the model returns a non-conforming response, Instructor retries with the
validation error as feedback. The schema is the source of truth, not the
prompt.

### Anti-Pattern Avoided: Leaking Third-Party Exceptions Across Stage Boundaries
Without the `try/except` wrapper, a network timeout from `httpx` or an
exhausted retry from `instructor` would propagate raw through the pipeline.
The API layer would need to know about `openai.APIConnectionError` to return
a sensible 503 — a direct coupling between the HTTP layer and the LLM client
library. Wrapping in `ExtractionError` keeps each stage's error vocabulary
self-contained.

### Challenge: AxiomDraft Extra Fields Rejection
Pydantic v2 models reject extra fields by default only if
`model_config = ConfigDict(extra="forbid")` is set. Without it,
`AxiomDraft(source_id="x", ...)` silently ignores the extra field rather than
raising `ValidationError`. The test `test_axiom_draft_has_no_source_id_or_emitted_at`
catches this — but the fix (adding `extra="forbid"`) was a TODO for the
implementation phase, resolved in Phase 3.

**Retrospective:** in hindsight this should have been fixed in Phase 2, not
deferred. Between Phase 2 and Phase 3, `AxiomDraft(source_id=..., emitted_at=...)`
would have silently succeeded — a window where an LLM echoing pipeline-owned
fields back would go undetected. The fix is one line
(`ConfigDict(extra="forbid")`); the risk of leaving the model boundary open,
even briefly, outweighed the cost of fixing it same-phase.

### Decision: AxiomDraft Rather Than a Partial Axiom
An alternative would be making `source_id` and `emitted_at` optional on
`Axiom` and treating a partially-populated instance as a draft. This was
rejected because it allows a partially-constructed `Axiom` to be passed to
the Emitter without ever being promoted — the type system can't distinguish
"draft Axiom" from "complete Axiom". Separate types make invalid pipeline
states unrepresentable.

---
