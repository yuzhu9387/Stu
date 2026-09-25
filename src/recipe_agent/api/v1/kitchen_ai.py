"""Authenticated AI previews and validated kitchen generation."""

from collections.abc import Awaitable
from typing import Any, Literal, cast
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from pydantic import ValidationError

from recipe_agent.api.dependencies import ScopeDependency
from recipe_agent.config import get_settings
from recipe_agent.domain.kitchen.ai import (
    AIUnavailable,
    ChatRequest,
    ExtractRequest,
    GenerateRequest,
    KitchenAI,
    PreferencesRequest,
)
from recipe_agent.domain.kitchen.fulfillment import FulfillmentRequest
from recipe_agent.infrastructure.jobs.kitchen_ai_tasks import KitchenAITasks

router = APIRouter(prefix="/api/v1/kitchen", tags=["kitchen-ai"])


def service(request: Request) -> KitchenAI:
    from recipe_agent.domain.kitchen.repository import KitchenRepository

    installed = getattr(request.app.state, "kitchen_ai", None)
    if installed is not None:
        return cast(KitchenAI, installed)
    settings = getattr(request.app.state, "settings", None) or get_settings()
    return KitchenAI(
        KitchenRepository(
            request.app.state.session_factory,
            relational_read=settings.kitchen_relational_read,
        ),
        settings,
    )


async def invoke[ResultT](call: Awaitable[ResultT]) -> ResultT:
    try:
        return await call
    except AIUnavailable as exc:
        raise HTTPException(503, str(exc)) from exc
    except (ValueError, ValidationError) as exc:
        raise HTTPException(getattr(exc, "status_code", 422), str(exc)) from exc


@router.post("/generate")
async def generate(
    body: GenerateRequest, request: Request, scope: ScopeDependency
) -> dict[str, Any]:
    return await invoke(service(request).generate(scope, body))


@router.post("/chat")
async def chat(body: ChatRequest, request: Request, scope: ScopeDependency) -> dict[str, Any]:
    return await invoke(service(request).chat(scope, body))


@router.post("/extract")
async def extract(body: ExtractRequest, request: Request, scope: ScopeDependency) -> dict[str, Any]:
    return await invoke(service(request).extract(scope, body))


@router.post("/preferences")
async def preferences(
    body: PreferencesRequest, request: Request, scope: ScopeDependency
) -> dict[str, Any]:
    return await invoke(service(request).preferences(scope, body))


# ── Stored AI tasks: the work outlives the page that asked for it ────────────
def tasks(request: Request) -> KitchenAITasks:
    return KitchenAITasks(request.app.state.session_factory, service(request))


async def run_task[ResultT](call: Awaitable[ResultT]) -> ResultT:
    from recipe_agent.domain.kitchen.engine import KitchenError

    try:
        return await call
    except KitchenError as exc:
        raise HTTPException(exc.status_code, str(exc)) from exc
    except (ValueError, ValidationError) as exc:
        raise HTTPException(422, str(exc)) from exc


@router.post("/ai-tasks/chat")
async def start_chat(body: ChatRequest, request: Request, scope: ScopeDependency) -> dict[str, Any]:
    """Add the message to the conversation and let Stu answer in the background."""
    return await run_task(tasks(request).start_chat(scope, body))


@router.post("/ai-tasks/generate")
async def start_generate(
    body: GenerateRequest, request: Request, scope: ScopeDependency
) -> dict[str, Any]:
    """Start drafting a week in the background; a draft already underway is reused."""
    return await run_task(tasks(request).start_generate(scope, body))


@router.post("/ai-tasks/fulfillment")
async def start_fulfillment(
    body: FulfillmentRequest, request: Request, scope: ScopeDependency
) -> dict[str, Any]:
    return await run_task(tasks(request).start_fulfillment(scope, body))


@router.get("/ai-tasks/latest")
async def latest_task(
    request: Request,
    scope: ScopeDependency,
    kind: Literal["chat", "generate", "fulfillment"],
    planId: str | None = None,
    weekStart: str | None = None,
) -> dict[str, Any]:
    return {"task": await tasks(request).latest(scope, kind, plan_id=planId, week_start=weekStart)}


@router.get("/ai-tasks/{task_id}")
async def get_task(task_id: UUID, request: Request, scope: ScopeDependency) -> dict[str, Any]:
    return {"task": await run_task(tasks(request).get(scope, task_id))}


@router.post("/ai-tasks/{task_id}/apply")
async def apply_task(task_id: UUID, request: Request, scope: ScopeDependency) -> dict[str, Any]:
    return await run_task(tasks(request).apply(scope, task_id))


@router.post("/ai-tasks/{task_id}/dismiss")
async def dismiss_task(task_id: UUID, request: Request, scope: ScopeDependency) -> dict[str, Any]:
    return {"task": await run_task(tasks(request).dismiss(scope, task_id))}
