from app.schemas.common import Quadrant, TaskStatus, TaskSource, SlotType, ReminderType, ReminderStatus, ReportType, FrequencyType


def test_quadrant_values():
    assert Quadrant.URGENT_IMPORTANT.value == "urgent_important"
    assert Quadrant.IMPORTANT.value == "important"
    assert Quadrant.URGENT.value == "urgent"
    assert Quadrant.NEITHER.value == "neither"


def test_task_status_values():
    assert TaskStatus.PENDING.value == "pending"
    assert TaskStatus.IN_PROGRESS.value == "in_progress"
    assert TaskStatus.COMPLETED.value == "completed"
    assert TaskStatus.CANCELLED.value == "cancelled"


def test_task_source_values():
    assert TaskSource.MANUAL.value == "manual"
    assert TaskSource.LARK_MSG.value == "lark_msg"
    assert TaskSource.EMAIL.value == "email"
    assert TaskSource.CALENDAR.value == "calendar"
