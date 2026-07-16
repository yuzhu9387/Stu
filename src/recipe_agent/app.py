from fastapi import FastAPI

from recipe_agent.config import Settings, get_settings


def create_app(settings: Settings | None = None) -> FastAPI:
    """Create the configured FastAPI application."""

    resolved_settings = settings or get_settings()
    app = FastAPI(title="Family Recipe Agent", version="0.1.0")
    app.state.settings = resolved_settings

    @app.get("/health/live", tags=["operations"])
    async def live() -> dict[str, str]:
        return {"status": "alive"}

    @app.get("/health/ready", tags=["operations"])
    async def ready() -> dict[str, str]:
        return {"status": "ready"}

    return app


app = create_app()
