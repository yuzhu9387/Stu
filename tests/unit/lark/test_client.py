import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import httpx
import pytest

from recipe_agent.domain.conversation.actions import IssuedSuggestedAction
from recipe_agent.domain.conversation.contracts import AgentProgress, AgentStage
from recipe_agent.domain.conversation.responses import FinalAgentResponse
from recipe_agent.domain.identity.locale import Locale, Translator
from recipe_agent.infrastructure.lark.client import LarkAPIError, LarkClient
from recipe_agent.infrastructure.lark.renderer import LarkCardRenderer


class StaticTokenProvider:
    async def tenant_access_token(self) -> str:
        return "tenant-token"

    async def invalidate(self, token: str) -> None:
        del token


@pytest.mark.asyncio
async def test_client_sends_localized_progress_card_to_lark_international() -> None:
    requests: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"code": 0, "data": {}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http:
        client = LarkClient(
            http=http,
            token_provider=StaticTokenProvider(),
            renderer=LarkCardRenderer(Translator.from_package()),
        )
        progress = AgentProgress(
            run_id=uuid4(),
            stage=AgentStage.ACTING,
            message_key="agent.stage.acting",
            values={"tool": "save_recipe"},
        )

        await client.send_progress("oc_family_chat", progress, Locale.EN_US)

    request = requests[0]
    body = json.loads(request.content)
    card = json.loads(body["content"])
    assert str(request.url).startswith("https://open.larksuite.com/open-apis/im/v1/messages")
    assert request.headers["Authorization"] == "Bearer tenant-token"
    assert body["receive_id"] == "oc_family_chat"
    assert card["elements"][0]["text"]["content"] == "Acting: running save_recipe."


@pytest.mark.asyncio
async def test_client_sends_one_final_card_with_signed_action_value() -> None:
    requests: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"code": 0, "data": {}})

    response = FinalAgentResponse(
        thinking="I understood your request.",
        plan="I checked your recipes.",
        act="I compared the choices.",
        answer="Try soup.",
        suggested_actions=(),
    )
    action = IssuedSuggestedAction(
        id=uuid4(),
        type="save_recipe",
        token="opaque-signed-token",
        expires_at=datetime.now(UTC) + timedelta(minutes=15),
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http:
        client = LarkClient(
            http=http,
            token_provider=StaticTokenProvider(),
            renderer=LarkCardRenderer(Translator.from_package()),
        )
        await client.send_final("oc_family_chat", response, (action,), Locale.EN_US)

    assert len(requests) == 1
    body = json.loads(requests[0].content)
    card = json.loads(body["content"])
    assert "opaque-signed-token" not in str(requests[0].url)
    assert any(
        element.get("actions", [{}])[0].get("value") == {"token": "opaque-signed-token"}
        for element in card["elements"]
        if element.get("tag") == "action"
    )


@pytest.mark.asyncio
async def test_client_failure_does_not_expose_provider_body_or_tenant_token() -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"code": 230001, "msg": "private provider payload tenant-token"},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http:
        client = LarkClient(
            http=http,
            token_provider=StaticTokenProvider(),
            renderer=LarkCardRenderer(Translator.from_package()),
        )
        with pytest.raises(LarkAPIError) as caught:
            await client.send_linking_instructions(
                "oc_family_chat",
                Locale.EN_US,
                idempotency_key=str(uuid4()),
            )

    assert str(caught.value) == "Lark message delivery failed"
    assert "tenant-token" not in str(caught.value)


@pytest.mark.asyncio
async def test_client_refreshes_rejected_tenant_token_once() -> None:
    requests: list[httpx.Request] = []

    class RotatingTokenProvider:
        def __init__(self) -> None:
            self.token = "expired-token"
            self.invalidated: list[str] = []

        async def tenant_access_token(self) -> str:
            return self.token

        async def invalidate(self, token: str) -> None:
            self.invalidated.append(token)
            if self.token == token:
                self.token = "fresh-token"

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.headers["Authorization"] == "Bearer expired-token":
            return httpx.Response(401, json={"code": 99991663})
        return httpx.Response(200, json={"code": 0, "data": {}})

    provider = RotatingTokenProvider()
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http:
        client = LarkClient(
            http=http,
            token_provider=provider,
            renderer=LarkCardRenderer(Translator.from_package()),
        )
        await client.send_linking_instructions(
            "oc_family_chat", Locale.EN_US, idempotency_key="stable-delivery-id"
        )

    assert provider.invalidated == ["expired-token"]
    assert [request.headers["Authorization"] for request in requests] == [
        "Bearer expired-token",
        "Bearer fresh-token",
    ]
    assert [json.loads(request.content)["uuid"] for request in requests] == [
        "stable-delivery-id",
        "stable-delivery-id",
    ]
