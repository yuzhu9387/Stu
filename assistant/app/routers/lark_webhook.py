from __future__ import annotations
import logging
from typing import Dict, Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_session
from app.lark.client import LarkClient
from app.lark.webhook import LarkEvent, WebhookHandler
from app.llm.router import LLMRouter
from app.models.user import User
from app.orchestrator.conversation import ConversationOrchestrator
from app.orchestrator.triggers import WelcomeTrigger
from app.services.lark_messenger import LarkMessenger

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/lark", tags=["lark"])

_webhook_handler = WebhookHandler(
    verification_token=settings.lark_verification_token or "test-verify-token"
)


def _lark_client() -> LarkClient:
    return LarkClient(app_id=settings.lark_app_id, app_secret=settings.lark_app_secret)


def _extract_open_id(event: LarkEvent) -> str | None:
    if event.user_id:
        return event.user_id
    return (
        event.raw.get("event", {})
        .get("sender", {})
        .get("sender_id", {})
        .get("open_id")
    )


@router.post("/webhook")
async def lark_webhook(payload: Dict[str, Any], session: AsyncSession = Depends(get_session)):
    event: LarkEvent = _webhook_handler.parse(payload)

    if event.event_type == "invalid":
        raise HTTPException(status_code=403, detail="Invalid verification token")
    if event.event_type == "url_verification":
        return {"challenge": event.challenge}
    if event.event_type == "duplicate":
        return {"status": "ok", "message": "duplicate event ignored"}

    if event.event_type == "im.message.receive_v1":
        return await _handle_message(event, session)

    if event.event_type == "card.action.trigger":
        return {"status": "ok"}

    return {"status": "ok", "message": f"unhandled event type: {event.event_type}"}


async def _handle_message(event: LarkEvent, session: AsyncSession) -> Dict[str, Any]:
    open_id = _extract_open_id(event)
    text = event.message_text or ""
    if not open_id:
        return {"status": "ok", "message": "no sender open_id"}

    user_row = (await session.execute(
        select(User).where(User.lark_user_id == open_id)
    )).scalar_one_or_none()

    client = _lark_client()
    messenger = LarkMessenger(client)
    llm = LLMRouter()
    orchestrator = ConversationOrchestrator(session=session, llm=llm)

    if user_row is None:
        user_row = User(name="(new)", lark_user_id=open_id, preferences={})
        session.add(user_row)
        await session.commit()
        await session.refresh(user_row)
        reply = await orchestrator.send_proactive(
            user_id=user_row.id,
            trigger=WelcomeTrigger(initial_message=text or None),
            complexity="low",
        )
        if reply:
            await messenger.push(open_id, reply)
        return {"status": "ok"}

    out = await orchestrator.handle(user_id=user_row.id, message=text)
    if out.reply:
        await messenger.push(open_id, out.reply)
    return {"status": "ok"}
