"""Real E2E service with only the paid fulfillment model replaced by a fixture.

All authentication, durable task storage, commands, validation and PostgreSQL
projection remain real. Other AI calls retain the unconfigured-key failure path.
"""

import asyncio
import json

from recipe_agent.app import app
from recipe_agent.domain.kitchen.ai import AIUnavailable, KitchenProvider

original_complete = KitchenProvider.complete


async def complete(self, messages, schema, *, vision=False):
    if schema.get("title") != "FulfillmentAdvice":
        return await original_complete(self, messages, schema, vision=vision)
    data = json.loads(messages[1]["content"])
    await asyncio.sleep(0.5)
    if data["plan"]["prompt"] == "E2E provider failure":
        raise AIUnavailable("E2E provider unavailable. Please try again.")
    return {
        "decisions": [
            {"recipeId": r["id"], "prepareAhead": True, "reason": "Batch cook", "steps": r["steps"]}
            for r in data["recipes"]
        ],
        "warnings": [],
    }


KitchenProvider.complete = complete
__all__ = ["app"]
