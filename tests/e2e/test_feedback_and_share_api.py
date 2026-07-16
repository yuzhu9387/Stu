from datetime import timedelta
from uuid import uuid4

from fastapi.testclient import TestClient

from recipe_agent.api.dependencies import get_household_scope
from recipe_agent.app import create_app
from recipe_agent.config import Settings
from recipe_agent.domain.feedback.contracts import (
    FeedbackEvent,
    FeedbackOutcome,
    RecipeVersionReference,
)
from recipe_agent.domain.identity.service import HouseholdScope
from recipe_agent.domain.sharing.service import ShareDelivery


class FixedFeedbackService:
    async def record(
        self,
        owner_account_id: object,
        household_id: object,
        recipe_id: object,
        raw_text: str,
    ) -> FeedbackOutcome:
        return FeedbackOutcome(
            feedback_event=FeedbackEvent(
                id=uuid4(),
                owner_account_id=owner_account_id,
                household_id=household_id,
                recipe_id=recipe_id,
                raw_text=raw_text,
            ),
            recipe_version=RecipeVersionReference(
                id=uuid4(),
                recipe_id=recipe_id,
                parent_version_id=uuid4(),
            ),
        )


class RecordingShareService:
    def __init__(self) -> None:
        self.snapshots: list[dict[str, object]] = []

    async def create_snapshot(
        self, snapshot: dict[str, object], *, expires_in: timedelta
    ) -> ShareDelivery:
        self.snapshots.append(snapshot)
        return ShareDelivery(token="private-token")


def test_feedback_and_share_creation_use_authenticated_scope_and_public_schema() -> None:
    app = create_app(Settings(environment="test", database_url="sqlite+aiosqlite:///:memory:"))
    household_id = uuid4()
    owner_account_id = uuid4()
    recipe_id = uuid4()
    shares = RecordingShareService()
    app.state.feedback_service = FixedFeedbackService()
    app.state.share_service = shares
    app.dependency_overrides[get_household_scope] = lambda: HouseholdScope(
        account_id=owner_account_id, household_id=household_id
    )
    client = TestClient(app)

    feedback = client.post(
        f"/api/v1/feedback/{recipe_id}",
        json={"text": "Cook longer"},
    )
    share = client.post(
        "/api/v1/shares",
        json={
            "id": str(recipe_id),
            "name": "Soup",
            "ingredients": ["tomato"],
            "steps": ["Simmer"],
        },
    )

    assert feedback.status_code == 201
    assert feedback.json()["feedback_event"]["owner_account_id"] == str(owner_account_id)
    assert share.status_code == 201
    assert share.json() == {"token": "private-token"}
    assert shares.snapshots[0] == {
        "id": str(recipe_id),
        "name": "Soup",
        "ingredients": ["tomato"],
        "steps": ["Simmer"],
    }
