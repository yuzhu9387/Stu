"""Fast acknowledgement boundary for Lark event callbacks."""

from typing import Annotated, Protocol

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel

from recipe_agent.domain.conversation.contracts import ConversationCommand
from recipe_agent.infrastructure.lark.crypto import LarkCipher
from recipe_agent.infrastructure.lark.normalizer import LarkEventNormalizer

router = APIRouter(prefix="/webhooks/lark", tags=["lark"])


class _Header(BaseModel):
    event_id: str
    token: str


class _Envelope(BaseModel):
    header: _Header


class _URLVerification(BaseModel):
    type: str
    token: str
    challenge: str


class EventStore(Protocol):
    async def claim(self, event_id: str) -> bool: ...


class CommandPublisher(Protocol):
    async def publish(self, command: ConversationCommand) -> None: ...


class LarkWebhookHandler:
    def __init__(
        self,
        *,
        verification_token: str,
        cipher: LarkCipher | None = None,
        normalizer: LarkEventNormalizer,
        event_store: EventStore,
        publisher: CommandPublisher,
    ) -> None:
        self._verification_token = verification_token
        self._cipher = cipher
        self._normalizer = normalizer
        self._event_store = event_store
        self._publisher = publisher

    async def handle(self, payload: object) -> dict[str, str]:
        if isinstance(payload, dict) and isinstance(payload.get("encrypt"), str):
            if self._cipher is None:
                raise PermissionError("Encrypted Lark payload is not configured")
            payload = self._cipher.decrypt(payload["encrypt"])
        if isinstance(payload, dict) and payload.get("type") == "url_verification":
            verification = _URLVerification.model_validate(payload)
            if not secrets_equal(verification.token, self._verification_token):
                raise PermissionError("Invalid Lark verification token")
            return {"challenge": verification.challenge}
        envelope = _Envelope.model_validate(payload)
        if not secrets_equal(envelope.header.token, self._verification_token):
            raise PermissionError("Invalid Lark verification token")
        if not await self._event_store.claim(envelope.header.event_id):
            return {"status": "accepted"}
        await self._publisher.publish(self._normalizer.normalize(payload))
        return {"status": "accepted"}


def secrets_equal(received: str, expected: str) -> bool:
    import hmac

    return hmac.compare_digest(received, expected)


def get_handler(request: Request) -> LarkWebhookHandler:
    handler: LarkWebhookHandler | None = getattr(request.app.state, "lark_handler", None)
    if handler is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE)
    return handler


@router.post("/events")
async def receive_event(
    payload: dict[str, object],
    handler: Annotated[LarkWebhookHandler, Depends(get_handler)],
) -> dict[str, str]:
    try:
        return await handler.handle(payload)
    except PermissionError as error:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED) from error
