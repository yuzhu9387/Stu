"""Normalize Lark v2 events into transport-independent commands."""

from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import BaseModel, ConfigDict, Field

from recipe_agent.domain.conversation.contracts import ConversationCommand
from recipe_agent.domain.identity.locale import Locale


class _Header(BaseModel):
    model_config = ConfigDict(extra="ignore")
    event_id: str = Field(min_length=1)


class _SenderId(BaseModel):
    open_id: str = Field(min_length=1)


class _Sender(BaseModel):
    sender_id: _SenderId


class _Message(BaseModel):
    chat_id: str = Field(min_length=1)
    message_id: str = Field(min_length=1)
    message_type: str
    content: str


class _Event(BaseModel):
    sender: _Sender
    message: _Message


class _Envelope(BaseModel):
    schema_: str = Field(alias="schema")
    header: _Header
    event: _Event


class _TextContent(BaseModel):
    text: str = Field(min_length=1)


class LarkEventNormalizer:
    def __init__(self, *, account_id: UUID, household_id: UUID, locale: Locale) -> None:
        self._account_id = account_id
        self._household_id = household_id
        self._locale = locale

    def normalize(self, payload: object) -> ConversationCommand:
        envelope = _Envelope.model_validate(payload)
        if envelope.schema_ != "2.0" or envelope.event.message.message_type != "text":
            raise ValueError("Unsupported Lark event")
        content = _TextContent.model_validate_json(envelope.event.message.content)
        return ConversationCommand(
            account_id=self._account_id,
            household_id=self._household_id,
            conversation_id=uuid5(NAMESPACE_URL, envelope.event.message.chat_id),
            locale=self._locale,
            message=content.text,
            transport="lark",
            idempotency_key=envelope.header.event_id,
        )
