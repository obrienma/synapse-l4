# Probes — Phase 2: AxiomDraft Model + Extractor Node

```markdown
---
type: cloze
deck: Rhizome::synapse-l4
tags: [synapse-l4, phase-2, bounded-llm-responsibility]
---
`AxiomDraft` omits `source_id` and `emitted_at` because both are
{{c1::pipeline-owned}} — `source_id` is already known from `RawTelemetry`,
and `emitted_at` {{c2::doesn't exist yet}} at extraction time (it's stamped
at delivery). Letting the LLM set either would mean trusting a probabilistic
model with data the pipeline already holds deterministically.

Extra: synapse-l4 · Phase 2 · Pattern: Bounded LLM Responsibility
See: docs/journal.md#phase-2-axiomdraft-model--extractor-node-2026-03-31
```

---

```markdown
---
type: cloze
deck: Rhizome::synapse-l4
tags: [synapse-l4, phase-2, dependency-injection]
---
The Instructor client is built {{c1::lazily}} on first call (`client=None`
default) rather than at module import — module-level construction would run
`OPENAI_API_KEY` validation at {{c2::import time}}, forcing every test that
imports the extractor to have a valid API key even if it never calls the LLM.

Extra: synapse-l4 · Phase 2 · Pattern: Injectable Client for Testability
See: docs/journal.md#phase-2-axiomdraft-model--extractor-node-2026-03-31
```

---

```markdown
---
type: cloze
deck: Rhizome::synapse-l4
tags: [synapse-l4, phase-2, exception-chaining]
---
`raise ExtractionError(...) {{c1::from exc}}` sets {{c2::__cause__}} on the
new exception, explicitly linking it to the original. Python's traceback
renderer prints both. Without it, the underlying `APIConnectionError` would
be lost — only `ExtractionError` would appear in logs.

Extra: synapse-l4 · Phase 2 · Pattern: Exception Chaining (raise ... from exc)
See: docs/journal.md#phase-2-axiomdraft-model--extractor-node-2026-03-31
```

---

```markdown
---
type: cloze
deck: Rhizome::synapse-l4
tags: [synapse-l4, phase-2, anti-pattern, structured-generation]
---
Instructor replaces "return JSON matching this schema" prompting with
{{c1::function-calling}} at the protocol level — if the model's response
doesn't conform, Instructor {{c2::retries with the validation error as
feedback}} instead of failing silently.

Extra: synapse-l4 · Phase 2 · Anti-Pattern Avoided: Prompt Engineering for Output Format
See: docs/journal.md#phase-2-axiomdraft-model--extractor-node-2026-03-31
```

---

```markdown
---
type: cloze
deck: Rhizome::synapse-l4
tags: [synapse-l4, phase-2, anti-pattern, error-boundaries]
---
Wrapping LLM client errors in {{c1::ExtractionError}} (via `raise ... from
exc`) keeps each pipeline stage's error vocabulary self-contained — the API
layer never needs to know about `openai.APIConnectionError` directly.

Extra: synapse-l4 · Phase 2 · Anti-Pattern Avoided: Leaking Third-Party Exceptions Across Stage Boundaries
See: docs/journal.md#phase-2-axiomdraft-model--extractor-node-2026-03-31
```

---

```markdown
---
type: cloze
deck: Rhizome::synapse-l4
tags: [synapse-l4, phase-2, pydantic-extra-forbid]
---
Without {{c1::extra="forbid"}} on `AxiomDraft`, calling
`AxiomDraft(source_id="x", ...)` would {{c2::silently ignore}} the extra
field rather than raising `ValidationError` — the model would construct
successfully and a test could pass for the wrong reason.

Extra: synapse-l4 · Phase 2 · Challenge: AxiomDraft Extra Fields Rejection
See: docs/journal.md#phase-2-axiomdraft-model--extractor-node-2026-03-31
```

---

```markdown
---
type: cloze
deck: Rhizome::synapse-l4
tags: [synapse-l4, phase-2, type-driven-design]
---
Making `source_id`/`emitted_at` {{c1::optional}} on `Axiom` (instead of a
separate `AxiomDraft` type) would let the Emitter accidentally emit an
`Axiom` with `source_id=None` — the type system couldn't distinguish a
{{c2::draft awaiting promotion}} from a complete, emission-ready `Axiom`.

Extra: synapse-l4 · Phase 2 · Decision: AxiomDraft Rather Than a Partial Axiom
See: docs/journal.md#phase-2-axiomdraft-model--extractor-node-2026-03-31
```
