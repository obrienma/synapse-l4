import asyncio
import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI

from config import settings

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(levelname)-8s %(name)s: %(message)s",
)
from src.api.ingest import router as ingest_router
from src.clients.eventhorizon import run as run_eventhorizon_consumer
from src.observation.instrumentation import configure_logfire, instrument_fastapi, instrument_httpx

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    configure_logfire()
    instrument_fastapi(app)
    instrument_httpx()

    consumer_task: asyncio.Task[None] | None = None
    if settings.eventhorizon_ws_url:
        consumer_task = asyncio.create_task(
            run_eventhorizon_consumer(str(settings.eventhorizon_ws_url))
        )
        logger.info("EventHorizon consumer started: %s", settings.eventhorizon_ws_url)

    yield

    if consumer_task is not None:
        consumer_task.cancel()
        try:
            await consumer_task
        except asyncio.CancelledError:
            pass


app = FastAPI(title="Synapse-L4", version="0.1.0", lifespan=lifespan)

app.include_router(ingest_router)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "version": "0.1.0"}
