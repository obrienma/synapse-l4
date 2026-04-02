# Synapse-L4 — Dev Getting Started

## Prerequisites

| Tool | Version | Install |
|---|---|---|
| Python | 3.12+ | [python.org](https://python.org) or `pyenv install 3.12` |
| uv | latest | `curl -LsSf https://astral.sh/uv/install.sh \| sh` |
| Git | any | |

Optional but recommended:
- **EventHorizon** running locally — provides the WebSocket telemetry feed
- **Sentinel-L7** running locally — receives emitted Axioms

---

## 1. Clone and Install

```bash
git clone https://github.com/obrienma/synapse-l4
cd synapse-l4
uv sync
uv add "logfire[fastapi,httpx]" redis pydantic
```

`uv sync` installs all dependencies from `pyproject.toml` into a managed virtual environment. No manual `venv` or `pip install` needed.

---

## 2. Configure Environment

```bash
cp .env.example .env
```

Open `.env` and fill in required values:

```env
# LLM provider — one of these is required
OPENAI_API_KEY=sk-...
# ANTHROPIC_API_KEY=sk-ant-...

# Downstream system — Redis Streams delivery (required)
SENTINEL_REDIS_URL=rediss://:PASSWORD@HOST:PORT
SENTINEL_L7_URL=http://localhost:8001  # optional, retained for health checks

# Upstream system (optional — only needed for WS consumer mode)
EVENTHORIZON_WS_URL=ws://localhost:3000/ws

# Observability (optional — omit to run without exporting traces)
LOGFIRE_TOKEN=...

# Optional tuning
LLM_MODEL=gpt-4o-mini
INSTRUCTOR_MAX_RETRIES=1        # keep low in development to preserve LLM quota
LLM_DRY_RUN=false               # set true to skip LLM calls entirely (stub response, no tokens burned)
LOG_LEVEL=INFO
```

Config is validated at startup by `config.py` using Pydantic `BaseSettings`. If any required var is missing, the process exits immediately with a clear error — it will not start in a broken state.

---

## 3. Run the Dev Server

```bash
uv run fastapi dev main.py
```

FastAPI starts with hot reload on `http://localhost:8000`.

- Interactive API docs: `http://localhost:8000/docs`
- Alternative docs: `http://localhost:8000/redoc`
- Health check: `http://localhost:8000/health`

---

## 4. Send a Test Event

```bash
curl -X POST http://localhost:8000/ingest \
  -H "Content-Type: application/json" \
  -d '{
    "source_id": "sensor-test-01",
    "payload": {
      "raw_log": "Memory usage at 94% on node staging-02 for 2 minutes",
      "timestamp": "2026-03-31T12:00:00Z",
      "tags": ["memory", "staging"]
    }
  }'
```

Expected response (with `LLM_DRY_RUN=false` and a valid API key):

```json
{
  "axiom": {
    "status": "critical",
    "metric_value": 94.0,
    "anomaly_score": 0.87,
    "source_id": "sensor-test-01",
    "emitted_at": "2026-03-31T12:00:01.234Z"
  },
  "pipeline_ms": 720
}
```

With `LLM_DRY_RUN=true`, the stub values `status: "nominal"`, `metric_value: 42.0`, `anomaly_score: 0.1` are returned instead.

---

## 5. Connect to EventHorizon (optional)

If EventHorizon is running locally, Synapse-L4 can subscribe to its WebSocket feed instead of waiting for HTTP pushes. Set `EVENTHORIZON_WS_URL` in your `.env`, then start the WebSocket consumer worker:

```bash
uv run python -m src.clients.eventhorizon
```

The consumer connects to EventHorizon's `/live` endpoint and routes every `{ type: "event" }` message through the Validation Node pipeline automatically.

---

## 6. Run Tests

```bash
uv run pytest                     # Full suite
uv run pytest -x                  # Stop on first failure
uv run pytest -v                  # Verbose (show test names)
uv run pytest src/nodes/          # Tests for a specific directory
uv run pytest --watch             # Watch mode (re-runs on file change)
```

For LLM-dependent tests, Instructor calls are mocked — no real API key is required to run the test suite.

---

## 7. Type Check

```bash
uv run mypy src/
```

All modules are typed. `config.py` and `src/models/` are held to strict `--disallow-untyped-defs`.

---

## 8. Verify the Pipeline End-to-End

With both EventHorizon and Sentinel-L7 running:

1. Start Synapse-L4 dev server (`uv run fastapi dev main.py`)
2. Start the EventHorizon WS consumer (`uv run python -m src.clients.eventhorizon`)
3. Seed EventHorizon: `cd ../EventHorizon && npm run seed`
4. Watch Logfire or the `/metrics` endpoint for Axiom emission counts

---

## Troubleshooting

**`ValidationError` on startup** — a required env var is missing or has the wrong type. Read the error output — it names the field and expected type.

**`extraction_failed` responses** — the LLM returned output that Instructor could not coerce to `Axiom` after `INSTRUCTOR_MAX_RETRIES` attempts. Try increasing retries or simplifying the payload in the prompt.

**`judge_rejected` responses** — the extracted Axiom violated a business rule. Check the `rule` field in the error response for the specific constraint.

**WS consumer disconnects** — the client reconnects with exponential backoff automatically. If EventHorizon is not reachable, it retries indefinitely and logs each attempt.

**LLM quota exhausted** — set `LLM_DRY_RUN=true` in `.env` and restart. The extractor returns a hardcoded stub `AxiomDraft`; the full pipeline (Judge → Emit) still runs. Useful for testing downstream behaviour and generating Logfire traces without burning tokens.
