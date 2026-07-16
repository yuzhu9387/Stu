"""Fast acknowledgement boundary for Lark events and card callbacks."""

import hmac
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, ValidationError

from recipe_agent.domain.conversation.actions import SuggestedActionNotFoundError
from recipe_agent.infrastructure.lark.crypto import LarkCipher
from recipe_agent.infrastructure.lark.normalizer import LarkEventNormalizer
from recipe_agent.infrastructure.lark.service import LarkInboundService

router = APIRouter(prefix="/webhooks/lark", tags=["lark"])


class _Header(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    event_id: str
    token: str


class _Envelope(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    header: _Header


class _URLVerification(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    type: str
    token: str
    challenge: str


class LarkWebhookHandler:
    """Verify, normalize, durably enqueue, and return without outbound I/O."""

    def __init__(
        self,
        *,
        verification_token: str,
        normalizer: LarkEventNormalizer,
        inbound: LarkInboundService,
        cipher: LarkCipher | None = None,
    ) -> None:
        self._verification_token = verification_token
        self._cipher = cipher
        self._normalizer = normalizer
        self._inbound = inbound

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
        event = self._normalizer.normalize(payload)
        await self._inbound.receive(event)
        return {"status": "accepted"}


def secrets_equal(received: str, expected: str) -> bool:
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
    except (ValidationError, ValueError) as error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unsupported Lark callback",
        ) from error
    except SuggestedActionNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND) from error
