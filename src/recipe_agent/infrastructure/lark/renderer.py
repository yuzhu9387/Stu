"""Render localized Lark interactive cards."""

from recipe_agent.domain.common.types import JsonValue
from recipe_agent.domain.conversation.contracts import AgentOutcome, AgentProgress
from recipe_agent.domain.identity.locale import Locale, Translator


class LarkCardRenderer:
    def __init__(self, translator: Translator) -> None:
        self._translator = translator

    def progress(self, progress: AgentProgress, locale: Locale) -> dict[str, JsonValue]:
        content = self._translator.render(locale, progress.message_key, progress.values)
        return {
            "config": {"wide_screen_mode": True},
            "elements": [
                {
                    "tag": "div",
                    "text": {"tag": "plain_text", "content": content},
                }
            ],
        }

    def outcome(self, outcome: AgentOutcome, locale: Locale) -> dict[str, JsonValue]:
        title = self._translator.render(locale, "agent.stage.completed")
        fields: list[JsonValue] = [
            {
                "is_short": False,
                "text": {"tag": "plain_text", "content": f"{key}: {value}"},
            }
            for key, value in outcome.result.items()
        ]
        return {
            "config": {"wide_screen_mode": True},
            "elements": [
                {"tag": "div", "text": {"tag": "plain_text", "content": title}},
                {"tag": "div", "fields": fields},
            ],
        }
