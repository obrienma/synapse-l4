# Probes — Phase 4: Emitter + Sentinel-L7 Client

```markdown
---
type: cloze
deck: Rhizome::synapse-l4
tags: [synapse-l4, phase-4, axiom-promotion]
---
`emitted_at` is stamped inside the {{c1::Emitter}}, not at extraction time —
it marks when the validated `Axiom` was {{c2::delivered}} to Sentinel-L7. The
Judge pass (and any retries) means meaningful time passes between extraction
and delivery, so an earlier timestamp would not be trustworthy as a delivery
marker.

Extra: synapse-l4 · Phase 4 · Pattern: AxiomDraft → Axiom Promotion
See: docs/journal.md#phase-4-emitter--sentinel-l7-client-2026-03-31
```

---

```markdown
---
type: cloze
deck: Rhizome::synapse-l4
tags: [synapse-l4, phase-4, idempotent-emission]
---
{{c1::Idempotent emission}} means delivering the same `Axiom` multiple times
has the same effect as delivering it once. Sentinel-L7 can detect a retried
delivery by comparing {{c2::source_id}} and {{c3::emitted_at}} and discard the
duplicate safely.

Extra: synapse-l4 · Phase 4 · Pattern: Idempotent Emission
See: docs/journal.md#phase-4-emitter--sentinel-l7-client-2026-03-31
```

---

```markdown
---
type: cloze
deck: Rhizome::synapse-l4
tags: [synapse-l4, phase-4, dependency-injection, respx]
---
`sentinel_test.py` mocks at the HTTP {{c1::transport layer}} via
{{c2::respx}} — verifying `SentinelClient` calls the correct URL and payload —
while `emitter_test.py` injects a mock `SentinelClient` entirely, testing the
pipeline logic in isolation from the HTTP layer.

Extra: synapse-l4 · Phase 4 · Pattern: Injectable HTTP Client for Testability
See: docs/journal.md#phase-4-emitter--sentinel-l7-client-2026-03-31
```

---

```markdown
---
type: cloze
deck: Rhizome::synapse-l4
tags: [synapse-l4, phase-4, anti-pattern, emitting-on-failure]
---
The Emitter only returns the `Axiom` if `post_axiom` {{c1::succeeds}} —
`EmitError` is raised {{c2::before}} `return axiom` is reached, so the caller
can never mistake a failed emission for a successful one.

Extra: synapse-l4 · Phase 4 · Anti-Pattern Avoided: Emitting on Failure
See: docs/journal.md#phase-4-emitter--sentinel-l7-client-2026-03-31
```

---

```markdown
---
type: cloze
deck: Rhizome::synapse-l4
tags: [synapse-l4, phase-4, anti-pattern, axiom-construction-timing]
---
`Axiom` is constructed {{c1::inside}} `emit()`, not before the HTTP call —
this ensures `emitted_at` reflects actual {{c2::delivery time}} rather than
when the function was entered.

Extra: synapse-l4 · Phase 4 · Anti-Pattern Avoided: Constructing Axiom Before Delivery Succeeds
See: docs/journal.md#phase-4-emitter--sentinel-l7-client-2026-03-31
```

---

```markdown
---
type: cloze
deck: Rhizome::synapse-l4
tags: [synapse-l4, phase-4, respx, testing]
---
`respx.mock` patches at the {{c1::transport level}} — if `httpx.AsyncClient`
is constructed {{c2::before}} `respx.mock` is entered (e.g. as a class-level
fixture), the mock has no effect and the test makes a real HTTP call.

Extra: synapse-l4 · Phase 4 · Challenge: respx Mock Must Be Activated Before httpx.AsyncClient Construction
See: docs/journal.md#phase-4-emitter--sentinel-l7-client-2026-03-31
```

---

```markdown
---
type: cloze
deck: Rhizome::synapse-l4
tags: [synapse-l4, phase-4, frozen-pydantic, model-copy]
---
Pydantic's `model_copy(update={...})` is {{c1::blocked}} on frozen models and
raises `ValidationError` — the Emitter constructs `Axiom` {{c2::from
scratch}} by merging `AxiomDraft` fields with pipeline-owned fields, rather
than copying and updating a draft.

Extra: synapse-l4 · Phase 4 · Challenge: frozen=True Axiom Cannot Be Constructed With model_copy()
See: docs/journal.md#phase-4-emitter--sentinel-l7-client-2026-03-31
```

---

```markdown
---
type: cloze
deck: Rhizome::synapse-l4
tags: [synapse-l4, phase-4, sentinel-client, http-vs-redis]
---
Phase 4 chose {{c1::HTTP POST}} to Sentinel-L7 over Redis XADD because
`SENTINEL_L7_URL` was already the only required downstream config and
{{c2::respx}} made the HTTP contract simple to test. If Redis Streams were
adopted later, only `src/clients/sentinel.py` would need to change — the
Emitter node would be unaffected.

Extra: synapse-l4 · Phase 4 · Decision: HTTP POST over Redis XADD (for now)
See: docs/journal.md#phase-4-emitter--sentinel-l7-client-2026-03-31
```

---

```markdown
---
type: cloze
deck: Rhizome::synapse-l4
tags: [synapse-l4, phase-4, emit-error, typed-errors]
---
`EmitError` carries the failed {{c1::Axiom}} so the API layer can include it
in the {{c2::502}} response body — mirroring how `JudgeRejection` carries the
draft and `ExtractionError` carries the raw payload.

Extra: synapse-l4 · Phase 4 · Decision: EmitError Carries the Axiom
See: docs/journal.md#phase-4-emitter--sentinel-l7-client-2026-03-31
```
