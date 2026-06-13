# Probes — Phase 3: Judge Pass + Business Rules

```markdown
---
type: cloze
deck: Rhizome::synapse-l4
tags: [synapse-l4, phase-3, validator-as-judge]
---
The Judge runs as a {{c1::separate stage}} after Instructor extraction rather
than as a Pydantic validator inside Instructor's retry loop — retrying on a
{{c2::business rule violation}} wastes tokens, since the same input produces
the same violation again. A separate stage also yields a distinct error type,
{{c3::JudgeRejection}}, unambiguous from `ExtractionError` in logs and API
responses.

Extra: synapse-l4 · Phase 3 · Pattern: Validator-as-Judge
See: docs/journal.md#phase-3-judge-pass--business-rules-2026-03-31
```

---

```markdown
---
type: cloze
deck: Rhizome::synapse-l4
tags: [synapse-l4, phase-3, rule-registry, open-closed-principle]
---
Adding a new business rule means adding a function to `rules.py` and
appending it to the ordered `_RULES` list — `judge()` itself
{{c1::never changes}}. This is the {{c2::Open/Closed Principle}}: open to
extension, closed to modification.

Extra: synapse-l4 · Phase 3 · Pattern: Rule Registry Pattern
See: docs/journal.md#phase-3-judge-pass--business-rules-2026-03-31
```

---

```markdown
---
type: cloze
deck: Rhizome::synapse-l4
tags: [synapse-l4, phase-3, fail-fast-validation]
---
The Judge raises `JudgeRejection` on the {{c1::first}} rule violation rather
than collecting all violations. Fail-fast suits a {{c2::machine-to-machine}}
pipeline — the caller returns 422 and the LLM re-runs regardless of whether
one or two rules failed. Collect-all matters for a {{c3::form validation UX}},
where a human needs every error in one round trip.

Extra: synapse-l4 · Phase 3 · Pattern: Fail-Fast Validation
See: docs/journal.md#phase-3-judge-pass--business-rules-2026-03-31
```

---

```markdown
---
type: cloze
deck: Rhizome::synapse-l4
tags: [synapse-l4, phase-3, anti-pattern, silent-contradiction]
---
An `Axiom` with `anomaly_score=0.91` but `status="nominal"` would be
internally contradictory — Sentinel-L7 would file a {{c1::low-priority}}
record for a {{c2::near-certain anomaly}}. The
`anomaly_score_status_consistency` rule makes this physically impossible to
emit.

Extra: synapse-l4 · Phase 3 · Anti-Pattern Avoided: Silent Contradiction
See: docs/journal.md#phase-3-judge-pass--business-rules-2026-03-31
```

---

```markdown
---
type: cloze
deck: Rhizome::synapse-l4
tags: [synapse-l4, phase-3, anti-pattern, sentinel-values]
---
LLMs hallucinate `{{c1::Infinity}}` or `{{c2::NaN}}` for `metric_value` when a
payload lacks a clear numeric signal — Pydantic accepts both as valid
`float`s, so the `metric_value_finite` rule must catch them before emission,
or Sentinel-L7 would receive a JSON payload that fails to parse.

Extra: synapse-l4 · Phase 3 · Anti-Pattern Avoided: Accepting Sentinel Float Values
See: docs/journal.md#phase-3-judge-pass--business-rules-2026-03-31
```

---

```markdown
---
type: cloze
deck: Rhizome::synapse-l4
tags: [synapse-l4, phase-3, pydantic, json-serialization]
---
Pydantic v2 validates {{c1::Python types}}, not {{c2::JSON-serialisability}} —
`NaN` and `Infinity` are legal IEEE 754 floats and pass a `float` field's
validation, but `json.dumps` raises `ValueError` on them. The
`metric_value_finite` rule in the Judge closes this gap.

Extra: synapse-l4 · Phase 3 · Challenge: Pydantic Accepts NaN and ±Infinity as Valid Floats
See: docs/journal.md#phase-3-judge-pass--business-rules-2026-03-31
```

---

```markdown
---
type: cloze
deck: Rhizome::synapse-l4
tags: [synapse-l4, phase-3, pydantic-extra-forbid]
---
Without {{c1::extra="forbid"}} on `AxiomDraft`, an LLM could include
`source_id` or `emitted_at` in its structured output, silently overriding
{{c2::pipeline-assigned}} provenance fields — `extra="forbid"` raises
`ValidationError` on any undeclared field instead.

Extra: synapse-l4 · Phase 3 · Challenge: extra="forbid" Missing from AxiomDraft
See: docs/journal.md#phase-3-judge-pass--business-rules-2026-03-31
```

---

```markdown
---
type: cloze
deck: Rhizome::synapse-l4
tags: [synapse-l4, phase-3, rule-ordering]
---
`metric_value_finite` runs before `anomaly_score_status_consistency` because
{{c1::structural validity}} must hold before {{c2::semantic consistency}} can
be evaluated — you can't ask whether a `NaN` magnitude is consistent with a
status.

Extra: synapse-l4 · Phase 3 · Decision: Rule Ordering — Structural Before Semantic
See: docs/journal.md#phase-3-judge-pass--business-rules-2026-03-31
```

---

```markdown
---
type: cloze
deck: Rhizome::synapse-l4
tags: [synapse-l4, phase-3, thresholds, deferred-config]
---
`ANOMALY_CRITICAL_THRESHOLD` and `ANOMALY_DEGRADED_THRESHOLD` live as
{{c1::module-level constants}} in `rules.py` rather than `config.py` env
vars — moving them to config would enable operational tuning, but was
deferred until the thresholds are {{c2::empirically validated}}.

Extra: synapse-l4 · Phase 3 · Decision: Thresholds as Module-Level Constants (Deferred Config)
See: docs/journal.md#phase-3-judge-pass--business-rules-2026-03-31
```
