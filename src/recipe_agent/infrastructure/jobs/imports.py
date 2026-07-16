"""Transport-neutral import worker boundary."""

from typing import Protocol
from uuid import UUID


class ImportProcessor[Result](Protocol):
    async def process(
        self,
        owner_account_id: UUID,
        household_id: UUID,
        raw_input_id: UUID,
    ) -> Result: ...


async def run_import_job[Result](
    processor: ImportProcessor[Result],
    owner_account_id: UUID,
    household_id: UUID,
    raw_input_id: UUID,
) -> Result:
    """Run one import; Celery and local workers share this entry point."""

    return await processor.process(owner_account_id, household_id, raw_input_id)
