from uuid import uuid4

from recipe_agent.domain.identity.service import HouseholdScope
from recipe_agent.domain.kitchen.repository import KitchenRepository


async def test_knowledge_persists_on_reload_and_is_isolated_by_household(session_factory):
    scope = HouseholdScope(uuid4(), uuid4())
    other_scope = HouseholdScope(uuid4(), uuid4())
    command = {
        "type": "knowledge.save",
        "payload": {
            "document": {
                "id": "doc",
                "title": "营养资料",
                "content": "用户保存的文档",
                "category": "Family",
                "enabled": True,
            }
        },
        "expectedRevision": 0,
        "operationId": "knowledge-first-save",
    }
    repository = KitchenRepository(session_factory)
    await repository.command(scope, command)
    reloaded = await KitchenRepository(session_factory).get(scope)
    assert reloaded["knowledgeDocuments"][0]["content"] == "用户保存的文档"
    assert reloaded["knowledgeDocuments"][0]["version"] == 1
    assert (await repository.get(other_scope))["knowledgeDocuments"] == []
    await repository.command(scope, command)
    assert (await repository.get(scope))["knowledgeDocuments"][0]["version"] == 1
