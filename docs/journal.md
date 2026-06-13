# Synapse-L4 — Engineering Journal

Append-only. One entry per build phase. Supersedes `LEARNING_LOG.md` (see
migration note at the top of that file). Format and Anki probe generation
follow `~/.claude/skills/journal-anki.md`.

Each entry uses typed, vocabulary-enforced sections:

- **Pattern: \<Formal Name\>** — the concept, named formally, then how it
  manifests in this implementation.
- **Anti-Pattern Avoided: \<Formal Name\>** — the trap, why it was tempting,
  and the failure mode it sidesteps.
- **Challenge: \<Short Label\>** — symptom, root cause, fix. Omitted when no
  real challenge occurred.
- **Decision: \<Short Label\>** — the chosen path, tradeoffs, what was
  deferred or rejected and why.

Paired Anki probe files live in `docs/probes/phase-N-<name>.md`.

## Deck Naming

| Repo | Anki deck |
|---|---|
| sentinel-l7 | `Rhizome::sentinel-l7` |
| EventHorizon | `Rhizome::EventHorizon` |
| synapse-l4 | `Rhizome::synapse-l4` |
| Ledger-L5 | `Rhizome::ledger-l5` |
| (cross-cutting) | `Rhizome::observability` |

---

## Phase 1 — Project Scaffold + Axiom Contract — 2026-03-31
Files: pyproject.toml, config.py, .env.example, src/models/axiom.py, src/models/axiom_test.py, main.py

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

## Phase 2 — AxiomDraft Model + Extractor Node — 2026-03-31
Files: src/models/axiom.py (added AxiomDraft), src/nodes/extractor.py, src/nodes/extractor_test.py

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

## Phase 3 — Judge Pass + Business Rules — 2026-03-31
Files: src/evaluation/rules.py, src/evaluation/rules_test.py, src/nodes/judge.py, src/nodes/judge_test.py
Also: fixed extra="forbid" on AxiomDraft

### Pattern: Validator-as-Judge
A deterministic code-level verification pass that runs after probabilistic
LLM extraction. The Judge is not another LLM call — it enforces business
rules that the LLM cannot be trusted to self-enforce. Rules are pure Python
functions with no I/O, making them trivially unit-testable and independently
auditable.

### Pattern: Rule Registry Pattern
Rules are registered in an ordered list (`_RULES`) in `judge.py`. Adding a
new business rule requires only adding a function to `rules.py` and appending
it to the list — the `judge()` function itself never changes. This is the
Open/Closed Principle: the Judge is open to extension (new rules) but closed
to modification.

### Pattern: Fail-Fast Validation
The Judge runs rules in order and raises `JudgeRejection` on the first
violation. It does not accumulate errors. This is the correct default for a
pipeline: a draft with a non-finite `metric_value` and a status inconsistency
is broken — there is no value in reporting both violations when the first
alone is sufficient to reject it.

### Anti-Pattern Avoided: Silent Contradiction
An `Axiom` where `anomaly_score` is 0.91 but `status` is `"nominal"` would be
internally contradictory. Sentinel-L7 would file a low-priority record for a
near-certain anomaly. The `anomaly_score_status_consistency` rule makes this
physically impossible to emit.

### Anti-Pattern Avoided: Accepting Sentinel Float Values
LLMs hallucinate `Infinity` or `NaN` for `metric_value` when the payload lacks
a clear numeric signal. Pydantic accepts these as valid Python `float`s — they
pass field validation. The `metric_value_finite` rule catches them before
emission. Without it, Sentinel-L7 would receive a JSON payload with
`"metric_value": Infinity`, which is not valid JSON and would cause a parse
error downstream.

### Challenge: Pydantic Accepts NaN and ±Infinity as Valid Floats
The `metric_value` field on `AxiomDraft` is typed as `float`. Pydantic v2
treats `NaN`, `Infinity`, and `-Infinity` as valid Python floats — they pass
schema validation without error. The problem only surfaced when considering
downstream serialisation: `json.dumps({"metric_value": float("inf")})` raises
`ValueError` because JSON has no `Infinity` literal. The fix was a dedicated
`metric_value_finite` rule rather than a Pydantic validator, to keep the
sentinel at the Judge boundary where all business rules live.

### Challenge: extra="forbid" Missing from AxiomDraft
`AxiomDraft` lacked `extra="forbid"`, meaning fields like `source_id` and
`emitted_at` — which are assigned by the pipeline, not the LLM — could be
included in LLM output without raising an error. This would silently let the
LLM override pipeline-controlled provenance fields. Adding `extra="forbid"`
actively rejects any unrecognised field at the model boundary, enforcing that
`AxiomDraft` is strictly an LLM output contract and nothing more.

### Decision: Rule Ordering — Structural Before Semantic
`metric_value_finite` runs before `anomaly_score_status_consistency`.
Structural sanity checks run before cross-field business logic. A draft with
`metric_value=NaN` is structurally broken regardless of its status — there's
no point evaluating the status rule. This also makes test assertions
deterministic: when both rules would fire, the test can assert which rule
name appears in the rejection.

### Decision: Thresholds as Module-Level Constants (Deferred Config)
`ANOMALY_CRITICAL_THRESHOLD = 0.8` and `ANOMALY_DEGRADED_THRESHOLD = 0.5` live
in `rules.py`. Moving them to `config.py` as env vars enables operational
tuning without code changes but adds cognitive overhead before the thresholds
have been empirically validated. Deferred intentionally — see TODO in
`rules.py`.

---
