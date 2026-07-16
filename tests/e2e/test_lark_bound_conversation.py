import json
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from recipe_agent.api.lark import LarkWebhookHandler
from recipe_agent.api.lark import router as lark_router
from recipe_agent.domain.conversation.actions import (
    SuggestedActionRepository,
    SuggestedActionService,
)
from recipe_agent.domain.conversation.hub import ConversationHub
from recipe_agent.domain.conversation.repository import (
    ACTION_EXECUTION_REQUESTED_TOPIC,
    LARK_RUN_COMPLETED_TOPIC,
    AgentRunRepository,
)
from recipe_agent.domain.conversation.responses import ActionArgument, SuggestedActionDraft
from recipe_agent.domain.identity.models import AgentRun, SuggestedActionRecord
from recipe_agent.domain.identity.service import HouseholdScope, IdentityService
from recipe_agent.infrastructure.db.outbox import OutboxEvent
from recipe_agent.infrastructure.lark.crypto import ActionContextSigner
from recipe_agent.infrastructure.lark.delivery import (
    LARK_LINKED_TOPIC,
    LARK_LINKING_INSTRUCTIONS_TOPIC,
    LarkDeliveryService,
    SqlLarkDeliveryQueue,
)
from recipe_agent.infrastructure.lark.events import SqlLarkEventStore
from recipe_agent.infrastructure.lark.normalizer import LarkEventNormalizer
from recipe_agent.infrastructure.lark.service import LarkInboundService


def _payload(*, event_id: str = "evt_recipe_001", open_id: str = "ou_family_cook") -> dict:
    fixture = Path(__file__).parents[1] / "contract" / "lark" / "fixtures" / "message_v2.json"
    payload = json.loads(fixture.read_text(encoding="utf-8"))
    payload["header"]["event_id"] = event_id
    payload["event"]["sender"]["sender_id"]["open_id"] = open_id
    return payload


def _handler(
    session_factory: async_sessionmaker[AsyncSession],
    identity: IdentityService,
    actions: SuggestedActionService | None = None,
) -> LarkWebhookHandler:
    event_store = SqlLarkEventStore(session_factory)
    inbound = LarkInboundService(
        identity=identity,
        hub=ConversationHub(AgentRunRepository(session_factory)),
        delivery_queue=SqlLarkDeliveryQueue(session_factory),
        event_store=event_store,
        actions=actions,
    )
    return LarkWebhookHandler(
        verification_token="verification-token",
        normalizer=LarkEventNormalizer(),
        inbound=inbound,
    )


class RecordingDeliveryClient:
    def __init__(self) -> None:
        self.finals: list[tuple] = []
        self.links: list[tuple] = []
        self.failures: list[tuple] = []

    async def send_final(self, chat_id, response, actions, locale, *, idempotency_key):
        self.finals.append((chat_id, response, actions, locale, idempotency_key))

    async def send_linking_instructions(self, chat_id, locale, *, idempotency_key):
        self.links.append((chat_id, locale, idempotency_key))

    async def send_linked(self, chat_id, locale, *, idempotency_key):
        self.links.append((chat_id, locale, idempotency_key))

    async def send_failure(self, chat_id, locale, *, idempotency_key):
        self.failures.append((chat_id, locale, idempotency_key))


@pytest.mark.asyncio
async def test_bound_lark_event_creates_one_private_run_through_shared_hub(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    identity = IdentityService(session_factory=session_factory)
    authenticated = await identity.consume_magic_link(
        (await identity.request_magic_link("lark-user@example.com")).token
    )
    link = await identity.create_lark_link_code(authenticated.account.id)
    await identity.link_lark_identity(link.code, "ou_family_cook")
    handler = _handler(session_factory, identity)

    assert await handler.handle(_payload()) == {"status": "accepted"}
    assert await handler.handle(_payload()) == {"status": "accepted"}

    async with session_factory() as session:
        runs = tuple((await session.scalars(select(AgentRun))).all())
    assert len(runs) == 1
    run = runs[0]
    request = json.loads(run.request_json)
    assert run.account_id == authenticated.account.id
    assert run.household_id == authenticated.household.id
    assert run.transport == "lark"
    assert request["reply_target"] == "oc_family_chat"
    assert request["locale"] == "en-US"


@pytest.mark.asyncio
async def test_lark_one_time_code_binds_existing_web_account_without_creating_run(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    identity = IdentityService(session_factory=session_factory)
    authenticated = await identity.consume_magic_link(
        (await identity.request_magic_link("bind-me@example.com")).token
    )
    link = await identity.create_lark_link_code(authenticated.account.id)
    payload = _payload(open_id="ou_new_link")
    payload["event"]["message"]["content"] = json.dumps({"text": f"link {link.code}"})

    assert await _handler(session_factory, identity).handle(payload) == {"status": "accepted"}

    resolved = await identity.resolve_lark_identity("ou_new_link")
    assert resolved is not None
    assert resolved.account_id == authenticated.account.id
    assert resolved.household_id == authenticated.household.id
    async with session_factory() as session:
        run_count = await session.scalar(select(func.count()).select_from(AgentRun))
        linked_events = tuple(
            (
                await session.scalars(
                    select(OutboxEvent).where(OutboxEvent.topic == LARK_LINKED_TOPIC)
                )
            ).all()
        )
    assert run_count == 0
    assert len(linked_events) == 1


@pytest.mark.asyncio
async def test_unbound_lark_event_commits_one_linking_delivery_intent(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    identity = IdentityService(session_factory=session_factory)
    handler = _handler(session_factory, identity)

    assert await handler.handle(_payload(open_id="ou_unbound")) == {"status": "accepted"}
    assert await handler.handle(_payload(open_id="ou_unbound")) == {"status": "accepted"}

    async with session_factory() as session:
        events = tuple(
            (
                await session.scalars(
                    select(OutboxEvent).where(
                        OutboxEvent.topic == LARK_LINKING_INSTRUCTIONS_TOPIC
                    )
                )
            ).all()
        )
        run_count = await session.scalar(select(func.count()).select_from(AgentRun))
    assert len(events) == 1
    assert events[0].payload == {
        "chat_id": "oc_family_chat",
        "locale": "en-US",
        "source_event_id": "evt_recipe_001",
    }
    assert run_count == 0

    client = RecordingDeliveryClient()
    await LarkDeliveryService(
        session_factory=session_factory,
        client=client,
    ).deliver_outbox(events[0].id)
    assert client.links == [("oc_family_chat", "en-US", str(events[0].id))]


@pytest.mark.asyncio
async def test_completing_lark_run_commits_delivery_intent_with_response(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    identity = IdentityService(session_factory=session_factory)
    authenticated = await identity.consume_magic_link(
        (await identity.request_magic_link("delivery@example.com")).token
    )
    link = await identity.create_lark_link_code(authenticated.account.id)
    await identity.link_lark_identity(link.code, "ou_family_cook")
    await _handler(session_factory, identity).handle(_payload())
    repository = AgentRunRepository(session_factory)

    async with session_factory() as session:
        run_id = await session.scalar(select(AgentRun.id))
    assert run_id is not None
    assert await repository.claim(run_id) is not None
    actions = SuggestedActionService(
        repository=SuggestedActionRepository(session_factory),
        signer=ActionContextSigner("delivery-signing-key"),
        handlers={},
    )
    issued = await actions.issue(
        SuggestedActionDraft(
            type="save_recipe",
            arguments=(
                ActionArgument(name="name", value_json='"Tomato soup"'),
                ActionArgument(name="ingredients", value_json="[]"),
                ActionArgument(name="steps", value_json="[]"),
            ),
        ),
        actor=HouseholdScope(authenticated.account.id, authenticated.household.id),
        source_run_id=run_id,
    )
    assert await repository.complete(
        run_id,
        {
            "thinking": "I understood your request.",
            "plan": "I checked your recipes.",
            "act": "I compared eligible options.",
            "answer": "Try tomato soup.",
            "suggested_actions": [issued.model_dump(mode="json")],
        },
    ) is not None

    async with session_factory() as session:
        events = tuple(
            (
                await session.scalars(
                    select(OutboxEvent).where(OutboxEvent.topic == LARK_RUN_COMPLETED_TOPIC)
                )
            ).all()
        )
        stored_run = await session.get(AgentRun, run_id)
    assert len(events) == 1
    assert events[0].payload == {"run_id": str(run_id)}
    assert stored_run is not None
    assert issued.token not in (stored_run.response_json or "")

    client = RecordingDeliveryClient()
    await LarkDeliveryService(
        session_factory=session_factory,
        client=client,
        actions=actions,
    ).deliver_outbox(events[0].id)
    assert len(client.finals) == 1
    chat_id, response, delivered_actions, locale, key = client.finals[0]
    assert chat_id == "oc_family_chat"
    assert response.answer == "Try tomato soup."
    assert len(delivered_actions) == 1
    assert delivered_actions[0].token == issued.token
    assert locale == "en-US"
    assert key == str(events[0].id)

    await LarkDeliveryService(
        session_factory=session_factory,
        client=client,
        actions=actions,
    ).deliver_outbox(events[0].id)
    assert len(client.finals) == 1


@pytest.mark.asyncio
async def test_documented_callback_route_queues_real_suggested_action_once(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    identity = IdentityService(session_factory=session_factory)
    authenticated = await identity.consume_magic_link(
        (await identity.request_magic_link("callback@example.com")).token
    )
    link = await identity.create_lark_link_code(authenticated.account.id)
    await identity.link_lark_identity(link.code, "ou_callback_user")
    await _handler(session_factory, identity).handle(
        _payload(open_id="ou_callback_user", event_id="evt_source_run")
    )
    async with session_factory() as session:
        run_id = await session.scalar(select(AgentRun.id))
    assert run_id is not None
    actions = SuggestedActionService(
        repository=SuggestedActionRepository(session_factory),
        signer=ActionContextSigner("callback-signing-key"),
        handlers={},
    )
    issued = await actions.issue(
        SuggestedActionDraft(
            type="save_recipe",
            arguments=(
                ActionArgument(name="name", value_json='"Soup"'),
                ActionArgument(name="ingredients", value_json="[]"),
                ActionArgument(name="steps", value_json="[]"),
            ),
        ),
        actor=HouseholdScope(authenticated.account.id, authenticated.household.id),
        source_run_id=run_id,
    )
    app = FastAPI()
    app.state.lark_handler = _handler(session_factory, identity, actions)
    app.include_router(lark_router)
    callback = {
        "schema": "2.0",
        "header": {
            "event_id": "evt_real_callback",
            "event_type": "card.action.trigger",
            "token": "verification-token",
        },
        "event": {
            "operator": {"open_id": "ou_callback_user"},
            "action": {"tag": "button", "value": {"token": issued.token}},
        },
    }

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        first = await client.post("/webhooks/lark/events", json=callback)
        second = await client.post("/webhooks/lark/events", json=callback)

    assert first.status_code == second.status_code == 200
    assert first.json() == second.json() == {}
    async with session_factory() as session:
        action = await session.get(SuggestedActionRecord, issued.id)
        queued_events = tuple(
            await session.scalars(
                select(OutboxEvent).where(
                    OutboxEvent.topic == ACTION_EXECUTION_REQUESTED_TOPIC
                )
            )
        )
    assert action is not None and action.execution_status == "queued"
    assert len(queued_events) == 1
