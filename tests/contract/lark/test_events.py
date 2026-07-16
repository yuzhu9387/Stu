import json
from pathlib import Path
from uuid import uuid4

import pytest

from recipe_agent.api.lark import LarkWebhookHandler
from recipe_agent.domain.conversation.contracts import AgentRunView, ConversationCommand
from recipe_agent.domain.identity.service import HouseholdScope
from recipe_agent.infrastructure.lark.crypto import LarkCipher
from recipe_agent.infrastructure.lark.events import LarkEventLease
from recipe_agent.infrastructure.lark.normalizer import LarkEventNormalizer, NormalizedLarkMessage
from recipe_agent.infrastructure.lark.service import LarkInboundService


def test_lark_v2_message_normalizes_without_transport_fields() -> None:
    fixture = Path(__file__).parent / "fixtures" / "message_v2.json"
    payload = json.loads(fixture.read_text(encoding="utf-8"))
    normalizer = LarkEventNormalizer()

    event = normalizer.normalize(payload)
    assert isinstance(event, NormalizedLarkMessage)
    command = event.to_command(HouseholdScope(uuid4(), uuid4()))

    assert command.channel == "lark"
    assert command.idempotency_key == payload["header"]["event_id"]
    assert command.text == "Save this recipe"
    assert command.allow_conversation_creation is True


def test_lark_v2_message_accepts_documented_transport_metadata() -> None:
    fixture = Path(__file__).parent / "fixtures" / "message_v2.json"
    payload = json.loads(fixture.read_text(encoding="utf-8"))
    payload["header"].update({"app_id": "cli_app", "tenant_key": "tenant"})
    payload["event"]["sender"].update({"sender_type": "user", "tenant_key": "tenant"})
    payload["event"]["message"].update({"create_time": "1720000000000", "chat_type": "p2p"})

    event = LarkEventNormalizer().normalize(payload)

    assert isinstance(event, NormalizedLarkMessage)
    assert event.open_id == "ou_family_cook"


class MemoryEventStore:
    def __init__(self) -> None:
        self.events: dict[str, tuple[str, str]] = {}

    async def reserve(self, event_id: str, fingerprint_hash: str):
        existing = self.events.get(event_id)
        if existing is None:
            self.events[event_id] = (fingerprint_hash, "processing")
            return LarkEventLease(attempt_count=1)
        if existing[0] != fingerprint_hash:
            raise ValueError("Lark event ID content mismatch")
        return "duplicate" if existing[1] == "accepted" else "busy"

    async def accept(
        self,
        event_id: str,
        fingerprint_hash: str,
        outcome: str,
        *,
        attempt_count: int,
    ) -> bool:
        del outcome, attempt_count
        self.events[event_id] = (fingerprint_hash, "accepted")
        return True


class RecordingSubmitter:
    def __init__(self) -> None:
        self.commands: list[ConversationCommand] = []

    async def submit_message(self, command: ConversationCommand) -> AgentRunView:
        self.commands.append(command)
        return AgentRunView.model_construct()


class StaticIdentity:
    def __init__(self, scope: HouseholdScope) -> None:
        self.scope = scope

    async def resolve_lark_identity(self, open_id: str) -> HouseholdScope | None:
        return self.scope


class UnusedDelivery:
    async def publish_linking_instructions(self, chat_id, locale, event_id, **kwargs):
        del kwargs
        raise AssertionError("bound sender must not queue linking guidance")


def handler_for(
    submitter: RecordingSubmitter,
    *,
    cipher: LarkCipher | None = None,
) -> LarkWebhookHandler:
    store = MemoryEventStore()
    inbound = LarkInboundService(
        identity=StaticIdentity(HouseholdScope(uuid4(), uuid4())),
        hub=submitter,
        delivery_queue=UnusedDelivery(),
        event_store=store,
        actions=None,
    )
    return LarkWebhookHandler(
        verification_token="verification-token",
        cipher=cipher,
        normalizer=LarkEventNormalizer(),
        inbound=inbound,
    )


@pytest.mark.asyncio
async def test_valid_event_reaches_shared_submitter() -> None:
    fixture = Path(__file__).parent / "fixtures" / "message_v2.json"
    payload = json.loads(fixture.read_text(encoding="utf-8"))
    submitter = RecordingSubmitter()
    handler = handler_for(submitter)

    assert await handler.handle(payload) == {"status": "accepted"}
    assert len(submitter.commands) == 1


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
    submitter = RecordingSubmitter()
    handler = handler_for(submitter, cipher=LarkCipher("test-encrypt-key"))

    assert await handler.handle({"encrypt": encrypted}) == {"status": "accepted"}
    assert len(submitter.commands) == 1


@pytest.mark.asyncio
async def test_url_verification_returns_challenge_without_submitting() -> None:
    submitter = RecordingSubmitter()
    handler = handler_for(submitter)

    result = await handler.handle(
        {
            "type": "url_verification",
            "token": "verification-token",
            "challenge": "challenge-value",
        }
    )

    assert result == {"challenge": "challenge-value"}
    assert submitter.commands == []


@pytest.mark.asyncio
async def test_invalid_verification_token_is_rejected_before_submitting() -> None:
    fixture = Path(__file__).parent / "fixtures" / "message_v2.json"
    payload = json.loads(fixture.read_text(encoding="utf-8"))
    payload["header"]["token"] = "wrong-token"
    submitter = RecordingSubmitter()
    handler = handler_for(submitter)

    with pytest.raises(PermissionError):
        await handler.handle(payload)

    assert submitter.commands == []
