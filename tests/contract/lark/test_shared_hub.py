import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from recipe_agent.api.lark import LarkWebhookHandler
from recipe_agent.api.lark import router as lark_router
from recipe_agent.domain.conversation.actions import (
    ActionResult,
    InvalidSuggestedActionError,
    SuggestedActionConflictError,
    SuggestedActionNotFoundError,
)
from recipe_agent.domain.conversation.contracts import AgentRunView, ConversationCommand
from recipe_agent.domain.identity.locale import Locale
from recipe_agent.domain.identity.service import HouseholdScope, InvalidTokenError
from recipe_agent.infrastructure.lark.events import (
    LarkEventLease,
    LarkEventSubstitutionError,
)
from recipe_agent.infrastructure.lark.normalizer import LarkEventNormalizer
from recipe_agent.infrastructure.lark.service import LarkInboundService


def _message_payload() -> dict[str, object]:
    fixture = Path(__file__).parent / "fixtures" / "message_v2.json"
    return json.loads(fixture.read_text(encoding="utf-8"))


def _callback_payload(
    *, open_id: str, token: str, event_id: str = "evt_action_001"
) -> dict[str, object]:
    return {
        "schema": "2.0",
        "header": {
            "event_id": event_id,
            "event_type": "card.action.trigger",
            "token": "verification-token",
        },
        "event": {
            "operator": {
                "open_id": open_id,
                "tenant_key": "tenant",
            },
            "action": {"tag": "button", "value": {"token": token}},
            "host": "im_message",
            "token": "callback-token",
        },
    }


class IdentityResolver:
    def __init__(self, scopes: dict[str, HouseholdScope]) -> None:
        self.scopes = scopes
        self.link_codes: dict[str, HouseholdScope] = {}

    async def resolve_lark_identity(self, open_id: str) -> HouseholdScope | None:
        return self.scopes.get(open_id)

    async def link_lark_identity(self, code: str, open_id: str) -> object:
        try:
            scope = self.link_codes[code]
        except KeyError as error:
            raise InvalidTokenError("invalid") from error
        self.scopes[open_id] = scope
        return object()


class RecordingHub:
    def __init__(self) -> None:
        self.commands: list[ConversationCommand] = []

    async def submit_message(self, command: ConversationCommand) -> AgentRunView:
        self.commands.append(command)
        return AgentRunView(
            id=command.run_id,
            conversation_id=command.conversation_id or uuid4(),
            account_id=command.account_id,
            household_id=command.household_id,
            transport=command.transport,
            status="queued",
            created_at=datetime.now(UTC),
        )


class RecordingDeliveryQueue:
    def __init__(self) -> None:
        self.linking: list[tuple[str, Locale, str]] = []
        self.linked: list[tuple[str, Locale, str]] = []

    async def publish_linking_instructions(
        self, chat_id: str, locale: Locale, event_id: str
    ) -> bool:
        self.linking.append((chat_id, locale, event_id))
        return True

    async def publish_linked(self, chat_id: str, locale: Locale, event_id: str) -> bool:
        self.linked.append((chat_id, locale, event_id))
        return True


class RecordingEventStore:
    def __init__(self) -> None:
        self.events: dict[str, tuple[str, str]] = {}

    async def reserve(self, event_id: str, fingerprint_hash: str):
        existing = self.events.get(event_id)
        if existing is None:
            self.events[event_id] = (fingerprint_hash, "processing")
            return LarkEventLease(attempt_count=1)
        if existing[0] != fingerprint_hash:
            raise LarkEventSubstitutionError("Lark event ID content mismatch")
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


class BusyEventStore(RecordingEventStore):
    async def reserve(self, event_id: str, fingerprint_hash: str):
        del event_id, fingerprint_hash
        return "busy"


class RecordingActions:
    def __init__(self) -> None:
        self.calls: list[tuple[str, HouseholdScope]] = []
        self.replayed: set[str] = set()

    async def consume(self, token: str, *, actor: HouseholdScope) -> ActionResult:
        if token in self.replayed:
            raise SuggestedActionConflictError("already consumed")
        self.replayed.add(token)
        self.calls.append((token, actor))
        return ActionResult(
            action_id=uuid4(),
            type="save_recipe",
            status="queued",
        )


def _handler(
    *,
    scopes: dict[str, HouseholdScope],
    hub: RecordingHub,
    delivery: RecordingDeliveryQueue,
    actions: RecordingActions | None = None,
) -> LarkWebhookHandler:
    identity = IdentityResolver(scopes)
    inbound = LarkInboundService(
        identity=identity,
        hub=hub,
        delivery_queue=delivery,
        event_store=RecordingEventStore(),
        actions=actions or RecordingActions(),
    )
    return LarkWebhookHandler(
        verification_token="verification-token",
        normalizer=LarkEventNormalizer(),
        inbound=inbound,
    )


@pytest.mark.asyncio
async def test_one_time_link_command_binds_sender_without_submitting_code_to_hub() -> None:
    scope = HouseholdScope(uuid4(), uuid4())
    identity = IdentityResolver({})
    identity.link_codes["one-time-code"] = scope
    hub = RecordingHub()
    delivery = RecordingDeliveryQueue()
    inbound = LarkInboundService(
        identity=identity,
        hub=hub,
        delivery_queue=delivery,
        event_store=RecordingEventStore(),
        actions=RecordingActions(),
    )
    handler = LarkWebhookHandler(
        verification_token="verification-token",
        normalizer=LarkEventNormalizer(),
        inbound=inbound,
    )
    payload = _message_payload()
    event = payload["event"]
    assert isinstance(event, dict)
    message = event["message"]
    assert isinstance(message, dict)
    message["content"] = json.dumps({"text": "link one-time-code"})

    assert await handler.handle(payload) == {"status": "accepted"}

    assert await identity.resolve_lark_identity("ou_family_cook") == scope
    assert hub.commands == []
    assert delivery.linked == [("oc_family_chat", Locale.EN_US, "evt_recipe_001")]


@pytest.mark.asyncio
async def test_bound_lark_message_submits_exact_identity_to_shared_hub() -> None:
    scope = HouseholdScope(uuid4(), uuid4())
    hub = RecordingHub()
    delivery = RecordingDeliveryQueue()
    handler = _handler(scopes={"ou_family_cook": scope}, hub=hub, delivery=delivery)

    result = await handler.handle(_message_payload())

    assert result == {"status": "accepted"}
    assert len(hub.commands) == 1
    command = hub.commands[0]
    assert command.transport == "lark"
    assert command.account_id == scope.account_id
    assert command.household_id == scope.household_id
    assert command.reply_target == "oc_family_chat"
    assert command.idempotency_key == "evt_recipe_001"
    assert delivery.linking == []


@pytest.mark.asyncio
async def test_unbound_sender_only_queues_durable_linking_instructions() -> None:
    hub = RecordingHub()
    delivery = RecordingDeliveryQueue()
    handler = _handler(scopes={}, hub=hub, delivery=delivery)

    result = await handler.handle(_message_payload())

    assert result == {"status": "accepted"}
    assert hub.commands == []
    assert delivery.linking == [("oc_family_chat", Locale.EN_US, "evt_recipe_001")]


@pytest.mark.asyncio
async def test_card_callback_uses_clicking_open_id_and_same_action_service() -> None:
    actor = HouseholdScope(uuid4(), uuid4())
    actions = RecordingActions()
    handler = _handler(
        scopes={"ou_clicker": actor},
        hub=RecordingHub(),
        delivery=RecordingDeliveryQueue(),
        actions=actions,
    )

    result = await handler.handle(_callback_payload(open_id="ou_clicker", token="signed-consent"))

    assert result == {}
    assert actions.calls == [("signed-consent", actor)]


@pytest.mark.asyncio
async def test_card_callback_replay_is_acknowledged_without_second_mutation() -> None:
    actor = HouseholdScope(uuid4(), uuid4())
    actions = RecordingActions()
    handler = _handler(
        scopes={"ou_clicker": actor},
        hub=RecordingHub(),
        delivery=RecordingDeliveryQueue(),
        actions=actions,
    )
    payload = _callback_payload(open_id="ou_clicker", token="single-use")

    assert await handler.handle(payload) == {}
    assert await handler.handle(payload) == {}
    assert actions.calls == [("single-use", actor)]


@pytest.mark.asyncio
async def test_callback_event_id_cannot_be_reused_with_another_token() -> None:
    actor = HouseholdScope(uuid4(), uuid4())
    actions = RecordingActions()
    handler = _handler(
        scopes={"ou_clicker": actor},
        hub=RecordingHub(),
        delivery=RecordingDeliveryQueue(),
        actions=actions,
    )

    assert await handler.handle(
        _callback_payload(open_id="ou_clicker", token="first", event_id="evt_same")
    ) == {}
    assert await handler.handle(
        _callback_payload(open_id="ou_clicker", token="second", event_id="evt_same")
    ) == {}

    assert actions.calls == [("first", actor)]


class RejectingActions(RecordingActions):
    def __init__(self, error: Exception) -> None:
        super().__init__()
        self.error = error

    async def consume(self, token: str, *, actor: HouseholdScope) -> ActionResult:
        del token, actor
        raise self.error


@pytest.mark.parametrize(
    "error",
    (
        InvalidSuggestedActionError("expired private-token"),
        SuggestedActionNotFoundError("cross-account private-token"),
        SuggestedActionConflictError("replayed private-token"),
    ),
)
def test_card_callback_route_returns_lark_200_without_leaking_action_error(
    error: Exception,
) -> None:
    actor = HouseholdScope(uuid4(), uuid4())
    actions = RejectingActions(error)
    handler = _handler(
        scopes={"ou_clicker": actor},
        hub=RecordingHub(),
        delivery=RecordingDeliveryQueue(),
        actions=actions,
    )
    app = FastAPI()
    app.state.lark_handler = handler
    app.include_router(lark_router)

    response = TestClient(app).post(
        "/webhooks/lark/events",
        json=_callback_payload(open_id="ou_clicker", token="private-token"),
    )

    assert response.status_code == 200
    assert response.json() in ({}, {"toast": response.json().get("toast")})
    assert "private-token" not in response.text
    assert actions.calls == []


def test_live_event_lease_returns_retryable_response_instead_of_acknowledging() -> None:
    inbound = LarkInboundService(
        identity=IdentityResolver({}),
        hub=RecordingHub(),
        delivery_queue=RecordingDeliveryQueue(),
        event_store=BusyEventStore(),
        actions=RecordingActions(),
    )
    app = FastAPI()
    app.state.lark_handler = LarkWebhookHandler(
        verification_token="verification-token",
        normalizer=LarkEventNormalizer(),
        inbound=inbound,
    )
    app.include_router(lark_router)

    response = TestClient(app).post("/webhooks/lark/events", json=_message_payload())

    assert response.status_code == 503


@pytest.mark.asyncio
async def test_unbound_callback_cannot_queue_an_action() -> None:
    actions = RecordingActions()
    handler = _handler(
        scopes={},
        hub=RecordingHub(),
        delivery=RecordingDeliveryQueue(),
        actions=actions,
    )

    assert await handler.handle(
        _callback_payload(open_id="ou_unknown", token="private-token")
    ) == {}

    assert actions.calls == []


@pytest.mark.asyncio
async def test_callback_value_rejects_arguments_and_account_spoofing() -> None:
    payload = _callback_payload(open_id="ou_clicker", token="signed-consent")
    event = payload["event"]
    assert isinstance(event, dict)
    action = event["action"]
    assert isinstance(action, dict)
    action["value"] = {
        "token": "signed-consent",
        "account_id": str(uuid4()),
        "arguments": {"name": "spoofed"},
    }
    handler = _handler(
        scopes={"ou_clicker": HouseholdScope(uuid4(), uuid4())},
        hub=RecordingHub(),
        delivery=RecordingDeliveryQueue(),
    )

    with pytest.raises(ValueError, match="Unsupported Lark event"):
        await handler.handle(payload)
