from __future__ import annotations
import json
import logging
from pathlib import Path
from typing import Literal, Optional

from app.coach.persona import load_coach_persona
from app.coach.web_search import tools_for_coach
from app.llm.router import LLMError, LLMRouter
from app.orchestrator.context import Context
from app.persona import load_persona

logger = logging.getLogger(__name__)

_PROMPT_PATH = Path(__file__).parent / "prompts" / "react.md"
_TEMPLATE: Optional[str] = None

_COACH_REACT_ADDENDUM_PATH = Path(__file__).parent.parent / "coach" / "prompts" / "react.md"
_COACH_REACT_ADDENDUM: Optional[str] = None


def _load_template() -> str:
    global _TEMPLATE
    if _TEMPLATE is None:
        _TEMPLATE = _PROMPT_PATH.read_text()
    return _TEMPLATE


def _load_coach_addendum() -> str:
    global _COACH_REACT_ADDENDUM
    if _COACH_REACT_ADDENDUM is None:
        _COACH_REACT_ADDENDUM = _COACH_REACT_ADDENDUM_PATH.read_text()
    return _COACH_REACT_ADDENDUM


async def react_or_raise(
    ctx: Context,
    message: str,
    action_results: list[dict],
    hint: Optional[str],
    complexity: Literal["low", "high"],
    llm: LLMRouter,
    piggyback: Optional[dict] = None,
) -> str:
    """Same work as react() but propagates LLMError instead of returning a fallback."""
    is_coach = ctx.active_flow == "coach"

    if is_coach:
        system_prompt = load_coach_persona(ctx.user_name) + "\n\n" + _load_coach_addendum()
        tools = tools_for_coach()
        max_tokens = 2000
        task_type = "reasoning"
    else:
        system_prompt = _load_template().replace("{persona}", load_persona(ctx.user_name))
        tools = None
        max_tokens = 1500
        task_type = "reasoning" if complexity == "high" else "react"

    history = "\n".join(f"{t['role']}: {t['content']}" for t in ctx.recent_turns)
    recall_block = json.dumps(ctx.episodic_recall, ensure_ascii=False)
    user_content = (
        f"<conversation_history>\n{history}\n</conversation_history>\n"
        f"<episodic_recall>{recall_block}</episodic_recall>\n"
        f"<user_message>{message}</user_message>\n"
        f"<actions_completed>{json.dumps(action_results, ensure_ascii=False)}</actions_completed>\n"
        f"<hint>{hint or ''}</hint>"
    )
    if piggyback:
        piggyback_block = json.dumps(piggyback, ensure_ascii=False)
        user_content = user_content + f"\n<piggyback_checkin>{piggyback_block}</piggyback_checkin>"

    return (await llm.complete(
        task_type,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
        max_tokens=max_tokens,
        tools=tools,
    )).strip()


async def react(
    ctx: Context,
    message: str,
    action_results: list[dict],
    hint: Optional[str],
    complexity: Literal["low", "high"],
    llm: LLMRouter,
    piggyback: Optional[dict] = None,
) -> str:
    try:
        return await react_or_raise(
            ctx, message, action_results, hint, complexity, llm, piggyback=piggyback
        )
    except LLMError as e:
        logger.warning("REACT call failed: %s", e)
        return "好的，已记下来。"
