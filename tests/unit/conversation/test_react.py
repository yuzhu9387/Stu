from collections.abc import Mapping
from typing import Any
from uuid import uuid4

import pytest
from pydantic import ValidationError

from recipe_agent.domain.conversation.react import (
    AgentContext,
    ReactAgent,
    ReactDecision,
    ReadOnlyToolCall,
    ReadOnlyToolDefinition,
    ToolObservation,
    UnknownReadOnlyToolError,
)
from recipe_agent.domain.conversation.responses import (
    ActionArgument,
    FinalAgentResponse,
    SuggestedActionDraft,
)
from recipe_agent.domain.identity.locale import Locale


def context() -> AgentContext:
    return AgentContext(
        run_id=uuid4(),
        account_id=uuid4(),
        household_id=uuid4(),
        locale=Locale.EN_US,
        message="What can I make for dinner?",
    )


def final_response(answer: str = "Try the tomato soup.") -> FinalAgentResponse:
    return FinalAgentResponse(
        thinking="You want a dinner idea from known recipes.",
        plan="Search family-visible recipes and summarize the best match.",
        act="Checked family-visible recipes.",
        answer=answer,
        suggested_actions=(),
    )


class FakeModel:
    def __init__(self, decisions: list[ReactDecision]) -> None:
        self._decisions = iter(decisions)
        self.observations: list[tuple[ToolObservation, ...]] = []
        self.finish_calls = 0

    async def decide(
        self,
        agent_context: AgentContext,
        observations: tuple[ToolObservation, ...],
    ) -> ReactDecision:
        del agent_context
        self.observations.append(observations)
        return next(self._decisions)

    async def finish(
        self,
        agent_context: AgentContext,
        observations: tuple[ToolObservation, ...],
    ) -> FinalAgentResponse:
        del agent_context, observations
        self.finish_calls += 1
        return final_response("I reached the read limit; here are the verified results.")


class FakeTools:
    def __init__(self, *, payload: Mapping[str, Any] | None = None) -> None:
        self.definitions = (
            ReadOnlyToolDefinition(
                name="search_family_recipes",
                description="Search family-visible recipes.",
                parameters={
                    "type": "object",
                    "properties": {"query": {"type": "string"}},
                    "required": ["query"],
                    "additionalProperties": False,
                },
            ),
        )
        self.payload = dict(payload or {"recipes": []})
        self.calls = 0

    async def execute(
        self,
        call: ReadOnlyToolCall,
        scope: object,
    ) -> ToolObservation:
        del scope
        self.calls += 1
        return ToolObservation(tool_name=call.name, data=self.payload)


def tool_decision(name: str = "search_family_recipes") -> ReactDecision:
    return ReactDecision(tool_call=ReadOnlyToolCall(name=name, arguments={"query": "dinner"}))


@pytest.mark.asyncio
async def test_react_stops_after_five_tool_iterations() -> None:
    model = FakeModel([tool_decision() for _ in range(5)])
    tools = FakeTools()

    response = await ReactAgent(model=model, tools=tools, max_iterations=5).run(context())

    assert tools.calls == 5
    assert model.finish_calls == 1
    assert response.answer
    assert "private_reasoning" not in type(response).model_fields
    assert "private_reasoning" not in response.model_dump()


@pytest.mark.asyncio
async def test_model_cannot_request_mutation_tool() -> None:
    model = FakeModel([tool_decision("save_recipe")])
    tools = FakeTools()

    with pytest.raises(UnknownReadOnlyToolError, match="save_recipe"):
        await ReactAgent(model=model, tools=tools).run(context())

    assert tools.calls == 0


@pytest.mark.asyncio
async def test_tool_observation_is_bounded_before_next_model_decision() -> None:
    model = FakeModel([tool_decision(), ReactDecision(final=final_response())])
    tools = FakeTools(payload={"blob": ('"\\\u5bb6\u5ead' * 2_000)})
    max_observation_chars = 128

    await ReactAgent(
        model=model,
        tools=tools,
        max_observation_chars=max_observation_chars,
    ).run(context())

    observation = model.observations[1][0]
    assert observation.truncated is True
    assert len(observation.model_dump_json()) <= max_observation_chars
    assert '"\\\u5bb6\u5ead' * 100 not in str(observation.data)


def test_react_decision_requires_exactly_one_choice() -> None:
    with pytest.raises(ValidationError):
        ReactDecision()
    with pytest.raises(ValidationError):
        ReactDecision(tool_call=tool_decision().tool_call, final=final_response())


def test_final_response_exposes_only_safe_summaries_and_typed_drafts() -> None:
    response = FinalAgentResponse(
        thinking="You asked me to remember this recipe.",
        plan="Prepare a save draft for your review.",
        act="Parsed the recipe without saving it.",
        answer="Review the suggested save action.",
        suggested_actions=(
            SuggestedActionDraft(
                type="save_recipe",
                arguments=(ActionArgument(name="name", value_json='"Soup"'),),
            ),
        ),
    )

    assert tuple(response.model_dump()) == (
        "thinking",
        "plan",
        "act",
        "answer",
        "suggested_actions",
    )
    serialized_action = response.model_dump(mode="json")["suggested_actions"][0]
    assert serialized_action["type"] == "save_recipe"
    assert serialized_action["arguments"] == [{"name": "name", "value_json": '"Soup"'}]
    with pytest.raises(ValidationError):
        FinalAgentResponse.model_validate(
            final_response().model_dump() | {"private_reasoning": "hidden reasoning"}
        )
    with pytest.raises(ValidationError):
        SuggestedActionDraft(type="delete_recipe", arguments=())
    with pytest.raises(ValidationError):
        FinalAgentResponse(
            thinking="Safe summary",
            plan="Safe plan",
            act="No action",
            answer="Answer",
            suggested_actions=tuple(
                SuggestedActionDraft(type="save_recipe", arguments=()) for _ in range(4)
            ),
        )
