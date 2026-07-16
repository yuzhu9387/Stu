from fastapi.testclient import TestClient

from recipe_agent.app import create_app
from recipe_agent.config import Settings


def test_health_endpoints_report_application_state() -> None:
    app = create_app(Settings(environment="test"))
    client = TestClient(app)

    assert client.get("/health/live").json() == {"status": "alive"}
    assert client.get("/health/ready").json() == {"status": "ready"}
