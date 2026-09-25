"""Knowledge is household data; edits must not rewrite planning evidence."""

from datetime import datetime

import pytest

from recipe_agent.api.v1.kitchen_mcp import tool_definitions
from recipe_agent.domain.kitchen.engine import initial_state
from tests.unit.kitchen.test_ai_scheduling_mcp import plan
from tests.unit.kitchen.test_engine import run


def document(**changes):
    return {
        "id": "family-nutrition",
        "title": "家庭搭配原则",
        "category": "Family nutrition",
        "content": "这是用户记录的膳食资料。",
        "sourceUrl": "https://example.org/nutrition",
        "enabled": True,
        **changes,
    }


def test_document_crud_versions_and_snapshot_are_persistent_and_independent():
    state = initial_state()
    assert state["knowledgeDocuments"] == []
    state = run(state, "knowledge.save", {"document": document(version=99, updatedAt="forged")})
    saved = state["knowledgeDocuments"][0]
    assert saved["version"] == 1
    assert datetime.fromisoformat(saved["updatedAt"]).tzinfo is not None
    weekly = plan()
    weekly["meals"] = []
    state = run(state, "plan.save", {"plan": weekly})
    assert state["plans"][0]["knowledgeSnapshot"] == [saved]
    state = run(state, "knowledge.save", {"document": document(content="新资料", enabled=False)})
    assert state["knowledgeDocuments"][0]["version"] == 2
    assert state["plans"][0]["knowledgeSnapshot"] == [saved]
    state = run(state, "knowledge.delete", {"id": saved["id"]})
    assert state["knowledgeDocuments"] == []
    assert state["plans"][0]["knowledgeSnapshot"] == [saved]


@pytest.mark.parametrize(
    "changes",
    [
        {"title": "   "},
        {"content": "  "},
        {"sourceUrl": "javascript:alert(1)"},
        {"content": "x" * 100001},
    ],
)
def test_document_rejects_invalid_content_and_unsafe_source_url(changes):
    state = initial_state()
    with pytest.raises(ValueError):
        run(state, "knowledge.save", {"document": document(**changes)})
    assert state["revision"] == 0


def test_disabled_docs_are_not_captured_and_mcp_exposes_crud():
    state = run(initial_state(), "knowledge.save", {"document": document(enabled=False)})
    weekly = plan()
    weekly["meals"] = []
    state = run(state, "plan.save", {"plan": weekly})
    assert state["plans"][0]["knowledgeSnapshot"] == []
    command = next(t for t in tool_definitions() if t["name"] == "kitchen_command")
    assert {"knowledge.save", "knowledge.delete"} <= set(
        command["inputSchema"]["properties"]["type"]["enum"]
    )


def test_stale_editor_cannot_overwrite_a_newer_document_version():
    state = run(initial_state(), "knowledge.save", {"document": document()})
    original = dict(state["knowledgeDocuments"][0])
    state = run(state, "knowledge.save", {"document": {**original, "content": "Latest content"}})
    with pytest.raises(ValueError, match="document changed"):
        run(state, "knowledge.save", {"document": {**original, "content": "Stale form content"}})
    assert state["knowledgeDocuments"][0]["content"] == "Latest content"
