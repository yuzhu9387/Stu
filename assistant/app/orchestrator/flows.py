from __future__ import annotations
from dataclasses import dataclass
from typing import Literal, Optional


FieldType = Literal["time", "time_range", "text", "number", "boolean", "date"]


@dataclass(frozen=True)
class FieldDef:
    name: str
    type: FieldType
    description: str


@dataclass(frozen=True)
class FlowDefinition:
    name: str
    required_fields: tuple[FieldDef, ...]

    def missing_fields(self, filled: dict) -> list[FieldDef]:
        return [f for f in self.required_fields if f.name not in filled or filled[f.name] is None]

    def is_complete(self, filled: dict) -> bool:
        return not self.missing_fields(filled)


ONBOARDING = FlowDefinition(
    name="onboarding",
    required_fields=(
        FieldDef("wake_up", "time", "wake-up time"),
        FieldDef("work_start", "time", "work-start time"),
        FieldDef("peak_hours_start", "time", "start of deep-work window"),
        FieldDef("peak_hours_end", "time", "end of deep-work window"),
        FieldDef("work_end", "time", "work-end time"),
        FieldDef("sleep_time", "time", "bedtime"),
        FieldDef("daily_habits", "text", "daily routines / habits"),
        FieldDef("user_expectations", "text", "what the user wants the assistant to help with"),
        FieldDef("yearly_goals", "text", "main goals for this year"),
    ),
)


COACH = FlowDefinition(
    name="coach",
    required_fields=(),
)


_REGISTRY: dict[str, FlowDefinition] = {
    ONBOARDING.name: ONBOARDING,
    COACH.name: COACH,
}


def get_flow(name: str) -> Optional[FlowDefinition]:
    return _REGISTRY.get(name)
