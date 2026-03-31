# ADR 0003 — Frozen Pydantic Models for Axioms

**Date:** 2026-03-31
**Status:** Accepted

---

## Context

An `Axiom` is the output of a validated pipeline run. Its value is determined by the Judge pass — the moment `judge()` returns without raising, the Axiom is considered verified. Any subsequent mutation of the Axiom object (before or during emission) would silently invalidate the verification.

In Python, nothing prevents a mutable object from being modified after it passes validation. A dict, a dataclass without `frozen=True`, or a Pydantic model without `model_config = ConfigDict(frozen=True)` can all be mutated at any point in the call stack. This is the **mutable validated output** anti-pattern — the verified state is not enforced by the type system.

---

## Decision

**All `Axiom` instances use `model_config = ConfigDict(frozen=True)`.**

---

## Rationale

`frozen=True` makes the Pydantic model immutable at the Python level:
- Setting any field after construction raises `ValidationError` immediately
- The instance becomes hashable (usable as a dict key or set member)
- The type system itself enforces the invariant — no runtime guard needed, no documentation required

This aligns with the project invariant: **"Axioms are immutable once emitted."** The invariant is not a convention; it is a type constraint.

**The anti-pattern avoided:** *Mutable Validated Output* — passing a validated object through multiple stages where any stage could inadvertently modify it, silently corrupting the verified state before emission.

---

## Alternatives Rejected

**Mutable Pydantic model + docstring convention**: "Don't mutate this after validation" is not enforced. It will be violated eventually — by accident, by a future contributor, or by a refactor that doesn't read the comment.

**`dataclass(frozen=True)`**: Provides immutability but loses Pydantic's field validation, `ge`/`le` constraints, and automatic JSON serialization. We need both.

**`TypedDict`**: Read-only at the type-checker level (via `ReadOnly`), but not enforced at runtime. Mypy catches it; a `dict` assignment at runtime does not.

---

## Consequences

- `Axiom.model_copy(update={...})` is the only way to produce a modified Axiom — it returns a new instance. If a pipeline stage needs to add a field, it must construct a new Axiom, not mutate the existing one.
- Tests that verify immutability: `with pytest.raises(ValidationError): axiom.status = "degraded"` — this is a required test for Phase 1.
- Any future models that represent "finalized" pipeline outputs should also use `frozen=True`.
