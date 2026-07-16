"""Durable Lark delivery intents and completion rendering."""

import json
from typing import Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict, ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from recipe_agent.domain.conversation.actions import IssuedSuggestedAction
from recipe_agent.domain.conversation.repository import LARK_RUN_COMPLETED_TOPIC
from recipe_agent.domain.conversation.responses import FinalAgentResponse
from recipe_agent.domain.identity.locale import Locale
from recipe_agent.domain.identity.models import AgentRun
from recipe_agent.infrastructure.db.outbox import OutboxEvent
from recipe_agent.infrastructure.lark.events import SqlLarkEventStore

LARK_LINKING_INSTRUCTIONS_TOPIC = "lark.linking_instructions.requested"
LARK_LINKED_TOPIC = "lark.linked.requested"


class _CompletedResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    thinking: str
    plan: str
    act: str
    answer: str
    suggested_actions: tuple[IssuedSuggestedAction, ...]

    @property
    def final(self) -> FinalAgentResponse:
        return FinalAgentResponse(
            thinking=self.thinking,
            plan=self.plan,
            act=self.act,
            answer=self.answer,
            suggested_actions=(),
        )


class LarkDeliveryClient(Protocol):
    async def send_final(
        self,
        chat_id: str,
        response: FinalAgentResponse,
        actions: tuple[IssuedSuggestedAction, ...],
        locale: Locale,
        *,
        idempotency_key: str,
    ) -> None: ...

    async def send_linking_instructions(
        self,
        chat_id: str,
        locale: Locale,
        *,
        idempotency_key: str,
    ) -> None: ...

    async def send_linked(
        self,
        chat_id: str,
        locale: Locale,
        *,
        idempotency_key: str,
    ) -> None: ...

    async def send_failure(
        self,
        chat_id: str,
        locale: Locale,
        *,
        idempotency_key: str,
    ) -> None: ...


class SqlLarkDeliveryQueue:
    """Queue unlinked guidance once in the event-receipt transaction."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._events = SqlLarkEventStore(session_factory)

    async def publish_linking_instructions(
        self,
        chat_id: str,
        locale: Locale,
        event_id: str,
    ) -> bool:
        return await self._events.claim_with_outbox(
            event_id,
            topic=LARK_LINKING_INSTRUCTIONS_TOPIC,
            payload={
                "chat_id": chat_id,
                "locale": locale.value,
                "source_event_id": event_id,
            },
        )

    async def publish_linked(
        self,
        chat_id: str,
        locale: Locale,
        event_id: str,
    ) -> bool:
        return await self._events.claim_with_outbox(
            event_id,
            topic=LARK_LINKED_TOPIC,
            payload={
                "chat_id": chat_id,
                "locale": locale.value,
                "source_event_id": event_id,
            },
        )


class LarkDeliveryService:
    """Load a durable outbox intent and perform one idempotent Lark send."""

    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        client: LarkDeliveryClient,
    ) -> None:
        self._session_factory = session_factory
        self._client = client

    async def deliver_outbox(self, event_id: UUID) -> None:
        async with self._session_factory() as session:
            event = await session.get(OutboxEvent, event_id)
            if event is None:
                raise LookupError("Lark delivery intent not found")
            payload = event.payload
            if event.topic == LARK_LINKING_INSTRUCTIONS_TOPIC:
                await self._client.send_linking_instructions(
                    _required_string(payload, "chat_id"),
                    Locale(_required_string(payload, "locale")),
                    idempotency_key=str(event.id),
                )
                return
            if event.topic == LARK_LINKED_TOPIC:
                await self._client.send_linked(
                    _required_string(payload, "chat_id"),
                    Locale(_required_string(payload, "locale")),
                    idempotency_key=str(event.id),
                )
                return
            if event.topic != LARK_RUN_COMPLETED_TOPIC:
                raise ValueError("Unsupported Lark delivery topic")
            run_id = UUID(_required_string(payload, "run_id"))
            run = await session.scalar(
                select(AgentRun).where(AgentRun.id == run_id, AgentRun.transport == "lark")
            )
            if run is None:
                raise LookupError("Lark run not found")
            request = _json_object(run.request_json, "Lark run request")
            chat_id = _required_string(request, "reply_target")
            locale = Locale(_required_string(request, "locale"))
            if run.status == "failed":
                await self._client.send_failure(
                    chat_id,
                    locale,
                    idempotency_key=str(event.id),
                )
                return
            if run.status != "completed" or run.response_json is None:
                raise ValueError("Lark run is not terminal")
            try:
                response = _CompletedResponse.model_validate(
                    _json_object(run.response_json, "Lark run response")
                )
            except ValidationError as error:
                raise ValueError("Lark run response is invalid") from error
            await self._client.send_final(
                chat_id,
                response.final,
                response.suggested_actions[:3],
                locale,
                idempotency_key=str(event.id),
            )


def _json_object(value: str, label: str) -> dict[str, object]:
    try:
        decoded = json.loads(value)
    except json.JSONDecodeError as error:
        raise ValueError(f"{label} is invalid") from error
    if not isinstance(decoded, dict):
        raise ValueError(f"{label} is invalid")
    return decoded


def _required_string(payload: object, key: str) -> str:
    if not isinstance(payload, dict):
        raise ValueError("Lark delivery payload is invalid")
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError("Lark delivery payload is invalid")
    return value


__all__ = [
    "LARK_LINKED_TOPIC",
    "LARK_LINKING_INSTRUCTIONS_TOPIC",
    "LarkDeliveryService",
    "SqlLarkDeliveryQueue",
]
