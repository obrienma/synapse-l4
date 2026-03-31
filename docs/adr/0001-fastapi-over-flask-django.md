# ADR 0001 — FastAPI over Flask / Django

**Date:** 2026-03-31
**Status:** Accepted

---

## Context

Synapse-L4 is an async microservice. Its pipeline stages involve LLM API calls (high latency, I/O-bound), a WebSocket client subscription to EventHorizon, and outbound HTTP to Sentinel-L7. All of these benefit from async concurrency. The framework choice determines how naturally the codebase expresses async/await and how well it integrates with Pydantic v2 (already a hard dependency for Instructor).

Candidates considered:
- **FastAPI** — async-first, Pydantic-native, automatic OpenAPI docs
- **Flask** — sync-first (async support is bolted on via `asgiref`), no native Pydantic integration
- **Django / Django REST Framework** — ORM-heavy, sync-first, substantial overhead for a focused microservice with no relational DB

---

## Decision

**Use FastAPI.**

---

## Rationale

1. **Async-first**: FastAPI routes are `async def` natively. LLM calls (via Instructor) and outbound HTTP (via httpx) both benefit from non-blocking I/O. Flask requires explicit async adapters; Django requires ASGI middleware layers.

2. **Pydantic v2 is already our contract layer**: FastAPI uses Pydantic v2 for request/response validation out of the box. Our `Axiom` model and `RawTelemetry` input model are reused directly as route parameters — zero additional serialization code.

3. **Automatic OpenAPI docs**: `POST /ingest` and `GET /metrics` are self-documented at `/docs` without extra configuration. Useful for EventHorizon and Sentinel-L7 developers consuming the API.

4. **`TestClient` and `httpx` integration**: FastAPI's test utilities wrap HTTPX, matching the same async client used in production code.

---

## Alternatives Rejected

**Flask** — async support is unofficial and requires `asgiref` wrapping. Pydantic integration requires separate serialization code. Smaller surface for a microservice, but inferior ergonomics for this specific tech stack.

**Django** — designed for full web applications with ORM, templating, and admin UI. All of that is overhead here. DRF adds another abstraction layer on top. Not appropriate for a focused async sidecar.

---

## Consequences

- All routes are `async def` — synchronous blocking calls (e.g., a hypothetical `time.sleep`) must be wrapped with `asyncio.to_thread`.
- Pydantic `BaseModel` is used uniformly across routes and internal types — no separate serialization layer.
- Startup and shutdown events use FastAPI `lifespan` context manager (not deprecated `on_event` handlers).
