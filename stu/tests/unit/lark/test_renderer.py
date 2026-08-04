from datetime import UTC, datetime, timedelta
from uuid import uuid4

from recipe_agent.domain.conversation.actions import IssuedSuggestedAction
from recipe_agent.domain.conversation.contracts import AgentOutcome, AgentProgress, AgentStage
from recipe_agent.domain.conversation.responses import FinalAgentResponse
from recipe_agent.domain.identity.locale import Locale, Translator
from recipe_agent.infrastructure.lark.renderer import LarkCardRenderer


def test_progress_card_uses_only_selected_locale() -> None:
    renderer = LarkCardRenderer(Translator.from_package())
    progress = AgentProgress(
        run_id=uuid4(),
        stage=AgentStage.ACTING,
        message_key="agent.stage.acting",
        values={"tool": "save_recipe"},
    )

    english = renderer.progress(progress, Locale.EN_US)
    chinese = renderer.progress(progress, Locale.ZH_CN)

    assert english["elements"][0]["text"]["content"] == "Acting: running save_recipe."
    assert chinese["elements"][0]["text"]["content"] == "执行：正在运行 save_recipe。"
    assert "执行" not in str(english)
    assert "Acting" not in str(chinese)


def test_outcome_card_contains_verified_result_in_one_locale() -> None:
    renderer = LarkCardRenderer(Translator.from_package())
    outcome = AgentOutcome(run_id=uuid4(), persisted=True, result={"recipe_id": "r1"})

    card = renderer.outcome(outcome, Locale.EN_US)

    assert card["elements"][0]["text"]["content"] == "The task is complete."
    assert card["elements"][1]["fields"][0]["text"]["content"] == "recipe_id: r1"


def test_final_card_has_safe_sections_and_at_most_three_signed_action_buttons() -> None:
    renderer = LarkCardRenderer(Translator.from_package())
    response = FinalAgentResponse(
        thinking="I understood that you want dinner ideas.",
        plan="I checked your saved recipes and family preferences.",
        act="I compared three eligible recipes.",
        answer="Try the tomato soup.",
        suggested_actions=(),
    )
    actions = tuple(
        IssuedSuggestedAction(
            id=uuid4(),
            type=action_type,
            token=f"signed-{index}",
            expires_at=datetime.now(UTC) + timedelta(minutes=15),
        )
        for index, action_type in enumerate(
            ("save_recipe", "create_plan", "replace_plan_item"), start=1
        )
    )

    card = renderer.final(response, actions, Locale.EN_US)

    rendered = str(card)
    assert "Thinking" in rendered
    assert "Plan" in rendered
    assert "Act" in rendered
    assert "Answer" in rendered
    assert "private_reasoning" not in rendered
    buttons = [element for element in card["elements"] if element.get("tag") == "action"]
    assert len(buttons) == 3
    assert [button["actions"][0]["value"] for button in buttons] == [
        {"token": "signed-1"},
        {"token": "signed-2"},
        {"token": "signed-3"},
    ]


def test_final_card_uses_only_chinese_labels_when_locale_is_chinese() -> None:
    renderer = LarkCardRenderer(Translator.from_package())
    response = FinalAgentResponse(
        thinking="我理解你想找晚餐灵感。",
        plan="我会查看已保存的菜谱。",
        act="我比较了三个符合条件的菜谱。",
        answer="建议试试番茄汤。",
        suggested_actions=(),
    )

    card = renderer.final(response, (), Locale.ZH_CN)

    rendered = str(card)
    assert all(label in rendered for label in ("思考", "计划", "执行", "回答"))
    assert all(label not in rendered for label in ("Thinking", "Plan", "Answer"))
