---
id: synapse-l4-20260331-judge-pass-business-rules
repo: synapse-l4
title: "Judge Pass + Business Rules"
date: 2026-03-31
phase: 3
tags: [accepting-sentinel-float-values, fail-fast-validation, rule-ordering-structural-before-semantic, rule-registry-pattern, silent-contradiction, thresholds-as-module-level-constants-deferred-config, validator-as-judge]
files: [src/evaluation/rules.py, src/evaluation/rules_test.py, src/nodes/judge.py, src/nodes/judge_test.py]
---

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
