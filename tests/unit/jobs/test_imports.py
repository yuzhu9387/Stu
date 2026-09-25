from uuid import uuid4

import pytest

from recipe_agent.infrastructure.jobs.imports import run_import_job


class RecordingImportService:
    def __init__(self) -> None:
        self.owner_account_ids: list[object] = []
        self.household_ids: list[object] = []
        self.raw_input_ids: list[object] = []

    async def process(
        self, owner_account_id: object, household_id: object, raw_input_id: object
    ) -> str:
        self.owner_account_ids.append(owner_account_id)
        self.household_ids.append(household_id)
        self.raw_input_ids.append(raw_input_id)
        return "completed"


@pytest.mark.asyncio
async def test_import_job_delegates_to_import_service() -> None:
    owner_account_id = uuid4()
    household_id = uuid4()
    raw_input_id = uuid4()
    service = RecordingImportService()

    result = await run_import_job(service, owner_account_id, household_id, raw_input_id)

    assert result == "completed"
    assert service.owner_account_ids == [owner_account_id]
    assert service.household_ids == [household_id]
    assert service.raw_input_ids == [raw_input_id]
