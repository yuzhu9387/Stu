from uuid import uuid4

from recipe_agent.domain.conversation.contracts import AgentProgress, AgentStage
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
