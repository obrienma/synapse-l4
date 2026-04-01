from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI

from config import settings  # noqa: F401  — validates env on import


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    # TODO: initialise Logfire, LLM client, Sentinel-L7 HTTP client
    yield
    # TODO: graceful shutdown — close HTTP clients, WS consumer


app = FastAPI(title="Synapse-L4", version="0.1.0", lifespan=lifespan)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "version": "0.1.0"}
