from uuid import uuid4

from fastapi.testclient import TestClient

from recipe_agent.app import create_app
from recipe_agent.config import Settings


def test_full_mvp_exposes_core_and_operational_routes() -> None:
    metrics_token = str(uuid4())
    settings = Settings(
        environment="test",
        database_url="sqlite+aiosqlite:///:memory:",
        session_signing_key=str(uuid4()),
        metrics_token=metrics_token,
    )
    client = TestClient(create_app(settings))
    paths = set(client.get("/openapi.json").json()["paths"])

    assert {
        "/api/v1/auth/magic-links",
        "/api/v1/recommendations",
        "/api/v1/plans/weeks",
        "/api/v1/feedback/{recipe_id}",
        "/api/v1/shares",
        "/webhooks/lark/events",
        "/health/live",
        "/health/ready",
        "/metrics",
    } <= paths

    assert client.get("/metrics").status_code == 401
    metrics = client.get("/metrics", headers={"authorization": f"Bearer {metrics_token}"})
    assert metrics.status_code == 200
    assert "recipe_agent_http_requests_total" in metrics.text
