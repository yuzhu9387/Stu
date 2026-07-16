from functools import lru_cache
from typing import Literal, Self

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Validated runtime configuration."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="RECIPE_AGENT_",
        extra="ignore",
    )

    environment: Literal["development", "test", "production"] = "development"
    database_url: str = "postgresql+asyncpg://recipe:recipe@localhost:5432/recipe"
    redis_url: str = "redis://localhost:6379/0"
    session_signing_key: str = "development-only-session-key"
    metrics_token: str = "development-only-metrics-token"
    max_request_bytes: int = 2 * 1024 * 1024
    max_upload_bytes: int = 10 * 1024 * 1024
    litellm_chat_model: str = Field(default="openai/gpt-5.1", min_length=1)
    litellm_fallback_model: str = Field(default="openai/gpt-5-mini", min_length=1)
    litellm_reasoning_effort: Literal["low", "medium", "high"] = "high"
    litellm_timeout_seconds: float = Field(default=30.0, gt=0, le=300)
    litellm_max_retries: int = Field(default=2, ge=0, le=5)
    react_max_iterations: int = Field(default=5, ge=1, le=5)

    @model_validator(mode="after")
    def reject_development_secret_in_production(self) -> Self:
        if self.environment == "production":
            if self.session_signing_key == "development-only-session-key":
                raise ValueError("A production session signing key is required")
            if self.metrics_token == "development-only-metrics-token":
                raise ValueError("A production metrics token is required")
        return self


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide settings instance."""

    return Settings()
