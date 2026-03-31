# ADR 0002 — Instructor for Structured LLM Output (over raw JSON prompting)

**Date:** 2026-03-31
**Status:** Accepted

---

## Context

Synapse-L4's core task is extracting a structured `Axiom` from unstructured telemetry text. The naive approach is to prompt the LLM to "return JSON matching this schema" and then parse the response string. This is the **prompt engineering for output format** anti-pattern, and it fails in production for well-documented reasons:

- LLMs frequently wrap JSON in markdown code fences (` ```json ... ``` `)
- LLMs omit required fields when the prompt is long or ambiguous
- LLMs invent additional fields not in the schema
- Field types are wrong (string instead of float, missing `null` for optional)
- None of these failures are reliably catchable without re-prompting

---

## Decision

**Use [Instructor](https://github.com/jxnl/instructor) patched over the LLM client for all structured extraction.**

---

## Rationale

Instructor uses the LLM provider's **function calling / tool use** protocol (not prompt tricks) to enforce schema conformance. The Pydantic model is passed to the API as a tool definition; the model is constrained to return a conforming object, not free text. If it fails, Instructor automatically retries with the validation error as feedback — up to `max_retries`.

**This means:**
- Schema conformance is enforced at the protocol level, not at the string-parsing level
- Our `Axiom` Pydantic model is used directly as the response schema — no duplication
- Retry logic is built-in — we do not write our own re-prompting loop
- The extractor either returns a valid `Axiom` or raises a structured error — never a partial/malformed dict

**The anti-pattern avoided:** *Prompt Engineering for Output Format* — using natural language instructions like "respond only with JSON" to coerce structure. This approach has no recovery mechanism and no type guarantees.

---

## Alternatives Rejected

**Raw JSON parsing with `json.loads()`**: Zero retry logic, no schema enforcement, brittle to markdown wrapping. Would require a custom retry/repair loop that recreates what Instructor already provides.

**LangChain output parsers**: Similar goal but tightly coupled to the LangChain ecosystem. Synapse-L4 should not take a framework dependency when Instructor solves the specific problem without it.

**Outlines / grammar-constrained decoding**: Enforces schema via token-level logit masking — stronger guarantees than function calling, but requires a self-hosted model. Not compatible with OpenAI/Anthropic API backends.

---

## Consequences

- The LLM client is always patched with `instructor.patch()` or `instructor.from_openai()` before use — never used raw.
- `max_retries` is configurable via `INSTRUCTOR_MAX_RETRIES` env var (default `3`). Exhaustion raises `InstructorRetryException` — the extractor converts this to `ExtractionError`.
- Instructor is async-compatible (`instructor.from_openai(AsyncOpenAI())`) — no threading workarounds needed.
- Adding a new extraction target means adding a new Pydantic model — no prompt engineering required.
