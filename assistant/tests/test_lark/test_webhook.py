import json
from app.lark.webhook import WebhookHandler


def test_parse_url_verification():
    handler = WebhookHandler(verification_token="test-token")
    event = handler.parse({"type": "url_verification", "challenge": "test-challenge", "token": "test-token"})
    assert event.event_type == "url_verification"
    assert event.challenge == "test-challenge"


def test_parse_message_event():
    handler = WebhookHandler(verification_token="test-token")
    payload = {"schema": "2.0", "header": {"event_id": "evt_1", "event_type": "im.message.receive_v1", "token": "test-token"}, "event": {"sender": {"sender_id": {"user_id": "user_abc"}}, "message": {"message_id": "msg_1", "message_type": "text", "content": json.dumps({"text": "hello"})}}}
    event = handler.parse(payload)
    assert event.event_type == "im.message.receive_v1"
    assert event.user_id == "user_abc"
    assert event.message_text == "hello"


def test_parse_card_action():
    handler = WebhookHandler(verification_token="test-token")
    payload = {"schema": "2.0", "header": {"event_id": "evt_2", "event_type": "card.action.trigger", "token": "test-token"}, "event": {"operator": {"user_id": "user_abc"}, "action": {"value": {"action": "confirm"}}}}
    event = handler.parse(payload)
    assert event.event_type == "card.action.trigger"
    assert event.action_value == "confirm"


def test_verify_token_mismatch():
    handler = WebhookHandler(verification_token="correct-token")
    event = handler.parse({"type": "url_verification", "challenge": "test", "token": "wrong-token"})
    assert event.event_type == "invalid"


def test_deduplicate_event():
    handler = WebhookHandler(verification_token="test-token")
    payload = {"schema": "2.0", "header": {"event_id": "evt_same", "event_type": "im.message.receive_v1", "token": "test-token"}, "event": {"sender": {"sender_id": {"user_id": "u"}}, "message": {"message_id": "m", "message_type": "text", "content": json.dumps({"text": "hi"})}}}
    e1 = handler.parse(payload)
    assert e1.event_type == "im.message.receive_v1"
    e2 = handler.parse(payload)
    assert e2.event_type == "duplicate"
