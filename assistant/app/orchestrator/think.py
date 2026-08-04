from __future__ import annotations
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Optional

from app.llm.router import LLMError, LLMRouter
from app.orchestrator.actions import ParsedAction, parse_action
from app.orchestrator.context import Context

logger = logging.getLogger(__name__)

_PROMPT_PATH = Path(__file__).parent / "prompts" / "think.md"
_SYSTEM_PROMPT: Optional[str] = None


def _load_system_prompt() -> str:
    global _SYSTEM_PROMPT
    if _SYSTEM_PROMPT is None:
        _SYSTEM_PROMPT = _PROMPT_PATH.read_text()
    return _SYSTEM_PROMPT


_COACH_ADDENDUM_PATH = Path(__file__).parent.parent / "coach" / "prompts" / "think.md"
_COACH_ADDENDUM: Optional[str] = None


def _load_coach_addendum() -> str:
    global _COACH_ADDENDUM
    if _COACH_ADDENDUM is None:
        _COACH_ADDENDUM = _COACH_ADDENDUM_PATH.read_text()
    return _COACH_ADDENDUM


@dataclass
class ThinkResult:
    intent: str
    actions: list[ParsedAction] = field(default_factory=list)
    should_reply: bool = True
    reply_complexity: Literal["low", "high"] = "low"
    reply_hint: Optional[str] = None
    reasoning: Optional[str] = None
    raw: Optional[dict] = None


def _build_user_content(ctx: Context, message: str) -> str:
    flow_block = ""
    if ctx.active_flow:
        missing = [f.name for f in ctx.flow_missing_fields]
        flow_block = (
            f"\nActive flow: {ctx.active_flow}\n"
            f"Filled fields: {json.dumps(ctx.flow_filled_fields, ensure_ascii=False)}\n"
            f"Missing fields (ask one): {missing}\n"
        )
    profile_block = ctx.profile.model_dump_json(exclude_none=True)
    patterns_block = json.dumps([p.model_dump() for p in ctx.procedural_patterns], ensure_ascii=False)
    history = "\n".join(
        f"{t['role']}: {t['content']}" for t in ctx.recent_turns
    )
    tasks_block = json.dumps(ctx.open_tasks, ensure_ascii=False)
    recall_block = json.dumps(ctx.episodic_recall, ensure_ascii=False)

    return (
        f"<user_profile>{profile_block}</user_profile>\n"
        f"<learned_patterns>{patterns_block}</learned_patterns>\n"
        f"<episodic_recall>{recall_block}</episodic_recall>\n"
        f"<open_tasks>{tasks_block}</open_tasks>\n"
        f"{flow_block}"
        f"<conversation_history>\n{history}\n</conversation_history>\n"
        f"<user_message>{message}</user_message>"
    )


async def think(ctx: Context, message: str, llm: LLMRouter) -> ThinkResult:
    system_prompt = _load_system_prompt()
    if ctx.active_flow == "coach":
        system_prompt = system_prompt + "\n\n" + _load_coach_addendum()
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": _build_user_content(ctx, message)},
    ]
    try:
        raw = await llm.complete_json("think", messages)
    except LLMError as e:
        logger.warning("THINK call failed: %s", e)
        return ThinkResult(
            intent="unknown",
            actions=[],
            should_reply=True,
            reply_complexity="low",
            reply_hint="apologize, ask user to rephrase",
            reasoning=f"LLM error: {e}",
        )

    parsed_actions: list[ParsedAction] = []
    for raw_action in raw.get("actions", []) or []:
        try:
            parsed_actions.append(parse_action(raw_action))
        except (ValueError, Exception) as e:
            logger.warning("dropping invalid action %s: %s", raw_action, e)

    return ThinkResult(
        intent=raw.get("intent", ""),
        actions=parsed_actions,
        should_reply=bool(raw.get("should_reply", True)),
        reply_complexity="high" if raw.get("reply_complexity") == "high" else "low",
        reply_hint=raw.get("reply_hint"),
        reasoning=raw.get("reasoning"),
        raw=raw,
    )
