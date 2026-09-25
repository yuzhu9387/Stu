"""The assembled application shares one scoped kitchen engine across HTTP and MCP."""

from uuid import uuid4

import httpx

from recipe_agent.api.dependencies import get_household_scope
from recipe_agent.app import create_app
from recipe_agent.config import Settings
from recipe_agent.domain.identity.service import HouseholdScope


async def test_registered_http_and_mcp_share_scope_and_revisions(session_factory):
    app = create_app(Settings(_env_file=None, environment="test"))
    app.state.session_factory = session_factory
    scope = HouseholdScope(uuid4(), uuid4())
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            assert (await client.get("/api/v1/kitchen")).status_code == 401
            app.dependency_overrides[get_household_scope] = lambda: scope
            state = (await client.get("/api/v1/kitchen")).json()
            assert state["revision"] == 0
            command = {
                "type": "tag.save",
                "payload": {"name": "家庭常用"},
                "expectedRevision": 0,
                "operationId": "api-tag",
            }
            result = await client.post("/api/v1/kitchen/commands", json=command)
            assert result.status_code == 200
            assert result.json()["state"]["revision"] == 1
            mcp = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {"name": "kitchen_read", "arguments": {}},
            }
            response = await client.post("/api/v1/kitchen/mcp", json=mcp)
            assert response.status_code == 200
            assert "家庭常用" in response.json()["result"]["content"][0]["text"]
            assert (
                await client.post(
                    "/api/v1/kitchen/mcp", content="{}", headers={"Content-Type": "text/plain"}
                )
            ).status_code == 415
            response = await client.post(
                "/api/v1/kitchen/commands", json={**command, "operationId": "stale"}
            )
            assert response.status_code == 409
            # Scope never comes from body parameters; a different authenticated scope is empty.
            scope = HouseholdScope(uuid4(), uuid4())
            assert (await client.get("/api/v1/kitchen")).json()["tags"] == []
    finally:
        await app.state.runtime.aclose()
