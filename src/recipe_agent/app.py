import hmac

from fastapi import FastAPI, Header, HTTPException, status
from fastapi.responses import PlainTextResponse

from recipe_agent.api.lark import router as lark_router
from recipe_agent.api.security import RequestSecurityMiddleware
from recipe_agent.api.session import SessionScopeMiddleware
from recipe_agent.api.v1.agent import router as agent_router
from recipe_agent.api.v1.auth import router as auth_router
from recipe_agent.api.v1.families import router as families_router
from recipe_agent.api.v1.feature_reads import router as feature_reads_router
from recipe_agent.api.v1.feedback import router as feedback_router
from recipe_agent.api.v1.imports import router as imports_router
from recipe_agent.api.v1.planning import router as planning_router
from recipe_agent.api.v1.recipes import router as recipes_router
from recipe_agent.api.v1.recommendations import router as recommendations_router
from recipe_agent.api.v1.settings import router as settings_router
from recipe_agent.api.v1.shares import router as shares_router
from recipe_agent.config import Settings, get_settings
from recipe_agent.domain.conversation.hub import ConversationHub
from recipe_agent.domain.conversation.repository import AgentRunRepository
from recipe_agent.domain.identity.service import IdentityService
from recipe_agent.infrastructure.db.session import create_session_factory
from recipe_agent.infrastructure.observability.metrics import MetricsRegistry


def create_app(settings: Settings | None = None) -> FastAPI:
    """Create the configured FastAPI application."""

    resolved_settings = settings or get_settings()
    app = FastAPI(title="Family Recipe Agent", version="0.1.0")
    app.state.settings = resolved_settings
    metrics_registry = MetricsRegistry()
    app.state.metrics = metrics_registry
    session_factory = create_session_factory(resolved_settings)
    app.state.session_factory = session_factory
    identity_service = IdentityService(session_factory=session_factory)
    app.state.identity_service = identity_service
    app.state.conversation_hub = ConversationHub(AgentRunRepository(session_factory))
    app.add_middleware(
        RequestSecurityMiddleware,
        max_request_bytes=resolved_settings.max_request_bytes,
        metrics=metrics_registry,
    )
    app.add_middleware(SessionScopeMiddleware, identity=identity_service)
    app.include_router(auth_router)
    app.include_router(agent_router)
    app.include_router(families_router)
    app.include_router(feedback_router)
    app.include_router(feature_reads_router)
    app.include_router(imports_router)
    app.include_router(planning_router)
    app.include_router(recipes_router)
    app.include_router(recommendations_router)
    app.include_router(shares_router)
    app.include_router(settings_router)
    app.include_router(lark_router)

    @app.get("/health/live", tags=["operations"])
    async def live() -> dict[str, str]:
        return {"status": "alive"}

    @app.get("/health/ready", tags=["operations"])
    async def ready() -> dict[str, str]:
        return {"status": "ready"}

    @app.get("/metrics", tags=["operations"], response_class=PlainTextResponse)
    async def metrics(authorization: str | None = Header(default=None)) -> str:
        expected = f"Bearer {resolved_settings.metrics_token}"
        if authorization is None or not hmac.compare_digest(authorization, expected):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
        return metrics_registry.render()

    return app


app = create_app()
