"""Identity-aware Lark inbound application service."""

from typing import Protocol

from recipe_agent.domain.conversation.actions import (
    ActionResult,
    InvalidSuggestedActionError,
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
from recipe_agent.infrastructure.lark.events import (
    LarkEventBusyError,
    LarkEventLease,
    LarkEventReservation,
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
    async def reserve(
        self, event_id: str, fingerprint_hash: str
    ) -> LarkEventReservation: ...

    async def accept(
        self,
        event_id: str,
        fingerprint_hash: str,
        outcome: str,
        *,
        attempt_count: int,
    ) -> bool: ...


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
        fingerprint_hash = event.fingerprint_hash()
        reservation = await self._event_store.reserve(event.event_id, fingerprint_hash)
        if reservation == "busy":
            raise LarkEventBusyError("Lark event is already processing")
        if not isinstance(reservation, LarkEventLease):
            return
        if isinstance(event, NormalizedLarkMessage):
            await self._receive_message(event, fingerprint_hash, reservation.attempt_count)
            return
        if isinstance(event, NormalizedLarkAction):
            await self._receive_action(event, fingerprint_hash, reservation.attempt_count)
            return
        raise TypeError("Unsupported normalized Lark event")

    async def _receive_message(
        self,
        event: NormalizedLarkMessage,
        fingerprint_hash: str,
        attempt_count: int,
    ) -> None:
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
                    await self._event_store.accept(
                        event.event_id,
                        fingerprint_hash,
                        "link_rejected",
                        attempt_count=attempt_count,
                    )
                    return
            await self._delivery_queue.publish_linked(
                event.chat_id,
                event.locale,
                event.event_id,
            )
            await self._event_store.accept(
                event.event_id,
                fingerprint_hash,
                "identity_linked",
                attempt_count=attempt_count,
            )
            return
        if scope is None:
            await self._delivery_queue.publish_linking_instructions(
                event.chat_id,
                event.locale,
                event.event_id,
            )
            await self._event_store.accept(
                event.event_id,
                fingerprint_hash,
                "linking_instructions_queued",
                attempt_count=attempt_count,
            )
            return
        await self._hub.submit_message(event.to_command(scope))
        await self._event_store.accept(
            event.event_id,
            fingerprint_hash,
            "message_submitted",
            attempt_count=attempt_count,
        )

    async def _receive_action(
        self,
        event: NormalizedLarkAction,
        fingerprint_hash: str,
        attempt_count: int,
    ) -> None:
        try:
            if self._actions is None:
                raise SuggestedActionNotFoundError(
                    "Suggested action service is unavailable"
                )
            scope = await self._identity.resolve_lark_identity(event.open_id)
            if scope is None:
                raise SuggestedActionNotFoundError("Suggested action not found")
            await self._actions.consume(event.token, actor=scope)
        except (
            InvalidSuggestedActionError,
            SuggestedActionConflictError,
            SuggestedActionNotFoundError,
        ):
            await self._event_store.accept(
                event.event_id,
                fingerprint_hash,
                "action_rejected",
                attempt_count=attempt_count,
            )
            raise
        await self._event_store.accept(
            event.event_id,
            fingerprint_hash,
            "action_queued",
            attempt_count=attempt_count,
        )


def _link_code(text: str) -> str | None:
    parts = text.strip().split(maxsplit=1)
    if len(parts) != 2 or parts[0].casefold() not in {"link", "绑定"}:
        return None
    code = parts[1].strip()
    return code or None


__all__ = ["LarkInboundService"]
