from __future__ import annotations
import json
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Optional, Any, Dict


@dataclass
class LarkEvent:
    event_type: str
    user_id: Optional[str] = None
    message_id: Optional[str] = None
    message_text: Optional[str] = None
    message_type: Optional[str] = None
    challenge: Optional[str] = None
    action_value: Optional[str] = None
    raw: Dict[str, Any] = field(default_factory=dict)


class WebhookHandler:
    def __init__(self, verification_token: str, max_cache: int = 1000):
        self._verification_token = verification_token
        self._seen_events: OrderedDict = OrderedDict()
        self._max_cache = max_cache

    def parse(self, payload: Dict[str, Any]) -> LarkEvent:
        if payload.get("type") == "url_verification":
            if payload.get("token") != self._verification_token:
                return LarkEvent(event_type="invalid", raw=payload)
            return LarkEvent(event_type="url_verification", challenge=payload.get("challenge"), raw=payload)

        header = payload.get("header", {})
        token = header.get("token", "")
        if token != self._verification_token:
            return LarkEvent(event_type="invalid", raw=payload)

        event_id = header.get("event_id", "")
        event_type = header.get("event_type", "unknown")

        if event_id and event_id in self._seen_events:
            return LarkEvent(event_type="duplicate", raw=payload)
        if event_id:
            self._seen_events[event_id] = True
            if len(self._seen_events) > self._max_cache:
                self._seen_events.popitem(last=False)

        event_data = payload.get("event", {})

        if event_type == "im.message.receive_v1":
            sender = event_data.get("sender", {}).get("sender_id", {})
            message = event_data.get("message", {})
            content = message.get("content", "{}")
            try:
                text = json.loads(content).get("text", "")
            except (json.JSONDecodeError, AttributeError):
                text = ""
            return LarkEvent(event_type=event_type, user_id=sender.get("user_id"), message_id=message.get("message_id"), message_text=text, message_type=message.get("message_type"), raw=payload)

        if event_type == "card.action.trigger":
            operator = event_data.get("operator", {})
            action = event_data.get("action", {})
            action_val = action.get("value", {})
            if isinstance(action_val, dict):
                action_val = action_val.get("action", "")
            return LarkEvent(event_type=event_type, user_id=operator.get("user_id"), action_value=action_val, raw=payload)

        return LarkEvent(event_type=event_type, raw=payload)
