"""One pass of scheduled weekly planning: `python -m recipe_agent.run_due`.

Deployments without the dispatcher run this as a Cloud Run job on a schedule.
It drafts each household's week whose planning time has come, then exits;
claims in the database keep a week from being drafted twice.
"""

import asyncio

from recipe_agent.config import get_settings
from recipe_agent.infrastructure.db.session import create_session_factory
from recipe_agent.infrastructure.jobs.kitchen import run_due_kitchen_jobs
from recipe_agent.infrastructure.observability.logging import render_log


async def main() -> int:
    settings = get_settings()
    session_factory = create_session_factory(settings)
    try:
        return await run_due_kitchen_jobs(session_factory, settings)
    finally:
        await session_factory.kw["bind"].dispose()


if __name__ == "__main__":
    completed = asyncio.run(main())
    print(render_log({"event": "kitchen.generation.completed", "count": completed}), flush=True)
