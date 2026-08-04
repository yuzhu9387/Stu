"""Shared request limits, correlation identifiers, and upload validation."""

import re
from pathlib import PurePath
from uuid import uuid4

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import JSONResponse, Response

from recipe_agent.infrastructure.observability.logging import (
    bind_correlation_id,
    reset_correlation_id,
)
from recipe_agent.infrastructure.observability.metrics import MetricsRegistry

ALLOWED_UPLOAD_TYPES = frozenset(
    {
        "application/vnd.ms-excel",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "image/jpeg",
        "image/png",
        "image/webp",
        "text/plain",
    }
)
CORRELATION_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,128}$")


class UploadRejected(ValueError):
    """Raised when an upload violates the storage boundary."""


def validate_upload(
    *,
    filename: str,
    content_type: str,
    size: int,
    limit: int = 10 * 1024 * 1024,
) -> None:
    """Validate upload metadata before any bytes reach object storage."""

    if PurePath(filename).name != filename or filename in {"", ".", ".."}:
        raise UploadRejected("Invalid filename")
    if content_type.casefold() not in ALLOWED_UPLOAD_TYPES:
        raise UploadRejected("Unsupported content type")
    if size < 0 or size > limit:
        raise UploadRejected("Upload size exceeds the configured limit")


class RequestSecurityMiddleware(BaseHTTPMiddleware):
    """Reject oversized bodies and attach one correlation ID to every response."""

    def __init__(
        self,
        app: object,
        *,
        max_request_bytes: int,
        metrics: MetricsRegistry,
    ) -> None:
        super().__init__(app)  # type: ignore[arg-type]
        self._max_request_bytes = max_request_bytes
        self._metrics = metrics

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        correlation_id = _correlation_id(request.headers.get("x-correlation-id"))
        correlation_token = bind_correlation_id(correlation_id)
        content_length = request.headers.get("content-length")
        try:
            if content_length is not None and _is_oversized(
                content_length, self._max_request_bytes
            ):
                response: Response = JSONResponse(
                    {"detail": "Request body is too large"},
                    status_code=413,
                )
            else:
                response = await call_next(request)
            response.headers["x-correlation-id"] = correlation_id
            route = request.scope.get("route")
            route_path = getattr(route, "path", request.url.path)
            self._metrics.record_request(
                method=request.method,
                route=route_path,
                status_code=response.status_code,
            )
            return response
        finally:
            reset_correlation_id(correlation_token)


def _correlation_id(received: str | None) -> str:
    if received is not None and CORRELATION_PATTERN.fullmatch(received):
        return received
    return str(uuid4())


def _is_oversized(raw_length: str, limit: int) -> bool:
    try:
        return int(raw_length) > limit
    except ValueError:
        return True
