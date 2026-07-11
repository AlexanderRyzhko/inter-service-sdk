"""
Canonical trace-id propagation for inter-service requests (BLA-1463 slice 3 contract).

Provides:
- TRACE_HEADER / trace_id_var / get_trace_id() / set_trace_id(): shared accessors
- BlazelTracingMiddleware: pure ASGI middleware (NOT starlette.middleware.base.BaseHTTPMiddleware).
  BaseHTTPMiddleware runs the wrapped app in a separate anyio task, which breaks contextvar
  propagation and caused the ordering bug fixed in BLA-1471 (CGAPI AuditMiddleware). A pure
  ASGI implementation keeps the whole request in one task, so that bug class is structurally
  impossible here.
- BlazelTraceFilter: stdlib logging filter injecting record.blazel_trace_id

Known limitation (Starlette architecture, not fixable within this middleware): Starlette
always wraps the whole app with its own ServerErrorMiddleware as the OUTERMOST layer,
regardless of `app.add_middleware()` order (see starlette.applications.Starlette.
build_middleware_stack). A truly unhandled exception (not an HTTPException) propagates
past this middleware and is turned into a 500 response by ServerErrorMiddleware using the
original `send`, never reaching our `send_wrapper` — so the trace header is missing on
that specific response. Installing via `app.add_middleware(BlazelTracingMiddleware)` does
NOT cover this case. To get trace headers on unhandled-exception 500s too, wrap the whole
app from outside instead: `asgi_app = BlazelTracingMiddleware(fastapi_app)` and serve
`asgi_app` directly — that puts BlazelTracingMiddleware outside Starlette's own
ServerErrorMiddleware. See test_middleware_add_middleware_pattern_misses_unhandled_500 /
test_middleware_outer_wrap_pattern_covers_unhandled_500 in tests/test_tracing.py.
"""

import logging
import uuid
from contextvars import ContextVar
from typing import Optional

TRACE_HEADER = "X-Blazel-Trace-Id"
REQUEST_ID_HEADER = "X-Request-ID"

trace_id_var: ContextVar[Optional[str]] = ContextVar("blazel_trace_id", default=None)


def get_trace_id() -> Optional[str]:
    """Return the trace id for the current context, or None if unset."""
    return trace_id_var.get()


def set_trace_id(trace_id: Optional[str]):
    """Set the trace id for the current context. Returns the ContextVar reset Token."""
    return trace_id_var.set(trace_id)


def _decode_scope_headers(raw_headers):
    decoded = {}
    for name, value in raw_headers:
        decoded[name.decode("latin-1").lower()] = value.decode("latin-1")
    return decoded


def _without_headers(raw_headers, names_lower):
    """Drop any existing tuples matching names_lower (case-insensitive) so the
    canonical value set below is never duplicated (e.g. by a wrapped app that
    already set X-Blazel-Trace-Id or X-Request-ID itself)."""
    return [
        (name, value)
        for name, value in raw_headers
        if name.decode("latin-1").lower() not in names_lower
    ]


class BlazelTracingMiddleware:
    """Pure ASGI middleware — assigns/propagates blazel_trace_id for the request lifecycle.

    See module docstring: `app.add_middleware(BlazelTracingMiddleware)` cannot add the
    trace header to unhandled-exception 500 responses (Starlette's ServerErrorMiddleware
    is always outermost). Wrap the whole app instead for full crash-response coverage.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = _decode_scope_headers(scope.get("headers", []))
        incoming_trace = headers.get(TRACE_HEADER.lower())
        incoming_request_id = headers.get(REQUEST_ID_HEADER.lower())

        if incoming_trace:
            trace_id = incoming_trace
        elif incoming_request_id:
            trace_id = incoming_request_id
        else:
            trace_id = str(uuid.uuid4())

        token = trace_id_var.set(trace_id)

        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                # Always strip any pre-existing values for both header names — a downstream
                # X-Request-ID left untouched here would let two different correlation ids
                # reach the client on the same response.
                names_to_replace = {TRACE_HEADER.lower(), REQUEST_ID_HEADER.lower()}
                response_headers = _without_headers(message.get("headers", []), names_to_replace)
                response_headers.append((TRACE_HEADER.encode("latin-1"), trace_id.encode("latin-1")))
                # Only echo X-Request-ID when it's exactly the value that became the
                # canonical trace id (the AC-5 fallback case). If the caller sent both
                # headers with DIFFERENT values, X-Blazel-Trace-Id already won precedence
                # above — echoing the original, now-stale X-Request-ID back would put two
                # conflicting correlation ids on the same response.
                if incoming_request_id and incoming_request_id == trace_id:
                    response_headers.append(
                        (REQUEST_ID_HEADER.encode("latin-1"), incoming_request_id.encode("latin-1"))
                    )
                message = {**message, "headers": response_headers}
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            trace_id_var.reset(token)


class BlazelTraceFilter(logging.Filter):
    """Attach to a logger so every record carries blazel_trace_id (safe default when unset)."""

    default_value = "-"

    def filter(self, record: logging.LogRecord) -> bool:
        record.blazel_trace_id = get_trace_id() or self.default_value
        return True
