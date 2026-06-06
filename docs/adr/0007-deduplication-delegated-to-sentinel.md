# ADR 0007 — Deduplication Delegated to Sentinel-L7 (not enforced in Synapse-L4)

**Date:** 2026-05-14
**Status:** Accepted

---

## Context

Synapse-L4 receives telemetry from EventHorizon over a WebSocket stream. EventHorizon may deliver the same event more than once — on reconnect, on retry, or if a producer publishes a duplicate `source_id`. Nothing in the pipeline currently prevents a repeated `source_id` from flowing through Extract → Judge → Emit twice, producing two distinct entries in the `synapse:axioms` Redis stream.

`source_id` is used only as a logging label during Extract and Judge, and is stamped onto the `Axiom` at emission time. It has no gate effect. `SentinelClient.post_axiom` calls `XADD synapse:axioms` with Redis's auto-generated `*` message ID, which is time-based and always unique — Redis does not deduplicate on field values.

The emitter module (`src/nodes/emitter.py`) documents an *intent* of idempotent emission — that Sentinel-L7 could detect re-deliveries using `source_id + emitted_at`. That intent is aspirational: neither Synapse-L4 nor Sentinel-L7 currently enforces it.

The question is: which system is responsible for deduplication?

---

## Decision

**Synapse-L4 does not deduplicate. Deduplication is Sentinel-L7's responsibility, keyed on `source_id + emitted_at`.**

---

## Rationale

**Why not deduplicate in Synapse-L4?**

1. **Wrong layer for the problem.** Synapse-L4 is a validation and classification node — it transforms raw telemetry into trusted Axioms. Whether a given `source_id` has been seen before is consumer state, not pipeline state. The pipeline's job is to emit a correct Axiom; the consumer's job is to decide what to do with it.

2. **In-process dedup requires shared state across workers.** The EventHorizon client runs a pool of `_worker` coroutines (see `eventhorizon.py`). A seen-IDs set would need to be shared across all workers, introducing a lock or an external store. This adds latency and a new failure mode for a guarantee that should be enforced downstream.

3. **At-least-once is the correct guarantee for a stream processor.** Redis Streams with consumer groups already provide at-least-once delivery semantics. Synapse-L4 sits upstream of that guarantee. Duplicating the dedup concern here would create two independent dedup layers with no coordination between them.

4. **`source_id` is not a globally unique event key.** A `source_id` identifies the *source* (a sensor, node, or service), not the *event*. The same source legitimately emits many events over time. Deduplicating on `source_id` alone would incorrectly suppress valid re-emissions from the same source.

**The anti-pattern avoided:** *Eager Deduplication* — filtering repeated identifiers at the earliest possible layer rather than at the layer that owns consumer state. This causes silent data loss when the dedup window is shorter than the retry window, and complicates horizontal scaling because each worker maintains its own incomplete view of seen IDs.

---

## Alternatives Rejected

**In-process `seen_ids` set in the worker pool:** Requires a shared lock or asyncio-safe structure across worker coroutines. Does not survive process restarts. Cannot span multiple Synapse-L4 instances. Rejected.

**Redis-backed dedup set with TTL:** Adds a Redis round-trip per telemetry event before the pipeline begins. Introduces a new failure dependency (dedup store unavailable = pipeline stalls). Dedup TTL is hard to tune without knowledge of EventHorizon's retry window. Rejected.

**Dedup inside the Judge stage:** The Judge validates semantic correctness against domain rules. Injecting consumer state (have-I-seen-this-ID?) into a pure domain logic stage violates the stage separation invariant and makes the Judge impure. Rejected.

---

## Consequences

- `source_id` carries its current meaning — source identity, not event identity. It is stamped onto the Axiom at emission time and passed to Sentinel-L7 as a field in the `synapse:axioms` stream entry.
- Synapse-L4's delivery guarantee is **at-least-once**: a duplicate inbound event produces a duplicate stream entry. This is expected and acceptable.
- **Sentinel-L7 must implement deduplication** on `synapse:axioms` consumption, keyed on `source_id + emitted_at`. Until it does, duplicate Axioms will be processed as two independent compliance events.
- This is a known gap. A follow-up ADR in Sentinel-L7 should document how dedup is implemented there.
