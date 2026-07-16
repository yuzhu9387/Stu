from functools import lru_cache
from typing import Literal, Self

from pydantic import model_validator
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

    @model_validator(mode="after")
    def reject_development_secret_in_production(self) -> Self:
        if (
            self.environment == "production"
            and self.session_signing_key == "development-only-session-key"
        ):
            raise ValueError("A production session signing key is required")
        return self


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide settings instance."""

    return Settings()
