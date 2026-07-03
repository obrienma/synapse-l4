---
id: synapse-l4-20260331-emitter-sentinel-l7-client
repo: synapse-l4
title: "Emitter + Sentinel-L7 Client"
date: 2026-03-31
phase: 4
tags: [axiomdraft-axiom-promotion, constructing-axiom-before-delivery-succeeds, emiterror-carries-the-axiom, emitting-on-failure, http-post-over-redis-xadd-for-now, idempotent-emission, injectable-http-client-for-testability]
cross_ref: observability
cross_ref_id: synapse-l4-20260331-emitter-sentinel-l7-client
files: [src/models/axiom.py (added EmitError), src/clients/sentinel.py, src/clients/sentinel_test.py, src/nodes/emitter.py, src/nodes/emitter_test.py]
---

### Pattern: AxiomDraft → Axiom Promotion
The Emitter is the only place in the pipeline where a full `Axiom` is
constructed. It merges the LLM-extracted fields from `AxiomDraft` with
pipeline-owned fields: `source_id` from `RawTelemetry` and `emitted_at`
stamped at the moment of delivery. No other stage constructs an `Axiom` —
this is enforced by design, not convention.

### Pattern: Idempotent Emission
The Axiom carries `source_id` + `emitted_at` so Sentinel-L7 can deduplicate on
re-delivery. If the emitter retries after a transient network failure,
Sentinel-L7 can detect the duplicate by comparing `source_id` and
`emitted_at` and discard it safely.

### Pattern: Injectable HTTP Client for Testability
`SentinelClient` accepts an `httpx.AsyncClient` at construction. Tests inject
a real `httpx.AsyncClient` mocked at the network layer via `respx`. The
emitter tests inject a mock `SentinelClient` entirely. Two levels of
injection — one for network-level tests (sentinel_test.py), one for
pipeline-level tests (emitter_test.py).

### Anti-Pattern Avoided: Emitting on Failure
The Axiom is only returned to the caller if `post_axiom` succeeds. If
`EmitError` is raised, the function exits without returning — the caller
cannot mistakenly treat a failed emission as a success. This is enforced by
the control flow: `await _client.post_axiom(axiom)` raises before
`return axiom` is reached.

### Anti-Pattern Avoided: Constructing Axiom Before Delivery Succeeds
The `Axiom` is constructed inside `emit()`, not before the call. This ensures
`emitted_at` reflects actual delivery time rather than when the function was
entered.

### Challenge: respx Mock Must Be Activated Before httpx.AsyncClient Construction
`respx.mock` patches at the transport level — it intercepts requests made
through `httpx.AsyncClient`. If the client is constructed before `respx.mock`
is entered (e.g., as a class-level fixture), the mock has no effect and the
test makes a real HTTP call. All `SentinelClient` tests that use `respx` must
construct the client inside the `respx.mock` context.

### Challenge: frozen=True Axiom Cannot Be Constructed With model_copy()
Pydantic's `model_copy(update={...})` is blocked on frozen models — it raises
`ValidationError`. The Emitter constructs `Axiom` from scratch (merging
`AxiomDraft` fields with pipeline-owned fields) rather than copying and
updating. This is correct behaviour, but it means there is no "update this
Axiom field" escape hatch — intentional, since mutation after validation is
the exact anti-pattern `frozen=True` prevents.

### Decision: HTTP POST over Redis XADD (for now)
ADR-0016 in Sentinel-L7 documents the open decision. HTTP is implemented first
because `SENTINEL_L7_URL` is already the only required downstream config, and
the synchronous request/response model is simpler to test with `respx`. If
Redis Streams are chosen, `src/clients/sentinel.py` is the only file that
changes — the emitter node is unaffected.

### Decision: EmitError Carries the Axiom
The failed Axiom is attached to `EmitError` so the API layer can include it in
the 502 response body. Callers that want to retry have the full Axiom
available without reconstructing it. This mirrors the pattern established by
`JudgeRejection` (carries draft) and `ExtractionError` (carries raw payload).

---
