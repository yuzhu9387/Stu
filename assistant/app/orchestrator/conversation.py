from __future__ import annotations
import asyncio
from dataclasses import dataclass
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.database import async_session_factory
from app.llm.router import LLMRouter
from app.memory.embeddings import embed_and_store
from app.models.conversation import Conversation
from app.orchestrator.act import ActionExecutor, _EVENT_TYPE_MAP
from app.orchestrator.context import load_context
from app.orchestrator.proactive import send_proactive_impl
from app.orchestrator.react import react
from app.orchestrator.think import think
from app.orchestrator.triggers import Trigger


async def _background_embed_user_message(user_id: int, msg_id: int, content: str) -> None:
    async with async_session_factory() as session:
        await embed_and_store(session, user_id, "conversation", msg_id, content)


@dataclass
class OrchestratorResponse:
    reply: Optional[str]
    actions_taken: list[str]


class ConversationOrchestrator:
    def __init__(self, session: AsyncSession, llm: LLMRouter):
        self.session = session
        self.llm = llm

    async def handle(self, user_id: int, message: str) -> OrchestratorResponse:
        user_msg = Conversation(user_id=user_id, role="user", content=message)
        self.session.add(user_msg)
        await self.session.commit()
        await self.session.refresh(user_msg)

        asyncio.create_task(
            _background_embed_user_message(user_id, user_msg.id, message)
        )

        ctx = await load_context(user_id, self.session, query_text=message)

        think_result = await think(ctx, message, self.llm)

        if think_result.intent:
            user_msg.intent = think_result.intent[:50]
            await self.session.commit()

        executor = ActionExecutor(self.session)
        action_results = await executor.execute_all(
            user_id=user_id,
            actions=think_result.actions,
            conversation_id=user_msg.id,
        )

        reply_text: Optional[str] = None
        if think_result.should_reply:
            reply_text = await react(
                ctx=ctx,
                message=message,
                action_results=[
                    {
                        "type": r.type.value,
                        "entity_type": r.entity_type,
                        "entity_id": r.entity_id,
                        "payload": r.payload,
                    }
                    for r in action_results
                ],
                hint=think_result.reply_hint,
                complexity=think_result.reply_complexity,
                llm=self.llm,
            )
            self.session.add(
                Conversation(
                    user_id=user_id,
                    role="assistant",
                    content=reply_text,
                    intent=think_result.intent[:50] if think_result.intent else None,
                )
            )
            await self.session.commit()

        return OrchestratorResponse(
            reply=reply_text,
            actions_taken=[_EVENT_TYPE_MAP[r.type] for r in action_results],
        )

    async def send_proactive(
        self,
        user_id: int,
        trigger: Trigger,
        complexity: str = "low",
    ) -> Optional[str]:
        return await send_proactive_impl(
            session=self.session,
            llm=self.llm,
            user_id=user_id,
            trigger=trigger,
            complexity=complexity,  # type: ignore[arg-type]
        )
