from uuid import uuid4

import pytest

from recipe_agent.infrastructure.jobs.imports import run_import_job


class RecordingImportService:
    def __init__(self) -> None:
        self.raw_input_ids: list[object] = []

    async def process(self, raw_input_id: object) -> str:
        self.raw_input_ids.append(raw_input_id)
        return "completed"


@pytest.mark.asyncio
async def test_import_job_delegates_to_import_service() -> None:
    raw_input_id = uuid4()
    service = RecordingImportService()

    result = await run_import_job(service, raw_input_id)

    assert result == "completed"
    assert service.raw_input_ids == [raw_input_id]
