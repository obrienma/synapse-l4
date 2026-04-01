from pydantic import AnyHttpUrl, AnyWebsocketUrl
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # LLM
    openai_api_key: str = ""
    anthropic_api_key: str = ""
    llm_model: str = "gpt-4o-mini"
    instructor_max_retries: int = 3

    # Downstream — Redis Streams delivery (ADR-0016)
    sentinel_redis_url: str  # Upstash Redis URL, e.g. rediss://...@host:port
    sentinel_l7_url: AnyHttpUrl | None = None  # retained for health checks / future use

    # Upstream (optional)
    eventhorizon_ws_url: AnyWebsocketUrl | None = None

    # Observability
    logfire_token: str | None = None
    log_level: str = "INFO"


settings = Settings()  # type: ignore[call-arg]  # validated from env on import
