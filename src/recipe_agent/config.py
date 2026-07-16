from functools import lru_cache
from typing import Literal, Self

from pydantic import AliasChoices, Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Validated runtime configuration."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="RECIPE_AGENT_",
        extra="ignore",
        populate_by_name=True,
        hide_input_in_errors=True,
    )

    environment: Literal["development", "test", "production"] = "development"
    database_url: str = "postgresql+asyncpg://recipe:recipe@localhost:5432/recipe"
    redis_url: str = "redis://localhost:6379/0"
    session_signing_key: str = "development-only-session-key"
    metrics_token: str = "development-only-metrics-token"
    action_signing_key: str = "development-only-action-key"
    max_request_bytes: int = 2 * 1024 * 1024
    max_upload_bytes: int = 10 * 1024 * 1024
    web_origin: str = "http://localhost:3000"
    openai_api_key: SecretStr | None = Field(
        default=None,
        validation_alias=AliasChoices("OPENAI_API_KEY", "RECIPE_AGENT_OPENAI_API_KEY"),
    )
    litellm_chat_model: str = Field(default="openai/gpt-5.1", min_length=1)
    litellm_fallback_model: str = Field(default="openai/gpt-5-mini", min_length=1)
    litellm_vision_model: str = Field(default="openai/gpt-5-mini", min_length=1)
    litellm_embedding_model: str = Field(default="openai/text-embedding-3-small", min_length=1)
    litellm_reasoning_effort: Literal["low", "medium", "high"] = "high"
    litellm_timeout_seconds: float = Field(default=30.0, gt=0, le=300)
    litellm_max_retries: int = Field(default=2, ge=0, le=5)
    react_max_iterations: int = Field(default=5, ge=1, le=5)
    suggested_action_lifetime_seconds: int = Field(default=900, ge=60, le=86_400)
    lark_enabled: bool = False
    lark_api_base_url: str = "https://open.larksuite.com"
    lark_app_id: str | None = None
    lark_app_secret: SecretStr | None = None
    lark_verification_token: SecretStr | None = None
    lark_encrypt_key: SecretStr | None = None

    @model_validator(mode="after")
    def reject_development_secret_in_production(self) -> Self:
        if self.lark_enabled and not all(
            (self.lark_app_id, self.lark_app_secret, self.lark_verification_token)
        ):
            raise ValueError("Lark configuration is incomplete")
        if self.environment == "production":
            if self.session_signing_key == "development-only-session-key":
                raise ValueError("A production session signing key is required")
            if self.metrics_token == "development-only-metrics-token":
                raise ValueError("A production metrics token is required")
            if self.action_signing_key == "development-only-action-key":
                raise ValueError("A production action signing key is required")
            if self.openai_api_key is None:
                raise ValueError("An OpenAI API key is required in production")
        return self


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide settings instance."""

    return Settings()
