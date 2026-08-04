from typing import Literal
from app.config import settings

TaskType = Literal["think", "react", "reasoning"]


def resolve_model(task_type: TaskType) -> str:
    return {
        "think": settings.llm_think_model,
        "react": settings.llm_react_model,
        "reasoning": settings.llm_reasoning_model,
    }[task_type]
