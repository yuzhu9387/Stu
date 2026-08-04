from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.llm.router import LLMRouter
from app.models.user import User
from app.orchestrator.conversation import ConversationOrchestrator

router = APIRouter(prefix="/api", tags=["conversation"])


class ConversationRequest(BaseModel):
    user_id: int
    message: str


class ConversationResponse(BaseModel):
    reply: Optional[str]
    actions_taken: list[str]


@router.post("/conversation", response_model=ConversationResponse)
async def conversation(
    req: ConversationRequest,
    session: AsyncSession = Depends(get_session),
):
    user = await session.get(User, req.user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="user not found")
    llm = LLMRouter()
    orchestrator = ConversationOrchestrator(session=session, llm=llm)
    out = await orchestrator.handle(user_id=req.user_id, message=req.message)
    return ConversationResponse(reply=out.reply, actions_taken=out.actions_taken)
