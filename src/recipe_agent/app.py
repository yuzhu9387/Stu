from fastapi import FastAPI

from recipe_agent.api.lark import router as lark_router
from recipe_agent.api.v1.auth import router as auth_router
from recipe_agent.api.v1.planning import router as planning_router
from recipe_agent.api.v1.recommendations import router as recommendations_router
from recipe_agent.config import Settings, get_settings
from recipe_agent.domain.identity.service import IdentityService
from recipe_agent.infrastructure.db.session import create_session_factory


def create_app(settings: Settings | None = None) -> FastAPI:
    """Create the configured FastAPI application."""

    resolved_settings = settings or get_settings()
    app = FastAPI(title="Family Recipe Agent", version="0.1.0")
    app.state.settings = resolved_settings
    app.state.identity_service = IdentityService(
        session_factory=create_session_factory(resolved_settings)
    )
    app.include_router(auth_router)
    app.include_router(planning_router)
    app.include_router(recommendations_router)
    app.include_router(lark_router)

    @app.get("/health/live", tags=["operations"])
    async def live() -> dict[str, str]:
        return {"status": "alive"}

    @app.get("/health/ready", tags=["operations"])
    async def ready() -> dict[str, str]:
        return {"status": "ready"}

    return app


app = create_app()
