"""Render localized Lark interactive cards."""

from recipe_agent.domain.common.types import JsonValue
from recipe_agent.domain.conversation.actions import IssuedSuggestedAction
from recipe_agent.domain.conversation.contracts import AgentOutcome, AgentProgress
from recipe_agent.domain.conversation.responses import FinalAgentResponse
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

    def final(
        self,
        response: FinalAgentResponse,
        actions: tuple[IssuedSuggestedAction, ...],
        locale: Locale,
    ) -> dict[str, JsonValue]:
        sections = (
            ("lark.section.thinking", response.thinking),
            ("lark.section.plan", response.plan),
            ("lark.section.act", response.act),
            ("lark.section.answer", response.answer),
        )
        elements: list[JsonValue] = [
            {
                "tag": "div",
                "text": {
                    "tag": "plain_text",
                    "content": f"{self._translator.render(locale, key)}\n{content}",
                },
            }
            for key, content in sections
        ]
        for action in actions[:3]:
            elements.append(
                {
                    "tag": "action",
                    "actions": [
                        {
                            "tag": "button",
                            "type": "primary",
                            "text": {
                                "tag": "plain_text",
                                "content": self._translator.render(
                                    locale, f"lark.action.{action.type}"
                                ),
                            },
                            "value": {"token": action.token},
                        }
                    ],
                }
            )
        return {"config": {"wide_screen_mode": True}, "elements": elements}

    def linking_instructions(self, locale: Locale) -> dict[str, JsonValue]:
        return self._single_text(self._translator.render(locale, "lark.link.instructions"))

    def linked(self, locale: Locale) -> dict[str, JsonValue]:
        return self._single_text(self._translator.render(locale, "lark.link.succeeded"))

    def failure(self, locale: Locale) -> dict[str, JsonValue]:
        return self._single_text(self._translator.render(locale, "lark.run.failed"))

    @staticmethod
    def _single_text(content: str) -> dict[str, JsonValue]:
        return {
            "config": {"wide_screen_mode": True},
            "elements": [
                {"tag": "div", "text": {"tag": "plain_text", "content": content}}
            ],
        }
