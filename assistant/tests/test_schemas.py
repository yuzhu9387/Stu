from datetime import date, datetime, timedelta, timezone
from app.schemas.task import TaskCreate, TaskRead
from app.schemas.user import UserCreate, UserRead
from app.schemas.goal import GoalCreate
from app.schemas.habit import HabitCreate


def test_user_create():
    data = UserCreate(name="Alice", lark_user_id="lark_s1")
    assert data.name == "Alice"


def test_task_create():
    data = TaskCreate(title="Write report", quadrant="urgent_important", estimated_duration_minutes=180, deadline=datetime(2026, 5, 15, tzinfo=timezone.utc))
    assert data.title == "Write report"
    assert data.estimated_duration_minutes == 180


def test_task_read_from_orm():
    class FakeTask:
        id = 1
        user_id = 1
        title = "Test"
        description = None
        quadrant = "urgent_important"
        status = "pending"
        priority_score = None
        estimated_duration = timedelta(hours=2)
        actual_duration = None
        deadline = None
        source = "manual"
        goal_id = None
        parent_task_id = None
        created_at = datetime.now(timezone.utc)
        updated_at = datetime.now(timezone.utc)

    read = TaskRead.model_validate(FakeTask(), from_attributes=True)
    assert read.id == 1
    assert read.estimated_duration == timedelta(hours=2)


def test_goal_create():
    data = GoalCreate(title="Read 12 books", target_value=12.0, unit="books", period_start=date(2026, 1, 1), period_end=date(2026, 12, 31))
    assert data.target_value == 12.0


def test_habit_create():
    data = HabitCreate(title="Workout", frequency_type="weekly", frequency_count=3)
    assert data.frequency_count == 3
