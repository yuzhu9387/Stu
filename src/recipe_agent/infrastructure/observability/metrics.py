"""Small dependency-free metrics registry for service health signals."""

from collections import Counter
from threading import Lock


class MetricsRegistry:
    """Record bounded HTTP counters and render Prometheus text format."""

    def __init__(self) -> None:
        self._requests: Counter[tuple[str, str, int]] = Counter()
        self._lock = Lock()

    def record_request(self, *, method: str, route: str, status_code: int) -> None:
        safe_route = route if len(route) <= 160 else "unknown"
        with self._lock:
            self._requests[(method, safe_route, status_code)] += 1

    def render(self) -> str:
        lines = [
            "# HELP recipe_agent_http_requests_total Total HTTP requests.",
            "# TYPE recipe_agent_http_requests_total counter",
        ]
        with self._lock:
            entries = sorted(self._requests.items())
        for (method, route, status_code), count in entries:
            lines.append(
                "recipe_agent_http_requests_total"
                f'{{method="{method}",route="{route}",status="{status_code}"}} {count}'
            )
        if not entries:
            lines.append(
                'recipe_agent_http_requests_total{method="none",route="none",status="0"} 0'
            )
        return "\n".join(lines) + "\n"
