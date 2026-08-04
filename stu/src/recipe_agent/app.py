import asyncio
import hmac
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Header, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse

from recipe_agent.api.lark import router as lark_router
from recipe_agent.api.security import RequestSecurityMiddleware
from recipe_agent.api.session import SessionScopeMiddleware
from recipe_agent.api.v1.actions import router as actions_router
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
from recipe_agent.api.v1.shares import public_router as public_shares_router
from recipe_agent.api.v1.shares import router as shares_router
from recipe_agent.api.v1.todos import router as todos_router
from recipe_agent.bootstrap import build_runtime
from recipe_agent.config import Settings, get_settings
from recipe_agent.infrastructure.observability.metrics import MetricsRegistry

READINESS_TIMEOUT_SECONDS = 2.0


def create_app(settings: Settings | None = None) -> FastAPI:
    """Create the configured FastAPI application."""

    resolved_settings = settings or get_settings()
    runtime = build_runtime(resolved_settings)

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        del application
        yield
        await runtime.aclose()

    app = FastAPI(title="Family Recipe Agent", version="0.1.0", lifespan=lifespan)
    app.state.settings = resolved_settings
    app.state.runtime = runtime
    metrics_registry = MetricsRegistry()
    app.state.metrics = metrics_registry
    app.state.session_factory = runtime.session_factory
    for name in (
        "identity_service",
        "conversation_hub",
        "agent_run_service",
        "suggested_action_service",
        "recommendation_service",
        "planning_service",
        "share_service",
        "feedback_service",
        "import_service",
        "lark_handler",
        "readiness",
    ):
        setattr(app.state, name, getattr(runtime, name))
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[resolved_settings.web_origin],
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", "Idempotency-Key"],
    )
    app.add_middleware(
        RequestSecurityMiddleware,
        max_request_bytes=resolved_settings.max_request_bytes,
        metrics=metrics_registry,
    )
    app.add_middleware(
        SessionScopeMiddleware,
        identity=runtime.identity_service,
    )
    app.include_router(auth_router)
    app.include_router(agent_router)
    app.include_router(actions_router)
    app.include_router(families_router)
    app.include_router(feedback_router)
    app.include_router(feature_reads_router)
    app.include_router(imports_router)
    app.include_router(planning_router)
    app.include_router(recipes_router)
    app.include_router(recommendations_router)
    app.include_router(shares_router)
    app.include_router(public_shares_router)
    app.include_router(settings_router)
    app.include_router(todos_router)
    app.include_router(lark_router)

    @app.get("/health/live", tags=["operations"])
    async def live() -> dict[str, str]:
        return {"status": "alive"}

    @app.get("/health/ready", tags=["operations"])
    async def ready() -> dict[str, str]:
        try:
            await asyncio.wait_for(
                app.state.readiness.check(),
                timeout=READINESS_TIMEOUT_SECONDS,
            )
        except Exception:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Application dependencies are unavailable",
            ) from None
        return {"status": "ready"}

    @app.get("/metrics", tags=["operations"], response_class=PlainTextResponse)
    async def metrics(authorization: str | None = Header(default=None)) -> str:
        expected = f"Bearer {resolved_settings.metrics_token}"
        if authorization is None or not hmac.compare_digest(authorization, expected):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
        return metrics_registry.render()

    return app


app = create_app()
