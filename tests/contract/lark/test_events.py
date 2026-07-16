import json
from pathlib import Path
from uuid import uuid4

import pytest

from recipe_agent.api.lark import LarkWebhookHandler
from recipe_agent.domain.identity.locale import Locale
from recipe_agent.infrastructure.lark.crypto import LarkCipher
from recipe_agent.infrastructure.lark.normalizer import LarkEventNormalizer


def test_lark_v2_message_normalizes_without_transport_fields() -> None:
    fixture = Path(__file__).parent / "fixtures" / "message_v2.json"
    payload = json.loads(fixture.read_text(encoding="utf-8"))
    normalizer = LarkEventNormalizer(account_id=uuid4(), household_id=uuid4(), locale=Locale.EN_US)

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


@pytest.mark.asyncio
async def test_encrypted_event_is_decrypted_before_verification_and_normalization() -> None:
    encrypted = (
        "kS14Aix3+Av1N/i2qiqJJWqYMuHMbG5m34/uHzWDDFR/r5me2DxKuUDoQfW2mFDNSkGC5KbgMi7ch+7l"
        "EQ8CDxJK0rb5M1AxL5EoJRYB1dF4Lfq9ZOIUm1wmTedoznE5CQzv5ge0DIoAVXcye848cXf9DUrZdaNrwWN4"
        "ZfCwfZki+DMjviU5OXXWeGTvaD6Gb9/JNIUH2650GS+RBrQnjo/nRf8XIfPMQmxm3Fn4A21JAeiFfVGx/2lS"
        "WI/CgwP8Anh61xAM2a7YmDuxliu0HJxUSOz/8BPPbyyaJLPT+bQhy3t3Ez/q5eoWvL/ANFKoQbWAszRl9sd9"
        "15vKqMXYVs3U4W4Hjn2buuzQZAKi2IGbuFQT3aLm0VJdi7fs5KU6gfUC/JTJGPkbq+ZZTr9V+O3t5RgbGyi"
        "0kQWuGt8YnfDwuujzeLHc2f87jX8nHDvMRFL44ALIrBnQa/j6zF2+NviV1E8FhozCMSVFNfRbqJOv4I+fz1"
        "aKZQ4Ggv0Fn5aB0Ynkpm7lcZ/C7pUTfZQX0jjnXu7wC+GEs32n0iv52o0="
    )
    publisher = RecordingPublisher()
    handler = LarkWebhookHandler(
        verification_token="verification-token",
        cipher=LarkCipher("test-encrypt-key"),
        normalizer=LarkEventNormalizer(
            account_id=uuid4(), household_id=uuid4(), locale=Locale.EN_US
        ),
        event_store=MemoryEventStore(),
        publisher=publisher,
    )

    assert await handler.handle({"encrypt": encrypted}) == {"status": "accepted"}
    assert len(publisher.commands) == 1


@pytest.mark.asyncio
async def test_url_verification_returns_challenge_without_publishing() -> None:
    publisher = RecordingPublisher()
    handler = LarkWebhookHandler(
        verification_token="verification-token",
        normalizer=LarkEventNormalizer(
            account_id=uuid4(), household_id=uuid4(), locale=Locale.EN_US
        ),
        event_store=MemoryEventStore(),
        publisher=publisher,
    )

    result = await handler.handle(
        {
            "type": "url_verification",
            "token": "verification-token",
            "challenge": "challenge-value",
        }
    )

    assert result == {"challenge": "challenge-value"}
    assert publisher.commands == []


@pytest.mark.asyncio
async def test_invalid_verification_token_is_rejected_before_publishing() -> None:
    fixture = Path(__file__).parent / "fixtures" / "message_v2.json"
    payload = json.loads(fixture.read_text(encoding="utf-8"))
    payload["header"]["token"] = "wrong-token"
    publisher = RecordingPublisher()
    handler = LarkWebhookHandler(
        verification_token="verification-token",
        normalizer=LarkEventNormalizer(
            account_id=uuid4(), household_id=uuid4(), locale=Locale.EN_US
        ),
        event_store=MemoryEventStore(),
        publisher=publisher,
    )

    with pytest.raises(PermissionError):
        await handler.handle(payload)

    assert publisher.commands == []
