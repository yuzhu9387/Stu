"""Stateless MCP Streamable HTTP, JSON responses, authenticated web-session transport.

Connect POST /api/v1/kitchen/mcp with the app's authenticated session cookie.
JSON content type, Origin validation and SameSite cookie provide browser CSRF defenses.
There is no CSRF-token header, OAuth discovery or bearer-token authentication.
GET deliberately returns 405 (no server-initiated SSE). Protocol 2025-03-26.
"""

import json
from typing import Any

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ValidationError

from recipe_agent.api.dependencies import ScopeDependency
from recipe_agent.api.v1.kitchen_ai import service
from recipe_agent.config import get_settings
from recipe_agent.domain.identity.service import HouseholdScope
from recipe_agent.domain.kitchen.ai import (
    AIUnavailable,
    ChatRequest,
    ExtractRequest,
    GenerateRequest,
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
    "change.undo",
]


def tool_definitions() -> list[dict[str, Any]]:
    ai_tools: list[tuple[str, str, type[BaseModel]]] = [
        ("kitchen_generate", "Generate and save a validated seven-day draft.", GenerateRequest),
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
            "version and updatedAt are assigned by the server. knowledge.delete payload: {id}.",
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
            for name, description, model in ai_tools
        ],
    ]


def rpc_error(rpc_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": rpc_id, "error": {"code": code, "message": message}}


async def dispatch(
    message: dict[str, Any], ai: KitchenAI, scope: HouseholdScope
) -> dict[str, Any] | None:
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
                data = await ai.generate(scope, GenerateRequest.model_validate(args))
            elif name == "kitchen_chat":
                data = await ai.chat(scope, ChatRequest.model_validate(args))
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


@router.get("/mcp")
async def no_stream(request: Request, scope: ScopeDependency) -> Response:
    validate_origin(request)
    return Response(status_code=405, headers={"Allow": "POST"})


@router.post("/mcp")
async def mcp(request: Request, scope: ScopeDependency) -> Response:
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
    ai = service(request)
    for message in messages:
        result = await dispatch(message, ai, scope)
        if result is not None:
            responses.append(result)
    if not responses:
        return Response(status_code=202)
    return JSONResponse(responses if batch else responses[0])
