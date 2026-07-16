"""Normalize verified Lark callbacks before identity resolution."""

from typing import Literal
from uuid import NAMESPACE_URL, uuid5

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from recipe_agent.domain.conversation.contracts import ConversationCommand
from recipe_agent.domain.identity.locale import Locale
from recipe_agent.domain.identity.service import HouseholdScope


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class _TransportModel(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)


class _Header(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    event_id: str = Field(min_length=1, max_length=128)
    event_type: str = Field(min_length=1, max_length=160)


class _SenderId(_TransportModel):
    open_id: str = Field(min_length=1, max_length=128)


class _Sender(_TransportModel):
    sender_id: _SenderId


class _Message(_TransportModel):
    chat_id: str = Field(min_length=1, max_length=128)
    message_id: str = Field(min_length=1, max_length=128)
    message_type: str
    content: str = Field(max_length=32_000)


class _MessageEvent(_TransportModel):
    sender: _Sender
    message: _Message


class _MessageEnvelope(_TransportModel):
    schema_: str = Field(alias="schema")
    header: _Header
    event: _MessageEvent


class _TextContent(_StrictModel):
    text: str = Field(min_length=1, max_length=8_000)


class _Operator(_TransportModel):
    operator_id: _SenderId


class _ActionValue(_StrictModel):
    token: str = Field(min_length=1, max_length=4096)


class _Action(_TransportModel):
    value: _ActionValue


class _ActionEvent(_TransportModel):
    operator: _Operator
    action: _Action


class _ActionEnvelope(_TransportModel):
    schema_: str = Field(alias="schema")
    header: _Header
    event: _ActionEvent


class NormalizedLarkMessage(_StrictModel):
    kind: Literal["message"] = "message"
    event_id: str
    open_id: str
    chat_id: str
    message_id: str
    text: str
    locale: Locale

    def to_command(self, scope: HouseholdScope) -> ConversationCommand:
        return ConversationCommand(
            account_id=scope.account_id,
            household_id=scope.household_id,
            conversation_id=uuid5(NAMESPACE_URL, f"{scope.account_id}:{self.chat_id}"),
            allow_conversation_creation=True,
            locale=self.locale,
            message=self.text,
            transport="lark",
            idempotency_key=self.event_id,
            reply_target=self.chat_id,
        )


class NormalizedLarkAction(_StrictModel):
    kind: Literal["action"] = "action"
    event_id: str
    open_id: str
    token: str


type NormalizedLarkEvent = NormalizedLarkMessage | NormalizedLarkAction


class LarkEventNormalizer:
    """Accept only supported message and action callback shapes."""

    def normalize(self, payload: object) -> NormalizedLarkEvent:
        try:
            envelope = _MessageEnvelope.model_validate(payload)
            if (
                envelope.schema_ == "2.0"
                and envelope.header.event_type == "im.message.receive_v1"
                and envelope.event.message.message_type == "text"
            ):
                content = _TextContent.model_validate_json(envelope.event.message.content)
                return NormalizedLarkMessage(
                    event_id=envelope.header.event_id,
                    open_id=envelope.event.sender.sender_id.open_id,
                    chat_id=envelope.event.message.chat_id,
                    message_id=envelope.event.message.message_id,
                    text=content.text,
                    locale=_infer_locale(content.text),
                )
        except ValidationError:
            pass

        try:
            envelope_action = _ActionEnvelope.model_validate(payload)
            if (
                envelope_action.schema_ == "2.0"
                and envelope_action.header.event_type == "card.action.trigger"
            ):
                return NormalizedLarkAction(
                    event_id=envelope_action.header.event_id,
                    open_id=envelope_action.event.operator.operator_id.open_id,
                    token=envelope_action.event.action.value.token,
                )
        except ValidationError:
            pass
        raise ValueError("Unsupported Lark event")


def _infer_locale(text: str) -> Locale:
    has_chinese = any("\u4e00" <= character <= "\u9fff" for character in text)
    return Locale.ZH_CN if has_chinese else Locale.EN_US


__all__ = [
    "LarkEventNormalizer",
    "NormalizedLarkAction",
    "NormalizedLarkEvent",
    "NormalizedLarkMessage",
]
