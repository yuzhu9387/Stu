"""AI clients reach the kitchen over MCP with a personal access token: it acts
in its own household only, cannot mint tokens, and stops working once revoked."""

import asyncio
import json

from recipe_agent.app import create_app
from tests.security.test_session_scope import _create_schema, _settings

MCP = "/api/v1/kitchen/mcp"


def rpc(method: str, params: dict | None = None, rpc_id: int = 1) -> dict:
    return {"jsonrpc": "2.0", "id": rpc_id, "method": method, "params": params or {}}


def call(tool: str, arguments: dict) -> dict:
    return rpc("tools/call", {"name": tool, "arguments": arguments})


def signed_up(client_factory, app, email: str):
    client = client_factory(app)
    response = client.post(
        "/api/v1/auth/register", json={"email": email, "password": "correct horse"}
    )
    assert response.status_code == 204
    return client


def test_an_access_token_drives_the_kitchen_over_mcp(client_factory, tmp_path) -> None:
    database_url = f"sqlite+aiosqlite:///{tmp_path / 'mcp.db'}"
    asyncio.run(_create_schema(database_url))
    app = create_app(_settings(database_url, environment="development"))
    web = signed_up(client_factory, app, "cook@example.com")

    created = web.post("/api/v1/auth/mcp-tokens", json={"name": "Claude"})
    assert created.status_code == 201
    token = created.json()["token"]
    assert token.startswith("stu_")
    listed = web.get("/api/v1/auth/mcp-tokens").json()["tokens"]
    assert [t["name"] for t in listed] == ["Claude"]
    assert "token" not in listed[0]  # shown once, never again

    ai = client_factory(app)  # no cookie: only the token
    bearer = {"Authorization": f"Bearer {token}"}
    tools = ai.post(MCP, json=rpc("tools/list"), headers=bearer).json()["result"]["tools"]
    names = {t["name"] for t in tools}
    assert {"kitchen_read", "kitchen_command", "kitchen_task", "kitchen_task_apply"} <= names
    commands = next(t for t in tools if t["name"] == "kitchen_command")["inputSchema"]
    assert "recipe.rate" in commands["properties"]["type"]["enum"]
    assert "plan.fulfill" not in commands["properties"]["type"]["enum"]

    saved = ai.post(
        MCP,
        json=call(
            "kitchen_command",
            {
                "type": "tag.save",
                "payload": {"name": "Soup"},
                "expectedRevision": 0,
                "operationId": "mcp-tag",
            },
        ),
        headers=bearer,
    ).json()["result"]
    assert not saved["isError"]
    workspace = ai.post(MCP, json=call("kitchen_read", {}), headers=bearer).json()["result"]
    assert json.loads(workspace["content"][0]["text"])["tags"] == ["Soup"]
    # The web app sees the same household.
    assert web.get("/api/v1/kitchen").json()["tags"] == ["Soup"]
    assert web.get("/api/v1/auth/mcp-tokens").json()["tokens"][0]["lastUsedAt"]


def test_tokens_stay_in_their_household_and_cannot_mint_tokens(client_factory, tmp_path) -> None:
    database_url = f"sqlite+aiosqlite:///{tmp_path / 'mcp-scope.db'}"
    asyncio.run(_create_schema(database_url))
    app = create_app(_settings(database_url, environment="development"))
    first = signed_up(client_factory, app, "first@example.com")
    second = signed_up(client_factory, app, "second@example.com")
    first.post(
        "/api/v1/kitchen/commands",
        json={
            "type": "tag.save",
            "payload": {"name": "Mine"},
            "expectedRevision": 0,
            "operationId": "t",
        },
    )
    token = second.post("/api/v1/auth/mcp-tokens", json={"name": "Other"}).json()["token"]

    ai = client_factory(app)
    bearer = {"Authorization": f"Bearer {token}"}
    workspace = ai.post(MCP, json=call("kitchen_read", {}), headers=bearer).json()["result"]
    assert json.loads(workspace["content"][0]["text"])["tags"] == []
    # A token uses the kitchen; it cannot list, mint or revoke tokens.
    assert ai.get("/api/v1/auth/mcp-tokens", headers=bearer).status_code == 401
    assert ai.post("/api/v1/auth/mcp-tokens", json={"name": "x"}, headers=bearer).status_code == 401
    # Nor can one account revoke another's token.
    token_id = second.get("/api/v1/auth/mcp-tokens").json()["tokens"][0]["id"]
    assert first.delete(f"/api/v1/auth/mcp-tokens/{token_id}").status_code == 404


def test_unknown_and_revoked_tokens_are_refused(client_factory, tmp_path) -> None:
    database_url = f"sqlite+aiosqlite:///{tmp_path / 'mcp-revoke.db'}"
    asyncio.run(_create_schema(database_url))
    app = create_app(_settings(database_url, environment="development"))
    web = signed_up(client_factory, app, "cook@example.com")
    created = web.post("/api/v1/auth/mcp-tokens", json={"name": "Claude"}).json()

    ai = client_factory(app)
    refused = ai.post(MCP, json=rpc("tools/list"), headers={"Authorization": "Bearer stu_nope"})
    assert refused.status_code == 401
    assert refused.headers["www-authenticate"].startswith("Bearer")
    assert ai.post(MCP, json=rpc("tools/list")).status_code == 401

    bearer = {"Authorization": f"Bearer {created['token']}"}
    assert ai.post(MCP, json=rpc("tools/list"), headers=bearer).status_code == 200
    assert web.delete(f"/api/v1/auth/mcp-tokens/{created['id']}").status_code == 204
    assert ai.post(MCP, json=rpc("tools/list"), headers=bearer).status_code == 401
