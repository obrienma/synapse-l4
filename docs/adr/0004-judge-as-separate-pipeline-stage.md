# ADR 0004 — Judge as a Separate Pipeline Stage (not inline with Instructor)

**Date:** 2026-03-31
**Status:** Accepted

---

## Context

Instructor already supports Pydantic validators (`@field_validator`, `@model_validator`) that run inside the Instructor retry loop. It is tempting to put all business rule checks inside the `Axiom` model validators — Instructor will retry the LLM if they fail. This would reduce the pipeline to two stages: Extract (with embedded validation) and Emit.

However, this conflates two distinct concerns: **schema conformance** (does the output match the type?) and **business logic** (does the output make sense for the domain?).

---

## Decision

**The Judge pass is a separate pipeline stage (`src/nodes/judge.py`), not embedded inside Instructor validators.**

---

## Rationale

**Why not inline the Judge inside Instructor validators?**

1. **Retry semantics differ.** Instructor retries when the LLM can't conform to the schema. Business rule failures (cross-field consistency, domain threshold violations) are often not recoverable by retrying the LLM with the same input — they indicate an ambiguous or mis-classified telemetry packet. Retrying wastes tokens and latency.

2. **Responsibility separation.** The `Axiom` model's validators should enforce what is *structurally valid* for an Axiom. The Judge enforces what is *semantically valid* for the domain. Mixing them makes the `Axiom` model aware of business rules it should not need to know.

3. **Testability.** A separate `judge()` function with a `JudgeRejection` return type is trivially unit-testable with pure Python — no mocking required, no Instructor interaction. Embedded validators are only exercised through Instructor's retry loop, requiring more complex test setup.

4. **Observability.** A separate stage produces a distinct Logfire span — you can see exactly how many extractions succeeded but were rejected by the Judge, vs. how many failed at the schema level. Inline validators obscure this distinction.

**The anti-pattern avoided:** *God Validator* — loading all correctness concerns (type, schema, business logic) into a single validation layer, making it impossible to distinguish extraction failures from domain rejections in logs, tests, and error responses.

---

## Alternatives Rejected

**Pydantic `@model_validator` inside `Axiom`**: Works for simple cross-field checks but triggers Instructor retries for domain-logic failures, burning tokens unnecessarily. Also couples the model to business rules.

**No Judge — rely on Pydantic alone**: Pydantic enforces types and field constraints, not cross-field business logic. `anomaly_score` between 0 and 1 is a type constraint; "high anomaly score requires critical status" is domain knowledge. These are different problems.

---

## Consequences

- `judge()` takes an `Axiom` and returns it unchanged (pass) or raises `JudgeRejection` (fail).
- `JudgeRejection` is a structured exception with a `rule` field — callers use this to return informative `422` responses.
- Business rules live in `src/evaluation/rules.py` as plain Python functions — fully decoupled from Pydantic and Instructor.
- The pipeline is explicitly: `extract() → judge() → emit()`. Skipping `judge()` is not permitted.
