"""Per-request logging and Prometheus metrics."""

import time
import uuid

import structlog
from prometheus_client import Counter, Histogram
from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

log = structlog.get_logger(__name__)

REQUESTS = Counter("http_requests_total", "HTTP requests handled.", ["method", "route", "status"])
LATENCY = Histogram(
    "http_request_duration_seconds", "HTTP request latency in seconds.", ["method", "route"]
)


class RequestObservabilityMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id = uuid.uuid4().hex
        status = 500  # Stays 500 if the app raises before sending a response.

        async def send_with_request_id(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                MutableHeaders(scope=message)["X-Request-ID"] = request_id
            await send(message)

        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=request_id)
        start = time.perf_counter()
        try:
            await self.app(scope, receive, send_with_request_id)
        finally:
            duration = time.perf_counter() - start
            # Label by route template, not raw path, so planet names can't inflate cardinality.
            route = getattr(scope.get("route"), "path", "unmatched")
            REQUESTS.labels(scope["method"], route, str(status)).inc()
            LATENCY.labels(scope["method"], route).observe(duration)
            log.info(
                "http_request",
                method=scope["method"],
                path=scope["path"],
                route=route,
                status=status,
                duration_ms=round(duration * 1000, 2),
            )
