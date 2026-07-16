import json
from pathlib import Path
from uuid import uuid4

import pytest

from recipe_agent.api.lark import LarkWebhookHandler
from recipe_agent.domain.identity.locale import Locale
from recipe_agent.infrastructure.lark.normalizer import LarkEventNormalizer


def test_lark_v2_message_normalizes_without_transport_fields() -> None:
    fixture = Path(__file__).parent / "fixtures" / "message_v2.json"
    payload = json.loads(fixture.read_text(encoding="utf-8"))
    normalizer = LarkEventNormalizer(
        account_id=uuid4(), household_id=uuid4(), locale=Locale.EN_US
    )

    command = normalizer.normalize(payload)

    assert command.channel == "lark"
    assert command.idempotency_key == payload["header"]["event_id"]
    assert command.text == "Save this recipe"


class MemoryEventStore:
    def __init__(self) -> None:
        self.ids: set[str] = set()

    async def claim(self, event_id: str) -> bool:
        if event_id in self.ids:
            return False
        self.ids.add(event_id)
        return True


class RecordingPublisher:
    def __init__(self) -> None:
        self.commands: list[object] = []

    async def publish(self, command: object) -> None:
        self.commands.append(command)


@pytest.mark.asyncio
async def test_duplicate_event_is_acknowledged_and_published_once() -> None:
    fixture = Path(__file__).parent / "fixtures" / "message_v2.json"
    payload = json.loads(fixture.read_text(encoding="utf-8"))
    store = MemoryEventStore()
    publisher = RecordingPublisher()
    handler = LarkWebhookHandler(
        verification_token="verification-token",
        normalizer=LarkEventNormalizer(
            account_id=uuid4(), household_id=uuid4(), locale=Locale.EN_US
        ),
        event_store=store,
        publisher=publisher,
    )

    assert await handler.handle(payload) == {"status": "accepted"}
    assert await handler.handle(payload) == {"status": "accepted"}
    assert len(publisher.commands) == 1
