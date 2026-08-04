from __future__ import annotations
import json
from typing import Any, Optional

import litellm

from app.config import settings
from app.llm.config import TaskType, resolve_model


class LLMError(Exception):
    """Raised when LLM call or response parsing fails."""


class LLMRouter:
    """Thin async LiteLLM wrapper with task-type → model resolution."""

    def __init__(self, *, api_key: Optional[str] = None):
        self._api_key = api_key or settings.anthropic_api_key

    async def complete(
        self,
        task_type: TaskType,
        messages: list[dict],
        max_tokens: int = 1500,
        response_format: Optional[dict] = None,
        tools: Optional[list[dict]] = None,
    ) -> str:
        model = resolve_model(task_type)
        kwargs: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "max_tokens": max_tokens,
        }
        if self._api_key:
            kwargs["api_key"] = self._api_key
        if response_format is not None:
            kwargs["response_format"] = response_format
        if tools is not None:
            kwargs["tools"] = tools
        try:
            response = await litellm.acompletion(**kwargs)
        except Exception as e:
            raise LLMError(f"LLM call failed: {e}") from e
        content = response.choices[0].message.content
        # When tools were used, content can be a list of blocks (text + tool_use + tool_result).
        if isinstance(content, list):
            text_parts = [
                b.get("text", "")
                for b in content
                if isinstance(b, dict) and b.get("type") == "text"
            ]
            content = "\n".join(p for p in text_parts if p)
        if content is None or content == "":
            raise LLMError("LLM returned empty content")
        return content

    async def complete_json(
        self,
        task_type: TaskType,
        messages: list[dict],
        max_tokens: int = 1500,
    ) -> dict:
        text = await self.complete(
            task_type,
            messages,
            max_tokens=max_tokens,
            response_format={"type": "json_object"},
        )
        text = text.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError as e:
            raise LLMError(f"LLM did not return valid JSON: {text[:200]}") from e
