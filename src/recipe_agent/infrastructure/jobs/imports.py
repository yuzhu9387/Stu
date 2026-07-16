"""Transport-neutral import worker boundary."""

from typing import Protocol
from uuid import UUID


class ImportProcessor[Result](Protocol):
    async def process(self, raw_input_id: UUID) -> Result: ...


async def run_import_job[Result](processor: ImportProcessor[Result], raw_input_id: UUID) -> Result:
    """Run one import; Celery and local workers share this entry point."""

    return await processor.process(raw_input_id)
