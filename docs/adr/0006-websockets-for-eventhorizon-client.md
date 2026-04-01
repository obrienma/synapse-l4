# ADR 0006 — `websockets` Library for EventHorizon Client

**Date:** 2026-03-31
**Status:** Accepted

---

## Context

Synapse-L4 needs to subscribe to EventHorizon's observation plane WebSocket endpoint (`/live`) as an outbound client. This is a long-lived, async, receive-only connection — EventHorizon pushes `{ type: "event" }` messages and Synapse-L4 routes them into the Validation Node pipeline.

The choice of WebSocket client library affects async compatibility, reconnection ergonomics, and how cleanly the connection lifecycle integrates with FastAPI's `lifespan` context manager.

Candidates considered:
- **`websockets`** — pure-Python, asyncio-native, widely used WS client/server library
- **`httpx-ws`** — WebSocket extension for httpx; keeps a single HTTP client for both REST and WS calls
- **`aiohttp` client** — async HTTP + WS in one package, but pulls in a large dependency
- **`starlette` WebSocket client** — not designed for outbound connections; server-side only

---

## Decision

**Use the `websockets` library for the EventHorizon WebSocket client.**

---

## Rationale

1. **Asyncio-native**: `websockets` is built on `asyncio` from the ground up. `async for message in websocket` is the idiomatic receive loop — no callbacks, no thread bridging, no adapter layers.

2. **Focused scope**: Synapse-L4's WS usage is one outbound subscription. `websockets` covers exactly this without pulling in a full HTTP client framework (`aiohttp`) or requiring an httpx extension plugin.

3. **Reconnection control**: `websockets.connect()` is a context manager — wrapping it in a `while True` loop with exponential backoff gives explicit, readable reconnection logic. Higher-level abstractions hide this behaviour, making failure modes harder to reason about.

4. **EventHorizon compatibility**: EventHorizon's WS server uses `@fastify/websocket` (raw WebSocket protocol, no socket.io). The `websockets` library speaks the raw WS protocol — no namespace or event-emitter negotiation required.

5. **No duplication with httpx**: Synapse-L4 uses `httpx` for outbound HTTP to Sentinel-L7. These are distinct concerns (short-lived REST calls vs. long-lived WS stream) — using the same client for both would conflate them.

---

## Alternatives Rejected

**`httpx-ws`**: Extends httpx with WS support. Appealing for code reuse, but httpx-ws is a thin wrapper that adds complexity without simplifying the async reconnection pattern. `websockets` is better documented for long-lived subscriber use cases.

**`aiohttp` client**: Provides both HTTP and WS, but `aiohttp` is a large dependency with its own event loop integration assumptions. Pulling it in solely for the WS client is disproportionate.

**`starlette` / FastAPI WS**: Designed for inbound server-side WebSocket handlers. Not usable for outbound client connections.

---

## Consequences

- `src/clients/eventhorizon.py` uses `websockets.connect()` as an async context manager inside a reconnection loop.
- Reconnection uses exponential backoff (configurable via env var — TODO for implementation phase).
- Only `{ type: "event" }` messages are routed to the pipeline; `stats` and `ping` messages are silently dropped.
- The WS consumer runs as a background `asyncio.Task` started in `main.py`'s `lifespan` and cancelled on shutdown.
