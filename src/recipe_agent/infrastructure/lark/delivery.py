"""Durable Lark delivery intents and completion rendering."""

import json
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict, ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from recipe_agent.domain.conversation.actions import IssuedSuggestedAction
from recipe_agent.domain.conversation.repository import LARK_RUN_COMPLETED_TOPIC
from recipe_agent.domain.conversation.responses import FinalAgentResponse
from recipe_agent.domain.identity.locale import Locale
from recipe_agent.domain.identity.models import AgentRun
from recipe_agent.domain.identity.service import HouseholdScope
from recipe_agent.infrastructure.db.outbox import OutboxRepository
from recipe_agent.infrastructure.lark.events import (
    SqlLarkDeliveryStore,
    add_lark_delivery_intent,
)

LARK_LINKING_INSTRUCTIONS_TOPIC = "lark.linking_instructions.requested"
LARK_LINKED_TOPIC = "lark.linked.requested"


class _CompletedResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    thinking: str
    plan: str
    act: str
    answer: str
    suggested_actions: tuple["_SuggestedActionReference", ...]

    @property
    def final(self) -> FinalAgentResponse:
        return FinalAgentResponse(
            thinking=self.thinking,
            plan=self.plan,
            act=self.act,
            answer=self.answer,
            suggested_actions=(),
        )


class _SuggestedActionReference(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: UUID
    type: str
    expires_at: str


@dataclass(frozen=True)
class _RunDelivery:
    id: UUID
    account_id: UUID
    household_id: UUID
    status: str
    request_json: str
    response_json: str | None


class LarkDeliveryActions(Protocol):
    async def reissue_for_delivery(
        self,
        action_ids: tuple[UUID, ...],
        *,
        actor: HouseholdScope,
        source_run_id: UUID,
    ) -> tuple[IssuedSuggestedAction, ...]: ...


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
        self._session_factory = session_factory
        self._outbox = OutboxRepository()

    async def publish_linking_instructions(
        self,
        chat_id: str,
        locale: Locale,
        event_id: str,
    ) -> bool:
        return await self._publish_once(
            topic=LARK_LINKING_INSTRUCTIONS_TOPIC,
            payload={"chat_id": chat_id, "locale": locale.value, "source_event_id": event_id},
            dedupe_key=f"event:{event_id}:identity_response",
        )

    async def publish_linked(
        self,
        chat_id: str,
        locale: Locale,
        event_id: str,
    ) -> bool:
        return await self._publish_once(
            topic=LARK_LINKED_TOPIC,
            payload={"chat_id": chat_id, "locale": locale.value, "source_event_id": event_id},
            dedupe_key=f"event:{event_id}:identity_response",
        )

    async def _publish_once(
        self, *, topic: str, payload: dict[str, str], dedupe_key: str
    ) -> bool:
        async with self._session_factory() as session, session.begin():
            try:
                async with session.begin_nested():
                    await add_lark_delivery_intent(
                        session,
                        self._outbox,
                        topic=topic,
                        payload=payload,
                        dedupe_key=dedupe_key,
                    )
            except IntegrityError:
                return False
            return True


class LarkDeliveryService:
    """Load a durable outbox intent and perform one idempotent Lark send."""

    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        client: LarkDeliveryClient,
        actions: LarkDeliveryActions | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._client = client
        self._actions = actions
        self._deliveries = SqlLarkDeliveryStore(session_factory)

    async def deliver_outbox(self, event_id: UUID) -> None:
        claimed = await self._deliveries.claim(event_id)
        if claimed is None:
            return
        try:
            payload = claimed.payload
            if claimed.topic == LARK_LINKING_INSTRUCTIONS_TOPIC:
                await self._client.send_linking_instructions(
                    _required_string(payload, "chat_id"),
                    Locale(_required_string(payload, "locale")),
                    idempotency_key=str(claimed.event_id),
                )
            elif claimed.topic == LARK_LINKED_TOPIC:
                await self._client.send_linked(
                    _required_string(payload, "chat_id"),
                    Locale(_required_string(payload, "locale")),
                    idempotency_key=str(claimed.event_id),
                )
            elif claimed.topic == LARK_RUN_COMPLETED_TOPIC:
                await self._deliver_run(claimed.event_id, payload)
            else:
                raise ValueError("Unsupported Lark delivery topic")
        except Exception as error:
            await self._deliveries.mark_retry(
                event_id,
                attempt_count=claimed.attempt_count,
                error_code=type(error).__name__,
            )
            raise
        await self._deliveries.mark_delivered(
            event_id, attempt_count=claimed.attempt_count
        )

    async def _deliver_run(self, event_id: UUID, payload: object) -> None:
        run_id = UUID(_required_string(payload, "run_id"))
        async with self._session_factory() as session:
            run = await session.scalar(
                select(AgentRun).where(AgentRun.id == run_id, AgentRun.transport == "lark")
            )
            if run is None:
                raise LookupError("Lark run not found")
            delivery = _RunDelivery(
                id=run.id,
                account_id=run.account_id,
                household_id=run.household_id,
                status=run.status,
                request_json=run.request_json,
                response_json=run.response_json,
            )
        request = _json_object(delivery.request_json, "Lark run request")
        chat_id = _required_string(request, "reply_target")
        locale = Locale(_required_string(request, "locale"))
        if delivery.status == "failed":
            await self._client.send_failure(
                chat_id,
                locale,
                idempotency_key=str(event_id),
            )
            return
        if delivery.status != "completed" or delivery.response_json is None:
            raise ValueError("Lark run is not terminal")
        try:
            response = _CompletedResponse.model_validate(
                _json_object(delivery.response_json, "Lark run response")
            )
        except ValidationError:
            raise ValueError("Lark run response is invalid") from None
        action_ids = tuple(action.id for action in response.suggested_actions[:3])
        if action_ids and self._actions is None:
            raise RuntimeError("Suggested action delivery is not configured")
        actions = (
            await self._actions.reissue_for_delivery(
                action_ids,
                actor=HouseholdScope(delivery.account_id, delivery.household_id),
                source_run_id=delivery.id,
            )
            if self._actions is not None
            else ()
        )
        await self._client.send_final(
            chat_id,
            response.final,
            actions,
            locale,
            idempotency_key=str(event_id),
        )


def _json_object(value: str, label: str) -> dict[str, object]:
    try:
        decoded = json.loads(value)
    except json.JSONDecodeError:
        raise ValueError(f"{label} is invalid") from None
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
