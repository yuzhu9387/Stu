"""Identity-aware Lark inbound application service."""

from contextlib import suppress
from typing import Protocol

from recipe_agent.domain.conversation.actions import (
    ActionResult,
    SuggestedActionConflictError,
    SuggestedActionNotFoundError,
)
from recipe_agent.domain.conversation.contracts import AgentRunView, ConversationCommand
from recipe_agent.domain.identity.locale import Locale
from recipe_agent.domain.identity.service import (
    HouseholdScope,
    IdentityConflictError,
    InvalidTokenError,
)
from recipe_agent.infrastructure.lark.normalizer import (
    NormalizedLarkAction,
    NormalizedLarkEvent,
    NormalizedLarkMessage,
)


class LarkIdentityResolver(Protocol):
    async def resolve_lark_identity(self, open_id: str) -> HouseholdScope | None: ...

    async def link_lark_identity(self, code: str, open_id: str) -> object: ...


class ConversationSubmitter(Protocol):
    async def submit_message(self, command: ConversationCommand) -> AgentRunView: ...


class LarkDeliveryQueue(Protocol):
    async def publish_linking_instructions(
        self,
        chat_id: str,
        locale: Locale,
        event_id: str,
    ) -> bool: ...

    async def publish_linked(
        self,
        chat_id: str,
        locale: Locale,
        event_id: str,
    ) -> bool: ...


class LarkEventStore(Protocol):
    async def claim(self, event_id: str) -> bool: ...

    async def is_claimed(self, event_id: str) -> bool: ...


class SuggestedActionConsumer(Protocol):
    async def consume(self, token: str, *, actor: HouseholdScope) -> ActionResult: ...


class LarkInboundService:
    """Resolve the actual Lark actor before using shared application services."""

    def __init__(
        self,
        *,
        identity: LarkIdentityResolver,
        hub: ConversationSubmitter,
        delivery_queue: LarkDeliveryQueue,
        event_store: LarkEventStore,
        actions: SuggestedActionConsumer | None,
    ) -> None:
        self._identity = identity
        self._hub = hub
        self._delivery_queue = delivery_queue
        self._event_store = event_store
        self._actions = actions

    async def receive(self, event: NormalizedLarkEvent) -> None:
        if isinstance(event, NormalizedLarkMessage):
            await self._receive_message(event)
            return
        if isinstance(event, NormalizedLarkAction):
            await self._receive_action(event)
            return
        raise TypeError("Unsupported normalized Lark event")

    async def _receive_message(self, event: NormalizedLarkMessage) -> None:
        scope = await self._identity.resolve_lark_identity(event.open_id)
        link_code = _link_code(event.text)
        if link_code is not None:
            if scope is None:
                try:
                    await self._identity.link_lark_identity(link_code, event.open_id)
                except (InvalidTokenError, IdentityConflictError):
                    await self._delivery_queue.publish_linking_instructions(
                        event.chat_id,
                        event.locale,
                        event.event_id,
                    )
                    return
            await self._delivery_queue.publish_linked(
                event.chat_id,
                event.locale,
                event.event_id,
            )
            return
        if scope is None:
            await self._delivery_queue.publish_linking_instructions(
                event.chat_id,
                event.locale,
                event.event_id,
            )
            return
        # ConversationHub's persisted transport/idempotency key is the durable replay guard.
        await self._hub.submit_message(event.to_command(scope))
        await self._event_store.claim(event.event_id)

    async def _receive_action(self, event: NormalizedLarkAction) -> None:
        if self._actions is None:
            raise SuggestedActionNotFoundError("Suggested action service is unavailable")
        if await self._event_store.is_claimed(event.event_id):
            return
        scope = await self._identity.resolve_lark_identity(event.open_id)
        if scope is None:
            raise SuggestedActionNotFoundError("Suggested action not found")
        # The consent token itself is the durable single-use replay guard.
        with suppress(SuggestedActionConflictError):
            await self._actions.consume(event.token, actor=scope)
        await self._event_store.claim(event.event_id)


def _link_code(text: str) -> str | None:
    parts = text.strip().split(maxsplit=1)
    if len(parts) != 2 or parts[0].casefold() not in {"link", "绑定"}:
        return None
    code = parts[1].strip()
    return code or None


__all__ = ["LarkInboundService"]
