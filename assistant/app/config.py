from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql+asyncpg://guoyuzhu:guoyuzhu@localhost:5432/my_assistant"
    test_database_url: str = "sqlite+aiosqlite:///./test.db"

    anthropic_api_key: str = ""

    llm_think_model: str = "claude-haiku-4-5-20251001"
    llm_react_model: str = "claude-sonnet-4-6"
    llm_reasoning_model: str = "claude-opus-4-7"

    lark_app_id: str = ""
    lark_app_secret: str = ""
    lark_verification_token: str = ""
    lark_encrypt_key: str = ""

    voyage_api_key: str = ""

    enable_scheduler: bool = True
    proactive_dry_run: bool = False

    model_config = {"env_prefix": "PA_", "env_file": ".env"}


settings = Settings()
