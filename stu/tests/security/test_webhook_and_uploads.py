from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from recipe_agent.api.security import UploadRejected, validate_upload
from recipe_agent.app import create_app
from recipe_agent.config import Settings
from recipe_agent.infrastructure.observability.logging import render_log


def test_structured_log_redacts_secrets_and_private_text() -> None:
    rendered = render_log(
        {
            "authorization": "Bearer secret",
            "message_text": "private recipe",
            "nested": {"access_token": "nested-token", "event_id": "event-1"},
        }
    )

    assert "secret" not in rendered
    assert "private recipe" not in rendered
    assert "nested-token" not in rendered
    assert rendered.count("[REDACTED]") == 3
    assert "event-1" in rendered


def test_upload_validation_rejects_unsupported_or_oversized_content() -> None:
    with pytest.raises(UploadRejected, match="content type"):
        validate_upload(filename="recipe.exe", content_type="application/x-msdownload", size=32)
    with pytest.raises(UploadRejected, match="size"):
        validate_upload(filename="recipe.jpg", content_type="image/jpeg", size=10_000, limit=100)

    validate_upload(filename="recipe.jpg", content_type="image/jpeg", size=100, limit=100)


def test_request_limits_and_correlation_id_are_enforced() -> None:
    settings = Settings(
        environment="test",
        database_url="sqlite+aiosqlite:///:memory:",
        session_signing_key=str(uuid4()),
        max_request_bytes=64,
    )
    client = TestClient(create_app(settings))

    response = client.get("/health/live")
    rejected = client.post(
        "/webhooks/lark/events",
        content=b"x" * 65,
        headers={"content-type": "application/json", "content-length": "65"},
    )

    assert response.headers["x-correlation-id"]
    assert rejected.status_code == 413
