from datetime import date
from uuid import uuid4

from fastapi.testclient import TestClient

from recipe_agent.api.dependencies import get_household_scope
from recipe_agent.app import create_app
from recipe_agent.config import Settings
from recipe_agent.domain.identity.service import HouseholdScope
from recipe_agent.domain.planning.contracts import MealPlan, PlanSlot


class RecordingPlanningService:
    def __init__(self) -> None:
        self.household_ids: list[object] = []

    async def create_week(
        self,
        household_id: object,
        week_start: date,
        slots: tuple[PlanSlot, ...],
    ) -> MealPlan:
        self.household_ids.append(household_id)
        return MealPlan(
            id=uuid4(),
            household_id=household_id,
            week_start=week_start,
            version=1,
            items=(),
        )


def test_weekly_plan_api_uses_authenticated_household_scope() -> None:
    app = create_app(Settings(environment="test", database_url="sqlite+aiosqlite:///:memory:"))
    household_id = uuid4()
    service = RecordingPlanningService()
    app.state.planning_service = service
    app.dependency_overrides[get_household_scope] = lambda: HouseholdScope(
        account_id=uuid4(), household_id=household_id
    )

    response = TestClient(app).post(
        "/api/v1/plans/weeks",
        json={
            "week_start": "2026-07-13",
            "slots": [{"day": "2026-07-13", "slot": "dinner"}],
        },
    )

    assert response.status_code == 201
    assert response.json()["household_id"] == str(household_id)
    assert service.household_ids == [household_id]
