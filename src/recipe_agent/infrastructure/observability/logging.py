"""Structured JSON logging with privacy-first field redaction."""

import json
from collections.abc import Mapping, Sequence
from contextvars import ContextVar, Token
from typing import Any

REDACTED = "[REDACTED]"
SENSITIVE_FIELDS = frozenset(
    {
        "access_token",
        "authorization",
        "body",
        "email",
        "message_text",
        "password",
        "phone",
        "prompt",
        "raw_text",
        "refresh_token",
        "secret",
        "session_signing_key",
        "token",
    }
)
_correlation_id: ContextVar[str | None] = ContextVar("correlation_id", default=None)


def bind_correlation_id(value: str) -> Token[str | None]:
    """Bind a correlation ID to the current asynchronous execution context."""

    return _correlation_id.set(value)


def reset_correlation_id(token: Token[str | None]) -> None:
    """Restore the previous asynchronous correlation context."""

    _correlation_id.reset(token)


def redact(value: Any, *, field_name: str | None = None) -> Any:
    """Return a JSON-compatible value with private fields replaced."""

    if field_name is not None and field_name.casefold() in SENSITIVE_FIELDS:
        return REDACTED
    if isinstance(value, Mapping):
        return {str(key): redact(item, field_name=str(key)) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [redact(item) for item in value]
    return value


def render_log(event: Mapping[str, Any]) -> str:
    """Serialize one redacted structured event for a log sink."""

    enriched = dict(event)
    correlation_id = _correlation_id.get()
    if correlation_id is not None:
        enriched.setdefault("correlation_id", correlation_id)
    return json.dumps(
        redact(enriched),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
