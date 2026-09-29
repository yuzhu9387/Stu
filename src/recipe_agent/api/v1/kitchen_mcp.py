"""Stateless MCP Streamable HTTP with JSON responses, for AI clients acting in
one household.

Connect POST /api/v1/kitchen/mcp with `Authorization: Bearer stu_…`, a personal
access token made in Settings (or, from the web app itself, the session cookie).
Every tool acts only in that account's household and goes through the kitchen
engine, so validation, revisions and undo history hold as in the app.
A cookie request also needs a JSON content type and an allowed Origin (CSRF);
a bearer token carries no ambient authority. GET returns 405 (no SSE).
Protocol 2025-03-26.
"""

import json
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, ValidationError

from recipe_agent.api.v1.kitchen_ai import service, tasks
from recipe_agent.config import get_settings
from recipe_agent.domain.identity.service import HouseholdScope, IdentityService
from recipe_agent.domain.kitchen.ai import (
    AIUnavailable,
    ChatRequest,
    ComposeRequest,
    ExtractRequest,
    FillRequest,
    GenerateRequest,
    ImportLinkRequest,
    KitchenAI,
)

router = APIRouter(prefix="/api/v1/kitchen", tags=["kitchen-mcp"])
PROTOCOL = "2025-03-26"
COMMANDS = [
    "knowledge.save",
    "knowledge.delete",
    "recipe.save",
    "recipe.delete",
    "tag.save",
    "tag.apply",
    "tag.delete",
    "tag.pin",
    "inventory.save",
    "inventory.delete",
    "inventory.arrange",
    "inventory.receive",
    "settings.save",
    "planning.prompt",
    "planning.workflow",
    "shopping.check",
    "shopping.save",
    "shopping.delete",
    "shopping.putAway",
    "plan.save",
    "plan.confirm",
    "meal.save",
    "meal.delete",
    "meal.leftovers",
    "meal.status",
    "meal.like",
    "meal.lock",
    "prep.save",
    "prep.delete",
    "prep.status",
    "prep.like",
    "meal.include",
    "plan.chat",
    "plan.presets",
    "preset.save",
    "recipe.rate",
    "change.undo",
]
# Not offered: plan.fulfill, the confirmed shopping snapshot, which only the
# confirmation task writes after checking it.


class TaskRef(BaseModel):
    taskId: UUID


class ApplyTask(TaskRef):
    """A finished chat task, and which of its meal changes to apply (all when absent)."""

    mealIds: list[str] | None = Field(default=None, max_length=21)


class LatestTask(BaseModel):
    kind: Literal["chat", "generate", "fulfillment"]
    planId: str | None = None
    weekStart: str | None = None


TASK_TOOLS: list[tuple[str, str, type[BaseModel]]] = [
    (
        "kitchen_task",
        "Status and result of a background AI task (drafting a week, a chat answer, "
        "confirmation). Poll until status is done or failed.",
        TaskRef,
    ),
    (
        "kitchen_task_latest",
        "The latest AI task of a kind, e.g. one the web app started.",
        LatestTask,
    ),
    (
        "kitchen_task_apply",
        "Apply a finished chat task's proposed changes to the plan; with mealIds, only "
        "those meals (and the new recipes and prep they use).",
        ApplyTask,
    ),
]


def tool_definitions() -> list[dict[str, Any]]:
    ai_tools: list[tuple[str, str, type[BaseModel]]] = [
        (
            "kitchen_generate",
            "Start drafting a validated seven-day plan in the background (minutes). "
            "Returns the task; poll it with kitchen_task.",
            GenerateRequest,
        ),
        (
            "kitchen_chat",
            "Preview changes within selected meal IDs; does not apply edits.",
            ChatRequest,
        ),
        (
            "kitchen_extract",
            "Extract recipe candidates from text/image; does not save.",
            ExtractRequest,
        ),
        (
            "kitchen_import_link",
            "Read a public recipe page or video link (http/https) and extract recipe "
            "candidates; does not save. A page that cannot be read says so.",
            ImportLinkRequest,
        ),
        (
            "kitchen_fill",
            "Fill the blanks of a meal's hand-written dishes (food group, ingredients, "
            "steps, minutes); keeps what is given; does not save.",
            FillRequest,
        ),
        (
            "kitchen_compose",
            "Make one dish from chosen fridge foods: a recipe and the portions it takes "
            "from each; does not save (add it with meal.save or prep.save).",
            ComposeRequest,
        ),
    ]
    return [
        {
            "name": "kitchen_read",
            "description": "Read the authenticated household workspace.",
            "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
        },
        {
            "name": "kitchen_command",
            "description": "Validated household CRUD and execution. Commands: "
            + ", ".join(COMMANDS)
            + ". knowledge.save: {document:{id,title,content,category,enabled,sourceUrl?}}; "
            "version and updatedAt are assigned by the server. knowledge.delete payload: {id}. "
            "shopping.save: {item:{id,name,quantity?,checked}} (the fridge door's note). "
            "shopping.delete: {id}. shopping.putAway: {items:[{id,location?,portions?,type?}]} "
            "(into the fridge; the rows leave the note). meal.status: {planId,mealId,"
            "status: planned|completed|skipped|changed, note?} (changed takes no stock). "
            "prep.status: {planId,prepId,status,actualPortions?,location?: freezer|fridge}; "
            'a prep task with origin "fridge" (+ Prep) can be done before its plan is '
            "confirmed, and 0 extra portions leave no box.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "type": {"type": "string", "enum": COMMANDS},
                    "payload": {"type": "object"},
                    "expectedRevision": {"type": "integer", "minimum": 0},
                    "operationId": {"type": "string", "minLength": 1, "maxLength": 160},
                },
                "required": ["type", "payload", "expectedRevision", "operationId"],
                "additionalProperties": False,
            },
        },
        *[
            {"name": name, "description": description, "inputSchema": model.model_json_schema()}
            for name, description, model in [*ai_tools, *TASK_TOOLS]
        ],
    ]


def rpc_error(rpc_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": rpc_id, "error": {"code": code, "message": message}}


async def dispatch(
    message: dict[str, Any], ai: KitchenAI, scope: HouseholdScope, background: Any = None
) -> dict[str, Any] | None:
    """`background` runs AI work as stored tasks (KitchenAITasks); without it,
    drafting a week runs inline."""
    rpc_id = message.get("id")
    if (
        message.get("jsonrpc") != "2.0"
        or not isinstance(message.get("method"), str)
        or ("id" in message and (isinstance(rpc_id, bool) or not isinstance(rpc_id, (str, int))))
    ):
        return rpc_error(None, -32600, "Invalid JSON-RPC request")
    method, params = message["method"], message.get("params", {})
    result: dict[str, Any]
    if not isinstance(params, dict):
        return rpc_error(rpc_id, -32602, "Parameters must be an object")
    if "id" not in message:
        return None  # Notifications never execute mutating tools.
    if method == "initialize":
        if not isinstance(params.get("protocolVersion"), str):
            return rpc_error(rpc_id, -32602, "protocolVersion is required")
        result = {
            "protocolVersion": PROTOCOL,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": "household-kitchen", "version": "1.0.0"},
        }
    elif method == "ping":
        result = {}
    elif method == "tools/list":
        result = {"tools": tool_definitions()}
    elif method == "tools/call":
        name, args = params.get("name"), params.get("arguments", {})
        if not isinstance(args, dict):
            return rpc_error(rpc_id, -32602, "Tool arguments must be an object")
        if name not in {t["name"] for t in tool_definitions()}:
            return rpc_error(rpc_id, -32602, "Unknown tool")
        try:
            if name == "kitchen_read":
                if args:
                    raise ValueError("kitchen_read accepts no ownership or filter arguments")
                data = await ai.repository.get(scope)
            elif name == "kitchen_command":
                from recipe_agent.domain.kitchen.contracts import KitchenCommand

                command = KitchenCommand.model_validate(args).model_dump(mode="json")
                if command["type"] not in COMMANDS:
                    raise ValueError("Unsupported command")
                data = await ai.repository.command(scope, command)
            elif name == "kitchen_generate":
                request = GenerateRequest.model_validate(args)
                data = (
                    await background.start_generate(scope, request)
                    if background is not None
                    else await ai.generate(scope, request)
                )
            elif name in {"kitchen_task", "kitchen_task_latest", "kitchen_task_apply"}:
                if background is None:
                    raise ValueError("Background AI tasks are not available here")
                if name == "kitchen_task_latest":
                    latest = LatestTask.model_validate(args)
                    data = {
                        "task": await background.latest(
                            scope,
                            latest.kind,
                            plan_id=latest.planId,
                            week_start=latest.weekStart,
                        )
                    }
                else:
                    if name == "kitchen_task":
                        ref = TaskRef.model_validate(args)
                        data = {"task": await background.get(scope, ref.taskId)}
                    else:
                        chosen = ApplyTask.model_validate(args)
                        data = await background.apply(scope, chosen.taskId, chosen.mealIds)
            elif name == "kitchen_chat":
                data = await ai.chat(scope, ChatRequest.model_validate(args))
            elif name == "kitchen_import_link":
                data = await ai.import_link(scope, ImportLinkRequest.model_validate(args))
            elif name == "kitchen_fill":
                data = await ai.fill(scope, FillRequest.model_validate(args))
            elif name == "kitchen_compose":
                data = await ai.compose(scope, ComposeRequest.model_validate(args))
            else:
                data = await ai.extract(scope, ExtractRequest.model_validate(args))
            result = {
                "content": [{"type": "text", "text": json.dumps(data, ensure_ascii=False)}],
                "isError": False,
            }
        except ValidationError:
            return rpc_error(rpc_id, -32602, "Invalid tool arguments")
        except (KeyError, TypeError):
            result = {
                "content": [{"type": "text", "text": "Invalid command payload"}],
                "isError": True,
            }
        except (ValueError, AIUnavailable) as exc:
            result = {"content": [{"type": "text", "text": str(exc)}], "isError": True}
    else:
        return rpc_error(rpc_id, -32601, "Method not found")
    return {"jsonrpc": "2.0", "id": rpc_id, "result": result}


def validate_origin(request: Request) -> None:
    settings = getattr(request.app.state, "settings", None) or get_settings()
    origin = request.headers.get("origin")
    if origin and origin.rstrip("/") != settings.web_origin.rstrip("/"):
        raise HTTPException(403, "Origin is not allowed")


async def mcp_scope(request: Request) -> HouseholdScope:
    """A bearer access token, else the web session; either names one household."""
    authorization = request.headers.get("authorization", "")
    scope: HouseholdScope | None = None
    if authorization:
        kind, _, token = authorization.partition(" ")
        if kind.lower() == "bearer" and token.strip():
            identity: IdentityService = request.app.state.identity_service
            scope = await identity.resolve_mcp_token(token.strip())
    else:
        scope = getattr(request.state, "household_scope", None)
    if scope is None:
        raise HTTPException(
            401,
            "Sign in, or send Authorization: Bearer with an access token from Settings",
            headers={"WWW-Authenticate": 'Bearer realm="stu"'},
        )
    return scope


McpScope = Annotated[HouseholdScope, Depends(mcp_scope)]


@router.get("/mcp")
async def no_stream(request: Request, scope: McpScope) -> Response:
    validate_origin(request)
    return Response(status_code=405, headers={"Allow": "POST"})


@router.post("/mcp")
async def mcp(request: Request, scope: McpScope) -> Response:
    validate_origin(request)
    if request.headers.get("content-type", "").split(";", 1)[0].strip() != "application/json":
        raise HTTPException(415, "Content-Type must be application/json")
    try:
        body = await request.json()
    except (ValueError, UnicodeDecodeError):
        return JSONResponse(rpc_error(None, -32700, "Parse error"), status_code=400)
    batch = isinstance(body, list)
    messages = body if batch else [body]
    if not messages or len(messages) > 32 or any(not isinstance(m, dict) for m in messages):
        return JSONResponse(rpc_error(None, -32600, "Invalid request"), status_code=400)
    responses = []
    # Background tasks need the database; a bare test app runs AI work inline.
    ai = service(request)
    background = tasks(request) if hasattr(request.app.state, "session_factory") else None
    for message in messages:
        result = await dispatch(message, ai, scope, background)
        if result is not None:
            responses.append(result)
    if not responses:
        return Response(status_code=202)
    return JSONResponse(responses if batch else responses[0])
