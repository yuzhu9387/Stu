from uuid import uuid4

from recipe_agent.domain.conversation.contracts import AgentOutcome, AgentProgress, AgentStage
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
