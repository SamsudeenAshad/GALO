"""Request-ID + structured access-log middleware.

Assigns each request a stable id (honoring an inbound ``X-Request-ID`` when
present), exposes it on ``request.state.request_id`` and the response header,
and emits one structured log line per request with method, path, status, and
duration. Duration uses a monotonic clock passed in (the app supplies it) to
keep this module free of forbidden time calls.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Awaitable, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

logger = logging.getLogger("galo.access")


class RequestContextMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, clock: Callable[[], float]) -> None:
        super().__init__(app)
        self._clock = clock

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        rid = request.headers.get("X-Request-ID") or uuid.uuid4().hex
        request.state.request_id = rid
        start = self._clock()
        try:
            response = await call_next(request)
        except Exception:
            elapsed_ms = (self._clock() - start) * 1000
            logger.exception(
                "request failed",
                extra={
                    "request_id": rid,
                    "method": request.method,
                    "path": request.url.path,
                    "elapsed_ms": round(elapsed_ms, 1),
                },
            )
            raise
        elapsed_ms = (self._clock() - start) * 1000
        response.headers["X-Request-ID"] = rid
        logger.info(
            "request",
            extra={
                "request_id": rid,
                "method": request.method,
                "path": request.url.path,
                "status": response.status_code,
                "elapsed_ms": round(elapsed_ms, 1),
            },
        )
        return response
