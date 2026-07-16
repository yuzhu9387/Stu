import json
from uuid import uuid4

import httpx
import pytest

from recipe_agent.domain.conversation.contracts import AgentProgress, AgentStage
from recipe_agent.domain.identity.locale import Locale, Translator
from recipe_agent.infrastructure.lark.client import LarkClient
from recipe_agent.infrastructure.lark.renderer import LarkCardRenderer


class StaticTokenProvider:
    async def tenant_access_token(self) -> str:
        return "tenant-token"


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
