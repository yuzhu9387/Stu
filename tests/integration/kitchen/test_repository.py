from uuid import uuid4

import pytest

from recipe_agent.domain.identity.service import HouseholdScope
from recipe_agent.domain.kitchen.engine import KitchenError
from recipe_agent.domain.kitchen.repository import KitchenRepository


async def test_idempotency_revision_and_household_isolation(session_factory):
    repo = KitchenRepository(session_factory)
    first = HouseholdScope(uuid4(), uuid4())
    second = HouseholdScope(uuid4(), uuid4())
    command = {
        "type": "tag.save",
        "payload": {"name": "宝宝喜欢"},
        "expectedRevision": 0,
        "operationId": "unique",
    }
    result = await repo.command(first, command)
    assert result == await repo.command(first, command)
    assert (await repo.get(first))["revision"] == 1
    assert (await repo.get(second))["tags"] == []
    with pytest.raises(KitchenError, match="Operation ID"):
        await repo.command(first, {**command, "payload": {"name": "other"}})
    with pytest.raises(KitchenError, match="Workspace changed"):
        await repo.command(first, {**command, "operationId": "new"})
    assert (await repo.get(first))["tags"] == ["宝宝喜欢"]


async def test_failed_command_has_no_receipt_or_state_mutation(session_factory):
    repo = KitchenRepository(session_factory)
    scope = HouseholdScope(uuid4(), uuid4())
    command = {
        "type": "tag.save",
        "payload": {"name": ""},
        "expectedRevision": 0,
        "operationId": "retry",
    }
    with pytest.raises(KitchenError):
        await repo.command(scope, command)
    assert (await repo.get(scope))["revision"] == 0
    result = await repo.command(scope, {**command, "payload": {"name": "fixed"}})
    assert result["state"]["revision"] == 1
